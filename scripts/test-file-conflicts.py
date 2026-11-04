#!/usr/bin/env python3
"""scripts/test-file-conflicts.py — check-file-conflicts.py on synthetic archives.

Archives are real tar files; when the machine has no `zstd` a pass-through
shim stands in for it (the checker only ever runs `zstd -dc FILE`)."""
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

SCRIPT = Path(__file__).resolve().parent / "check-file-conflicts.py"


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
    if shutil.which("zstd"):
        # zstd refuses input == output: compress next to it, then move over it
        tmp = path.with_name(path.name + ".tmp")
        subprocess.run(["zstd", "-q", "-f", str(path), "-o", str(tmp)], check=True)
        os.replace(tmp, path)


class Conflicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        (d / "out").mkdir()
        self.env = dict(os.environ)
        if not shutil.which("zstd"):
            (d / "bin").mkdir()
            shim = d / "bin" / "zstd"
            shim.write_text('#!/bin/sh\nfor last; do :; done\nexec cat "$last"\n')
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            self.env["PATH"] = f"{d / 'bin'}:{self.env['PATH']}"

    def tearDown(self):
        self.tmp.cleanup()

    def recipe(self, name, run=()):
        p = self.d / "recipes" / "base" / name
        p.mkdir(parents=True, exist_ok=True)
        (p / "recipe.toml").write_text(
            f'[package]\nname = "{name}"\nversion = "1"\nrel = 1\n'
            f'[depends]\nbuild = []\nrun = [{", ".join(chr(34) + x + chr(34) for x in run)}]\n')

    def archive(self, name, entries):
        # the layout nawa writes: metadata at the top, the files under payload/
        make_archive(self.d / "out" / f"{name}-1-1.nawa.tar.zst",
                     {".PKGINFO": b"name\n", "payload/": None,
                      **{f"payload/{k}": v for k, v in entries.items()}})

    def run_check(self, flavors_toml, *extra):
        (self.d / "f.toml").write_text(textwrap.dedent(flavors_toml))
        r = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.d / "out"), "--flavors", str(self.d / "f.toml"),
             "--recipes", str(self.d / "recipes"), *extra],
            capture_output=True, text=True, env=self.env)
        return r

    @unittest.skipUnless(shutil.which("zstd"), "zstd is required for this streaming regression")
    def test_zstd_stream_is_drained_after_tar_end_markers(self):
        self.recipe("streamed")
        raw = self.d / "streamed.tar"
        with tarfile.open(raw, "w") as tf:
            info = tarfile.TarInfo(".PKGINFO")
            info.size = 5
            tf.addfile(info, io.BytesIO(b"name\n"))
            info = tarfile.TarInfo("payload/usr/bin/streamed")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))

        # A tar reader stops at its end markers.  Keep enough valid trailing
        # tar padding in the zstd frame to fill a pipe if the caller does not
        # drain it; zstd would otherwise exit with SIGPIPE.
        with raw.open("ab") as stream:
            stream.write(b"\\0" * (16 * 1024 * 1024))
        archive = self.d / "out" / "streamed-1-1.nawa.tar.zst"
        subprocess.run(["zstd", "-q", "-f", str(raw), "-o", str(archive)], check=True)
        raw.unlink()

        result = self.run_check('[flavor.x]\\ninclude = ["streamed"]\\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_file_in_one_flavor_is_an_error(self):
        for n in ("util-linux", "sysklogd"):
            self.recipe(n)
        self.archive("util-linux", {"usr/": None, "usr/bin/": None, "usr/bin/logger": b"a"})
        self.archive("sysklogd", {"usr/bin/logger": b"b", "usr/sbin/syslogd": b"c"})
        r = self.run_check('[flavor.x]\ninclude = ["util-linux", "sysklogd"]\n')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CONFLICT x: /usr/bin/logger is shipped by util-linux, sysklogd", r.stdout)

    def test_shared_directories_and_disjoint_files_are_fine(self):
        for n in ("a", "b"):
            self.recipe(n)
        self.archive("a", {"usr/": None, "usr/bin/": None, "usr/bin/a": b"1"})
        self.archive("b", {"usr/": None, "usr/bin/": None, "usr/bin/b": b"2"})
        r = self.run_check('[flavor.x]\ninclude = ["a", "b"]\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_conflict_only_counts_inside_one_flavor(self):
        for n in ("fw", "fw-lite"):
            self.recipe(n)
        self.archive("fw", {"usr/lib/firmware/x.bin": b"1"})
        self.archive("fw-lite", {"usr/lib/firmware/x.bin": b"1"})
        toml = '[flavor.big]\ninclude = ["fw"]\n[flavor.small]\ninclude = ["fw-lite"]\n'
        self.assertEqual(self.run_check(toml).returncode, 0)
        r = self.run_check(toml, "--all")
        self.assertEqual(r.returncode, 0)
        self.assertIn("no flavor installs them together", r.stderr)

    def test_merged_usr_paths_collide(self):
        for n in ("old", "new"):
            self.recipe(n)
        self.archive("old", {"bin/tool": b"1"})
        self.archive("new", {"usr/bin/tool": b"2"})
        r = self.run_check('[flavor.x]\ninclude = ["old", "new"]\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn("/usr/bin/tool", r.stdout)

    def test_symlink_before_directory_is_fine_after_it_is_an_error(self):
        # base-files' /sbin symlink must be installed before glibc's /sbin
        # directory; the other way round nawa fails ("/sbin (owned by glibc)")
        for n in ("links", "libc"):
            self.recipe(n)
        self.archive("links", {"sbin": ("->", "usr/bin")})
        self.archive("libc", {"usr/": None, "usr/bin/": None, "usr/bin/ldd": b"1", "sbin/": None})
        good = self.run_check('[flavor.x]\ninclude = ["links", "libc"]\n')
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertEqual(good.stderr, "")
        bad = self.run_check('[flavor.x]\ninclude = ["libc", "links"]\n')
        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertIn("/sbin is a file/symlink of links but a directory of libc", bad.stdout)

    def test_files_outside_payload_are_metadata(self):
        for n in ("a", "b"):
            self.recipe(n)
        self.archive("a", {"usr/bin/a": b"1"})
        self.archive("b", {"usr/bin/b": b"2"})
        # .PKGINFO exists in both archives; it must never count as a shared file
        r = self.run_check('[flavor.x]\ninclude = ["a", "b"]\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_archive_is_a_warning_and_an_error_when_strict(self):
        self.recipe("ghost")
        toml = '[flavor.x]\ninclude = ["ghost"]\n'
        r = self.run_check(toml)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no archive ghost-1-1.nawa.tar.zst", r.stderr)
        self.assertEqual(self.run_check(toml, "--strict").returncode, 1)


if __name__ == "__main__":
    unittest.main()
