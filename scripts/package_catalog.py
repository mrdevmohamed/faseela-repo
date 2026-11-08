#!/usr/bin/env python3
"""scripts/package_catalog.py - package records and the package catalog.

Phase 0 of docs/package-repository-design.md. A package *record* is a small
JSON document derived once from a built archive; the *catalog* is the set of
records. Neither is read by end-user `nawa` clients, so the signed index schema
is untouched. They exist so that publisher-side work (index checks, file
conflict checks) does not have to reopen every archive.

    package_catalog.py record  ARCHIVE... --out-dir DIR
    package_catalog.py build   ARCHIVE_DIR --out-dir DIR [--index index.toml]
    package_catalog.py merge   --catalog CAT [--add RECORD...] [--remove FILE...]
                               --out-dir DIR [--index index.toml]
    package_catalog.py verify  --catalog CAT [--archives DIR] [--index index.toml]
                               [--strict]

  record   write <name>-<ver>-<rel>.nawa.record.json.zst for each archive
  build    records for every archive of a directory plus the catalog and its
           pointer; deterministic (same archives -> same catalog bytes)
  merge    new catalog from an old one plus records, WITHOUT opening archives
  verify   catalog against archives (sha256 and size) and/or against a
           repository index.toml (file, version, rel, arch, sha256, size)

The catalog file is named catalog-<sha256 of its canonical JSON>.json.zst, so
it is immutable and safe to cache forever. catalog.toml names the current
catalog. NOTE: catalog.toml written here is NOT signed. Signing it with the
repository key (`nawa sign`) belongs to the publish job and is not implemented
in this script; never publish an unsigned pointer.

Compression goes through the `zstd` program, like check-file-conflicts.py.
Needs Python >= 3.11.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

SCHEMA = 1
ARCHIVE_SUFFIX = ".nawa.tar.zst"
RECIPES_SUFFIX = ".recipes.tar.zst"
RECORD_SUFFIX = ".nawa.record.json.zst"
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~:-]*\Z")
CATALOG_RE = re.compile(r"catalog-([0-9a-f]{64})\.json\.zst\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class CatalogError(Exception):
    """A record, catalog or archive that cannot be used."""


# --------------------------------------------------------------------------
# zstd and file helpers
# --------------------------------------------------------------------------

def zstd_compress(data: bytes) -> bytes:
    proc = subprocess.run(["zstd", "-q", "-19", "-c"], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise CatalogError("zstd could not compress: " + proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def zstd_decompress_file(path: Path) -> bytes:
    proc = subprocess.run(["zstd", "-dc", "--", str(path)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise CatalogError(f"{path}: zstd could not decompress it: "
                           + proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def sha256_file(path: Path):
    """-> (hex digest, size in bytes) of one file."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def canonical(obj) -> bytes:
    """Deterministic JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

def parse_pkginfo(text: str, where: str) -> dict:
    """Validate the package metadata required to create a schema-v3 index."""
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        info[k.strip()] = v.strip()
    name = info.get("pkgname", "")
    if not NAME_RE.fullmatch(name):
        raise CatalogError(f"{where}: .PKGINFO has a missing or invalid pkgname {name!r}")
    version = info.get("pkgver", "")
    if not VERSION_RE.fullmatch(version):
        raise CatalogError(f"{where}: .PKGINFO has a missing or invalid pkgver {version!r}")
    raw_rel = info.get("pkgrel")
    if raw_rel is None:
        raise CatalogError(f"{where}: .PKGINFO is missing pkgrel")
    if not raw_rel.isascii() or not raw_rel.isdigit():
        raise CatalogError(f"{where}: .PKGINFO has an invalid pkgrel {raw_rel!r}")
    rel = int(raw_rel)
    if rel == 0:
        raise CatalogError(f"{where}: .PKGINFO has invalid pkgrel 0")
    arch = info.get("arch", "")
    if not arch or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", arch):
        raise CatalogError(f"{where}: .PKGINFO has a missing or invalid arch {arch!r}")
    installed = info.get("size")
    if installed is None or not installed.isascii() or not installed.isdigit():
        raise CatalogError(f"{where}: .PKGINFO has a missing or invalid size {installed!r}")
    return {
        "name": name,
        "version": version,
        "rel": rel,
        "arch": arch,
        "installed_size": int(installed),
    }


def _safe_parts(name: str, where: str):
    """Return normalized archive path components, rejecting traversal."""
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise CatalogError(f"{where}: unsafe archive path {name!r}")
    if name.startswith("/"):
        raise CatalogError(f"{where}: absolute archive path {name!r}")
    # Tar directory members conventionally end in one slash.
    normalized = name.rstrip("/")
    parts = normalized.split("/")
    while parts and parts[0] in ("", "."):
        parts.pop(0)
    if any(part in ("", ".", "..") for part in parts):
        raise CatalogError(f"{where}: unsafe archive path {name!r}")
    return [part for part in parts if part != "."]


def _strip(name: str):
    p = name.strip("/")
    while p.startswith("./"):
        p = p[2:]
    return [x for x in p.split("/") if x and x != "."]


def scan_archive(path: Path):
    """One streaming pass -> (.PKGINFO text, [{"path", "kind"}]) for an archive.

    Paths are the RAW ones below payload/ (no merged-/usr mapping: that is a
    policy of the consumer, applied at check time). kind is "dir" or "other"
    (file, symlink or anything else), the distinction check-file-conflicts needs.
    """
    proc = subprocess.Popen(["zstd", "-dc", "--", str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pkginfo = None
    files = {}
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            for m in tf:
                parts = _safe_parts(m.name, str(path))
                if parts == [".PKGINFO"]:
                    f = tf.extractfile(m)
                    if f is not None:
                        pkginfo = f.read().decode("utf-8", "replace")
                    continue
                if len(parts) > 1 and parts[0] == "payload":
                    files["/".join(parts[1:])] = "dir" if m.isdir() else "other"
    except tarfile.TarError as exc:
        raise CatalogError(f"{path}: not a readable archive: {exc}") from exc
    finally:
        # drain the rest so zstd can verify the whole frame instead of SIGPIPE
        while proc.stdout.read(1024 * 1024):
            pass
        proc.stdout.close()
        stderr = proc.stderr.read()
        proc.stderr.close()
        returncode = proc.wait()
    if returncode != 0:
        raise CatalogError(f"{path}: zstd could not decompress it: "
                           + stderr.decode("utf-8", "replace").strip())
    if pkginfo is None:
        raise CatalogError(f"{path}: no .PKGINFO in archive")
    return pkginfo, [{"path": p, "kind": files[p]} for p in sorted(files)]


def make_record(archive: Path) -> dict:
    """Derive the record of one archive, from the archive itself."""
    if not archive.name.endswith(ARCHIVE_SUFFIX) or archive.name.endswith(RECIPES_SUFFIX):
        raise CatalogError(f"{archive}: not a package archive name")
    pkginfo, files = scan_archive(archive)
    info = parse_pkginfo(pkginfo, str(archive))
    expected = f"{info['name']}-{info['version']}-{info['rel']}{ARCHIVE_SUFFIX}"
    if archive.name != expected:
        raise CatalogError(f"{archive}: file name does not match its .PKGINFO (expected {expected})")
    sha256, size = sha256_file(archive)
    return {
        "schema": SCHEMA,
        "name": info["name"],
        "version": info["version"],
        "rel": info["rel"],
        "arch": info["arch"],
        "file": archive.name,
        "sha256": sha256,
        "size": size,
        "installed_size": info["installed_size"],
        "files": files,
    }


def record_filename(file: str) -> str:
    return file[: -len(ARCHIVE_SUFFIX)] + RECORD_SUFFIX


def validate_record(rec, where: str) -> dict:
    expected_keys = {"schema", "name", "version", "rel", "arch", "file", "sha256",
                     "size", "installed_size", "files"}
    if (not isinstance(rec, dict) or set(rec) != expected_keys
            or type(rec.get("schema")) is not int or rec["schema"] != SCHEMA):
        raise CatalogError(f"{where}: not a schema-{SCHEMA} package record")
    for key, typ in (("name", str), ("version", str), ("rel", int), ("arch", str), ("file", str),
                     ("sha256", str), ("size", int), ("installed_size", int), ("files", list)):
        if not isinstance(rec.get(key), typ) or isinstance(rec.get(key), bool):
            raise CatalogError(f"{where}: record field {key!r} is missing or has the wrong type")
    if (not NAME_RE.fullmatch(rec["name"]) or not VERSION_RE.fullmatch(rec["version"])
            or rec["rel"] < 1 or not rec["arch"]
            or not re.fullmatch(r"[A-Za-z0-9_+-]+", rec["arch"])):
        raise CatalogError(f"{where}: record has an invalid name, version, rel or arch")
    if rec["size"] < 0 or rec["installed_size"] < 0:
        raise CatalogError(f"{where}: record size fields must be non-negative integers")
    if rec["file"] != f"{rec['name']}-{rec['version']}-{rec['rel']}{ARCHIVE_SUFFIX}":
        raise CatalogError(f"{where}: record file name does not match name-version-rel")
    if not SHA256_RE.fullmatch(rec["sha256"]):
        raise CatalogError(f"{where}: record sha256 is not 64 lowercase hex digits")
    seen_paths = {}
    for item in rec["files"]:
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or item.get("kind") not in ("dir", "other")):
            raise CatalogError(f"{where}: record has a malformed files entry {item!r}")
        raw_path = item["path"]
        if (not raw_path or raw_path.startswith("/") or "\\" in raw_path
                or "\x00" in raw_path or any(part in ("", ".", "..") for part in raw_path.split("/"))):
            raise CatalogError(f"{where}: record has an unsafe payload path {raw_path!r}")
        if raw_path in seen_paths:
            raise CatalogError(f"{where}: record has duplicate payload path {raw_path!r}")
        seen_paths[raw_path] = item["kind"]
    return rec


def load_record(path: Path) -> dict:
    try:
        rec = json.loads(zstd_decompress_file(path))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path}: not valid JSON: {exc}") from exc
    return validate_record(rec, str(path))


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------

def catalog_bytes(records) -> bytes:
    """Canonical JSON of a record set. One record per archive file name."""
    by_file = {}
    for rec in records:
        if rec["file"] in by_file and by_file[rec["file"]] != rec:
            raise CatalogError(f"two different records for {rec['file']}")
        by_file[rec["file"]] = rec
    return canonical({"schema": SCHEMA, "records": [by_file[f] for f in sorted(by_file)]})


def load_catalog(path: Path) -> dict:
    """-> {archive file name: record}"""
    raw = zstd_decompress_file(path)
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path}: not valid JSON: {exc}") from exc
    if (not isinstance(doc, dict) or set(doc) != {"schema", "records"}
            or type(doc.get("schema")) is not int or doc["schema"] != SCHEMA
            or not isinstance(doc.get("records"), list)):
        raise CatalogError(f"{path}: not a schema-{SCHEMA} catalog")
    if canonical(doc) != raw:
        raise CatalogError(f"{path}: catalog JSON is not in canonical form")
    out = {}
    for rec in doc["records"]:
        validate_record(rec, str(path))
        if rec["file"] in out:
            raise CatalogError(f"{path}: duplicate record for {rec['file']}")
        out[rec["file"]] = rec
    m = CATALOG_RE.fullmatch(path.name)
    if not m:
        raise CatalogError(f"{path}: catalog filename must be catalog-<sha256>.json.zst")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != m.group(1):
        raise CatalogError(f"{path}: content does not match the sha256 in its file name")
    return out


def write_catalog(records, out_dir: Path, index: Path | None = None) -> Path:
    """Write catalog-<sha>.json.zst and the (UNSIGNED) catalog.toml pointer."""
    raw = catalog_bytes(records)
    digest = hashlib.sha256(raw).hexdigest()
    name = f"catalog-{digest}.json.zst"
    atomic_write(out_dir / name, zstd_compress(raw))
    pointer = [
        "# UNSIGNED catalog pointer. Sign it with the repository key before publishing.",
        "schema = 1",
        f'catalog_file = "{name}"',
        f'catalog_sha256 = "{digest}"',
    ]
    if index is not None:
        pointer.append(f'index_sha256 = "{sha256_file(index)[0]}"')
    atomic_write(out_dir / "catalog.toml", ("\n".join(pointer) + "\n").encode("utf-8"))
    return out_dir / name


def files_of(record: dict) -> dict:
    """-> {raw payload path: 'dir' | 'other'}; what check-file-conflicts consumes."""
    return {item["path"]: item["kind"] for item in record["files"]}


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify(catalog: dict, archives: Path | None, index: Path | None, strict: bool):
    """-> (errors, warnings), both lists of messages."""
    errors, warnings = [], []
    if archives is not None:
        present = set()
        for p in sorted(archives.iterdir()):
            if p.name.endswith(ARCHIVE_SUFFIX) and not p.name.endswith(RECIPES_SUFFIX):
                present.add(p.name)
        for file, rec in sorted(catalog.items()):
            path = archives / file
            if file not in present:
                warnings.append(f"{file}: in the catalog but not in {archives}")
                continue
            sha256, size = sha256_file(path)
            if size != rec["size"]:
                errors.append(f"{file}: size {size} differs from the catalog ({rec['size']})")
            if sha256 != rec["sha256"]:
                errors.append(f"{file}: sha256 differs from the catalog")
        for file in sorted(present - set(catalog)):
            (errors if strict else warnings).append(f"{file}: archive has no record in the catalog")
    if index is not None:
        try:
            entries = tomllib.loads(index.read_text(encoding="utf-8")).get("package", [])
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise CatalogError(f"{index}: cannot read index: {exc}") from exc
        for e in entries:
            file = e.get("file")
            rec = catalog.get(file)
            if rec is None:
                errors.append(f"{file}: in the index but has no record in the catalog")
                continue
            for key in ("name", "version", "rel", "arch", "sha256", "size", "installed_size"):
                if e.get(key, 0 if key in ("size", "installed_size") else None) != rec[key]:
                    errors.append(f"{file}: index {key} {e.get(key)!r} differs from the catalog {rec[key]!r}")
        # One direction only: every indexed package must match a record. The
        # catalog may hold older archives the index no longer lists (it keeps
        # the newest per name), and deciding which one is newest needs nawa's
        # version comparison, which is deliberately not re-implemented here.
    return errors, warnings


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

def archives_in(directory: Path):
    return sorted(p for p in directory.iterdir()
                  if p.name.endswith(ARCHIVE_SUFFIX) and not p.name.endswith(RECIPES_SUFFIX))


def cmd_record(a):
    for archive in a.archives:
        rec = make_record(archive)
        atomic_write(a.out_dir / record_filename(rec["file"]), zstd_compress(canonical(rec)))
        print(f"record {rec['file']} ({len(rec['files'])} paths)")


def cmd_build(a):
    records = []
    for archive in archives_in(a.archive_dir):
        rec = make_record(archive)
        atomic_write(a.out_dir / record_filename(rec["file"]), zstd_compress(canonical(rec)))
        records.append(rec)
    cat = write_catalog(records, a.out_dir, a.index)
    print(f"catalog {cat.name}: {len(records)} record(s)")


def cmd_merge(a):
    records = dict(load_catalog(a.catalog))
    for file in a.remove or []:
        if records.pop(file, None) is None:
            raise CatalogError(f"--remove {file}: not in the catalog")
    for path in a.add or []:
        rec = load_record(path)
        records[rec["file"]] = rec
    cat = write_catalog(records.values(), a.out_dir, a.index)
    print(f"catalog {cat.name}: {len(records)} record(s)")


def cmd_verify(a):
    errors, warnings = verify(load_catalog(a.catalog), a.archives, a.index, a.strict)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"MISMATCH {e}")
    print(f"{len(errors)} mismatch(es), {len(warnings)} warning(s)")
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record")
    p.add_argument("archives", type=Path, nargs="+")
    p.add_argument("--out-dir", type=Path, required=True)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("build")
    p.add_argument("archive_dir", type=Path)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--index", type=Path)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("merge")
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--add", type=Path, nargs="*")
    p.add_argument("--remove", nargs="*")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--index", type=Path)
    p.set_defaults(fn=cmd_merge)

    p = sub.add_parser("verify")
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--archives", type=Path)
    p.add_argument("--index", type=Path)
    p.add_argument("--strict", action="store_true")
    p.set_defaults(fn=cmd_verify)

    a = ap.parse_args(argv)
    try:
        return a.fn(a) or 0
    except CatalogError as exc:
        print(f"package_catalog: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
