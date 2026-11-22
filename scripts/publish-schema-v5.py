#!/usr/bin/env python3
"""Prepare a complete, authenticated schema-v5 package repository.

This command intentionally refuses partial recipe sets, recipes with unknown
relation declarations, unsigned archives, and indexes that do not exactly
describe the archive directory. It prepares artifacts only; the isolated
GitHub Actions workflow publishes the validated plan to stable-v5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen


ARCHIVE_SUFFIX = ".nawa.tar.zst"
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
REV_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class PublishError(RuntimeError):
    pass


def recipes(root: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    problems: list[str] = []
    for path in sorted(root.glob("*/*/recipe.toml")):
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
            package = doc["package"]
            name, version, rel = package["name"], package["version"], package["rel"]
        except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
            problems.append(f"{path}: cannot read package identity: {exc}")
            continue
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            problems.append(f"{path}: invalid package.name")
            continue
        if not isinstance(version, str) or not NAME_RE.fullmatch(version):
            problems.append(f"{path}: invalid package.version")
            continue
        if not isinstance(rel, int) or isinstance(rel, bool) or rel < 1:
            problems.append(f"{path}: package.rel must be a positive integer")
            continue
        archive = f"{name}-{version}-{rel}{ARCHIVE_SUFFIX}"
        if archive in found:
            problems.append(f"{path}: duplicate recipe archive identity {archive}")
            continue
        for suffix in ("-doc", "-lang"):
            split_archive = f"{name}{suffix}-{version}-{rel}{ARCHIVE_SUFFIX}"
            if split_archive in found:
                problems.append(
                    f"{path}: split archive identity {split_archive} collides with another recipe"
                )

        # Nawa's Depends model defaults run to [], and package builds
        # always serialize that resolved list as .PKGINFO rundeps. The v5
        # publisher validates authenticated archive metadata, so an omitted
        # recipe [depends].run is a valid empty runtime-dependency declaration.
        capabilities = doc.get("capabilities")
        if not isinstance(capabilities, dict) or not isinstance(capabilities.get("provides"), list):
            problems.append(f"{path}: [capabilities].provides must be explicit (use [] when empty)")
        relations = doc.get("relations")
        if (
            not isinstance(relations, dict)
            or relations.get("schema") != 1
            or isinstance(relations.get("schema"), bool)
            or not isinstance(relations.get("conflicts"), list)
            or not isinstance(relations.get("replaces"), list)
        ):
            problems.append(
                f"{path}: [relations] schema = 1, conflicts, and replaces must be explicit"
            )
        found[archive] = {
            "name": name,
            "version": version,
            "rel": rel,
            "path": path,
            "doc": doc,
        }
    if not found:
        problems.append(f"{root}: no recipe.toml files found")
    if problems:
        preview = "\n".join(f"  - {item}" for item in problems[:40])
        if len(problems) > 40:
            preview += f"\n  - ... and {len(problems) - 40} more"
        raise PublishError(
            f"{len(problems)} schema-v5 recipe declaration problem(s):\n{preview}"
        )
    return found


def audit_archives(recipe_map: dict[str, dict], archive_dir: Path) -> list[Path]:
    if not archive_dir.is_dir():
        raise PublishError(f"archive directory does not exist: {archive_dir}")
    expected: set[str] = set()
    owners: dict[str, str] = {}
    for filename, package in recipe_map.items():
        previous = owners.get(filename)
        if previous is not None and previous != package["name"]:
            raise PublishError(
                f"recipe archive identity {filename} collides with split package from {previous}"
            )
        expected.add(filename)
        owners[filename] = package["name"]
        for suffix in ("-doc", "-lang"):
            split = f"{package['name']}{suffix}-{package['version']}-{package['rel']}{ARCHIVE_SUFFIX}"
            previous = owners.get(split)
            if previous is not None and previous != package["name"]:
                raise PublishError(
                    f"split package identity {split} collides with recipe {previous}"
                )
            owners[split] = package["name"]
            expected.add(split)
    candidates = list(archive_dir.glob(f"*{ARCHIVE_SUFFIX}"))
    if any(path.is_symlink() for path in candidates):
        raise PublishError("package archive directory must not contain symlinked archives")
    present = {path.name for path in candidates if path.is_file()}
    missing = sorted(set(recipe_map) - present)
    extra = sorted(present - expected)
    if missing or extra:
        details = []
        if missing:
            details.append("missing recipe archives: " + ", ".join(missing[:30]))
        if extra:
            details.append("stale or non-recipe archives: " + ", ".join(extra[:30]))
        raise PublishError("incomplete schema-v5 package set: " + "; ".join(details))
    archives = sorted(path for path in candidates if path.is_file())
    empty = [path.name for path in archives if path.stat().st_size == 0]
    if empty:
        raise PublishError("empty package archive(s): " + ", ".join(empty[:30]))
    return archives


def stage_archives(recipe_map: dict[str, dict], source_dir: Path, archive_dir: Path) -> list[Path]:
    """Copy only current recipe archives and their optional Nawa split outputs."""
    if not source_dir.is_dir():
        raise PublishError(f"package build output directory does not exist: {source_dir}")
    if archive_dir.exists() and any(archive_dir.iterdir()):
        raise PublishError(f"schema-v5 staging directory is not empty: {archive_dir}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    expected: set[str] = set(recipe_map)
    for package in recipe_map.values():
        for suffix in ("-doc", "-lang"):
            expected.add(f"{package['name']}{suffix}-{package['version']}-{package['rel']}{ARCHIVE_SUFFIX}")
    for name in sorted(expected):
        source = source_dir / name
        if source.is_symlink():
            raise PublishError(f"refusing symlinked package archive: {source}")
        if not source.is_file():
            if name in recipe_map:
                raise PublishError(f"missing recipe package archive: {source}")
            continue
        shutil.copy2(source, archive_dir / name)
    return audit_archives(recipe_map, archive_dir)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def locations_text(archives: list[Path], repository: str, tag: str, recipe_file: str) -> str:
    lines = ["schema = 1", "", "[package_urls]"]
    for archive in archives:
        url = f"https://github.com/{repository}/releases/download/{tag}/{quote(archive.name, safe='._+-')}"
        lines.append(f"{toml_string(archive.name)} = {toml_string(url)}")
    recipe_url = f"https://github.com/{repository}/releases/download/{tag}/{quote(recipe_file, safe='._+-')}"
    lines.extend(["", "[recipe_urls]", f"{toml_string(recipe_file)} = {toml_string(recipe_url)}"])
    return "\n".join(lines) + "\n"


def run(argv: list[str]) -> None:
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode:
        raise PublishError(f"command failed ({result.returncode}): {argv[0]}")


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(nawa: Path, path: Path, public_key: Path) -> None:
    run([str(nawa), "verify", str(path), "--key", str(public_key)])


def fetch_v3(
    index_path: Path,
    archive_dir: Path,
    recipe_root: Path,
    nawa: Path,
    public_key: Path,
    repository: str,
) -> list[Path]:
    """Fetch only current recipe archives authenticated by the signed v3 index.

    Schema-v3's detached index signature authenticates each archive digest. The
    candidate is then re-signed with the v5 publisher key before it can be
    referenced by a schema-v5 index.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise PublishError("repository must be OWNER/NAME")
    recipe_map = recipes(recipe_root)
    if archive_dir.exists() and any(archive_dir.iterdir()):
        raise PublishError(f"schema-v5 staging directory is not empty: {archive_dir}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    verify(nawa, index_path, public_key)
    try:
        doc = tomllib.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PublishError(f"cannot parse verified schema-v3 index: {exc}") from exc
    repository_meta = doc.get("repository")
    if (
        not isinstance(repository_meta, dict)
        or repository_meta.get("schema") != 3
        or repository_meta.get("archive_location") != "per-package-url"
    ):
        raise PublishError("source index must be schema v3 with per-package URLs")

    allowed: dict[str, tuple[str, str, int]] = {}
    required: set[str] = set()
    for filename, package in recipe_map.items():
        identity = (package["name"], package["version"], package["rel"])
        allowed[filename] = identity
        required.add(filename)
        for suffix in ("-doc", "-lang"):
            split = f"{package['name']}{suffix}-{package['version']}-{package['rel']}{ARCHIVE_SUFFIX}"
            if split in allowed and allowed[split] != identity:
                raise PublishError(f"split archive identity collision: {split}")
            allowed[split] = (f"{package['name']}{suffix}", package["version"], package["rel"])

    entries = doc.get("package")
    if not isinstance(entries, list):
        raise PublishError("verified schema-v3 index has no package entries")
    selected: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PublishError("verified schema-v3 index contains a non-table package entry")
        filename = entry.get("file")
        if not isinstance(filename, str) or filename not in allowed:
            continue
        if filename in selected:
            raise PublishError(f"duplicate current archive in schema-v3 index: {filename}")
        if (entry.get("name"), entry.get("version"), entry.get("rel")) != allowed[filename]:
            raise PublishError(f"schema-v3 index identity differs from current recipe: {filename}")
        selected[filename] = entry

    missing = sorted(required - set(selected))
    if missing:
        raise PublishError(
            "schema-v3 index is missing current recipe archives: " + ", ".join(missing[:30])
        )

    prefix = f"/{repository}/releases/download/"
    downloaded: list[Path] = []
    for filename in sorted(selected):
        entry = selected[filename]
        digest = entry.get("sha256")
        size = entry.get("size")
        location = entry.get("download_url")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PublishError(f"schema-v3 index has invalid SHA-256 for {filename}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise PublishError(f"schema-v3 index has invalid size for {filename}")
        if not isinstance(location, str):
            raise PublishError(f"schema-v3 index has no authenticated download URL for {filename}")
        parsed = urlsplit(location)
        path_parts = parsed.path.split("/")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(prefix)
            or len(path_parts) != 7
            or not re.fullmatch(r"packages-[0-9]{4,}", path_parts[5])
            or unquote(path_parts[6]) != filename
        ):
            raise PublishError(f"schema-v3 index has an unsafe or unexpected archive URL: {filename}")

        destination = archive_dir / filename
        temporary = archive_dir / f".{filename}.part"
        hasher = hashlib.sha256()
        written = 0
        try:
            with urlopen(location, timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    written += len(chunk)
                    if written > size:
                        raise PublishError(f"download exceeds signed index size: {filename}")
                    hasher.update(chunk)
                    output.write(chunk)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        if written != size or hasher.hexdigest() != digest:
            temporary.unlink(missing_ok=True)
            raise PublishError(f"downloaded archive differs from signed schema-v3 index: {filename}")
        temporary.replace(destination)
        downloaded.append(destination)

    print(f"fetched {len(downloaded)} current recipe archive(s) from the signed schema-v3 index")
    return downloaded


def verify_reused(plan_path: Path, archive_dir: Path, existing_dir: Path,
                  nawa: Path, public_key: Path) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for item in plan.get("reused", []):
        tag, name = item["tag"], item["name"]
        local = archive_dir / name
        local_sig = archive_dir / f"{name}.sig"
        remote = existing_dir / tag / name
        remote_sig = existing_dir / tag / f"{name}.sig"
        for path in (local, local_sig, remote, remote_sig):
            if not path.is_file() or path.stat().st_size == 0:
                raise PublishError(f"schema-v5 reused asset is missing or empty: {path}")
        if checksum(local) != checksum(remote) or checksum(local_sig) != checksum(remote_sig):
            raise PublishError(f"schema-v5 immutable release asset differs from candidate: {tag}/{name}")
        verify(nawa, remote, public_key)
    print(f"verified {len(plan.get('reused', []))} reused signed archive(s)")


def download_reused(plan_path: Path, existing_dir: Path, repository: str) -> None:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    by_tag: dict[str, set[str]] = {}
    for item in plan.get("reused", []):
        by_tag.setdefault(item["tag"], set()).add(item["name"])
    for tag, names in sorted(by_tag.items()):
        destination = existing_dir / tag
        destination.mkdir(parents=True, exist_ok=True)
        missing = [name for name in sorted(names) if not (destination / name).is_file() or not (destination / f"{name}.sig").is_file()]
        if not missing:
            continue
        command = ["gh", "release", "download", tag, "--repo", repository, "--dir", str(destination)]
        for name in missing:
            command.extend(("--pattern", name, "--pattern", f"{name}.sig"))
        run(command)


def validate_index_identities(
    recipe_map: dict[str, dict], archive_paths: list[Path], indexed: dict[str, dict]
) -> None:
    """Bind every index entry to its recipe, exact archive filename, and split parent."""
    archive_names = {path.name for path in archive_paths}
    if archive_names != set(indexed):
        missing = sorted(archive_names - set(indexed))
        extra = sorted(set(indexed) - archive_names)
        raise PublishError(
            f"index/archive membership differs (unindexed={missing[:20]}, absent={extra[:20]})"
        )

    recipe_by_name = {item["name"]: item for item in recipe_map.values()}
    for filename, entry in indexed.items():
        if not isinstance(entry, dict):
            raise PublishError(f"generated index entry is not a table: {filename}")
        name, version, rel = entry.get("name"), entry.get("version"), entry.get("rel")
        if (
            not isinstance(name, str)
            or not isinstance(version, str)
            or not isinstance(rel, int)
            or isinstance(rel, bool)
        ):
            raise PublishError(f"generated index has invalid package identity: {filename}")
        expected_filename = f"{name}-{version}-{rel}{ARCHIVE_SUFFIX}"
        if expected_filename != filename:
            raise PublishError(
                f"archive/index identity differs for {filename}: index describes {expected_filename}"
            )
        recipe = recipe_map.get(filename)
        if recipe is not None:
            if (name, version, rel) != (recipe["name"], recipe["version"], recipe["rel"]):
                raise PublishError(f"index metadata differs from recipe identity: {filename}")
            continue

        parent = None
        for suffix in ("-doc", "-lang"):
            if name.endswith(suffix):
                parent = recipe_by_name.get(name[: -len(suffix)])
                break
        if parent is None or (version, rel) != (parent["version"], parent["rel"]):
            raise PublishError(f"split archive has no matching current recipe identity: {filename}")


def verify_index(
    archive_dir: Path, nawa: Path, public_key: Path, recipe_map: dict[str, dict]
) -> None:
    index_path = archive_dir / "index.toml"
    if not (archive_dir / "index.toml.sig").is_file():
        raise PublishError("generated index has no detached signature")
    verify(nawa, index_path, public_key)
    try:
        doc = tomllib.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PublishError(f"cannot parse generated index: {exc}") from exc
    repository = doc.get("repository")
    if not isinstance(repository, dict) or repository.get("schema") != 5:
        raise PublishError("generated index does not declare repository schema 5")
    entries = doc.get("package")
    if not isinstance(entries, list):
        raise PublishError("generated schema-v5 index has no package entries")
    indexed: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PublishError("generated index contains a non-table package entry")
        name = entry.get("file")
        if not isinstance(name, str) or name in indexed:
            raise PublishError(f"generated index has a missing or duplicate archive identity: {name!r}")
        indexed[name] = entry
        if not isinstance(entry.get("rundeps"), list) or not isinstance(entry.get("provides"), list):
            raise PublishError(f"generated index has unknown solving metadata: {name}")
        relations = entry.get("relations")
        if (
            not isinstance(relations, dict)
            or relations.get("schema") != 1
            or isinstance(relations.get("schema"), bool)
            or not isinstance(relations.get("conflicts"), list)
            or not isinstance(relations.get("replaces"), list)
        ):
            raise PublishError(f"generated index has unknown package relations: {name}")
    archive_paths = sorted(archive_dir.glob(f"*{ARCHIVE_SUFFIX}"))
    validate_index_identities(recipe_map, archive_paths, indexed)
    for path in archive_paths:
        entry = indexed[path.name]
        if not (archive_dir / f"{path.name}.sig").is_file():
            raise PublishError(f"signed package archive has no detached signature: {path.name}")
        verify(nawa, path, public_key)
        if entry.get("sha256") != checksum(path):
            raise PublishError(f"index SHA-256 differs from archive: {path.name}")
        if entry.get("size") != path.stat().st_size:
            raise PublishError(f"index size differs from archive: {path.name}")
    recipes = doc.get("recipes")
    if not isinstance(recipes, dict):
        raise PublishError("generated index does not authenticate a recipe snapshot")
    recipe_file = recipes.get("file")
    if not isinstance(recipe_file, str) or not re.fullmatch(r"recipes-[A-Za-z0-9._-]+\.recipes\.tar\.zst", recipe_file):
        raise PublishError("generated index has an unsafe recipe snapshot filename")
    recipe_path = archive_dir / recipe_file
    if not recipe_path.is_file() or checksum(recipe_path) != recipes.get("sha256"):
        raise PublishError("recipe snapshot is absent or differs from its signed index digest")
    if recipes.get("size") != recipe_path.stat().st_size:
        raise PublishError("recipe snapshot size differs from its signed index")
    if not Path(f"{recipe_path}.sig").is_file():
        raise PublishError("recipe snapshot has no detached signature")
    verify(nawa, recipe_path, public_key)
    print(f"verified schema-v5 index and {len(archive_paths)} indexed package archive(s)")


def create_repository(args: argparse.Namespace) -> None:
    if args.stable_tag != "stable-v5":
        raise PublishError("schema-v5 publishing requires the isolated stable-v5 endpoint")
    recipe_map = recipes(args.recipes)
    if args.source_dir:
        archives = stage_archives(recipe_map, args.source_dir, args.archive_dir)
    else:
        archives = audit_archives(recipe_map, args.archive_dir)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise PublishError("repository must be OWNER/NAME")
    if not REV_RE.fullmatch(args.revision):
        raise PublishError("revision must be a safe commit or tag")
    for archive in archives:
        run([str(args.nawa), "sign", str(archive), "--key", str(args.signing_key)])

    recipe_file = f"recipes-{args.revision}.recipes.tar.zst"
    provisional = args.archive_dir / "locations-provisional.toml"
    provisional.write_text(
        locations_text(archives, args.repository, args.stable_tag, recipe_file), encoding="utf-8"
    )
    common = [
        str(args.nawa), "repo-create", str(args.archive_dir), "--out", "index.toml",
        "--index-version", "5", "--locations", str(provisional), "--sign",
        "--key", str(args.signing_key), "--recipes", str(args.recipes),
        "--recipes-rev", args.revision,
    ]
    run(common)
    recipe_path = args.archive_dir / recipe_file
    run([str(args.nawa), "sign", str(recipe_path), "--key", str(args.signing_key)])

    planner = [
        sys.executable, "-I", str(args.planner), "plan",
        "--releases-json", str(args.releases_json), "--repo-dir", str(args.archive_dir),
        "--repository", args.repository, "--stable-tag", args.stable_tag,
        "--recipe-file", recipe_file, "--max-assets", str(args.max_assets),
        "--index-version", "5", "--output", str(args.plan),
        "--manifest", str(args.locations),
    ]
    run(planner)
    if not args.existing_dir:
        raise PublishError("prepare requires --existing-dir so reused release assets can be authenticated")
    download_reused(args.plan, args.existing_dir, args.repository)
    verify_reused(args.plan, args.archive_dir, args.existing_dir, args.nawa, args.public_key)

    common[common.index("--locations") + 1] = str(args.locations)
    run(common)
    # Packing is deterministic; sign again after the final repo-create in case
    # the recipe snapshot was freshly regenerated.
    run([str(args.nawa), "sign", str(recipe_path), "--key", str(args.signing_key)])
    verify_index(args.archive_dir, args.nawa, args.public_key, recipe_map)
    print(f"prepared isolated schema-v5 plan: {args.plan}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit", help="check all recipe declarations and package-set coverage")
    prepare = sub.add_parser("prepare", help="sign, index, and validate a complete schema-v5 set")
    for option in (audit, prepare):
        option.add_argument("--recipes", type=Path, required=True)
        option.add_argument("--archive-dir", type=Path, required=True)
    check = sub.add_parser("check-recipes", help="validate explicit v5 declarations without package archives")
    check.add_argument("--recipes", type=Path, required=True)
    fetch = sub.add_parser("fetch-v3", help="fetch exact current archives from a signed schema-v3 index")
    fetch.add_argument("--index", type=Path, required=True)
    fetch.add_argument("--recipes", type=Path, required=True)
    fetch.add_argument("--archive-dir", type=Path, required=True)
    fetch.add_argument("--nawa", type=Path, required=True)
    fetch.add_argument("--public-key", type=Path, required=True)
    fetch.add_argument("--repository", required=True)
    prepare.add_argument(
        "--source-dir",
        type=Path,
        help="optional build output directory; only exact current recipe archives are copied into the empty --archive-dir",
    )
    prepare.add_argument("--nawa", type=Path, required=True)
    prepare.add_argument("--signing-key", type=Path, required=True)
    prepare.add_argument("--public-key", type=Path, required=True)
    prepare.add_argument("--repository", required=True)
    prepare.add_argument("--stable-tag", default="stable-v5")
    prepare.add_argument("--revision", required=True)
    prepare.add_argument("--releases-json", type=Path, required=True)
    prepare.add_argument("--planner", type=Path, required=True)
    prepare.add_argument("--plan", type=Path, required=True)
    prepare.add_argument("--locations", type=Path, required=True)
    prepare.add_argument("--existing-dir", type=Path, required=True)
    prepare.add_argument("--max-assets", type=int, default=900)
    args = parser.parse_args()
    try:
        if args.command == "check-recipes":
            recipe_map = recipes(args.recipes)
            print(f"schema-v5 recipe declarations are complete: {len(recipe_map)} recipe(s)")
        elif args.command == "fetch-v3":
            fetch_v3(
                args.index,
                args.archive_dir,
                args.recipes,
                args.nawa,
                args.public_key,
                args.repository,
            )
        elif args.command == "audit":
            recipe_map = recipes(args.recipes)
            archive_list = audit_archives(recipe_map, args.archive_dir)
            print(f"complete schema-v5 candidate set: {len(recipe_map)} recipe(s), {len(archive_list)} archive(s)")
        else:
            create_repository(args)
        return 0
    except (OSError, json.JSONDecodeError, PublishError, subprocess.SubprocessError) as exc:
        print(f"publish-schema-v5: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
