#!/usr/bin/env python3
"""Plan immutable GitHub Release shards for Nawa's schema-v3 repository.

The stable release carries only index.toml + its signature. Package and recipe
archives live in packages-NNNN releases; the signed v3 index stores each
archive's HTTPS browser URL. This avoids GitHub's per-release 1,000-asset cap.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

PACKAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.nawa\.tar\.zst\Z")
PACKAGE_SIG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.nawa\.tar\.zst\.sig\Z")
RECIPES_RE = re.compile(r"recipes-[A-Za-z0-9._-]+\.recipes\.tar\.zst\Z")
SHARD_RE = re.compile(r"packages-(\d{4,})\Z")


def flatten(value):
    if isinstance(value, list):
        for item in value:
            yield from flatten(item)
    elif isinstance(value, dict) and isinstance(value.get("tag_name"), str):
        yield value


def read_releases(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"distributed-releases: cannot read release metadata: {exc}") from exc
    return list(flatten(raw))


def asset_names(release: dict) -> list[str]:
    return [
        str(asset.get("name", ""))
        for asset in release.get("assets", [])
        if isinstance(asset, dict) and asset.get("name")
    ]


def is_archive(name: str) -> bool:
    return bool(PACKAGE_RE.fullmatch(name) or RECIPES_RE.fullmatch(name))


def is_shard(tag: str) -> bool:
    return bool(SHARD_RE.fullmatch(tag))


def list_published(releases: list[dict], stable_tag: str) -> list[tuple[str, str]]:
    # Prefer a packages-NNNN copy to a legacy copy still present in stable.
    # If duplicated across shards, pick the lowest shard number deterministically.
    found: dict[str, tuple[tuple[int, int], str]] = {}
    for release in releases:
        tag = release["tag_name"]
        if tag != stable_tag and not is_shard(tag):
            continue
        priority = (0, int(SHARD_RE.fullmatch(tag).group(1))) if is_shard(tag) else (1, 0)
        for name in asset_names(release):
            if not PACKAGE_RE.fullmatch(name):
                continue
            current = found.get(name)
            if current is None or priority < current[0]:
                found[name] = (priority, tag)
    return sorted(
        ((tag, name) for name, (_, tag) in found.items()),
        key=lambda item: item[1],
    )


def quote_toml(value: str) -> str:
    # JSON basic strings are valid TOML basic strings for these ASCII URLs/names.
    return json.dumps(value, ensure_ascii=True)


def build_plan(
    releases: list[dict],
    repo_dir: Path,
    repository: str,
    stable_tag: str,
    recipe_file: str,
    max_assets: int,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise SystemExit("distributed-releases: repository must be owner/name")
    if max_assets < 1 or max_assets > 900:
        raise SystemExit("distributed-releases: max-assets must be in the range 1..900")
    if recipe_file and not RECIPES_RE.fullmatch(recipe_file):
        raise SystemExit(f"distributed-releases: unsafe recipe archive name: {recipe_file!r}")

    packages = sorted(p.name for p in repo_dir.glob("*.nawa.tar.zst") if p.is_file())
    for name in packages:
        if not PACKAGE_RE.fullmatch(name):
            raise SystemExit(f"distributed-releases: unsafe package archive name: {name!r}")
    desired = packages + ([recipe_file] if recipe_file else [])
    desired_set = set(desired)

    shard_releases = {
        release["tag_name"]: release
        for release in releases
        if is_shard(release["tag_name"])
    }
    shard_tags = sorted(
        shard_releases,
        key=lambda tag: int(SHARD_RE.fullmatch(tag).group(1)),
    )
    counts = {tag: len(asset_names(shard_releases[tag])) for tag in shard_tags}
    locations: dict[str, list[str]] = defaultdict(list)
    for tag in shard_tags:
        for name in asset_names(shard_releases[tag]):
            if is_archive(name):
                locations[name].append(tag)

    assignments: dict[str, str] = {}
    uploads: dict[str, list[str]] = defaultdict(list)
    create_releases: set[str] = set()
    cleanup: set[tuple[str, str]] = set()

    next_number = max(
        (int(SHARD_RE.fullmatch(tag).group(1)) for tag in shard_tags),
        default=0,
    ) + 1

    def allocate() -> str:
        nonlocal next_number
        for tag in reversed(shard_tags):
            if counts[tag] < max_assets:
                return tag
        tag = f"packages-{next_number:04d}"
        next_number += 1
        shard_tags.append(tag)
        counts[tag] = 0
        create_releases.add(tag)
        return tag

    for name in desired:
        existing = sorted(
            locations.get(name, []),
            key=lambda tag: int(SHARD_RE.fullmatch(tag).group(1)),
        )
        if existing:
            selected = existing[0]
            assignments[name] = selected
            for duplicate in existing[1:]:
                cleanup.add((duplicate, name))
            continue
        selected = allocate()
        assignments[name] = selected
        uploads[selected].append(name)
        counts[selected] += 1

    for tag in sorted(shard_releases, key=lambda t: int(SHARD_RE.fullmatch(t).group(1))):
        for name in asset_names(shard_releases[tag]):
            if PACKAGE_SIG_RE.fullmatch(name):
                cleanup.add((tag, name))
            elif is_archive(name) and (name not in desired_set or assignments.get(name) != tag):
                cleanup.add((tag, name))

    legacy_cleanup: list[str] = []
    for release in releases:
        if release["tag_name"] != stable_tag:
            continue
        for name in asset_names(release):
            if PACKAGE_RE.fullmatch(name) or PACKAGE_SIG_RE.fullmatch(name) or RECIPES_RE.fullmatch(name):
                legacy_cleanup.append(name)

    locations_toml = ["schema = 1", "", "[package_urls]"]
    for name in packages:
        tag = assignments[name]
        url = f"https://github.com/{repository}/releases/download/{tag}/{quote(name, safe='._+-')}"
        locations_toml.append(f"{quote_toml(name)} = {quote_toml(url)}")
    if recipe_file:
        tag = assignments[recipe_file]
        url = f"https://github.com/{repository}/releases/download/{tag}/{quote(recipe_file, safe='._+-')}"
        locations_toml.extend(["", "[recipe_urls]", f"{quote_toml(recipe_file)} = {quote_toml(url)}"])

    return {
        "schema": 1,
        "repository": repository,
        "stable_tag": stable_tag,
        "max_assets": max_assets,
        "archive_count": len(packages),
        "recipe_file": recipe_file,
        "assignments": assignments,
        "uploads": {tag: sorted(names) for tag, names in sorted(uploads.items())},
        "create_releases": sorted(
            create_releases, key=lambda tag: int(SHARD_RE.fullmatch(tag).group(1))
        ),
        "cleanup": [
            {"tag": tag, "name": name}
            for tag, name in sorted(cleanup)
        ],
        "legacy_cleanup": sorted(set(legacy_cleanup)),
        "locations_toml": "\n".join(locations_toml) + "\n",
    }


def cmd_list(args) -> int:
    for tag, name in list_published(read_releases(args.releases_json), args.stable_tag):
        print(f"{tag}\t{name}")
    return 0


def cmd_plan(args) -> int:
    plan = build_plan(
        read_releases(args.releases_json),
        args.repo_dir,
        args.repository,
        args.stable_tag,
        args.recipe_file,
        args.max_assets,
    )
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.manifest.write_text(plan.pop("locations_toml"), encoding="utf-8")
    print(
        f"distributed-releases: {plan['archive_count']} package archive(s), "
        f"{len(plan['assignments'])} indexed archive(s), "
        f"{sum(map(len, plan['uploads'].values()))} upload(s), "
        f"{len(plan['create_releases'])} new shard(s), "
        f"{len(plan['cleanup']) + len(plan['legacy_cleanup'])} post-index cleanup(s)"
    )
    return 0


def load_plan(path: Path) -> dict:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"distributed-releases: cannot read plan: {exc}") from exc
    if plan.get("schema") != 1:
        raise SystemExit("distributed-releases: unsupported plan schema")
    return plan


def cmd_create(args) -> int:
    for tag in load_plan(args.plan)["create_releases"]:
        print(tag)
    return 0


def cmd_uploads(args) -> int:
    plan = load_plan(args.plan)
    for name in plan.get("uploads", {}).get(args.tag, []):
        print(str(args.repo_dir / name))
    return 0


def cmd_cleanup(args) -> int:
    plan = load_plan(args.plan)
    if args.kind == "shards":
        for item in plan.get("cleanup", []):
            print(f"{item['tag']}\t{item['name']}")
    else:
        for name in plan.get("legacy_cleanup", []):
            print(f"{plan['stable_tag']}\t{name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list published package archives and their release tags")
    listing.add_argument("--releases-json", type=Path, required=True)
    listing.add_argument("--stable-tag", required=True)
    listing.set_defaults(func=cmd_list)

    plan = sub.add_parser("plan", help="plan shard allocation and write a v3 locations manifest")
    plan.add_argument("--releases-json", type=Path, required=True)
    plan.add_argument("--repo-dir", type=Path, required=True)
    plan.add_argument("--repository", required=True)
    plan.add_argument("--stable-tag", required=True)
    plan.add_argument("--recipe-file", default="")
    plan.add_argument("--max-assets", type=int, default=900)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--manifest", type=Path, required=True)
    plan.set_defaults(func=cmd_plan)

    create = sub.add_parser("create", help="print newly required shard release tags")
    create.add_argument("--plan", type=Path, required=True)
    create.set_defaults(func=cmd_create)

    uploads = sub.add_parser("uploads", help="print local upload paths for one shard")
    uploads.add_argument("--plan", type=Path, required=True)
    uploads.add_argument("--repo-dir", type=Path, required=True)
    uploads.add_argument("--tag", required=True)
    uploads.set_defaults(func=cmd_uploads)

    cleanup = sub.add_parser("cleanup", help="print assets to delete after publishing the new index")
    cleanup.add_argument("--plan", type=Path, required=True)
    cleanup.add_argument("--kind", choices=("shards", "legacy"), required=True)
    cleanup.set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
