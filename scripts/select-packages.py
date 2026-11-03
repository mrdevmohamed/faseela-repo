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
    core: bool = False,
    categories: list[str] | None = None,
    package_names: list[str] | None = None,
    flavor_names: list[str] | None = None,
    exclusions: list[str] | None = None,
    allow_empty: bool = False,
    source: str = "manual",
) -> dict:
    """Resolve additive selectors to a deterministic, de-duplicated target list."""
    categories = categories or []
    package_names = package_names or []
    flavor_names = flavor_names or []
    exclusions = exclusions or []
    available_categories = sorted({category for category, _ in recipes.values()})
    category_set = set(available_categories)
    selected_categories: list[str] = []
    selected: list[str] = []

    def add_categories(names: list[str]) -> None:
        for category in names:
            if category not in category_set:
                raise SelectionError(
                    f"unknown category '{category}'; available: {', '.join(available_categories)}"
                )
            if category not in selected_categories:
                selected_categories.append(category)
            selected.extend(
                name for name, (cat, _) in sorted(recipes.items()) if cat == category
            )

    if all_packages:
        # ALL discovers categories from recipes, so new categories join it
        # automatically. Toolchain stays excluded from normal package builds.
        add_categories([category for category in available_categories if category != "toolchain"])
    if core:
        add_categories(list(CORE_CATEGORIES))
    if categories:
        add_categories(categories)

    for name in package_names:
        if name not in recipes:
            raise SelectionError(f"no recipe named '{name}'")
        selected.append(name)

    resolved_flavors: list[str] = []
    if flavor_names:
        if "bootstrap" not in flavors:
            raise SelectionError("flavors.toml has no 'bootstrap' flavor required for flavor selection")
        bootstrap = set(flavor_module.resolve(flavors, recipes, "bootstrap"))
        toolchain_names = {
            name for name, (category, _) in recipes.items() if category == "toolchain"
        }
        for flavor_name in flavor_names:
            try:
                full = flavor_module.resolve(flavors, recipes, flavor_name)
            except flavor_module.FlavorError as exc:
                raise SelectionError(str(exc)) from exc
            resolved_flavors.append(flavor_name)
            # Keep current flavor behavior: include everything beyond bootstrap,
            # plus shared bootstrap toolchain packages so they remain published.
            selected.extend(name for name in full if name not in bootstrap)
            selected.extend(
                name for name in full if name in bootstrap and name in toolchain_names
            )

    if not selected and not allow_empty:
        raise SelectionError(
            "no package selection was made; select ALL, CORE, one or more categories, "
            "package names, or flavors"
        )

    deduplicated: list[str] = []
    seen: set[str] = set()
    for name in selected:
        if name not in seen:
            seen.add(name)
            deduplicated.append(name)

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
    counts: dict[str, int] = {}
    for name in final:
        category = recipes[name][0]
        counts[category] = counts.get(category, 0) + 1
    removed = excluded.intersection(deduplicated)
    return {
        "schema": 1,
        "source": source,
        "packages": final,
        "package_count": len(final),
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
    parser.add_argument("--core", action="store_true")
    parser.add_argument("--categories", nargs="*", default=[])
    parser.add_argument("--packages", default="", help="names separated by spaces or commas")
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
            args.all_packages or args.core or bool(args.categories)
            or bool(split_values(args.packages)) or bool(split_values(args.flavors))
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
                core=args.core,
                categories=args.categories,
                package_names=split_values(args.packages),
                flavor_names=split_values(args.flavors),
                exclusions=split_values(args.exclude),
            )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"Selected {plan['package_count']} package(s) from {plan['source']}.")
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
