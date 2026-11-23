#!/usr/bin/env python3
"""Regression tests for scripts/pr-shard-cache.py against a fake `gh` CLI."""
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("pr-shard-cache.py")
spec = importlib.util.spec_from_file_location("pr_shard_cache", SCRIPT)
sc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sc
spec.loader.exec_module(sc)

FAKE_GH = r'''#!/usr/bin/env python3
import fnmatch, hashlib, json, os, shutil, sys
from pathlib import Path
root = Path(os.environ["FAKE_GH_STATE"])
a = sys.argv[1:]
def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default
if a[0] == "api":
    ids = {}
    out = []
    for d in sorted(root.iterdir()) if root.exists() else []:
        assets = []
        for f in sorted(d.iterdir()):
            ids[len(ids) + 1000] = f
            assets.append({"id": len(ids) + 999, "name": f.name,
                           "digest": "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()})
        out.append({"tag_name": d.name, "draft": True, "assets": assets})
    for arg in a:
        if "/releases/assets/" in arg:
            # an asset is addressed by id only; the tag endpoint is unusable for drafts
            if os.environ.get("FAKE_GH_ASSET_FAIL"): sys.exit(1)
            sys.stdout.buffer.write(ids[int(arg.rsplit("/", 1)[1])].read_bytes()); sys.exit(0)
    print(json.dumps([out])); sys.exit(0)
cmd, tag = a[0] + " " + a[1], (a[2] if len(a) > 2 else "")
rel = root / tag
if cmd == "release view":
    if os.environ.get("FAKE_GH_NO_TAG_DOWNLOAD"): print("release not found", file=sys.stderr); sys.exit(1)
    sys.exit(0 if rel.is_dir() else 1)
if cmd == "release create":
    rel.mkdir(parents=True, exist_ok=True); sys.exit(0)
if cmd == "release upload":
    if not rel.is_dir(): sys.exit(1)
    for f in a[3:]:
        if not f.startswith("--") and Path(f).is_file():
            shutil.copy2(f, rel / Path(f).name)
    sys.exit(0)
if cmd == "release download":
    if os.environ.get("FAKE_GH_NO_TAG_DOWNLOAD"): print("release not found", file=sys.stderr); sys.exit(1)
    n = 0
    for f in sorted(rel.iterdir()) if rel.is_dir() else []:
        if fnmatch.fnmatch(f.name, opt("--pattern")):
            shutil.copy2(f, Path(opt("--dir")) / f.name); n += 1
    sys.exit(0 if n else 1)
if cmd == "release delete-asset":
    (rel / a[3]).unlink(missing_ok=True); sys.exit(0)
if cmd == "release delete":
    shutil.rmtree(rel, ignore_errors=True); sys.exit(0)
sys.exit(2)
'''


def add_recipe(root, category, name, build=(), version="1.0", rel=1):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    deps = ", ".join(f'"{x}"' for x in build)
    (d / "recipe.toml").write_text(
        f'[package]\nname = "{name}"\nversion = "{version}"\nrel = {rel}\n[depends]\nbuild = [{deps}]\n')


class ShardCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        gh = self.root / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.state = self.root / "state"
        os.environ["GH_BIN"] = str(gh)
        os.environ["FAKE_GH_STATE"] = str(self.state)
        self.recipes = self.root / "recipes"
        add_recipe(self.recipes, "base", "lib")
        add_recipe(self.recipes, "extra", "app", build=["lib"])
        self.out = self.root / "out"
        self.out.mkdir()
        self.marker = self.root / "start"
        self.marker.write_text("x")
        os.utime(self.marker, (time.time() - 20, time.time() - 20))
        self.prefix = "schema-v5-build-pr-7"
        self.common = ["--repo", "o/r", "--prefix", self.prefix]

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("GH_BIN", None)

    def run_cli(self, *argv):
        return sc.main(list(argv))

    def build(self, stem, shard, payload=b"data", status="BUILT=1\nINCOMPLETE=0\n"):
        (self.out / f"{stem}.nawa.tar.zst").write_bytes(payload)
        report = self.root / f"report-{shard}.txt"
        report.write_text(f"BUILT    {stem}  (1 min into the run, 5G disk free)\n")
        st = self.root / f"status-{shard}"
        st.write_text(status)
        return self.run_cli("save", *self.common, "--recipes", str(self.recipes), "--shard", shard,
                            "--out-dir", str(self.out), "--since", str(self.marker), "--report", str(report),
                            "--status", str(st), "--run-id", "11")

    def test_two_shards_save_independently_and_next_wave_restores_closure_only(self):
        self.assertEqual(self.build("lib-1.0-1", "w1s1"), 0)
        self.assertEqual(self.build("app-1.0-1", "w1s2"), 0)
        names = sorted(p.name for p in (self.state / f"{self.prefix}-manifest").iterdir())
        self.assertEqual(names, ["entries-w1s1.json", "entries-w1s2.json"])
        dest = self.root / "restore"
        self.assertEqual(self.run_cli("restore", *self.common, "--recipes", str(self.recipes),
                                      "--out-dir", str(dest), "--names", "lib"), 0)
        self.assertEqual([p.name for p in dest.iterdir()], ["lib-1.0-1.nawa.tar.zst"])

    def test_draft_lookup_by_tag_is_never_needed(self):
        # `gh release view/download TAG` answered "release not found" for drafts in CI:
        # listing and asset ids must be enough to restore and to merge
        self.build("lib-1.0-1", "w1s1")
        self.build("app-1.0-1", "w1s2")
        os.environ["FAKE_GH_NO_TAG_DOWNLOAD"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_GH_NO_TAG_DOWNLOAD", None)
        dest = self.root / "restore"
        self.assertEqual(self.run_cli("restore", *self.common, "--recipes", str(self.recipes),
                                      "--out-dir", str(dest), "--all"), 0)
        self.assertEqual(sorted(p.name for p in dest.iterdir()),
                         ["app-1.0-1.nawa.tar.zst", "lib-1.0-1.nawa.tar.zst"])
        self.assertEqual(self.run_cli("merge", *self.common, "--recipes", str(self.recipes),
                                      "--run-id", "11", "--head-sha", "a" * 40), 0)
        # no second draft with the manifest tag may appear
        self.assertEqual(sum(1 for p in self.state.iterdir() if p.name.endswith("-manifest")), 1)

    def test_changed_dependency_invalidates_dependent_entry(self):
        self.build("lib-1.0-1", "w1s1")
        self.build("app-1.0-1", "w1s2")
        (self.recipes / "base" / "lib" / "extra.patch").write_text("changed")
        dest = self.root / "restore"
        self.run_cli("restore", *self.common, "--recipes", str(self.recipes), "--out-dir", str(dest), "--all")
        self.assertEqual(list(dest.iterdir()), [])

    def test_corrupt_asset_is_rejected(self):
        self.build("lib-1.0-1", "w1s1")
        asset = next((self.state).glob("*-base-0001/lib-1.0-1.nawa.tar.zst"))
        asset.write_bytes(b"tampered")
        stems = self.root / "stems"
        sc_out = []
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.run_cli("valid-stems", *self.common, "--recipes", str(self.recipes))
        self.assertEqual(buf.getvalue().split(), [])

    def test_valid_stems_lists_cached_packages(self):
        self.build("lib-1.0-1", "w1s1")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.run_cli("valid-stems", *self.common, "--recipes", str(self.recipes))
        self.assertEqual(buf.getvalue().split(), ["lib-1.0-1"])

    def test_merge_writes_legacy_manifest_candidate_and_reports_status(self):
        self.build("lib-1.0-1", "w1s1")
        self.build("app-1.0-1", "w2s1", status="BUILT=1\nINCOMPLETE=1\n")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(self.run_cli("merge", *self.common, "--recipes", str(self.recipes),
                                          "--run-id", "11", "--head-sha", "a" * 40), 0)
        self.assertIn("INCOMPLETE=1", buf.getvalue())
        state = self.state / f"{self.prefix}-manifest"
        # records of this run stay so a re-run of the final job still sees every status
        self.assertEqual(sorted(p.name for p in state.iterdir()),
                         ["candidate.json", "entries-w1s1.json", "entries-w2s1.json", "manifest.json"])
        manifest = json.loads((state / "manifest.json").read_text())
        self.assertEqual([p["name"] for p in manifest["packages"]], ["app", "lib"])
        candidate = json.loads((state / "candidate.json").read_text())
        self.assertEqual(candidate["manifest_sha256"], hashlib.sha256((state / "manifest.json").read_bytes()).hexdigest())
        self.assertEqual(candidate["shards"], [f"{self.prefix}-base-0001", f"{self.prefix}-extra-0001"])
        # the legacy layout is consumed unchanged by the single-writer tooling
        spec2 = importlib.util.spec_from_file_location("rc", Path(__file__).with_name("pr-build-release-cache.py"))
        rc = importlib.util.module_from_spec(spec2)
        sys.modules[spec2.name] = rc
        spec2.loader.exec_module(rc)
        rc.verify_candidate(state / "candidate.json", state / "manifest.json", 7)
        # and a later restore still works from manifest.json alone
        dest = self.root / "again"
        self.run_cli("restore", *self.common, "--recipes", str(self.recipes), "--out-dir", str(dest), "--all")
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["app-1.0-1.nawa.tar.zst", "lib-1.0-1.nawa.tar.zst"])

    def test_merge_folds_records_of_older_runs_into_the_manifest(self):
        self.build("lib-1.0-1", "w1s1")  # run 11
        self.run_cli("merge", *self.common, "--recipes", str(self.recipes), "--run-id", "12", "--head-sha", "c" * 40)
        state = self.state / f"{self.prefix}-manifest"
        self.assertEqual(sorted(p.name for p in state.iterdir()), ["candidate.json", "manifest.json"])
        self.assertEqual([p["name"] for p in json.loads((state / "manifest.json").read_text())["packages"]], ["lib"])

    def test_merge_removes_superseded_archives(self):
        self.build("lib-1.0-1", "w1s1")
        add_recipe(self.recipes, "base", "lib", version="2.0")
        (self.out / "lib-1.0-1.nawa.tar.zst").unlink()
        self.build("lib-2.0-1", "w2s1")
        self.run_cli("merge", *self.common, "--recipes", str(self.recipes), "--run-id", "11", "--head-sha", "b" * 40)
        names = sorted(p.name for p in (self.state / f"{self.prefix}-base-0001").iterdir())
        self.assertEqual(names, ["lib-2.0-1.nawa.tar.zst"])

    def test_toolchain_entries_only_restored_on_request(self):
        (self.out / "lib-1.0-1.nawa.tar.zst").write_bytes(b"tc")
        report = self.root / "r"
        report.write_text("BUILT    lib-1.0-1  (Bootstrap Stage 3)\n")
        st = self.root / "s"
        st.write_text("")
        self.run_cli("save", *self.common, "--recipes", str(self.recipes), "--shard", "tc", "--out-dir", str(self.out),
                     "--since", str(self.marker), "--report", str(report), "--status", str(st),
                     "--toolchain-stems", "lib-1.0-1")
        plain = self.root / "plain"
        self.run_cli("restore", *self.common, "--recipes", str(self.recipes), "--out-dir", str(plain), "--names", "")
        self.assertEqual(list(plain.iterdir()), [])
        lst = self.root / "list"
        withtc = self.root / "withtc"
        self.run_cli("restore", *self.common, "--recipes", str(self.recipes), "--out-dir", str(withtc),
                     "--names", "", "--with-toolchain", "--toolchain-list", str(lst))
        self.assertEqual(lst.read_text().split(), ["lib-1.0-1.nawa.tar.zst"])

    def test_failed_shard_without_archives_still_records_status(self):
        report = self.root / "r"
        report.write_text("FAILED   app-1.0-1\nSKIPPED  x-1-1 (dependency app failed)\n")
        st = self.root / "s"
        st.write_text("FAILED=1\nINCOMPLETE=0\n")
        self.run_cli("save", *self.common, "--recipes", str(self.recipes), "--shard", "w3s1", "--out-dir",
                     str(self.out), "--since", str(self.marker), "--report", str(report), "--status", str(st))
        record = json.loads((self.state / f"{self.prefix}-manifest" / "entries-w3s1.json").read_text())
        self.assertEqual(record["failed"], ["app-1.0-1", "x-1-1"])
        self.assertEqual(record["entries"], [])

    def test_drop_deletes_every_release_of_the_prefix_only(self):
        self.build("lib-1.0-1", "w1s1")
        other = self.state / "schema-v5-build-pr-8-manifest"
        other.mkdir()
        self.run_cli("drop", *self.common)
        self.assertEqual([p.name for p in self.state.iterdir()], ["schema-v5-build-pr-8-manifest"])

    def test_unsafe_prefix_and_shard_are_refused(self):
        self.assertEqual(self.run_cli("drop", "--repo", "o/r", "--prefix", "../x"), 1)
        self.assertEqual(self.run_cli("save", "--repo", "o/r", "--prefix", self.prefix, "--recipes", str(self.recipes),
                                      "--shard", "../x", "--out-dir", str(self.out), "--since", str(self.marker),
                                      "--report", str(self.root / "r"), "--status", str(self.root / "s")), 1)


if __name__ == "__main__":
    unittest.main()
