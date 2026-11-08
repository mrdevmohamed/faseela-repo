#!/usr/bin/env python3
"""scripts/check-file-conflicts.py — no two packages of one image may own the same file.

nawa refuses to install a package that ships a file another installed package
owns ("file conflicts installing X: /usr/bin/logger (owned by util-linux)"),
and it only finds out when the image is being assembled, one package at a time.
This looks at the BUILT archives instead, before they are published, and
answers for every flavor of flavors.toml at once.

    check-file-conflicts.py [ARCHIVE_DIR] [--catalog FILE] [--flavor NAME ...]
                            [--recipes DIR] [--flavors FILE] [--all] [--strict]

  ARCHIVE_DIR   directory holding <name>-<version>-<rel>.nawa.tar.zst
                (the exact version/rel each recipe currently says)
  --catalog     package catalog (scripts/package_catalog.py): file lists are
                read from its records instead of opening archives. An archive
                present in ARCHIVE_DIR still wins for the same file name, so
                packages built by this run are checked without a record. At
                least one of ARCHIVE_DIR and --catalog is required.
  --flavor      only these flavors (default: all of them)
  --all         also list files shared by packages that no single flavor
                installs together (alternatives such as linux-firmware and
                linux-firmware-lite are expected to overlap; informational)
  --strict      a package of a flavor without a built archive is an error
                (default: a warning, the archive may simply not be built yet)

Exit 1 when two packages of one flavor ship the same non-directory path.
Directories are shared by design. A directory in one package against a
symlink or file in another (the merged-/usr links of base-files vs the
directories of glibc) is fine when the symlink/file comes FIRST in the
flavor's install order and an error when it comes after (that is the
"/sbin (owned by glibc)" failure of base-files).

Paths below /bin, /sbin, /lib, /lib64 are compared after the merged-/usr
mapping base-files lays down (-> /usr/bin, /usr/bin, /usr/lib, /usr/lib64), so
a package that still ships /bin/x collides with one that ships /usr/bin/x.
An archive keeps its files under payload/; everything outside it (.PKGINFO,
the file list) is metadata.
Needs Python >= 3.11 and the `zstd` program.
"""
import argparse
import subprocess
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import flavor  # noqa: E402
import package_catalog  # noqa: E402

MERGED = {"bin": "usr/bin", "sbin": "usr/bin", "lib": "usr/lib", "lib64": "usr/lib64"}


def norm(name: str):
    """Path of an archive member inside the installed system, None for metadata."""
    p = name.strip("/")
    while p.startswith("./"):
        p = p[2:]
    parts = [x for x in p.split("/") if x and x != "."]
    if not parts or parts[0] != "payload":
        return None
    parts = parts[1:]
    # only what lives UNDER /bin, /sbin ... moves; the entry itself (base-files'
    # symlink, a package's directory of the same name) keeps its own path
    if len(parts) > 1 and parts[0] in MERGED:
        parts[:1] = MERGED[parts[0]].split("/")
    return "/".join(parts)


def read_archive(path: Path):
    """-> {normalised path: 'dir' | 'other'} for the payload of one archive."""
    out = {}
    proc = subprocess.Popen(
        ["zstd", "-dc", "--", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            for m in tf:
                p = norm(m.name)
                if p:  # None/"" : metadata, or the payload/ directory itself
                    out[p] = "dir" if m.isdir() else "other"
    finally:
        # tarfile's streaming reader stops at the tar end markers.  Consume
        # the rest of zstd's output so the decompressor can finish and verify
        # the complete compressed frame instead of dying with SIGPIPE.
        while proc.stdout.read(1024 * 1024):
            pass
        proc.stdout.close()
        stderr = proc.stderr.read()
        returncode = proc.wait()

    if returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        suffix = f": {detail}" if detail else ""
        raise OSError(f"{path}: zstd could not decompress it{suffix}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("archives", type=Path, nargs="?")
    ap.add_argument("--catalog", type=Path)
    ap.add_argument("--flavors", type=Path, default=ROOT / "flavors.toml")
    ap.add_argument("--recipes", type=Path, default=ROOT / "recipes")
    ap.add_argument("--flavor", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    if a.archives is None and a.catalog is None:
        ap.error("give an ARCHIVE_DIR, a --catalog, or both")
    catalog = package_catalog.load_catalog(a.catalog) if a.catalog else {}

    flavors = flavor.load_flavors(a.flavors)
    recipes_toml = {}
    for f in sorted(a.recipes.glob("*/*/recipe.toml")):
        import tomllib
        pkg = tomllib.loads(f.read_text(encoding="utf-8"))["package"]
        recipes_toml[pkg["name"]] = f"{pkg['name']}-{pkg['version']}-{pkg.get('rel', 1)}.nawa.tar.zst"
    recipes = flavor.load_recipes(a.recipes)

    cache = {}

    def files(pkg):
        if pkg not in cache:
            arc = a.archives / recipes_toml[pkg] if a.archives else None
            if arc is not None and arc.exists():
                cache[pkg] = read_archive(arc)
            elif recipes_toml[pkg] in catalog:
                # the records hold RAW payload paths; norm() applies the same
                # merged-/usr mapping an archive member goes through
                cache[pkg] = {norm("payload/" + path): kind
                              for path, kind in package_catalog.files_of(catalog[recipes_toml[pkg]]).items()}
            else:
                cache[pkg] = None
        return cache[pkg]

    errors, warnings = [], []
    names = a.flavor or list(flavors)
    together = set()  # (pkgA, pkgB) installed together by some flavor
    for fl in names:
        pkgs = flavor.resolve(flavors, recipes, fl)
        owners = defaultdict(list)  # path -> [(pkg, kind)]
        for pkg in pkgs:
            idx = files(pkg)
            if idx is None:
                (errors if a.strict else warnings).append(
                    f"{fl}: no archive {recipes_toml[pkg]} for {pkg} - not checked")
                continue
            for path, kind in idx.items():
                owners[path].append((pkg, kind))
        for path, own in sorted(owners.items()):
            if len(own) < 2:
                continue
            solid = [p for p, k in own if k != "dir"]
            if len(solid) >= 2:
                errors.append(f"{fl}: /{path} is shipped by {', '.join(solid)}")
                together.update((x, y) for x in solid for y in solid if x < y)
            elif solid:
                dirs = [p for p, k in own if k == "dir"]
                late = [d for d in dirs if pkgs.index(d) < pkgs.index(solid[0])]
                if late:
                    errors.append(f"{fl}: /{path} is a file/symlink of {solid[0]} but a directory of "
                                  f"{', '.join(late)}, installed before it - {solid[0]} must come first")

    if a.all:
        every = defaultdict(list)
        for pkg in recipes_toml:
            idx = files(pkg)
            for path, kind in (idx or {}).items():
                if kind != "dir":
                    every[path].append(pkg)
        for path, own in sorted(every.items()):
            if len(own) > 1 and not any((x, y) in together for x in own for y in own if x < y):
                warnings.append(f"(no flavor installs them together) /{path}: {', '.join(own)}")

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"CONFLICT {e}")
    n = len(errors)
    print(f"{n} file conflict(s) in {len(names)} flavor(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
