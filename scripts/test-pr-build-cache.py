#!/usr/bin/env python3
"""Regression tests for scripts/pr-build-cache.py."""
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("pr-build-cache.py")
spec = importlib.util.spec_from_file_location("pr_build_cache", SCRIPT)
cache = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cache
spec.loader.exec_module(cache)


def add_recipe(root: Path, category: str, name: str, build=(), version="1.0", rel=1):
    directory = root / category / name
    directory.mkdir(parents=True, exist_ok=True)
    deps = ", ".join(f'"{item}"' for item in build)
    (directory / "recipe.toml").write_text(
        f'[package]\nname = "{name}"\nversion = "{version}"\nrel = {rel}\n\n'
        f'[depends]\nbuild = [{deps}]\n',
        encoding="utf-8",
    )
    return directory


class PullRequestPackageCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.recipes = self.root / "recipes"
        self.cache_dir = self.root / "cache"
        self.out_dir = self.root / "out"
        self.marker = self.root / "run-start"
        self.report = self.root / "report.txt"
        add_recipe(self.recipes, "base", "libfoo")
        app = add_recipe(self.recipes, "extra", "demo-app", build=("libfoo",))
        (app / "assets").mkdir()
        (app / "assets" / "patch.diff").write_text("original patch\n", encoding="utf-8")
        self.marker.write_text("start\n", encoding="utf-8")
        os.utime(self.marker, (time.time() - 10, time.time() - 10))

    def tearDown(self):
        self.temp.cleanup()

    def write_archive(self, name="demo-app-1.0-1.nawa.tar.zst", payload=b"archive"):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / name
        path.write_bytes(payload)
        os.utime(path, (time.time(), time.time()))
        self.report.write_text(f"BUILT    {name.removesuffix('.nawa.tar.zst')}  (0 min into the run)\\n", encoding="utf-8")
        return path

    def test_save_and_restore_successful_build(self):
        self.write_archive()
        added, total = cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        self.assertEqual((added, total), (1, 1))
        (self.out_dir / "demo-app-1.0-1.nawa.tar.zst").unlink()
        restored, rejected = cache.restore_cache(self.recipes, self.cache_dir, self.out_dir)
        self.assertEqual((restored, rejected), (1, 0))
        self.assertEqual(
            (self.out_dir / "demo-app-1.0-1.nawa.tar.zst").read_bytes(),
            b"archive",
        )

    def test_recipe_asset_change_invalidates_cached_archive(self):
        self.write_archive()
        cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        (self.out_dir / "demo-app-1.0-1.nawa.tar.zst").unlink()

        asset = self.recipes / "extra" / "demo-app" / "assets" / "patch.diff"
        asset.write_text("changed patch\n", encoding="utf-8")
        restored, rejected = cache.restore_cache(self.recipes, self.cache_dir, self.out_dir)
        self.assertEqual((restored, rejected), (0, 1))
        self.assertFalse((self.out_dir / "demo-app-1.0-1.nawa.tar.zst").exists())

    def test_build_dependency_change_invalidates_dependent_archive(self):
        self.write_archive()
        cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        (self.out_dir / "demo-app-1.0-1.nawa.tar.zst").unlink()

        dependency_asset = self.recipes / "base" / "libfoo" / "new-source.patch"
        dependency_asset.write_text("changed build dependency\n", encoding="utf-8")
        restored, rejected = cache.restore_cache(self.recipes, self.cache_dir, self.out_dir)
        self.assertEqual((restored, rejected), (0, 1))

    def test_does_not_overwrite_archive_already_fetched_from_repository(self):
        self.write_archive()
        cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        existing = self.out_dir / "demo-app-1.0-1.nawa.tar.zst"
        existing.write_bytes(b"published archive")
        restored, rejected = cache.restore_cache(self.recipes, self.cache_dir, self.out_dir)
        self.assertEqual((restored, rejected), (0, 0))
        self.assertEqual(existing.read_bytes(), b"published archive")

    def test_does_not_cache_archive_when_install_failed(self):
        self.write_archive()
        self.report.write_text("FAILED   demo-app-1.0-1\\n", encoding="utf-8")
        added, total = cache.save_cache(
            self.recipes, self.cache_dir, self.out_dir, self.marker, self.report,
        )
        self.assertEqual((added, total), (0, 0))
        self.assertFalse((self.cache_dir / "demo-app-1.0-1.nawa.tar.zst").exists())

    def test_save_ignores_archives_older_than_build_start(self):
        self.write_archive()
        os.utime(self.marker, (time.time() + 10, time.time() + 10))
        added, total = cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        self.assertEqual((added, total), (0, 0))
        self.assertFalse((self.cache_dir / "demo-app-1.0-1.nawa.tar.zst").exists())

    def test_tampered_cached_archive_is_rejected_by_digest(self):
        self.write_archive()
        cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        cached = self.cache_dir / "demo-app-1.0-1.nawa.tar.zst"
        (self.out_dir / cached.name).unlink()
        cached.write_bytes(b"tampered archive")
        restored, rejected = cache.restore_cache(self.recipes, self.cache_dir, self.out_dir)
        self.assertEqual((restored, rejected), (0, 1))
        self.assertFalse((self.out_dir / cached.name).exists())

    def test_manifest_records_archive_sha256(self):
        self.write_archive()
        cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        import json
        manifest = json.loads((self.cache_dir / cache.MANIFEST_NAME).read_text(encoding="utf-8"))
        entry = manifest["packages"][0]
        self.assertEqual(manifest["schema"], 3)
        self.assertEqual(entry["archive_sha256"], cache.sha256_file(self.cache_dir / entry["archive"]))

    def test_successful_toolchain_stage3_output_is_cacheable(self):
        toolchain_root = self.recipes / "toolchain" / "gcc"
        toolchain_root.mkdir(parents=True)
        (toolchain_root / "recipe.toml").write_text(
            '[package]\nname = "gcc"\nversion = "14.2"\nrel = 3\n'
            '[depends]\nbuild = []\n',
            encoding="utf-8",
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)
        archive = self.out_dir / "gcc-14.2-3.nawa.tar.zst"
        archive.write_bytes(b"stage3 toolchain archive")
        os.utime(archive, (time.time(), time.time()))
        self.report.write_text(
            "BUILT    gcc-14.2-3  (Bootstrap Stage 3)\n",
            encoding="utf-8",
        )
        added, total = cache.save_cache(
            self.recipes, self.cache_dir, self.out_dir, self.marker, self.report,
        )
        self.assertEqual((added, total), (1, 1))
        restored, rejected = cache.restore_cache(
            self.recipes, self.cache_dir, self.root / "toolchain-restored",
        )
        self.assertEqual((restored, rejected), (1, 0))
        self.assertEqual(
            (self.root / "toolchain-restored" / archive.name).read_bytes(),
            b"stage3 toolchain archive",
        )

    def test_split_archives_are_cached_and_restored(self):
        self.write_archive()
        doc = self.out_dir / "demo-app-doc-1.0-1.nawa.tar.zst"
        lang = self.out_dir / "demo-app-lang-1.0-1.nawa.tar.zst"
        doc.write_bytes(b"documentation")
        lang.write_bytes(b"language")
        os.utime(doc, (time.time(), time.time()))
        os.utime(lang, (time.time(), time.time()))
        cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        doc.unlink()
        lang.unlink()
        (self.out_dir / "demo-app-1.0-1.nawa.tar.zst").unlink()
        restored, rejected = cache.restore_cache(self.recipes, self.cache_dir, self.out_dir)
        self.assertEqual((restored, rejected), (1, 0))
        self.assertEqual(doc.read_bytes(), b"documentation")
        self.assertEqual(lang.read_bytes(), b"language")

    def test_relation_archive_invalidation_removes_base_and_split_files(self):
        app_recipe = self.recipes / "extra" / "demo-app" / "recipe.toml"
        app_recipe.write_text(
            app_recipe.read_text(encoding="utf-8")
            + "\n[relations]\nschema = 1\nconflicts = []\nreplaces = []\n",
            encoding="utf-8",
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)
        names = (
            "demo-app-1.0-1.nawa.tar.zst",
            "demo-app-doc-1.0-1.nawa.tar.zst",
            "demo-app-lang-1.0-1.nawa.tar.zst",
        )
        for name in names:
            (self.out_dir / name).write_bytes(b"legacy v3 archive")
        removed = cache.invalidate_relation_archives(self.recipes, self.out_dir, ["demo-app"])
        self.assertEqual(removed, 3)
        self.assertFalse(any((self.out_dir / name).exists() for name in names))

    def test_recipe_release_change_invalidates_cached_archive(self):
        self.write_archive()
        cache.save_cache(self.recipes, self.cache_dir, self.out_dir, self.marker, self.report)
        (self.out_dir / "demo-app-1.0-1.nawa.tar.zst").unlink()

        app_recipe = self.recipes / "extra" / "demo-app" / "recipe.toml"
        app_recipe.write_text(app_recipe.read_text(encoding="utf-8").replace("rel = 1", "rel = 2"), encoding="utf-8")
        restored, rejected = cache.restore_cache(self.recipes, self.cache_dir, self.out_dir)
        self.assertEqual((restored, rejected), (0, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
