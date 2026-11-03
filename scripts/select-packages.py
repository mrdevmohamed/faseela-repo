#!/usr/bin/env python3
"""Resolve GitHub Actions package selections against the live recipe tree."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import flavor as flavor_module  # noqa: E402

CORE_CATEGORIES = ("base", "system", "boot", "extra")


class SelectionError(Exception):
    """Invalid or ambiguous package selection."""


def split_values(value: str | list[str] | None) -> list[str]:
    """Split workflow text values on whitespace, commas, or newlines."""
    if value is None:
        return []
    raw = " ".join(value) if isinstance(value, list) else value
    return [part for part in re.split(r"[\s,]+", raw.strip()) if part]


def changed_recipes(recipes_dir: Path, before: str, after: str) -> list[str]:
    """Return still-existing recipe names changed between two Git revisions."""
    if not after:
        raise SelectionError("the push event did not provide a target commit")
    if not before or set(before) == {"0"}:
        probe = subprocess.run(
            ["git", "rev-parse", "HEAD^"], check=False, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if probe.returncode != 0:
            raise SelectionError("cannot determine the previous commit for CHANGED selection")
        before = probe.stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--name-only", before, after, "--", str(recipes_dir)],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if diff.returncode != 0:
        raise SelectionError(f"git diff failed: {diff.stderr.strip()}")
    names: set[str] = set()
    for raw in diff.stdout.splitlines():
        parts = Path(raw).parts
        if len(parts) >= 4 and parts[0] == recipes_dir.name:
            names.add(parts[2])
    return sorted(names)


def resolve_selection(
    recipes: dict[str, tuple[str, dict]],
    flavors: dict,
    *,
    all_packages: bool = False,
    all_toolchain: bool = False,
    core: bool = False,
    categories: list[str] | None = None,
    package_names: list[str] | None = None,
    toolchain_package_names: list[str] | None = None,
    flavor_names: list[str] | None = None,
    exclusions: list[str] | None = None,
    allow_empty: bool = False,
    source: str = "manual",
) -> dict:
    """Resolve ordinary and Toolchain targets into separate safe build plans."""
    categories = categories or []
    package_names = package_names or []
    toolchain_package_names = toolchain_package_names or []
    flavor_names = flavor_names or []
    exclusions = exclusions or []
    available_categories = sorted({category for category, _ in recipes.values()})
    category_set = set(available_categories)
    all_toolchain_names = {
        name for name, (category, _) in recipes.items() if category == "toolchain"
    }
    selected_categories: list[str] = []
    selected: list[str] = []
    selected_toolchain: list[str] = []

    def add_categories(names: list[str]) -> None:
        for category in names:
            if category not in category_set:
                raise SelectionError(
                    f"unknown category '{category}'; available: {', '.join(available_categories)}"
                )
            if category == "toolchain":
                raise SelectionError(
                    "Toolchain cannot be built by the ordinary package workflow; "
                    "use the Toolchain checkbox or toolchain_packages field to route it through Bootstrap"
                )
            if category not in selected_categories:
                selected_categories.append(category)
            selected.extend(
                name for name, (cat, _) in sorted(recipes.items()) if cat == category
            )

    if all_packages:
        # ALL discovers every current and future non-Toolchain category.
        add_categories([category for category in available_categories if category != "toolchain"])
    if all_toolchain:
        selected_toolchain.extend(sorted(all_toolchain_names))
        if "toolchain" not in selected_categories:
            selected_categories.append("toolchain")
    if core:
        add_categories(list(CORE_CATEGORIES))
    if categories:
        add_categories(categories)

    for name in package_names:
        if name not in recipes:
            raise SelectionError(f"no recipe named '{name}'")
        if recipes[name][0] == "toolchain":
            selected_toolchain.append(name)
        else:
            selected.append(name)

    for name in toolchain_package_names:
        if name not in recipes:
            raise SelectionError(f"no recipe named '{name}'")
        if recipes[name][0] != "toolchain":
            raise SelectionError(
                f"'{name}' is not a Toolchain recipe; Toolchain packages must live under recipes/toolchain"
            )
        selected_toolchain.append(name)

    resolved_flavors: list[str] = []
    if flavor_names:
        if "bootstrap" not in flavors:
            raise SelectionError("flavors.toml has no 'bootstrap' flavor required for flavor selection")
        bootstrap = set(flavor_module.resolve(flavors, recipes, "bootstrap"))
        for flavor_name in flavor_names:
            try:
                full = flavor_module.resolve(flavors, recipes, flavor_name)
            except flavor_module.FlavorError as exc:
                raise SelectionError(str(exc)) from exc
            resolved_flavors.append(flavor_name)
            # Ordinary flavor packages remain in the regular build. Toolchain
            # entries are routed to Bootstrap, including shared bootstrap tools.
            for name in full:
                category = recipes[name][0]
                if category == "toolchain":
                    selected_toolchain.append(name)
                elif name not in bootstrap:
                    selected.append(name)

    if not selected and not selected_toolchain and not allow_empty:
        raise SelectionError(
            "no package selection was made; select ALL, CORE, a Toolchain option, "
            "one or more categories, package names, or flavors"
        )

    def deduplicate(names: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for name in names:
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    deduplicated = deduplicate(selected)
    deduplicated_toolchain = deduplicate(selected_toolchain)

    excluded: set[str] = set()
    for item in exclusions:
        if item.startswith("@"):
            category = item[1:]
            if category not in category_set:
                raise SelectionError(
                    f"cannot exclude unknown category '{category}'; available: {', '.join(available_categories)}"
                )
            excluded.update(name for name, (cat, _) in recipes.items() if cat == category)
        else:
            if item not in recipes:
                raise SelectionError(f"cannot exclude unknown package '{item}'")
            excluded.add(item)

    final = [name for name in deduplicated if name not in excluded]
    final_toolchain = [name for name in deduplicated_toolchain if name not in excluded]
    counts: dict[str, int] = {}
    for name in final + final_toolchain:
        category = recipes[name][0]
        counts[category] = counts.get(category, 0) + 1
    removed = excluded.intersection(deduplicated + deduplicated_toolchain)
    toolchain_all = bool(all_toolchain_names) and set(final_toolchain) == all_toolchain_names
    return {
        "schema": 2,
        "source": source,
        "packages": final,
        "package_count": len(final),
        "toolchain_packages": final_toolchain,
        "toolchain_package_count": len(final_toolchain),
        "toolchain_all": toolchain_all,
        "total_count": len(final) + len(final_toolchain),
        "category_counts": dict(sorted(counts.items())),
        "selected_categories": selected_categories,
        "flavors": resolved_flavors,
        "excluded": sorted(removed),
        "excluded_count": len(removed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, default=ROOT / "recipes")
    parser.add_argument("--flavors-file", type=Path, default=ROOT / "flavors.toml")
    parser.add_argument("--all", action="store_true", dest="all_packages")
    parser.add_argument("--toolchain-all", action="store_true", dest="all_toolchain")
    parser.add_argument("--core", action="store_true")
    parser.add_argument("--categories", nargs="*", default=[])
    parser.add_argument("--packages", default="", help="exact recipe names; Toolchain names are routed to Bootstrap")
    parser.add_argument("--toolchain-packages", default="", help="Toolchain recipe names separated by spaces or commas")
    parser.add_argument("--flavors", default="", help="flavor names separated by spaces or commas")
    parser.add_argument("--exclude", default="", help="package names or @categories to exclude")
    parser.add_argument("--changed-from")
    parser.add_argument("--changed-to")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if not args.recipes.is_dir():
            raise SelectionError(f"recipes directory does not exist: {args.recipes}")
        recipes = flavor_module.load_recipes(args.recipes)
        flavors = flavor_module.load_flavors(args.flavors_file)
        manual_values = (
            args.all_packages or args.all_toolchain or args.core or bool(args.categories)
            or bool(split_values(args.packages)) or bool(split_values(args.toolchain_packages))
            or bool(split_values(args.flavors))
            or bool(split_values(args.exclude))
        )
        changed_mode = args.changed_from is not None or args.changed_to is not None
        if changed_mode and manual_values:
            raise SelectionError("CHANGED selection cannot be combined with manual selectors")

        if changed_mode:
            if args.changed_from is None or args.changed_to is None:
                raise SelectionError("both --changed-from and --changed-to are required")
            names = changed_recipes(args.recipes, args.changed_from, args.changed_to)
            current_names = [name for name in names if name in recipes]
            plan = resolve_selection(
                recipes, flavors, package_names=current_names,
                allow_empty=True, source="CHANGED",
            )
            plan["changed_recipe_names"] = current_names
        else:
            plan = resolve_selection(
                recipes, flavors,
                all_packages=args.all_packages,
                all_toolchain=args.all_toolchain,
                core=args.core,
                categories=args.categories,
                package_names=split_values(args.packages),
                toolchain_package_names=split_values(args.toolchain_packages),
                flavor_names=split_values(args.flavors),
                exclusions=split_values(args.exclude),
            )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"Selected {plan['package_count']} regular package(s) and {plan['toolchain_package_count']} Toolchain package(s) from {plan['source']}.")
        for category, count in plan["category_counts"].items():
            print(f"  {category}: {count}")
        if plan["excluded_count"]:
            print(f"Excluded {plan['excluded_count']} selected target(s): {', '.join(plan['excluded'])}")
        print(f"Selection plan: {args.output}")
        return 0
    except (SelectionError, flavor_module.FlavorError, OSError, tomllib.TOMLDecodeError, KeyError) as exc:
        print(f"::error::package selection: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
