#!/usr/bin/env python3
"""Build and publish the schema-v5 package repository incrementally.

A wave signs and uploads the archives it built (`stage-wave`, `derive`). The
publish job applies only the new entries to the previous signed index with
`nawa repo-update` (`update`) and keeps the package catalog the same way
(`catalog`): no archive that is already published is downloaded or opened. The
command refuses partial recipe sets, recipes with unknown relation
declarations, unsigned archives, and an index that does not cover every recipe.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
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




# --------------------------------------------------------------------------
# incremental publishing
#
# A shard job signs and uploads the archives it built (`stage-wave`, then
# `derive` for the index entries and catalog records of exactly those
# archives). The publish job never opens an old archive: `update` applies the
# new entries to the previous signed index with `nawa repo-update`, and
# `catalog` does the same for the package catalog the file-conflict check reads.
# --------------------------------------------------------------------------

STABLE_TAG = "stable-v5"
PLACEHOLDER_TAG = "packages-v5-0000"
HERE = Path(__file__).resolve().parent
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _load_script(module: str, filename: str):
    spec = importlib.util.spec_from_file_location(module, HERE / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


RELEASES = _load_script("distributed_releases", "distributed-releases.py")
CATALOG = _load_script("package_catalog", "package_catalog.py")


def check_repository(repository: str, revision: str | None = None) -> None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise PublishError("repository must be OWNER/NAME")
    if revision is not None and not REV_RE.fullmatch(revision):
        raise PublishError("revision must be a safe commit or tag")


def expected_identities(recipe_map: dict[str, dict]) -> dict[str, tuple[str, str, int]]:
    """Every archive file name a current recipe can publish -> (name, version, rel)."""
    out: dict[str, tuple[str, str, int]] = {}
    for filename, package in recipe_map.items():
        out[filename] = (package["name"], package["version"], package["rel"])
    for package in recipe_map.values():
        for suffix in ("-doc", "-lang"):
            split = f"{package['name']}{suffix}-{package['version']}-{package['rel']}{ARCHIVE_SUFFIX}"
            out.setdefault(split, (f"{package['name']}{suffix}", package["version"], package["rel"]))
    return out


def download_url(repository: str, tag: str, name: str) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{quote(name, safe='._+-')}"


def shard_holders(releases: list[dict]) -> dict[str, set[str]]:
    """Archive name -> schema-v5 shard tags that hold it together with its signature."""
    holders: dict[str, set[str]] = {}
    for release in releases:
        match = RELEASES.SHARD_RE.fullmatch(release["tag_name"])
        if match is None or match.group(1) != "packages-v5":
            continue
        names = set(RELEASES.asset_names(release))
        for name in names:
            if RELEASES.PACKAGE_RE.fullmatch(name) and f"{name}.sig" in names:
                holders.setdefault(name, set()).add(release["tag_name"])
    return holders


def asset_digests(releases: list[dict]) -> dict[tuple[str, str], str]:
    """(tag, asset) -> sha256 as GitHub computed it, where the API reports one."""
    out: dict[tuple[str, str], str] = {}
    for release in releases:
        for asset in release.get("assets", []):
            digest = asset.get("digest") if isinstance(asset, dict) else None
            if isinstance(digest, str) and digest.startswith("sha256:") and asset.get("name"):
                out[(release["tag_name"], str(asset["name"]))] = digest[len("sha256:"):]
    return out


def entry_blocks(text: str) -> list[str]:
    """Split TOML text into its `[[package]]` blocks (each with its subtables)."""
    parts = re.split(r"(?m)^(?=\[\[package\]\]\s*$)", text)
    return [part.rstrip("\n") + "\n" for part in parts if part.lstrip().startswith("[[package]]")]


def strip_download_url(block: str) -> str:
    return re.sub(r"(?m)^download_url = .*\n", "", block)


def block_entry(block: str) -> dict:
    try:
        entry = tomllib.loads(block)["package"][0]
    except (KeyError, IndexError, tomllib.TOMLDecodeError) as exc:
        raise PublishError(f"unreadable index entry: {exc}") from exc
    if not isinstance(entry.get("file"), str) or not isinstance(entry.get("sha256"), str):
        raise PublishError("index entry without file or sha256")
    return entry


def stage_wave(
    recipe_map: dict[str, dict], built_dir: Path, releases: list[dict], stage_dir: Path,
    nawa: Path, signing_key: Path,
) -> list[str]:
    """Copy the archives a wave built that are not published yet and sign them."""
    if not built_dir.is_dir():
        raise PublishError(f"build output directory does not exist: {built_dir}")
    if stage_dir.exists() and any(stage_dir.iterdir()):
        raise PublishError(f"staging directory is not empty: {stage_dir}")
    stage_dir.mkdir(parents=True, exist_ok=True)
    expected = expected_identities(recipe_map)
    published = {name for _, name in RELEASES.list_published(releases, STABLE_TAG, 5)}
    staged: dict[str, Path] = {}
    for path in sorted(built_dir.rglob(f"*{ARCHIVE_SUFFIX}")):
        if path.is_symlink():
            raise PublishError(f"refusing symlinked package archive: {path}")
        if not path.is_file():
            continue
        name = path.name
        if name not in expected:
            print(f"skip {name}: not an archive of a current recipe")
            continue
        if name in published:
            print(f"skip {name}: already published (the published copy is immutable)")
            continue
        if path.stat().st_size == 0:
            raise PublishError(f"empty package archive: {path}")
        if name in staged:
            if checksum(staged[name]) != checksum(path):
                raise PublishError(f"two different builds of {name} in one wave")
            continue
        shutil.copy2(path, stage_dir / name)
        staged[name] = stage_dir / name
    for path in staged.values():
        run([str(nawa), "sign", str(path), "--key", str(signing_key)])
    print(f"staged and signed {len(staged)} new archive(s)")
    return sorted(staged)


def derive(
    archive_dir: Path, repository: str, nawa: Path, signing_key: Path,
    out_entries: Path, records_dir: Path,
) -> list[str]:
    """Index entries (nawa's own repo-create output) and catalog records of a directory of archives.

    The entries carry no download_url: the publish job derives every URL from
    the release listing, so an entry never promises a location it did not check.
    """
    archives = sorted(p for p in archive_dir.glob(f"*{ARCHIVE_SUFFIX}") if p.is_file())
    out_entries.parent.mkdir(parents=True, exist_ok=True)
    records_dir.mkdir(parents=True, exist_ok=True)
    if not archives:
        out_entries.write_text("", encoding="utf-8")
        return []
    with tempfile.TemporaryDirectory(prefix="derive-") as td:
        tmp = Path(td)
        locations = tmp / "locations.toml"
        lines = ["schema = 1", "", "[package_urls]"]
        lines += [
            f"{toml_string(a.name)} = {toml_string(download_url(repository, PLACEHOLDER_TAG, a.name))}"
            for a in archives
        ]
        locations.write_text("\n".join(lines) + "\n", encoding="utf-8")
        index = tmp / "index.toml"
        run([
            str(nawa), "repo-create", str(archive_dir), "--out", str(index),
            "--index-version", "5", "--locations", str(locations),
            "--sign", "--key", str(signing_key),
        ])
        blocks = [strip_download_url(b) for b in entry_blocks(index.read_text(encoding="utf-8"))]
    by_file = {block_entry(b)["file"]: b for b in blocks}
    names = [a.name for a in archives]
    if sorted(by_file) != names:
        raise PublishError("repo-create did not index exactly the staged archives")
    for archive in archives:
        if block_entry(by_file[archive.name])["sha256"] != checksum(archive):
            raise PublishError(f"derived index entry differs from the archive bytes: {archive.name}")
    out_entries.write_text("".join(by_file[n] + "\n" for n in names), encoding="utf-8")
    for archive in archives:
        record = CATALOG.make_record(archive)
        CATALOG.atomic_write(
            records_dir / CATALOG.record_filename(record["file"]),
            CATALOG.zstd_compress(CATALOG.canonical(record)),
        )
    print(f"derived {len(names)} index entr(ies) and catalog record(s)")
    return names


def collect_fragments(meta_dir: Path | None) -> dict[str, str]:
    """file name -> `[[package]]` block, from the entries-*.toml the upload jobs wrote."""
    out: dict[str, str] = {}
    if meta_dir is None or not meta_dir.is_dir():
        return out
    for path in sorted(meta_dir.glob("entries-*.toml")):
        for block in entry_blocks(path.read_text(encoding="utf-8")):
            file = block_entry(block)["file"]
            if file in out and out[file] != block:
                raise PublishError(f"two different index entries for {file}")
            out[file] = block
    return out


def load_base(base_index: Path | None, nawa: Path, public_key: Path) -> dict[str, dict] | None:
    """Entries of the previous signed index, or None when nothing is published yet."""
    if base_index is None:
        return None
    verify(nawa, base_index, public_key)
    try:
        doc = tomllib.loads(base_index.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PublishError(f"cannot parse the published index: {exc}") from exc
    meta = doc.get("repository")
    if not isinstance(meta, dict) or meta.get("schema") != 5:
        raise PublishError("the published stable-v5 index does not declare repository schema 5")
    entries: dict[str, dict] = {}
    for entry in doc.get("package", []):
        file = entry.get("file") if isinstance(entry, dict) else None
        if not isinstance(file, str) or file in entries:
            raise PublishError(f"the published index has a missing or duplicate archive: {file!r}")
        entries[file] = entry
    return entries


class Delta:
    def __init__(self, needed: list[str], stragglers: list[str], remove: list[str], drop: list[str]):
        self.needed, self.stragglers, self.remove, self.drop = needed, stragglers, remove, drop


def plan_delta(
    recipe_map: dict[str, dict], base: dict[str, dict], published: dict[str, str],
    fragments: dict[str, str],
) -> Delta:
    """What the new index must add and drop, compared with the previous signed one."""
    expected = expected_identities(recipe_map)
    unpublished = sorted(f for f in recipe_map if f not in published)
    if unpublished:
        preview = ", ".join(unpublished[:30]) + (" ..." if len(unpublished) > 30 else "")
        raise PublishError(
            f"incomplete schema-v5 package set: {len(unpublished)} recipe archive(s) are not published: {preview}"
        )
    needed = sorted(f for f in published if f in expected and f not in base)
    stragglers = [f for f in needed if f not in fragments]
    stale = sorted(f for f in base if f not in expected)
    replaced = {expected[f][0] for f in needed}
    drop = sorted({str(base[f].get("name")) for f in stale} - replaced)
    return Delta(needed, stragglers, stale, drop)


def fetch_list(args: argparse.Namespace) -> None:
    """Write `tag<TAB>asset` for every published archive (and signature) the index lacks and no wave described."""
    recipe_map = recipes(args.recipes)
    releases = RELEASES.read_releases(args.releases_json)
    published = {name: tag for tag, name in RELEASES.list_published(releases, STABLE_TAG, 5)}
    base = load_base(args.base_index, args.nawa, args.public_key) or {}
    delta = plan_delta(recipe_map, base, published, collect_fragments(args.meta_dir))
    lines = []
    for file in delta.stragglers:
        lines += [f"{published[file]}\t{file}", f"{published[file]}\t{file}.sig"]
    args.output.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    print(f"{len(delta.stragglers)} published archive(s) have no index entry yet")


def locations_manifest(package_urls: dict[str, str], recipe_file: str, recipe_url: str) -> str:
    lines = ["schema = 1", "", "[package_urls]"]
    lines += [f"{toml_string(k)} = {toml_string(v)}" for k, v in sorted(package_urls.items())]
    lines += ["", "[recipe_urls]", f"{toml_string(recipe_file)} = {toml_string(recipe_url)}"]
    return "\n".join(lines) + "\n"


def validate_index_identities(recipe_map: dict[str, dict], indexed: dict[str, dict]) -> None:
    """Bind every index entry to its recipe, exact archive filename, and split parent."""
    recipe_by_name = {item["name"]: item for item in recipe_map.values()}
    for filename, entry in indexed.items():
        if not isinstance(entry, dict):
            raise PublishError(f"index entry is not a table: {filename}")
        name, version, rel = entry.get("name"), entry.get("version"), entry.get("rel")
        if (
            not isinstance(name, str)
            or not isinstance(version, str)
            or not isinstance(rel, int)
            or isinstance(rel, bool)
        ):
            raise PublishError(f"index has invalid package identity: {filename}")
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


def verify_updated(
    out_dir: Path, nawa: Path, public_key: Path, recipe_map: dict[str, dict],
    repository: str, holders: dict[str, set[str]], recipe_tag: str,
) -> dict[str, dict]:
    """Check the index `update` wrote without opening any archive."""
    index_path = out_dir / "index.toml"
    if not (out_dir / "index.toml.sig").is_file():
        raise PublishError("generated index has no detached signature")
    verify(nawa, index_path, public_key)
    try:
        doc = tomllib.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PublishError(f"cannot parse generated index: {exc}") from exc
    meta = doc.get("repository")
    if not isinstance(meta, dict) or meta.get("schema") != 5:
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
    missing = sorted(set(recipe_map) - set(indexed))
    if missing:
        raise PublishError("generated index is missing recipe archives: " + ", ".join(missing[:30]))
    validate_index_identities(recipe_map, indexed)
    prefix = f"https://github.com/{repository}/releases/download/"
    for name, entry in indexed.items():
        url = entry.get("download_url")
        if not isinstance(url, str) or not url.startswith(prefix):
            raise PublishError(f"index entry has no release URL of this repository: {name}")
        parts = url[len(prefix):].split("/")
        if len(parts) != 2 or unquote(parts[1]) != name or parts[0] not in holders.get(name, set()):
            raise PublishError(f"index URL does not point at a signed release asset: {name}")
    recipes_meta = doc.get("recipes")
    if not isinstance(recipes_meta, dict):
        raise PublishError("generated index does not authenticate a recipe snapshot")
    recipe_file = recipes_meta.get("file")
    if not isinstance(recipe_file, str) or not re.fullmatch(r"recipes-[A-Za-z0-9._-]+\.recipes\.tar\.zst", recipe_file):
        raise PublishError("generated index has an unsafe recipe snapshot filename")
    recipe_path = out_dir / recipe_file
    if not recipe_path.is_file() or checksum(recipe_path) != recipes_meta.get("sha256"):
        raise PublishError("recipe snapshot is absent or differs from its signed index digest")
    if recipes_meta.get("download_url") != download_url(repository, recipe_tag, recipe_file):
        raise PublishError("recipe snapshot URL differs from the planned release")
    if not Path(f"{recipe_path}.sig").is_file():
        raise PublishError("recipe snapshot has no detached signature")
    verify(nawa, recipe_path, public_key)
    print(f"verified the schema-v5 index: {len(indexed)} package(s), {len(recipe_map)} recipe(s)")
    return indexed


def update_repository(args: argparse.Namespace) -> None:
    """Previous signed index + the new archives -> new signed index, no old archive opened."""
    if args.stable_tag != STABLE_TAG:
        raise PublishError("schema-v5 publishing requires the isolated stable-v5 endpoint")
    check_repository(args.repository, args.revision)
    recipe_map = recipes(args.recipes)
    releases = RELEASES.read_releases(args.releases_json)
    published = {name: tag for tag, name in RELEASES.list_published(releases, STABLE_TAG, 5)}
    holders = shard_holders(releases)
    digests = asset_digests(releases)
    if args.out_dir.exists() and any(args.out_dir.iterdir()):
        raise PublishError(f"output directory is not empty: {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    recipe_file = f"recipes-{args.revision}.recipes.tar.zst"

    with tempfile.TemporaryDirectory(prefix="update-") as td:
        work = Path(td)
        base_path = args.base_index
        base = load_base(base_path, args.nawa, args.public_key)
        if base is None:
            # First publication: an empty, signed base keeps a single code path.
            empty = work / "empty"
            empty.mkdir()
            (work / "base").mkdir()
            seed = work / "seed-locations.toml"
            seed.write_text(
                locations_manifest({}, recipe_file, download_url(args.repository, PLACEHOLDER_TAG, recipe_file)),
                encoding="utf-8",
            )
            run([
                str(args.nawa), "repo-create", str(empty), "--out", str(work / "base" / "index.toml"),
                "--index-version", "5", "--locations", str(seed), "--sign", "--key", str(args.signing_key),
                "--recipes", str(args.recipes), "--recipes-rev", args.revision,
            ])
            base_path = work / "base" / "index.toml"
            base = {}
            print("no index is published yet: starting from an empty signed base")

        fragments = collect_fragments(args.meta_dir)
        delta = plan_delta(recipe_map, base, published, fragments)
        blocks = {f: fragments[f] for f in delta.needed if f in fragments}
        if delta.stragglers:
            directory = args.straggler_dir
            absent = [
                f for f in delta.stragglers
                if directory is None or not (directory / f).is_file() or not (directory / f"{f}.sig").is_file()
            ]
            if absent:
                raise PublishError(
                    "published archives have no index entry and were not downloaded: " + ", ".join(absent[:30])
                )
            stage = work / "stragglers"
            stage.mkdir()
            for f in delta.stragglers:
                shutil.copy2(directory / f, stage / f)
                shutil.copy2(directory / f"{f}.sig", stage / f"{f}.sig")
                verify(args.nawa, stage / f, args.public_key)
            derived = work / "entries-stragglers.toml"
            derive(stage, args.repository, args.nawa, args.signing_key, derived, args.records_dir)
            for block in entry_blocks(derived.read_text(encoding="utf-8")):
                blocks[block_entry(block)["file"]] = block
        for f in delta.needed:
            entry = block_entry(blocks[f])
            known = digests.get((published[f], f))
            if known is not None and known != entry["sha256"]:
                raise PublishError(f"{f}: the entry describes other bytes than the published release asset")
        add_entries = work / "add-entries.toml"
        add_entries.write_text("".join(blocks[f] + "\n" for f in delta.needed), encoding="utf-8")
        package_urls = {f: download_url(args.repository, published[f], f) for f in delta.needed}

        def run_update(recipe_tag: str) -> None:
            locations = work / "locations.toml"
            locations.write_text(
                locations_manifest(package_urls, recipe_file, download_url(args.repository, recipe_tag, recipe_file)),
                encoding="utf-8",
            )
            command = [
                str(args.nawa), "repo-update", str(args.out_dir), "--base", str(base_path),
                "--trust-key", str(args.public_key), "--out", "index.toml",
                "--locations", str(locations), "--recipes", str(args.recipes),
                "--recipes-rev", args.revision, "--key", str(args.signing_key),
            ]
            if delta.needed:
                command += ["--add-entries", str(add_entries)]
            for f in delta.remove:
                command += ["--remove", f]
            for name in delta.drop:
                command += ["--drop", name]
            run(command)
            run([str(args.nawa), "sign", str(args.out_dir / recipe_file), "--key", str(args.signing_key)])

        # The snapshot's release is decided after packing it (its name is its
        # revision); packing is deterministic, so the second run changes only URLs.
        run_update(PLACEHOLDER_TAG)
        plan = RELEASES.build_plan(releases, args.out_dir, args.repository, STABLE_TAG, recipe_file, args.max_assets, 5)
        recipe_tag = plan["assignments"][recipe_file]
        args.plan.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if plan["reused"]:
            if not args.existing_dir:
                raise PublishError("update requires --existing-dir to authenticate a reused recipe snapshot")
            download_reused(args.plan, args.existing_dir, args.repository)
            verify_reused(args.plan, args.out_dir, args.existing_dir, args.nawa, args.public_key)
        (args.out_dir / "index.toml").unlink()
        (args.out_dir / "index.toml.sig").unlink()
        run_update(recipe_tag)

    verify_updated(args.out_dir, args.nawa, args.public_key, recipe_map, args.repository, holders, recipe_tag)
    print(
        f"updated the index: {len(delta.needed)} added ({len(delta.stragglers)} derived from downloads), "
        f"{len(delta.remove)} removed, {len(delta.drop)} dropped; plan: {args.plan}"
    )


def update_catalog(args: argparse.Namespace) -> None:
    """Previous signed catalog + new records, restricted to what the new index lists."""
    try:
        doc = tomllib.loads(args.index.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PublishError(f"cannot parse the index: {exc}") from exc
    indexed = {e["file"] for e in doc.get("package", []) if isinstance(e, dict) and "file" in e}
    records: dict[str, dict] = {}
    if args.base_catalog_dir is not None:
        pointer = args.base_catalog_dir / "catalog.toml"
        verify(args.nawa, pointer, args.public_key)
        try:
            meta = tomllib.loads(pointer.read_text(encoding="utf-8"))
            file, digest = meta["catalog_file"], meta["catalog_sha256"]
        except (KeyError, tomllib.TOMLDecodeError) as exc:
            raise PublishError(f"unreadable catalog pointer: {exc}") from exc
        if file != f"catalog-{digest}.json.zst":
            raise PublishError("catalog pointer names a file that is not content addressed")
        try:
            records = dict(CATALOG.load_catalog(args.base_catalog_dir / file))
        except CATALOG.CatalogError as exc:
            raise PublishError(str(exc)) from exc
    elif args.have_base_index:
        raise PublishError("an index is published but its catalog is not: rebuild it with the catalog backfill first")
    try:
        for path in sorted(args.records_dir.glob(f"*{CATALOG.RECORD_SUFFIX}")):
            record = CATALOG.load_record(path)
            if record["file"] in records and records[record["file"]] != record:
                raise PublishError(f"{record['file']}: a different record is already in the catalog (archives are immutable)")
            records[record["file"]] = record
        records = {f: r for f, r in records.items() if f in indexed}
        args.out_dir.mkdir(parents=True, exist_ok=True)
        CATALOG.write_catalog(records.values(), args.out_dir, args.index)
        errors, _ = CATALOG.verify(records, None, args.index, True)
    except CATALOG.CatalogError as exc:
        raise PublishError(str(exc)) from exc
    if errors:
        raise PublishError("catalog does not match the index:\n  " + "\n  ".join(errors[:30]))
    pointer = args.out_dir / "catalog.toml"
    text = pointer.read_text(encoding="utf-8").split("\n", 1)[1]  # drop the UNSIGNED notice
    pointer.write_text(text, encoding="utf-8")
    run([str(args.nawa), "sign", str(pointer), "--key", str(args.signing_key)])
    verify(args.nawa, pointer, args.public_key)
    print(f"catalog: {len(records)} record(s), one per indexed archive")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="check all recipe declarations and package-set coverage")
    audit.add_argument("--recipes", type=Path, required=True)
    audit.add_argument("--archive-dir", type=Path, required=True)

    check = sub.add_parser("check-recipes", help="validate explicit v5 declarations without package archives")
    check.add_argument("--recipes", type=Path, required=True)

    fetch = sub.add_parser("fetch-v3", help="fetch exact current archives from a signed schema-v3 index")
    fetch.add_argument("--index", type=Path, required=True)
    fetch.add_argument("--recipes", type=Path, required=True)
    fetch.add_argument("--archive-dir", type=Path, required=True)
    fetch.add_argument("--nawa", type=Path, required=True)
    fetch.add_argument("--public-key", type=Path, required=True)
    fetch.add_argument("--repository", required=True)

    stage = sub.add_parser("stage-wave", help="copy and sign the not-yet-published archives of one wave")
    stage.add_argument("--recipes", type=Path, required=True)
    stage.add_argument("--built-dir", type=Path, required=True)
    stage.add_argument("--releases-json", type=Path, required=True)
    stage.add_argument("--stage-dir", type=Path, required=True)
    stage.add_argument("--nawa", type=Path, required=True)
    stage.add_argument("--signing-key", type=Path, required=True)

    derive_p = sub.add_parser("derive", help="index entries and catalog records of signed archives")
    derive_p.add_argument("--archive-dir", type=Path, required=True)
    derive_p.add_argument("--repository", required=True)
    derive_p.add_argument("--nawa", type=Path, required=True)
    derive_p.add_argument("--signing-key", type=Path, required=True)
    derive_p.add_argument("--out-entries", type=Path, required=True)
    derive_p.add_argument("--records-dir", type=Path, required=True)

    for name, help_text in (
        ("stragglers", "list published archives the index lacks and no wave described"),
        ("update", "previous signed index + new archives -> new signed index"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--recipes", type=Path, required=True)
        p.add_argument("--releases-json", type=Path, required=True)
        p.add_argument("--base-index", type=Path, help="previous index.toml (omit before the first publication)")
        p.add_argument("--meta-dir", type=Path, help="directory holding the entries-*.toml of the waves")
        p.add_argument("--nawa", type=Path, required=True)
        p.add_argument("--public-key", type=Path, required=True)
        if name == "stragglers":
            p.add_argument("--output", type=Path, required=True)
        if name == "update":
            p.add_argument("--signing-key", type=Path, required=True)
            p.add_argument("--repository", required=True)
            p.add_argument("--stable-tag", default=STABLE_TAG)
            p.add_argument("--revision", required=True)
            p.add_argument("--straggler-dir", type=Path)
            p.add_argument("--records-dir", type=Path, required=True)
            p.add_argument("--out-dir", type=Path, required=True)
            p.add_argument("--plan", type=Path, required=True)
            p.add_argument("--existing-dir", type=Path)
            p.add_argument("--max-assets", type=int, default=900)

    cat = sub.add_parser("catalog", help="previous signed catalog + new records -> new signed catalog")
    cat.add_argument("--index", type=Path, required=True, help="the NEW index.toml")
    cat.add_argument("--records-dir", type=Path, required=True)
    cat.add_argument("--base-catalog-dir", type=Path, help="directory with the published catalog.toml(.sig) and catalog file")
    cat.add_argument("--have-base-index", action="store_true")
    cat.add_argument("--out-dir", type=Path, required=True)
    cat.add_argument("--nawa", type=Path, required=True)
    cat.add_argument("--signing-key", type=Path, required=True)
    cat.add_argument("--public-key", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "check-recipes":
            recipe_map = recipes(args.recipes)
            print(f"schema-v5 recipe declarations are complete: {len(recipe_map)} recipe(s)")
        elif args.command == "fetch-v3":
            fetch_v3(args.index, args.archive_dir, args.recipes, args.nawa, args.public_key, args.repository)
        elif args.command == "audit":
            recipe_map = recipes(args.recipes)
            archive_list = audit_archives(recipe_map, args.archive_dir)
            print(f"complete schema-v5 candidate set: {len(recipe_map)} recipe(s), {len(archive_list)} archive(s)")
        elif args.command == "stage-wave":
            stage_wave(
                recipes(args.recipes), args.built_dir, RELEASES.read_releases(args.releases_json),
                args.stage_dir, args.nawa, args.signing_key,
            )
        elif args.command == "derive":
            check_repository(args.repository)
            derive(args.archive_dir, args.repository, args.nawa, args.signing_key, args.out_entries, args.records_dir)
        elif args.command == "stragglers":
            fetch_list(args)
        elif args.command == "update":
            update_repository(args)
        else:
            update_catalog(args)
        return 0
    except (OSError, json.JSONDecodeError, PublishError, subprocess.SubprocessError) as exc:
        print(f"publish-schema-v5: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
