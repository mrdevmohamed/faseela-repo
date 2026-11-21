#!/usr/bin/env python3
"""Audit every recipe for explicit schema-v5 runtime metadata.

This is deliberately report-first: an absent declaration is not silently
interpreted as an empty declaration, and the tool never invents package
relationships. Use --strict in the final schema-v5 publication gate.
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import Counter
from pathlib import Path

# These names intentionally have no current recipe: they are legacy package
# identities that current recipes may supersede during an upgrade.
LEGACY_PACKAGE_NAMES = {"eudev", "elogind", "dhcpcd", "wireless-tools"}


def audit(root: Path) -> dict:
    records = {}
    errors = []
    for path in sorted(root.rglob("recipe.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            errors.append({"path": str(path), "kind": "parse-error", "detail": str(exc)})
            continue
        package = data.get("package")
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            errors.append({"path": str(path), "kind": "missing-package-name"})
            continue
        name = package["name"]
        if name in records:
            errors.append({"path": str(path), "kind": "duplicate-package", "detail": name})
            continue
        records[name] = (path, data)

    missing = []
    relation_counts = Counter()
    for name, (path, data) in records.items():
        depends = data.get("depends")
        if not isinstance(depends, dict) or "run" not in depends:
            missing.append({"package": name, "path": str(path), "field": "depends.run"})
        elif not isinstance(depends["run"], list):
            errors.append({"package": name, "path": str(path), "kind": "invalid-depends.run"})

        capabilities = data.get("capabilities")
        if not isinstance(capabilities, dict) or "provides" not in capabilities:
            missing.append({"package": name, "path": str(path), "field": "capabilities.provides"})
        elif not isinstance(capabilities["provides"], list):
            errors.append({"package": name, "path": str(path), "kind": "invalid-capabilities.provides"})

        relations = data.get("relations")
        if not isinstance(relations, dict):
            missing.append({"package": name, "path": str(path), "field": "relations"})
            continue
        if relations.get("schema") != 1:
            errors.append({"package": name, "path": str(path), "kind": "invalid-relations-schema"})
        for field in ("conflicts", "replaces"):
            if field not in relations:
                missing.append({"package": name, "path": str(path), "field": f"relations.{field}"})
                continue
            values = relations[field]
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                errors.append({"package": name, "path": str(path), "kind": f"invalid-relations.{field}"})
                continue
            if len(values) != len(set(values)):
                errors.append({"package": name, "path": str(path), "kind": f"duplicate-relations.{field}"})
            for target in values:
                relation_counts[field] += 1
                if target == name:
                    errors.append({"package": name, "path": str(path), "kind": f"self-{field}"})
                elif target not in records and target not in LEGACY_PACKAGE_NAMES:
                    errors.append({"package": name, "path": str(path), "kind": f"unknown-{field}-target", "detail": target})

    return {
        "recipe_count": len(records),
        "missing_declarations": missing,
        "missing_count": len(missing),
        "missing_by_field": dict(Counter(item["field"] for item in missing)),
        "errors": errors,
        "error_count": len(errors),
        "relation_entries": dict(relation_counts),
        "complete": not missing and not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, default=Path("recipes"))
    parser.add_argument("--json", type=Path, help="write the complete audit report as JSON")
    parser.add_argument("--strict", action="store_true", help="fail if any declaration is missing")
    args = parser.parse_args()
    report = audit(args.recipes)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Schema-v5 metadata audit: {report['recipe_count']} recipes")
    print(f"  missing declarations: {report['missing_count']}")
    print(f"  missing by field: {report['missing_by_field']}")
    print(f"  invalid metadata/references: {report['error_count']}")
    print(f"  declared relations: {report['relation_entries']}")
    for item in report["errors"]:
        print("ERROR:", json.dumps(item, sort_keys=True))
    if args.strict:
        for item in report["missing_declarations"]:
            print("MISSING:", json.dumps(item, sort_keys=True))
    return 1 if report["error_count"] or (args.strict and report["missing_count"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
