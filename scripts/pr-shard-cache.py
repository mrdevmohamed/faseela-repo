#!/usr/bin/env python3
"""Exchange package archives between the parallel shards of one build.

A sharded build (plan-build-shards.py) runs its shards on different runners at
the same time, so the single-writer manifest of pr-build-cache.py cannot be
used while they run. Here every shard only ADDS files that nobody else writes:

  * archives go to draft releases   <prefix>-<category>-NNNN   (one asset per
    archive; the name already contains version and rel);
  * a shard's record of what it built goes to the state release
    <prefix>-manifest as   entries-<shard>.json   (a name nobody else uses).

Readers (the next wave, the final job, a re-run of the workflow) rebuild the
picture from those files: an entry is usable only if the recipe, its archive
name and its build key (recipe tree + build dependencies, see pr-build-cache.py)
still match the checked-out recipes and the asset exists in a cache release
with the recorded SHA-256. The legacy single-writer `manifest.json` written by
`merge` is read as one more set of entries, so caches made before sharding keep
working and `merge` leaves exactly the layout publish-schema-v5.py expects.

Pull requests use the prefix  schema-v5-build-pr-<N>  (kept across runs: that is
the resume cache). Other runs use  faseela-build-run-<run id>  and delete it
with `drop` once published.

Commands (all talk to GitHub through the `gh` CLI, set GH_BIN to replace it):
  valid-stems  print the archive stems the cache can supply (planning)
  restore      download the usable archives of the given packages into out-dir
  save         upload the archives this shard built and its entries file
  merge        write manifest.json + candidate.json, report shard status
  drop         delete a run-scoped cache
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("pr_build_cache", SCRIPT_DIR / "pr-build-cache.py")
CACHE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = CACHE
_SPEC.loader.exec_module(CACHE)  # type: ignore[union-attr]

MAX_ASSETS = 900  # GitHub's hard limit is 1000 assets per release
PREFIX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SHARD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
ENTRIES_RE = re.compile(r"entries-([A-Za-z0-9][A-Za-z0-9_-]*)\.json\Z")
PR_PREFIX_RE = re.compile(r"schema-v5-build-pr-([1-9][0-9]*)\Z")
MAX_BYTES = 2 * 1024 * 1024 * 1024


class ShardCacheError(RuntimeError):
    pass


# ---------------------------------------------------------------- GitHub ----

def gh(*args: str, capture: bool = False, check: bool = True) -> str:
    cmd = [os.environ.get("GH_BIN", "gh"), *args]
    result = subprocess.run(cmd, check=False, text=True,
                            stdout=subprocess.PIPE if capture else None)
    if check and result.returncode != 0:
        raise ShardCacheError(f"{' '.join(cmd[:4])} failed with exit {result.returncode}")
    return result.stdout if capture else ""


def retry(action, what: str, attempts: int = 3):
    for number in range(1, attempts + 1):
        try:
            return action()
        except ShardCacheError as exc:
            if number == attempts:
                raise ShardCacheError(f"{what}: {exc}") from exc
            print(f"{what}: attempt {number} failed, retrying", file=sys.stderr)
            time.sleep(number * 10 if os.environ.get("GH_BIN") is None else 0)


def list_releases(repo: str, prefix: str) -> dict[str, dict[str, dict]]:
    """tag -> {asset name -> asset} for every release whose tag starts with prefix-."""
    text = gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100", capture=True)
    value = json.loads(text or "[]")
    result: dict[str, dict[str, dict]] = {}

    def walk(item):
        if isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, dict) and isinstance(item.get("tag_name"), str):
            tag = item["tag_name"]
            if tag.startswith(prefix + "-"):
                result[tag] = {a["name"]: a for a in item.get("assets", []) if isinstance(a, dict) and "name" in a}

    walk(value)
    return result


def asset_digest(asset: dict) -> str | None:
    value = asset.get("digest")
    if isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value[7:]
    return None


def ensure_release(repo: str, tag: str, notes: str) -> None:
    if subprocess.run([os.environ.get("GH_BIN", "gh"), "release", "view", tag, "--repo", repo],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return
    # Parallel shards race here: losing the race is fine as long as it exists afterwards.
    subprocess.run([os.environ.get("GH_BIN", "gh"), "release", "create", tag, "--repo", repo, "--draft",
                    "--title", tag, "--notes", notes], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    gh("release", "view", tag, "--repo", repo, capture=True)


# ----------------------------------------------------------------- state ----

def state_tag(prefix: str) -> str:
    return f"{prefix}-manifest"


def check_prefix(prefix: str) -> str:
    if not PREFIX_RE.fullmatch(prefix):
        raise ShardCacheError(f"unsafe cache prefix: {prefix!r}")
    return prefix


def load_entry_files(directory: Path) -> list[dict]:
    """Entries of manifest.json and every entries-*.json in a directory."""
    entries: list[dict] = []
    manifest = directory / CACHE.MANIFEST_NAME
    if manifest.is_file():
        entries += [dict(e) for e in CACHE.read_manifest(directory)]
    for path in sorted(directory.glob("entries-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            entries += [dict(e, shard=value.get("shard", path.stem)) for e in value.get("entries", [])]
        except (OSError, ValueError, AttributeError, TypeError):
            print(f"::warning::ignoring unreadable {path.name}", file=sys.stderr)
    return entries


def fetch_state(repo: str, prefix: str, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tag = state_tag(prefix)
    probe = subprocess.run([os.environ.get("GH_BIN", "gh"), "release", "view", tag, "--repo", repo],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode != 0:
        return
    for pattern in (CACHE.MANIFEST_NAME, "entries-*.json"):
        # a missing pattern is normal (no shard has saved yet): do not fail on it
        subprocess.run([os.environ.get("GH_BIN", "gh"), "release", "download", tag, "--repo", repo,
                        "--pattern", pattern, "--dir", str(directory), "--clobber"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def usable(entries: list[dict], recipes: dict, keys: dict[str, str],
           releases: dict[str, dict[str, dict]]) -> dict[str, dict]:
    """name -> entry whose recipe, key and cached assets all still match."""
    where: dict[str, tuple[str, dict]] = {}
    for tag, assets in releases.items():
        for name, asset in assets.items():
            where[name] = (tag, asset)
    result: dict[str, dict] = {}
    for entry in entries:
        name, archive = entry.get("name"), entry.get("archive")
        recipe = recipes.get(name) if isinstance(name, str) else None
        digest = entry.get("archive_sha256")
        if (recipe is None or recipe.archive != archive or keys.get(name) != entry.get("build_key")
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            continue
        located = where.get(archive)
        if located is None or (asset_digest(located[1]) not in (None, digest)):
            continue
        splits = []
        expected = {recipe.split_archive("doc"), recipe.split_archive("lang")}
        ok = True
        for split in entry.get("split_archives", []):
            sname, sdigest = split.get("archive"), split.get("archive_sha256")
            slocated = where.get(sname) if isinstance(sname, str) else None
            if (sname not in expected or slocated is None
                    or not isinstance(sdigest, str) or asset_digest(slocated[1]) not in (None, sdigest)):
                ok = False
                break
            splits.append(split)
        if not ok:
            continue
        result[name] = dict(entry, split_archives=splits)
    return result


def context(args):
    check_prefix(args.prefix)
    recipes = CACHE.load_recipes(args.recipes)
    keys = CACHE.build_keys(recipes)
    return recipes, keys


# -------------------------------------------------------------- commands ----

def cmd_valid_stems(args) -> int:
    recipes, keys = context(args)
    with tempfile.TemporaryDirectory() as tmp:
        fetch_state(args.repo, args.prefix, Path(tmp))
        good = usable(load_entry_files(Path(tmp)), recipes, keys, list_releases(args.repo, args.prefix))
    for name in sorted(good):
        print(recipes[name].archive.removesuffix(".nawa.tar.zst"))
    return 0


def cmd_restore(args) -> int:
    recipes, keys = context(args)
    wanted = set(args.names.split())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    releases = list_releases(args.repo, args.prefix)
    where = {name: tag for tag, assets in releases.items() for name in assets}
    with tempfile.TemporaryDirectory() as tmp:
        fetch_state(args.repo, args.prefix, Path(tmp))
        good = usable(load_entry_files(Path(tmp)), recipes, keys, releases)
    selected = [n for n in sorted(good)
                if args.all or n in wanted or (args.with_toolchain and good[n].get("toolchain"))]
    wanted_files = []
    for name in selected:
        entry = good[name]
        wanted_files += [(entry["archive"], entry["archive_sha256"])] + [
            (s["archive"], s["archive_sha256"]) for s in entry.get("split_archives", [])]

    def fetch(item) -> int:
        asset, digest = item
        target = args.out_dir / asset
        if target.is_file() and CACHE.sha256_file(target) == digest:
            return 0

        def download():
            target.unlink(missing_ok=True)
            gh("release", "download", where[asset], "--repo", args.repo, "--pattern", asset,
               "--dir", str(args.out_dir), "--clobber")
            if not target.is_file() or CACHE.sha256_file(target) != digest:
                target.unlink(missing_ok=True)
                raise ShardCacheError(f"{asset} does not match its recorded SHA-256")

        retry(download, f"download {asset}")
        return 1

    # A complete restore is hundreds of archives: download several at once.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.jobs, 16))) as pool:
        restored = sum(pool.map(fetch, wanted_files))
    if args.toolchain_list:
        args.toolchain_list.write_text(
            "".join(f"{recipes[n].archive}\n" for n in selected if args.with_toolchain and good[n].get("toolchain")),
            encoding="utf-8")
    print(f"shard cache: restored {restored} archive(s) for {len(selected)} package(s)")
    return 0


def pick_archive_tag(prefix: str, category: str, releases: dict[str, dict[str, dict]]) -> str:
    number = 1
    while True:
        tag = f"{prefix}-{category}-{number:04d}"
        if len(releases.get(tag, {})) < MAX_ASSETS:
            return tag
        number += 1


def cmd_save(args) -> int:
    recipes, keys = context(args)
    if not SHARD_RE.fullmatch(args.shard):
        raise ShardCacheError(f"unsafe shard id: {args.shard!r}")
    report = args.report.read_text(encoding="utf-8") if args.report.is_file() else ""
    built = set(re.findall(r"^BUILT\s+([A-Za-z0-9][A-Za-z0-9._+-]*)\b", report, re.MULTILINE))
    toolchain = set(args.toolchain_stems.split())
    since = args.since.stat().st_mtime_ns
    releases = list_releases(args.repo, args.prefix)
    entries = []
    uploads: list[tuple[str, Path]] = []
    for recipe in sorted(recipes.values(), key=lambda r: r.name):
        stem = recipe.archive.removesuffix(".nawa.tar.zst")
        if stem not in built:
            continue
        path = args.out_dir / recipe.archive
        if not path.is_file() or path.stat().st_size == 0 or path.stat().st_mtime_ns <= since:
            continue
        files = [path]
        splits = []
        for suffix in ("doc", "lang"):
            split = args.out_dir / recipe.split_archive(suffix)
            if split.is_file() and split.stat().st_size > 0 and split.stat().st_mtime_ns > since:
                files.append(split)
                splits.append({"archive": split.name, "archive_sha256": CACHE.sha256_file(split)})
        for file in files:
            if file.stat().st_size >= MAX_BYTES:
                raise ShardCacheError(f"GitHub Release asset must be smaller than 2 GiB: {file.name}")
        category = recipe.directory.parent.name
        tag = pick_archive_tag(args.prefix, category, releases)
        releases.setdefault(tag, {})
        for file in files:
            releases[tag][file.name] = {"name": file.name}
            uploads.append((tag, file))
        entry = {"name": recipe.name, "archive": recipe.archive, "build_key": keys[recipe.name],
                 "archive_sha256": CACHE.sha256_file(path), "split_archives": splits}
        if stem in toolchain:
            entry["toolchain"] = True
        entries.append(entry)

    for tag in sorted({t for t, _ in uploads}):
        ensure_release(args.repo, tag, f"Internal draft build cache ({args.prefix}). Not a package repository.")
    for tag, file in uploads:
        retry(lambda tag=tag, file=file: gh("release", "upload", tag, str(file), "--repo", args.repo, "--clobber"),
              f"upload {file.name}")

    status = {}
    if args.status.is_file():
        for line in args.status.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.isupper() and value.isdigit():
                status[key.lower()] = int(value)
    failed = re.findall(r"^(?:FAILED|SKIPPED)\s+([A-Za-z0-9][A-Za-z0-9._+-]*)", report, re.MULTILINE)
    record = {"schema": 1, "shard": args.shard, "run_id": args.run_id, "entries": entries,
              "status": status, "failed": failed}
    # Uploaded even when nothing was built: the final job reads failures and
    # budget exhaustion from these files.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"entries-{args.shard}.json"
        path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        ensure_release(args.repo, state_tag(args.prefix), f"Internal draft build cache state ({args.prefix}).")
        retry(lambda: gh("release", "upload", state_tag(args.prefix), str(path), "--repo", args.repo, "--clobber"),
              "upload shard entries")
    print(f"shard cache: shard {args.shard} saved {len(entries)} package(s), {len(uploads)} asset(s)")
    return 0


def cmd_merge(args) -> int:
    recipes, keys = context(args)
    releases = list_releases(args.repo, args.prefix)
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        fetch_state(args.repo, args.prefix, directory)
        entries = load_entry_files(directory)
        good = usable(entries, recipes, keys, releases)
        incomplete, failed, shards = 0, [], []
        current_records: set[str] = set()
        for path in sorted(directory.glob("entries-*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if args.run_id and value.get("run_id") not in (None, args.run_id):
                continue  # a shard record of an older run
            current_records.add(path.name)
            shards.append(value.get("shard", path.stem))
            incomplete |= int(bool(value.get("status", {}).get("incomplete")))
            failed += value.get("failed", [])

        manifest = {"schema": CACHE.MANIFEST_SCHEMA, "packages": [
            {k: v for k, v in good[name].items() if k in
             {"name", "archive", "build_key", "archive_sha256", "split_archives"}} for name in sorted(good)]}
        where = {n: t for t, assets in releases.items() for n in assets}
        shard_tags = sorted({where[f] for e in good.values()
                             for f in [e["archive"], *[s["archive"] for s in e["split_archives"]]]})
        manifest_path = directory / CACHE.MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        match = PR_PREFIX_RE.fullmatch(args.prefix)
        uploads = [manifest_path]
        if match:
            import hashlib  # noqa: PLC0415
            candidate = {
                "schema": 1, "pr_number": int(match.group(1)), "build_run_id": args.run_id,
                "head_sha": args.head_sha,
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "shards": shard_tags, "package_count": len(good),
                "archive_count": sum(1 + len(e["split_archives"]) for e in good.values()),
            }
            candidate_path = directory / "candidate.json"
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            uploads.append(candidate_path)
        tag = state_tag(args.prefix)
        ensure_release(args.repo, tag, f"Internal draft build cache state ({args.prefix}).")
        for path in uploads:
            retry(lambda path=path: gh("release", "upload", tag, str(path), "--repo", args.repo, "--clobber"),
                  f"upload {path.name}")

        # Housekeeping, only after the new manifest is in place: drop assets no
        # valid entry refers to (superseded versions) and the merged shard records.
        keep = {f for e in good.values() for f in [e["archive"], *[s["archive"] for s in e["split_archives"]]]}
        for rtag, assets in sorted(releases.items()):
            for name in sorted(assets):
                stale_archive = rtag != tag and name not in keep
                # Records of THIS run stay (a re-run of the final job still needs
                # their status); older records are folded into manifest.json.
                old_record = rtag == tag and ENTRIES_RE.fullmatch(name) and name not in current_records
                if stale_archive or old_record:
                    subprocess.run([os.environ.get("GH_BIN", "gh"), "release", "delete-asset", rtag, name,
                                    "--repo", args.repo, "--yes"], stdout=subprocess.DEVNULL)
    print(f"shard cache: {len(good)} reusable package(s) in {len(shard_tags)} release(s) from {len(shards)} shard record(s)")
    print(f"INCOMPLETE={incomplete}")
    print(f"FAILED={len(failed)}")
    return 0


def cmd_drop(args) -> int:
    check_prefix(args.prefix)
    for tag in sorted(list_releases(args.repo, args.prefix)):
        subprocess.run([os.environ.get("GH_BIN", "gh"), "release", "delete", tag, "--repo", args.repo,
                        "--yes", "--cleanup-tag"], stdout=subprocess.DEVNULL)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, recipes=True):
        p.add_argument("--repo", required=True, help="OWNER/NAME holding the cache releases")
        p.add_argument("--prefix", required=True)
        if recipes:
            p.add_argument("--recipes", type=Path, required=True)

    p = sub.add_parser("valid-stems")
    common(p)
    p = sub.add_parser("restore")
    common(p)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--names", default="", help="package names to restore")
    p.add_argument("--all", action="store_true", help="restore every usable package")
    p.add_argument("--jobs", type=int, default=8, help="parallel downloads")
    p.add_argument("--with-toolchain", action="store_true",
                   help="also restore the archives Bootstrap built in this build (wave 0)")
    p.add_argument("--toolchain-list", type=Path, help="write the archive names of restored Toolchain entries here")
    p = sub.add_parser("save")
    common(p)
    p.add_argument("--shard", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--since", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--status", type=Path, required=True)
    p.add_argument("--run-id", type=int, default=0)
    p.add_argument("--toolchain-stems", default="", help="archive stems built by Bootstrap")
    p = sub.add_parser("merge")
    common(p)
    p.add_argument("--run-id", type=int, default=0)
    p.add_argument("--head-sha", default="")
    p = sub.add_parser("drop")
    common(p, recipes=False)

    args = parser.parse_args(argv)
    try:
        return {"valid-stems": cmd_valid_stems, "restore": cmd_restore, "save": cmd_save,
                "merge": cmd_merge, "drop": cmd_drop}[args.command](args)
    except (ShardCacheError, CACHE.CacheError, OSError, ValueError, KeyError) as exc:
        print(f"::error::pr-shard-cache: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
