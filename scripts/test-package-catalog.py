#!/usr/bin/env python3
"""scripts/test-package-catalog.py - package records, the catalog, and the
catalog-based file-conflict check, on synthetic archives.

Archives are real tar files. When the machine has no `zstd`, a pass-through shim
stands in for it (the tools only ever run `zstd -dc FILE` and `zstd ... -c`
reading stdin), exactly like test-file-conflicts.py."""
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import package_catalog as pc  # noqa: E402

REAL_ZSTD = shutil.which("zstd")  # looked up before any shim is put on PATH
CHECKER = HERE / "check-file-conflicts.py"
TOOL = HERE / "package_catalog.py"


def pkginfo(name, version="1", rel=1, extra=""):
    return (f"pkgname = {name}\npkgver = {version}\npkgrel = {rel}\narch = x86_64\n"
            f"size = 1234\n{extra}").encode()


def make_archive(path: Path, entries: dict):
    """entries: name -> bytes (file) | None (dir) | ('->', target) (symlink)."""
    with tarfile.open(path, "w") as tf:
        for name, v in entries.items():
            ti = tarfile.TarInfo(name)
            if v is None:
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                tf.addfile(ti)
            elif isinstance(v, tuple):
                ti.type = tarfile.SYMTYPE
                ti.linkname = v[1]
                tf.addfile(ti)
            else:
                ti.size = len(v)
                tf.addfile(ti, io.BytesIO(v))
    if REAL_ZSTD:
        tmp = path.with_name(path.name + ".tmp")
        subprocess.run(["zstd", "-q", "-f", str(path), "-o", str(tmp)], check=True)
        os.replace(tmp, path)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "out").mkdir()
        self._path = os.environ["PATH"]
        if not REAL_ZSTD:
            (self.d / "bin").mkdir()
            shim = self.d / "bin" / "zstd"
            shim.write_text('#!/bin/sh\nfor last; do :; done\n'
                            'if [ -f "$last" ]; then exec cat "$last"; else exec cat; fi\n')
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            os.environ["PATH"] = f"{self.d / 'bin'}:{self._path}"

    def tearDown(self):
        os.environ["PATH"] = self._path
        self.tmp.cleanup()

    def archive(self, name, entries, version="1", rel=1, info=None):
        path = self.d / "out" / f"{name}-{version}-{rel}.nawa.tar.zst"
        make_archive(path, {".PKGINFO": info or pkginfo(name, version, rel), "payload/": None,
                            **{f"payload/{k}": v for k, v in entries.items()}})
        return path

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *map(str, args)],
                              capture_output=True, text=True, env=os.environ)

    def build(self, name="cat"):
        out = self.d / name
        r = self.run_tool("build", self.d / "out", "--out-dir", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (cat,) = out.glob("catalog-*.json.zst")
        return out, cat


class Records(Base):
    def test_record_fields_and_raw_sorted_paths(self):
        arc = self.archive("tool", {"usr/": None, "usr/bin/": None, "usr/bin/tool": b"x",
                                    "sbin": ("->", "usr/bin"), "bin/old": b"y"})
        rec = pc.make_record(arc)
        sha, size = pc.sha256_file(arc)
        self.assertEqual((rec["name"], rec["version"], rec["rel"], rec["arch"]),
                         ("tool", "1", 1, "x86_64"))
        self.assertEqual((rec["file"], rec["sha256"], rec["size"], rec["installed_size"]),
                         ("tool-1-1.nawa.tar.zst", sha, size, 1234))
        # raw payload paths (no merged-/usr mapping), sorted, payload/ itself and
        # .PKGINFO are not part of the file list
        self.assertEqual(rec["files"], [
            {"path": "bin/old", "kind": "other"},
            {"path": "sbin", "kind": "other"},
            {"path": "usr", "kind": "dir"},
            {"path": "usr/bin", "kind": "dir"},
            {"path": "usr/bin/tool", "kind": "other"},
        ])

    def test_invalid_pkginfo_is_rejected(self):
        cases = {
            "no-rel": b"pkgname = a\npkgver = 1\n",
            "rel-zero": pkginfo("rel-zero", rel=0),
            "rel-text": b"pkgname = rel-text\npkgver = 1\npkgrel = x\n",
            "bad-name": b"pkgname = ../evil\npkgver = 1\npkgrel = 1\n",
        }
        for name, info in cases.items():
            with self.subTest(name):
                arc = self.archive(name, {"usr/bin/x": b"1"}, info=info)
                with self.assertRaises(pc.CatalogError):
                    pc.make_record(arc)

    def test_file_name_must_match_pkginfo(self):
        arc = self.archive("tool", {"usr/bin/x": b"1"}, info=pkginfo("tool", "2", 1))
        with self.assertRaises(pc.CatalogError):
            pc.make_record(arc)

    def test_archive_without_pkginfo_is_rejected(self):
        path = self.d / "out" / "bare-1-1.nawa.tar.zst"
        make_archive(path, {"payload/usr/bin/x": b"1"})
        with self.assertRaises(pc.CatalogError):
            pc.make_record(path)

    def test_record_command_round_trips(self):
        arc = self.archive("tool", {"usr/bin/tool": b"x"})
        r = self.run_tool("record", arc, "--out-dir", self.d / "rec")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = pc.load_record(self.d / "rec" / "tool-1-1.nawa.record.json.zst")
        self.assertEqual(rec, pc.make_record(arc))

    def test_pkginfo_requires_arch_and_nonnegative_decimal_size(self):
        cases = (
            b"pkgname = a\npkgver = 1\npkgrel = 1\nsize = 10\n",
            b"pkgname = a\npkgver = 1\npkgrel = 1\narch = x86_64\n",
            b"pkgname = a\npkgver = 1\npkgrel = 1\narch = x86_64\nsize = nope\n",
            b"pkgname = a\npkgver = 1\npkgrel = 1\narch = x86_64\nsize = -1\n",
        )
        for info in cases:
            with self.subTest(info=info):
                with self.assertRaises(pc.CatalogError):
                    pc.parse_pkginfo(info.decode(), "test")

    def test_record_rejects_unsafe_and_duplicate_paths(self):
        arc = self.archive("tool", {"usr/bin/tool": b"x"})
        rec = pc.make_record(arc)
        for bad in ("../escape", "/absolute", "usr//bin/tool", "usr/./bin/tool", r"usr\\bin\\tool"):
            changed = dict(rec)
            changed["files"] = [{"path": bad, "kind": "other"}]
            with self.subTest(path=bad), self.assertRaises(pc.CatalogError):
                pc.validate_record(changed, "test")
        changed = dict(rec)
        changed["files"] = [{"path": "usr/bin/tool", "kind": "other"},
                            {"path": "usr/bin/tool", "kind": "other"}]
        with self.assertRaises(pc.CatalogError):
            pc.validate_record(changed, "test")

    def test_archive_payload_path_traversal_is_rejected(self):
        arc = self.archive("tool", {"../escape": b"x"})
        with self.assertRaises(pc.CatalogError):
            pc.make_record(arc)


class Catalog(Base):
    def test_build_is_deterministic_and_content_addressed(self):
        self.archive("a", {"usr/bin/a": b"1"})
        self.archive("b", {"usr/bin/b": b"2"})
        out1, cat1 = self.build("one")
        out2, cat2 = self.build("two")
        self.assertEqual(cat1.name, cat2.name)
        self.assertEqual(cat1.read_bytes(), cat2.read_bytes())
        self.assertRegex(cat1.name, r"^catalog-[0-9a-f]{64}\.json\.zst$")
        pointer = (out1 / "catalog.toml").read_text()
        self.assertIn("UNSIGNED", pointer)
        self.assertIn(f'catalog_file = "{cat1.name}"', pointer)
        self.assertEqual(sorted(pc.load_catalog(cat1)),
                         ["a-1-1.nawa.tar.zst", "b-1-1.nawa.tar.zst"])

    def test_recipe_snapshots_are_not_packages(self):
        self.archive("a", {"usr/bin/a": b"1"})
        (self.d / "out" / "recipes-abc.recipes.tar.zst").write_bytes(b"not a package")
        _, cat = self.build()
        self.assertEqual(list(pc.load_catalog(cat)), ["a-1-1.nawa.tar.zst"])

    def test_tampered_catalog_name_is_detected(self):
        self.archive("a", {"usr/bin/a": b"1"})
        out, cat = self.build()
        other = out / ("catalog-" + "0" * 64 + ".json.zst")
        shutil.copy(cat, other)
        with self.assertRaises(pc.CatalogError):
            pc.load_catalog(other)

    def test_catalog_requires_content_addressed_filename(self):
        self.archive("a", {"usr/bin/a": b"1"})
        out, cat = self.build()
        plain = out / "catalog.json.zst"
        shutil.copy(cat, plain)
        with self.assertRaises(pc.CatalogError):
            pc.load_catalog(plain)

    def test_catalog_rejects_noncanonical_json_even_with_matching_name(self):
        self.archive("a", {"usr/bin/a": b"1"})
        out, cat = self.build()
        noncanonical = pc.zstd_decompress_file(cat) + b"\\n"
        renamed = out / ("catalog-" + hashlib.sha256(noncanonical).hexdigest() + ".json.zst")
        renamed.write_bytes(pc.zstd_compress(noncanonical))
        with self.assertRaises(pc.CatalogError):
            pc.load_catalog(renamed)

    def test_merge_equals_a_fresh_build(self):
        # the catalog-level form of the repo-update == repo-create invariant:
        # merging records into an old catalog gives what a full rebuild gives
        self.archive("keep", {"usr/bin/keep": b"1"})
        self.archive("old", {"usr/bin/old": b"1"})
        self.archive("swap", {"usr/bin/swap": b"1"})
        _, base = self.build("base")

        (self.d / "out" / "old-1-1.nawa.tar.zst").unlink()
        new = self.archive("swap", {"usr/bin/swap": b"2", "usr/bin/swap2": b"3"}, rel=2)
        added = self.archive("fresh", {"usr/bin/fresh": b"4"})
        r = self.run_tool("record", new, added, "--out-dir", self.d / "rec")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        r = self.run_tool("merge", "--catalog", base,
                          "--add", self.d / "rec" / "swap-1-2.nawa.record.json.zst",
                          self.d / "rec" / "fresh-1-1.nawa.record.json.zst",
                          "--remove", "old-1-1.nawa.tar.zst", "--out-dir", self.d / "merged")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        # a fresh build over the same archive set (swap-1-1 is still present)
        _, fresh = self.build("fresh")
        (merged,) = (self.d / "merged").glob("catalog-*.json.zst")
        self.assertEqual(merged.name, fresh.name)

    def test_merge_refuses_to_remove_an_unknown_file(self):
        self.archive("a", {"usr/bin/a": b"1"})
        _, cat = self.build()
        r = self.run_tool("merge", "--catalog", cat, "--remove", "ghost-1-1.nawa.tar.zst",
                          "--out-dir", self.d / "merged")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ghost-1-1.nawa.tar.zst", r.stderr)


class Verify(Base):
    def test_matching_archives_verify(self):
        self.archive("a", {"usr/bin/a": b"1"})
        _, cat = self.build()
        r = self.run_tool("verify", "--catalog", cat, "--archives", self.d / "out", "--strict")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_changed_archive_is_a_mismatch(self):
        arc = self.archive("a", {"usr/bin/a": b"1"})
        _, cat = self.build()
        make_archive(arc, {".PKGINFO": pkginfo("a"), "payload/": None, "payload/usr/bin/a": b"changed"})
        r = self.run_tool("verify", "--catalog", cat, "--archives", self.d / "out")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("MISMATCH a-1-1.nawa.tar.zst", r.stdout)

    def test_archive_without_record_is_strict_only(self):
        self.archive("a", {"usr/bin/a": b"1"})
        _, cat = self.build()
        self.archive("b", {"usr/bin/b": b"2"})
        lax = self.run_tool("verify", "--catalog", cat, "--archives", self.d / "out")
        self.assertEqual(lax.returncode, 0, lax.stdout + lax.stderr)
        self.assertIn("b-1-1.nawa.tar.zst: archive has no record", lax.stderr)
        strict = self.run_tool("verify", "--catalog", cat, "--archives", self.d / "out", "--strict")
        self.assertEqual(strict.returncode, 1)

    def index_for(self, records, **override):
        lines = ["[repository]", "schema = 3", ""]
        for rec in records:
            e = {k: rec[k] for k in ("name", "version", "rel", "arch", "file", "sha256", "size",
                                     "installed_size")}
            e.update(override)
            lines.append("[[package]]")
            lines += [f"{k} = {v!r}".replace("'", '"') for k, v in e.items()]
            lines.append("")
        path = self.d / "index.toml"
        path.write_text("\n".join(lines))
        return path

    def test_index_matches_catalog(self):
        a = self.archive("a", {"usr/bin/a": b"1"})
        _, cat = self.build()
        index = self.index_for([pc.make_record(a)])
        r = self.run_tool("verify", "--catalog", cat, "--index", index)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_index_drift_is_reported(self):
        a = self.archive("a", {"usr/bin/a": b"1"})
        _, cat = self.build()
        index = self.index_for([pc.make_record(a)], sha256="f" * 64)
        r = self.run_tool("verify", "--catalog", cat, "--index", index)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("sha256", r.stdout)

    def test_indexed_package_without_a_record_is_reported(self):
        a = self.archive("a", {"usr/bin/a": b"1"})
        rec = pc.make_record(a)
        a.unlink()
        self.archive("b", {"usr/bin/b": b"2"})
        _, cat = self.build()
        index = self.index_for([rec])
        r = self.run_tool("verify", "--catalog", cat, "--index", index)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("has no record in the catalog", r.stdout)


class ConflictParity(Base):
    """The catalog-based check must report exactly what the archive-based one does."""

    def recipe(self, name):
        p = self.d / "recipes" / "base" / name
        p.mkdir(parents=True, exist_ok=True)
        (p / "recipe.toml").write_text(
            f'[package]\nname = "{name}"\nversion = "1"\nrel = 1\n[depends]\nbuild = []\nrun = []\n')

    def check(self, flavors_toml, *extra, catalog=None, archives=True):
        (self.d / "f.toml").write_text(textwrap.dedent(flavors_toml))
        cmd = [sys.executable, str(CHECKER)]
        if archives:
            cmd.append(str(self.d / "out"))
        if catalog:
            cmd += ["--catalog", str(catalog)]
        cmd += ["--flavors", str(self.d / "f.toml"), "--recipes", str(self.d / "recipes"), *extra]
        return subprocess.run(cmd, capture_output=True, text=True, env=os.environ)

    def assert_parity(self, flavors_toml, *extra):
        _, cat = self.build()
        want = self.check(flavors_toml, *extra)
        got = self.check(flavors_toml, *extra, catalog=cat, archives=False)
        self.assertEqual((got.returncode, got.stdout, got.stderr),
                         (want.returncode, want.stdout, want.stderr))
        return want

    def test_shared_file_conflict(self):
        for n in ("util-linux", "sysklogd"):
            self.recipe(n)
        self.archive("util-linux", {"usr/": None, "usr/bin/": None, "usr/bin/logger": b"a"})
        self.archive("sysklogd", {"usr/bin/logger": b"b", "usr/sbin/syslogd": b"c"})
        r = self.assert_parity('[flavor.x]\ninclude = ["util-linux", "sysklogd"]\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn("/usr/bin/logger is shipped by util-linux, sysklogd", r.stdout)

    def test_merged_usr_paths_collide(self):
        for n in ("old", "new"):
            self.recipe(n)
        self.archive("old", {"bin/tool": b"1"})
        self.archive("new", {"usr/bin/tool": b"2"})
        r = self.assert_parity('[flavor.x]\ninclude = ["old", "new"]\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn("/usr/bin/tool", r.stdout)

    def test_symlink_before_directory_ordering(self):
        for n in ("links", "libc"):
            self.recipe(n)
        self.archive("links", {"sbin": ("->", "usr/bin")})
        self.archive("libc", {"usr/": None, "usr/bin/": None, "usr/bin/ldd": b"1", "sbin/": None})
        good = self.assert_parity('[flavor.x]\ninclude = ["links", "libc"]\n')
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        bad = self.assert_parity('[flavor.x]\ninclude = ["libc", "links"]\n')
        self.assertEqual(bad.returncode, 1)
        self.assertIn("/sbin is a file/symlink of links but a directory of libc", bad.stdout)

    def test_all_flag_and_disjoint_packages(self):
        for n in ("fw", "fw-lite"):
            self.recipe(n)
        self.archive("fw", {"usr/lib/firmware/x.bin": b"1"})
        self.archive("fw-lite", {"usr/lib/firmware/x.bin": b"1"})
        toml = '[flavor.big]\ninclude = ["fw"]\n[flavor.small]\ninclude = ["fw-lite"]\n'
        r = self.assert_parity(toml, "--all")
        self.assertIn("no flavor installs them together", r.stderr)

    def test_missing_package_behaves_like_a_missing_archive(self):
        self.recipe("ghost")
        toml = '[flavor.x]\ninclude = ["ghost"]\n'
        lax = self.assert_parity(toml)
        self.assertIn("no archive ghost-1-1.nawa.tar.zst", lax.stderr)
        strict = self.assert_parity(toml, "--strict")
        self.assertEqual(strict.returncode, 1)

    def test_archive_of_this_run_wins_and_catalog_covers_the_rest(self):
        # published package: only in the catalog; new package: only as an archive
        for n in ("published", "fresh"):
            self.recipe(n)
        self.archive("published", {"usr/bin/shared": b"1"})
        _, cat = self.build()
        (self.d / "out" / "published-1-1.nawa.tar.zst").unlink()
        self.archive("fresh", {"usr/bin/shared": b"2"})
        r = self.check('[flavor.x]\ninclude = ["published", "fresh"]\n', catalog=cat)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("/usr/bin/shared is shipped by published, fresh", r.stdout)

    def test_neither_archives_nor_catalog_is_a_usage_error(self):
        r = subprocess.run([sys.executable, str(CHECKER)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
