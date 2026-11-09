#!/usr/bin/env python3
"""Validate the published package-group catalog against the recipe tree."""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "groups.toml"
ID_RE = re.compile(r"^[A-Za-z0-9+_.-]+$")


def fail(message: str) -> None:
    print(f"check-groups: error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    try:
        data = tomllib.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"cannot read {CATALOG.relative_to(ROOT)}: {exc}")

    groups = data.get("group")
    if not isinstance(groups, list) or not groups:
        fail("groups.toml must contain at least one [[group]] definition")

    recipes = {
        path.parent.name
        for path in (ROOT / "recipes").glob("*/*/recipe.toml")
        if path.is_file()
    }
    seen_ids: set[str] = set()
    total_members = 0
    for position, group in enumerate(groups, 1):
        if not isinstance(group, dict):
            fail(f"group #{position} is not a TOML table")
        group_id = group.get("id")
        name = group.get("name")
        if not isinstance(group_id, str) or not ID_RE.fullmatch(group_id):
            fail(f"group #{position} has an invalid id: {group_id!r}")
        if group_id in seen_ids:
            fail(f"duplicate group id: {group_id}")
        seen_ids.add(group_id)
        if group.get("schema") != 1:
            fail(f"group {group_id}: schema must equal 1")
        if not isinstance(name, str) or not name.strip():
            fail(f"group {group_id}: name must be a non-empty string")
        if not isinstance(group.get("description", ""), str):
            fail(f"group {group_id}: description must be a string")

        member_count = 0
        for category in ("mandatory", "default", "optional"):
            members = group.get(category, [])
            if not isinstance(members, list) or any(not isinstance(p, str) for p in members):
                fail(f"group {group_id}: {category} must be a string array")
            if len(members) != len(set(members)):
                fail(f"group {group_id}: duplicate package in {category}")
            for package in members:
                if not ID_RE.fullmatch(package):
                    fail(f"group {group_id}: invalid package name {package!r}")
                if package not in recipes:
                    fail(f"group {group_id}: package {package!r} has no recipe")
            member_count += len(members)
        if member_count == 0:
            fail(f"group {group_id}: no packages are defined")
        total_members += member_count

    print(f"check-groups: {len(groups)} group(s), {total_members} package selections; all recipes exist")


if __name__ == "__main__":
    main()
