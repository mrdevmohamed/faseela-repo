#!/usr/bin/env python3
"""Every recipe must be in the schema-v5 recipe form.

Guards against a recipe (or a generator/copy-paste) reintroducing the legacy
single-source fields, which Nawa's relations-aware recipe parser rejects.
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = "local:/nawa-package-relations-1-requires-a-newer-nawa"
LEGACY_KEYS = ("sha256", "source_dir", "mirrors")
SOURCE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
HEX64 = re.compile(r"[0-9a-f]{64}")

errors = []
count = 0
for path in sorted((ROOT / "recipes").glob("*/*/recipe.toml")):
    count += 1
    rel = path.relative_to(ROOT)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    pkg = data["package"]
    name = pkg["name"]

    if pkg.get("source") != MARKER:
        errors.append(f"{rel}: [package].source must be the relations marker, got {pkg.get('source')!r}")
    for key in LEGACY_KEYS:
        if key in pkg:
            errors.append(f"{rel}: legacy [package].{key} must move into [[package.sources]]")
    if not isinstance(pkg.get("rel"), int) or pkg["rel"] < 2:
        errors.append(f"{rel}: rel must be >= 2 (archive metadata changed in the schema-v5 migration)")

    relations = data.get("relations")
    if not isinstance(relations, dict) or relations.get("schema") != 1:
        errors.append(f"{rel}: [relations] with schema = 1 is required")
    else:
        for field in ("conflicts", "replaces"):
            if not isinstance(relations.get(field), list):
                errors.append(f"{rel}: [relations].{field} must be a list")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("provides"), list):
        errors.append(f"{rel}: [capabilities].provides must be a list")

    sources = pkg.get("sources", [])
    seen = set()
    for index, source in enumerate(sources):
        label = f"{rel}: sources[{index}]"
        if not SOURCE_NAME.fullmatch(source.get("name", "")):
            errors.append(f"{label}: invalid or missing name")
        if source.get("name") in seen:
            errors.append(f"{label}: duplicate name {source.get('name')!r}")
        seen.add(source.get("name"))
        if not source.get("url", "").startswith(("https://", "http://")):
            errors.append(f"{label}: url must be http(s); the sha256 pin is the integrity check")
        if not HEX64.fullmatch(source.get("sha256", "")):
            errors.append(f"{label}: sha256 must be 64 lowercase hex chars")
        if source.get("unpack") is False and source.get("strip_components"):
            errors.append(f"{label}: strip_components makes no sense with unpack = false")
    if "%{" in pkg.get("workdir", ""):
        errors.append(f"{rel}: workdir is not expanded by Nawa; write the literal path")

if errors:
    print("\n".join(errors[:60]))
    print(f"{len(errors)} schema-v5 recipe error(s) in {count} recipes")
    sys.exit(1)
print(f"{count} recipes are in the schema-v5 form")
