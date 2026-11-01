#!/usr/bin/env python3
"""scripts/flavor.py — resolve the flavors defined in flavors.toml.

    flavor.py list                          flavor names with their summary
    flavor.py resolve NAME [--without OTHER] [--recipes DIR]
                                            the packages of a flavor, ONE per
                                            line, dependencies first; --without
                                            leaves out those of flavor OTHER
                                            (what a flavor adds on top of it)
    flavor.py check [--recipes DIR]         every flavor resolves; exit 1 if not

A flavor is a list of package names / @categories (+ other flavors, minus an
exclude list), expanded through the recipes' dependencies:
  closure = "run"    [depends].run, transitively (what an installation needs)
  closure = "build"  [depends].build and .run, transitively (what a build needs)
See flavors.toml for the format. Needs Python >= 3.11 (tomllib).
"""
import argparse
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLOSURES = ("run", "build")


class FlavorError(Exception):
    pass


def load_recipes(recipes: Path):
    """-> {name: (category, depends-table)}"""
    out = {}
    for f in sorted(recipes.glob("*/*/recipe.toml")):
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        name = data["package"]["name"]
        out[name] = (f.parent.parent.name, data.get("depends", {}))
    if not out:
        raise FlavorError(f"no recipes under {recipes}")
    return out


def load_flavors(path: Path):
    flavors = tomllib.loads(path.read_text(encoding="utf-8")).get("flavor", {})
    if not flavors:
        raise FlavorError(f"{path}: no [flavor.*] tables")
    for name, f in flavors.items():
        unknown = set(f) - {"summary", "include", "extends", "exclude", "closure"}
        if unknown:
            raise FlavorError(f"flavor {name}: unknown key(s) {sorted(unknown)}")
        if f.get("closure", "run") not in CLOSURES:
            raise FlavorError(f"flavor {name}: closure must be one of {CLOSURES}")
    return flavors


def _flat(flavors, name, seen=()):
    """include / exclude / closure of a flavor with its `extends` folded in."""
    if name not in flavors:
        raise FlavorError(f"no flavor named '{name}' (have: {', '.join(sorted(flavors))})")
    if name in seen:
        raise FlavorError(f"flavor cycle: {' -> '.join((*seen, name))}")
    f = flavors[name]
    include, exclude = [], []
    closure = f.get("closure", "run")
    for base in f.get("extends", []):
        b_inc, b_exc, b_clo = _flat(flavors, base, (*seen, name))
        include += b_inc
        exclude += b_exc
        # the wider closure wins: a build closure covers the run closure
        if b_clo == "build":
            closure = "build"
    include += f.get("include", [])
    exclude += f.get("exclude", [])
    return include, exclude, closure


def resolve(flavors, recipes, name):
    include, exclude, closure = _flat(flavors, name)
    categories = {cat for cat, _ in recipes.values()}
    roots = []
    for item in include:
        if item.startswith("@"):
            cat = item[1:]
            if cat not in categories:
                raise FlavorError(f"flavor {name}: no recipe category '{cat}' (have: {', '.join(sorted(categories))})")
            roots += sorted(n for n, (c, _) in recipes.items() if c == cat)
        elif item in recipes:
            roots.append(item)
        else:
            raise FlavorError(f"flavor {name}: no recipe named '{item}'")
    for item in exclude:
        if item not in recipes:
            raise FlavorError(f"flavor {name}: exclude names '{item}', which has no recipe")

    kinds = ("run",) if closure == "run" else ("build", "run")
    order, state = [], {}

    def visit(pkg, parent):
        if state.get(pkg):
            return
        if pkg not in recipes:
            raise FlavorError(f"flavor {name}: '{parent}' depends on '{pkg}', which has no recipe")
        state[pkg] = 1
        for kind in kinds:
            for dep in recipes[pkg][1].get(kind, []):
                visit(dep, pkg)
        state[pkg] = 2
        order.append(pkg)

    for pkg in roots:
        visit(pkg, None)
    drop = set(exclude)
    return [p for p in order if p not in drop]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--flavors", type=Path, default=ROOT / "flavors.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("resolve", "check"):
        p = sub.add_parser(c)
        p.add_argument("--recipes", type=Path, default=ROOT / "recipes")
        if c == "resolve":
            p.add_argument("name")
            p.add_argument("--without", metavar="OTHER", help="leave out the packages of this flavor")
    a = ap.parse_args(argv)
    try:
        flavors = load_flavors(a.flavors)
        if a.cmd == "list":
            for n, f in flavors.items():
                print(f"{n:<12} {f.get('summary', '')}")
            return 0
        recipes = load_recipes(a.recipes)
        if a.cmd == "resolve":
            pkgs = resolve(flavors, recipes, a.name)
            if a.without:
                skip = set(resolve(flavors, recipes, a.without))
                pkgs = [p for p in pkgs if p not in skip]
            print("\n".join(pkgs))
            return 0
        bad = 0
        for n in flavors:
            try:
                print(f"ok    {n:<12} {len(resolve(flavors, recipes, n))} packages")
            except FlavorError as e:
                print(f"FAIL  {e}", file=sys.stderr)
                bad += 1
        return 1 if bad else 0
    except (FlavorError, OSError, tomllib.TOMLDecodeError, KeyError) as e:
        print(f"flavor: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
