#!/usr/bin/env python3
"""Persist resumable schema-v5 PR build caches in draft GitHub Releases.

The release assets are not package-repository assets. They are private-to-the-
repository draft candidates, addressed only by the explicit PR build workflow
and consumed only after that PR has been merged and its build run is verified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_SCRIPT = SCRIPT_DIR / "pr-build-cache.py"
SPEC = importlib.util.spec_from_file_location("pr_build_cache", CACHE_SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("pr-build-release-cache: cannot load pr-build-cache.py")
CACHE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CACHE
SPEC.loader.exec_module(CACHE)

MANIFEST = CACHE.MANIFEST_NAME
CANDIDATE = "candidate.json"
TAG_PREFIX = "schema-v5-build-pr-"
TAG_RE = re.compile(r"schema-v5-build-pr-([1-9][0-9]*)-([A-Za-z0-9][A-Za-z0-9._-]*)-([0-9]{4})\Z")
MANIFEST_TAG_RE = re.compile(r"schema-v5-build-pr-([1-9][0-9]*)-manifest\Z")
ASSET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.nawa\.tar\.zst\Z")


class CacheReleaseError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flatten(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from flatten(item)
    elif isinstance(value, dict) and isinstance(value.get("tag_name"), str):
        yield value


def read_releases(path: Path) -> dict[str, dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheReleaseError(f"cannot read GitHub release metadata: {exc}") from exc
    return {item["tag_name"]: item for item in flatten(value)}


def assets(release: dict | None) -> dict[str, dict]:
    if not release:
        return {}
    result = {}
    for item in release.get("assets", []):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result[item["name"]] = item
    return result


def digest_from_asset(asset: dict) -> str | None:
    value = asset.get("digest")
    if isinstance(value, str) and value.startswith("sha256:"):
        digest = value.removeprefix("sha256:")
        if re.fullmatch(r"[0-9a-f]{64}", digest):
            return digest
    return None


def cache_entries(recipes_root: Path, cache_dir: Path) -> list[dict]:
    recipes = CACHE.load_recipes(recipes_root)
    keys = CACHE.build_keys(recipes)
    manifest = CACHE.read_manifest(cache_dir)
    selected: list[dict] = []
    seen: set[str] = set()
    for entry in manifest:
        checked = CACHE.valid_entry(entry, recipes, keys, cache_dir)
        if checked is None:
            raise CacheReleaseError(
                f"cache entry failed current recipe/build-dependency/SHA-256 validation: {entry.get('name', '<unknown>')}"
            )
        recipe, archive_path, split_paths = checked
        if recipe.name in seen:
            raise CacheReleaseError(f"duplicate package in cache manifest: {recipe.name}")
        seen.add(recipe.name)
        category = recipe.directory.relative_to(recipes_root).parts[0]
        files = [archive_path, *(path for _, path in split_paths)]
        for path in files:
            if not ASSET_RE.fullmatch(path.name):
                raise CacheReleaseError(f"unsafe package archive name: {path.name}")
        selected.append({
            "name": recipe.name,
            "category": category,
            "files": [str(path) for path in files],
        })
    return sorted(selected, key=lambda item: (item["category"], item["name"]))


def build_plan(
    recipes_root: Path,
    cache_dir: Path,
    releases_path: Path,
    repository: str,
    pr_number: int,
    run_id: int,
    head_sha: str,
    out_dir: Path,
    max_assets: int = 900,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise CacheReleaseError("repository must be OWNER/NAME")
    if pr_number < 1 or run_id < 1:
        raise CacheReleaseError("PR number and build run ID must be positive")
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise CacheReleaseError("head SHA must be a 40-character lowercase commit ID")
    if not 1 <= max_assets <= 900:
        raise CacheReleaseError("max-assets must be in range 1..900")

    entries = cache_entries(recipes_root, cache_dir)
    groups: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        groups[entry["category"]].extend(entry["files"])

    releases = read_releases(releases_path)
    desired: dict[str, list[Path]] = {}
    for category, names in sorted(groups.items()):
        names = sorted(set(names))
        for offset in range(0, len(names), max_assets):
            shard_no = offset // max_assets + 1
            tag = f"{TAG_PREFIX}{pr_number}-{category}-{shard_no:04d}"
            desired[tag] = [Path(path) for name in names[offset:offset + max_assets]
                            for path in (cache_dir / name,)]

    manifest_tag = f"{TAG_PREFIX}{pr_number}-manifest"
    plan_uploads: dict[str, list[str]] = {}
    cleanup: list[dict[str, str]] = []
    create_releases = []
    desired_tags = set(desired) | {manifest_tag}

    for tag, paths in sorted(desired.items()):
        release = releases.get(tag)
        if release is None:
            create_releases.append(tag)
        elif release.get("draft") is not True:
            raise CacheReleaseError(f"refusing to use non-draft cache release: {tag}")
        existing = assets(release)
        wanted = {path.name for path in paths}
        for path in paths:
            actual = sha256_file(path)
            current = existing.get(path.name)
            if current is None or digest_from_asset(current) != actual:
                plan_uploads.setdefault(tag, []).append(str(path))
        for old_name in sorted(set(existing) - wanted):
            cleanup.append({"tag": tag, "name": old_name})

    for old_tag, release in sorted(releases.items()):
        match = TAG_RE.fullmatch(old_tag)
        if not match or int(match.group(1)) != pr_number or old_tag in desired_tags:
            continue
        for old_name in sorted(assets(release)):
            cleanup.append({"tag": old_tag, "name": old_name})

    manifest_path = cache_dir / MANIFEST
    if not manifest_path.is_file():
        raise CacheReleaseError(f"cache manifest is missing: {manifest_path}")
    manifest_digest = sha256_file(manifest_path)
    candidate = {
        "schema": 1,
        "pr_number": pr_number,
        "build_run_id": run_id,
        "head_sha": head_sha,
        "manifest_sha256": manifest_digest,
        "shards": sorted(desired),
        "package_count": len(entries),
        "archive_count": sum(len(item["files"]) for item in entries),
    }
    candidate_path = cache_dir / CANDIDATE
    candidate_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_release = releases.get(manifest_tag)
    if manifest_release is None:
        create_releases.append(manifest_tag)
    elif manifest_release.get("draft") is not True:
        raise CacheReleaseError(f"refusing to use non-draft cache manifest release: {manifest_tag}")
    current_manifest_assets = assets(manifest_release)
    if digest_from_asset(current_manifest_assets.get(MANIFEST, {})) != manifest_digest:
        plan_uploads.setdefault(manifest_tag, []).append(str(manifest_path))
    candidate_digest = sha256_file(candidate_path)
    if digest_from_asset(current_manifest_assets.get(CANDIDATE, {})) != candidate_digest:
        plan_uploads.setdefault(manifest_tag, []).append(str(candidate_path))
    for old_name in sorted(set(current_manifest_assets) - {MANIFEST, CANDIDATE}):
        cleanup.append({"tag": manifest_tag, "name": old_name})

    plan = {
        "schema": 1,
        "repository": repository,
        "pr_number": pr_number,
        "build_run_id": run_id,
        "head_sha": head_sha,
        "manifest_tag": manifest_tag,
        "create_releases": sorted(set(create_releases)),
        "uploads": {tag: sorted(paths) for tag, paths in sorted(plan_uploads.items())},
        "cleanup": cleanup,
        "shards": sorted(desired),
        "candidate_path": str(candidate_path),
        "manifest_path": str(manifest_path),
        "package_count": len(entries),
        "archive_count": sum(len(item["files"]) for item in entries),
    }
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    out_dir.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def read_plan(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheReleaseError(f"cannot read release-cache plan: {exc}") from exc
    if value.get("schema") != 1:
        raise CacheReleaseError("unsupported release-cache plan schema")
    return value


def verify_candidate(
    candidate_path: Path,
    manifest_path: Path,
    pr_number: int,
    build_run_id: int | None = None,
    head_sha: str | None = None,
) -> dict:
    try:
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheReleaseError(f"cannot read candidate metadata: {exc}") from exc
    if candidate.get("schema") != 1 or candidate.get("pr_number") != pr_number:
        raise CacheReleaseError("candidate metadata is for another PR or schema")
    if build_run_id is not None and candidate.get("build_run_id") != build_run_id:
        raise CacheReleaseError("candidate cache was not published by the selected successful build run")
    if head_sha is not None and candidate.get("head_sha") != head_sha:
        raise CacheReleaseError("candidate cache does not match the selected PR head SHA")
    expected = candidate.get("manifest_sha256")
    if not isinstance(expected, str) or expected != sha256_file(manifest_path):
        raise CacheReleaseError("candidate cache manifest digest does not match candidate.json")
    shards = candidate.get("shards")
    if (
        not isinstance(shards, list)
        or any(
            not isinstance(tag, str)
            or TAG_RE.fullmatch(tag) is None
            or int(TAG_RE.fullmatch(tag).group(1)) != pr_number
            for tag in shards
        )
        or len(shards) != len(set(shards))
    ):
        raise CacheReleaseError("candidate contains invalid PR cache shard tags")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="plan draft-release uploads for a PR build cache")
    plan.add_argument("--recipes", type=Path, required=True)
    plan.add_argument("--cache-dir", type=Path, required=True)
    plan.add_argument("--releases-json", type=Path, required=True)
    plan.add_argument("--repository", required=True)
    plan.add_argument("--pr-number", type=int, required=True)
    plan.add_argument("--run-id", type=int, required=True)
    plan.add_argument("--head-sha", required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--max-assets", type=int, default=900)

    for command_name in ("create", "shards", "uploads", "cleanup", "manifest-tag"):
        command = sub.add_parser(command_name)
        command.add_argument("--plan", type=Path, required=True)
        if command_name in {"uploads", "cleanup"}:
            command.add_argument("--tag")

    verify = sub.add_parser("verify-candidate")
    verify.add_argument("--candidate", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--pr-number", type=int, required=True)
    verify.add_argument("--build-run-id", type=int)
    verify.add_argument("--head-sha")

    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = build_plan(
                args.recipes, args.cache_dir, args.releases_json, args.repository,
                args.pr_number, args.run_id, args.head_sha, args.output, args.max_assets,
            )
            print(
                f"PR release cache: {result['package_count']} package(s), "
                f"{result['archive_count']} archive(s), "
                f"{sum(map(len, result['uploads'].values()))} upload(s), "
                f"{len(result['create_releases'])} draft release(s) to create"
            )
        elif args.command == "verify-candidate":
            verify_candidate(
                args.candidate, args.manifest, args.pr_number, args.build_run_id, args.head_sha
            )
            print("PR release-cache candidate identity and manifest digest verified.")
        else:
            value = read_plan(args.plan)
            if args.command == "create":
                for tag in value["create_releases"]:
                    print(tag)
            elif args.command == "shards":
                for tag in value["shards"]:
                    print(tag)
            elif args.command == "manifest-tag":
                print(value["manifest_tag"])
            elif args.command == "uploads":
                for path in value["uploads"].get(args.tag, []):
                    print(path)
            elif args.command == "cleanup":
                for item in value["cleanup"]:
                    if args.tag is None or item["tag"] == args.tag:
                        print(f"{item['tag']}\t{item['name']}")
        return 0
    except (CacheReleaseError, CACHE.CacheError, OSError, ValueError, KeyError) as exc:
        print(f"::error::pr-build-release-cache: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
