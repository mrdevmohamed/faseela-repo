#!/usr/bin/env python3
"""scripts/check-recipes.py — offline sanity check of the recipe tree.

Checks (no network, no cargo needed):
  * every recipe.toml parses and has name/version/arch
  * package names are unique
  * every build/run dependency names an existing recipe
  * the dependency graph (build + run) has no cycles
  * sha256 is a 64-hex string (or the all-zero placeholder, reported)
  * linux-firmware-lite / -extra carry the same KEEP list

Usage:
  python3 scripts/check-recipes.py              # whole tree
  python3 scripts/check-recipes.py sway foot    # also print the build order
                                                # needed for those targets
"""
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipe_source  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "recipes"
ZERO = "0" * 64

SERVICE_MANAGER_COMMAND = re.compile(
    r"(?im)(?:^|[;&|]\s*|\bthen\s+|\bdo\s+)\s*(?:if\s+)?(?:!\s*)?"
    r"(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*)\s+)*(?:(?:command|sudo|doas)\s+)*"
    r"(?:/usr/bin/)?(systemctl|sv|service|rc-service)\s+"
    r"(preset(?:-all)?|enable|disable|start|stop|restart|try-restart|reload|"
    r"reload-or-restart|daemon-reload|mask|unmask|revert|link|isolate|"
    r"up|down|force-stop|halt|shutdown)\b"
)


def service_hook_policy(recs):
    """Reject service state changes in package hooks and transaction triggers."""
    errors = []
    for name, recipe in recs.items():
        recipe_path = Path(recipe["_path"])
        hooks = recipe.get("hooks", {})
        if isinstance(hooks, dict):
            for hook_name, body in hooks.items():
                if not isinstance(body, str):
                    continue
                for match in SERVICE_MANAGER_COMMAND.finditer(body):
                    line = body.count("\n", 0, match.start()) + 1
                    manager, action = match.group(1), match.group(2)
                    errors.append(
                        f"{recipe_path}: hook {hook_name} line {line} invokes "
                        f"{manager} {action}; service activation belongs to "
                        "distribution provisioning or the administrator"
                    )

        # Nawa executes regular *.sh files from this directory after
        # package-changing transactions. Inspect every recipe-local shell
        # asset when the recipe declares the transaction-trigger directory.
        try:
            recipe_source = recipe_path.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{recipe_path}: cannot read recipe for trigger policy: {error}")
            continue
        if "transaction-hooks.d" not in recipe_source:
            continue

        trigger_sources = []
        for phase, body in recipe.get("build", {}).items():
            if isinstance(body, str):
                trigger_sources.append((f"{recipe_path} [build.{phase}]", body))
        for asset in sorted(recipe_path.parent.rglob("*.sh")):
            try:
                trigger_sources.append((str(asset), asset.read_text(encoding="utf-8")))
            except (OSError, UnicodeError) as error:
                errors.append(f"{asset}: cannot inspect transaction-trigger source: {error}")

        for source_name, body in trigger_sources:
            for match in SERVICE_MANAGER_COMMAND.finditer(body):
                line = body.count("\n", 0, match.start()) + 1
                manager, action = match.group(1), match.group(2)
                errors.append(
                    f"{source_name}: transaction-trigger source line {line} invokes "
                    f"{manager} {action}; service activation belongs to "
                    "distribution provisioning or the administrator"
                )
    return errors


def load():
    recs, errors = {}, []
    for p in sorted(ROOT.rglob("recipe.toml")):
        try:
            r = tomllib.loads(p.read_text())
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p}: parse error: {e}")
            continue
        pkg = r.get("package", {})
        name = pkg.get("name", "")
        if not name or not pkg.get("version"):
            errors.append(f"{p}: missing package.name/version")
            continue
        if name in recs:
            errors.append(f"{p}: duplicate package name `{name}`")
            continue
        if p.parent.name != name:
            errors.append(f"{p}: directory name != package name `{name}`")
        r["_path"] = p
        recs[name] = r
    return recs, errors


def requirement_name(raw):
    """Return a dependency's package name after validating Nawa's requirement syntax."""
    if not isinstance(raw, str):
        raise ValueError(f"dependency must be a string, got {type(raw).__name__}")
    raw = raw.strip()
    split = next((i for i, char in enumerate(raw) if char in "<>=!"), None)
    if split is None:
        name = raw
    else:
        rest = raw[split:]
        operator = next((op for op in (">=", "<=", "!=", "=", ">", "<") if rest.startswith(op)), None)
        if operator is None:
            raise ValueError(f"invalid comparison operator in {raw!r}")
        version_rel = rest[len(operator):].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.~:-]*-[1-9][0-9]*", version_rel):
            raise ValueError(f"version requirement must end in version-rel, got {raw!r}")
        name = raw[:split].strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.-]{0,127}", name):
        raise ValueError(f"invalid package name in dependency {raw!r}")
    return name


def deps_of(r):
    d = r.get("depends", {})
    return list(dict.fromkeys(d.get("build", []) + d.get("run", [])))


def order(recs, targets):
    seen, out, stack = set(), [], []

    def visit(n):
        if n in seen:
            return
        if n in stack:
            raise SystemExit("dependency cycle: " + " -> ".join(stack[stack.index(n):] + [n]))
        stack.append(n)
        for raw in deps_of(recs[n]):
            visit(requirement_name(raw))
        stack.pop()
        seen.add(n)
        out.append(n)

    for t in targets:
        visit(t)
    return out


def keep_list(r):
    """The KEEP='...' word list of a recipe's install script (None if absent)."""
    m = re.search(r"KEEP='([^']*)'", r.get("build", {}).get("install", ""))
    return m.group(1).split() if m else None


def firmware_split(recs):
    """linux-firmware-lite and -extra split ONE file set: their KEEP lists must match."""
    lite, extra = recs.get("linux-firmware-lite"), recs.get("linux-firmware-extra")
    if not (lite and extra):
        return []
    a, b = keep_list(lite), keep_list(extra)
    if a is None or b is None or a != b:
        return [f"{extra['_path']}: KEEP differs from linux-firmware-lite's - the two "
                "packages would overlap or drop files (see scripts/test-firmware-split.py)"]
    return []


def assetsdir_policy(recs):
    """A recipe that references %{assetsdir} must declare [assets].

    Nawa only materialises the assets snapshot for recipes that declare
    the table (fetch-phase.md §5.3); without it the build fails at fetch
    with "recipe uses %{assetsdir} but does not enable it". Also verify
    every declared include file exists under the recipe directory.
    """
    errors = []
    for name, recipe in recs.items():
        recipe_path = Path(recipe["_path"])
        try:
            source = recipe_path.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"{recipe_path}: cannot read recipe for assets policy: {error}")
            continue
        if "%{assetsdir}" not in source:
            continue
        assets = recipe.get("assets")
        if not isinstance(assets, dict):
            errors.append(
                f"{recipe_path}: `{name}` references %{{assetsdir}} but declares "
                "no [assets] table; add one listing the referenced files"
            )
            continue
        for include in assets.get("include", []):
            if not (recipe_path.parent / include).is_file():
                errors.append(
                    f"{recipe_path}: [assets] lists missing file `{include}`"
                )
    return errors


def main():
    recs, errors = load()
    placeholders = []
    for n, r in recs.items():
        for raw in deps_of(r):
            try:
                dependency = requirement_name(raw)
            except ValueError as error:
                errors.append(f"{r['_path']}: `{n}` has invalid dependency {raw!r}: {error}")
                continue
            if dependency not in recs:
                errors.append(
                    f"{r['_path']}: `{n}` depends on unknown recipe `{dependency}`"
                )
        pkg = r["package"]
        for declared in recipe_source.sources(pkg):
            sha = declared.get("sha256", "")
            if sha == ZERO:
                if n not in placeholders:
                    placeholders.append(n)
            elif not re.fullmatch(r"[0-9a-f]{64}", sha):
                errors.append(f"{r['_path']}: sha256 is not 64 hex chars")
    errors += firmware_split(recs)
    errors += service_hook_policy(recs)
    errors += assetsdir_policy(recs)
    if not errors:
        try:
            order(recs, list(recs))
        except SystemExit as e:
            errors.append(str(e))
    for e in errors:
        print("ERROR:", e)
    print(f"{len(recs)} recipes, {len(errors)} errors, "
          f"{len(placeholders)} with placeholder sha256")
    if placeholders:
        print("  placeholders:", " ".join(placeholders))
    targets = [t for t in sys.argv[1:] if t in recs]
    for t in sys.argv[1:]:
        if t not in recs:
            print(f"unknown target `{t}`")
            errors.append("unknown target")
    if targets and not errors:
        print("build order:", " ".join(order(recs, targets)))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
