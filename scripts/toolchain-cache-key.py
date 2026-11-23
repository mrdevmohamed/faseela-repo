#!/usr/bin/env python3
"""Print the cache key for Bootstrap Toolchain (Stage 3) outputs.

The Stage 1/2/3 bootstrap takes the better part of an hour and is a pure
function of: the distribution tooling revision, every recipe tree in the
bootstrap flavor and in recipes/toolchain (including their recursive build
dependencies), the flavor definitions, the isolation mode and the Stage 3
package selection. Whatever feeds that function is hashed here, so a cache
hit means the archives that would be rebuilt are already the right ones.

A week stamp is mixed in on purpose: the seed toolchain is assembled from
unpinned upstream packages at build time, so the cache is refreshed weekly
rather than trusted forever.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipe_keys as _cache  # noqa: E402

VERSION = "v1"


def toolchain_key(
    recipes_root: Path,
    bootstrap_packages: list[str],
    toolchain_packages: list[str],
    flavors_file: Path,
    tooling_rev: str,
    isolation: str,
    week: str,
) -> str:
    recipes = _cache.load_recipes(recipes_root)
    keys = _cache.build_keys(recipes)
    names = set(bootstrap_packages) | set(toolchain_packages)
    # Any toolchain recipe can change the resolved Stage 3 output set.
    names |= {name for name, recipe in recipes.items() if recipe.directory.parent.name == "toolchain"}
    missing = sorted(name for name in names if name not in recipes)
    if missing:
        raise SystemExit(f"toolchain-cache-key: no recipe for: {' '.join(missing)}")

    digest = hashlib.sha256()

    def feed(label: str, value: str) -> None:
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")

    feed("version", VERSION)
    feed("tooling", tooling_rev)
    feed("isolation", isolation)
    feed("week", week)
    feed("selection", " ".join(sorted(set(toolchain_packages))))
    feed("flavors", hashlib.sha256(flavors_file.read_bytes()).hexdigest())
    for name in sorted(names):
        feed(f"recipe:{name}", keys[name])
    return f"bootstrap-toolchain-{VERSION}-{digest.hexdigest()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--bootstrap-list", type=Path, required=True)
    parser.add_argument("--toolchain-packages", default="")
    parser.add_argument("--flavors", type=Path, required=True)
    parser.add_argument("--tooling-rev", required=True)
    parser.add_argument("--isolation", required=True)
    parser.add_argument("--week", required=True)
    args = parser.parse_args(argv)
    bootstrap = args.bootstrap_list.read_text(encoding="utf-8").split()
    if not bootstrap:
        raise SystemExit("toolchain-cache-key: the bootstrap package list is empty")
    if not args.tooling_rev.strip():
        raise SystemExit("toolchain-cache-key: the tooling revision is empty")
    print(
        toolchain_key(
            args.recipes,
            bootstrap,
            args.toolchain_packages.split(),
            args.flavors,
            args.tooling_rev.strip(),
            args.isolation,
            args.week,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
