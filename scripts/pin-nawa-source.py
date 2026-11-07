#!/usr/bin/env python3
"""Pin the Nawa recipe to one commit from github.com/mrdevmohamed/nawa.

Usage:
    python3 scripts/pin-nawa-source.py
    python3 scripts/pin-nawa-source.py <full-40-character-commit>
"""
import hashlib
import io
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "mrdevmohamed/nawa"
RECIPE = ROOT / "recipes" / "base" / "nawa" / "recipe.toml"
SOURCE_NAME = "nawa"


def replace_once(text, pattern, replacement, description):
    updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.M)
    if count != 1:
        sys.exit(f"pin-nawa-source: expected exactly one {description} in {RECIPE}")
    return updated


def replace_source_field(text, field, value):
    pattern = (
        r'(?ms)(^\[\[package\.sources\]\]\s*\n'
        r'name = "' + re.escape(SOURCE_NAME) + r'"\s*\n'
        r'.*?^' + re.escape(field) + r' = ")[^"]+(")'
    )
    updated, count = re.subn(
        pattern,
        lambda match: match.group(1) + value + match.group(2),
        text,
        count=1,
    )
    if count != 1:
        sys.exit(f"pin-nawa-source: no {field} field in source {SOURCE_NAME!r}")
    return updated


def main():
    if len(sys.argv) > 2 or sys.argv[1:] in (["-h"], ["--help"]):
        sys.exit(__doc__)

    if len(sys.argv) == 2:
        commit = sys.argv[1].lower()
    else:
        result = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{REPO}", "HEAD"],
            check=True, capture_output=True, text=True,
        )
        commit = result.stdout.split()[0].lower()

    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        sys.exit("pin-nawa-source: commit must be a full 40-character SHA")

    url = f"https://github.com/{REPO}/archive/{commit}.tar.gz"
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as response:
        data = response.read()

    sha256 = hashlib.sha256(data).hexdigest()
    top = f"nawa-{commit}"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        cargo_file = archive.extractfile(f"{top}/Cargo.toml")
        if cargo_file is None:
            sys.exit("pin-nawa-source: Cargo.toml missing from upstream archive")
        cargo_toml = cargo_file.read().decode("utf-8")

    version_match = re.search(r'(?m)^version = "([^"]+)"', cargo_toml)
    if not version_match:
        sys.exit("pin-nawa-source: package version missing from Cargo.toml")
    version = version_match.group(1)

    recipe = RECIPE.read_text(encoding="utf-8")
    old_version_match = re.search(r'(?m)^version = "([^"]*)"$', recipe)
    old_rel_match = re.search(r"(?m)^rel = (\d+)$", recipe)
    source_match = re.search(
        r'(?ms)^\[\[package\.sources\]\]\s*\n'
        r'name = "' + re.escape(SOURCE_NAME) + r'"\s*\n(.*?)(?=^\[|\Z)',
        recipe,
    )
    if not old_version_match or not old_rel_match or not source_match:
        sys.exit("pin-nawa-source: recipe is missing version, rel, or named source entry")

    old_sha_match = re.search(r'(?m)^sha256 = "([^"]+)"$', source_match.group(1))
    if not old_sha_match:
        sys.exit("pin-nawa-source: sha256 missing from named source entry")

    old_version = old_version_match.group(1)
    old_rel = int(old_rel_match.group(1))
    old_sha = old_sha_match.group(1)
    rel = 1 if old_version != version else (old_rel if old_sha == sha256 else old_rel + 1)

    recipe = replace_once(recipe, r'^version = ".*"$', f'version = "{version}"', "version")
    recipe = replace_once(recipe, r"^rel = \d+$", f"rel = {rel}", "rel")
    recipe = replace_source_field(recipe, "url", url)
    recipe = replace_source_field(recipe, "sha256", sha256)

    RECIPE.write_text(recipe, encoding="utf-8")
    print(f"nawa: version {version} rel {rel} -> {commit[:12]}  sha256 {sha256}")


if __name__ == "__main__":
    main()
