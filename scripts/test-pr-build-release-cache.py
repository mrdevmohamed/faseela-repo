#!/usr/bin/env python3
"""Offline acceptance tests for the PR draft-release package cache."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("pr-build-release-cache.py")
SPEC = importlib.util.spec_from_file_location("pr_build_release_cache", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load PR build-release cache module")
release_cache = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_cache
SPEC.loader.exec_module(release_cache)

CACHE = release_cache.CACHE


class PullRequestReleaseCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.recipes = self.root / "recipes"
        self.cache_dir = self.root / "cache"
        self.out_dir = self.root / "out"
        self.marker = self.root / "run-start"
        self.report = self.root / "report.txt"
        self.recipe_dir = self.recipes / "base" / "demo"
        self.recipe_dir.mkdir(parents=True)
        (self.recipe_dir / "recipe.toml").write_text(
            '[package]\nname = "demo"\nversion = "1.0"\nrel = 2\n'
            '[depends]\nbuild = []\n',
            encoding="utf-8",
        )
        self.marker.write_text("start\n", encoding="utf-8")
        os.utime(self.marker, (time.time() - 20, time.time() - 20))
        self.out_dir.mkdir()
        archive = self.out_dir / "demo-1.0-2.nawa.tar.zst"
        archive.write_bytes(b"demo package archive")
        os.utime(archive, (time.time(), time.time()))
        self.report.write_text(
            "BUILT    demo-1.0-2  (successful PR build)\n",
            encoding="utf-8",
        )
        CACHE.save_cache(
            self.recipes, self.cache_dir, self.out_dir, self.marker, self.report,
        )
        self.releases_path = self.root / "releases.json"
        self.releases_path.write_text("[]\n", encoding="utf-8")
        self.plan_path = self.root / "plan.json"
        self.head_sha = "a" * 40

    def tearDown(self):
        self.temp.cleanup()

    def make_plan(self, *, max_assets=900):
        return release_cache.build_plan(
            self.recipes,
            self.cache_dir,
            self.releases_path,
            "owner/repo",
            215,
            12345,
            self.head_sha,
            self.plan_path,
            max_assets,
        )

    def test_plan_creates_draft_shard_and_candidate_manifest(self):
        plan = self.make_plan()
        self.assertEqual(plan["package_count"], 1)
        self.assertEqual(plan["archive_count"], 1)
        self.assertIn("schema-v5-build-pr-215-base-0001", plan["create_releases"])
        self.assertIn("schema-v5-build-pr-215-manifest", plan["create_releases"])
        self.assertEqual(
            plan["uploads"]["schema-v5-build-pr-215-base-0001"],
            [str(self.cache_dir / "demo-1.0-2.nawa.tar.zst")],
        )
        candidate_path = self.cache_dir / "candidate.json"
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        manifest = self.cache_dir / CACHE.MANIFEST_NAME
        self.assertEqual(candidate["pr_number"], 215)
        self.assertEqual(candidate["build_run_id"], 12345)
        self.assertEqual(candidate["head_sha"], self.head_sha)
        self.assertEqual(candidate["manifest_sha256"], release_cache.sha256_file(manifest))
        checked = release_cache.verify_candidate(
            candidate_path, manifest, 215, 12345, self.head_sha,
        )
        self.assertEqual(checked["shards"], ["schema-v5-build-pr-215-base-0001"])

    def test_existing_matching_assets_are_reused(self):
        shard_tag = "schema-v5-build-pr-215-base-0001"
        archive_digest = release_cache.sha256_file(self.cache_dir / "demo-1.0-2.nawa.tar.zst")
        releases = [
            {
                "tag_name": shard_tag,
                "draft": True,
                "assets": [
                    {"name": "demo-1.0-2.nawa.tar.zst", "digest": "sha256:" + archive_digest}
                ],
            },
            {
                "tag_name": "schema-v5-build-pr-215-manifest",
                "draft": True,
                "assets": [],
            },
        ]
        self.releases_path.write_text(json.dumps(releases), encoding="utf-8")
        plan = self.make_plan()
        self.assertNotIn(shard_tag, plan["create_releases"])
        self.assertNotIn(
            str(self.cache_dir / "demo-1.0-2.nawa.tar.zst"),
            plan["uploads"].get(shard_tag, []),
        )

    def test_non_draft_cache_release_is_rejected(self):
        self.releases_path.write_text(
            json.dumps([{
                "tag_name": "schema-v5-build-pr-215-base-0001",
                "draft": False,
                "assets": [],
            }]),
            encoding="utf-8",
        )
        with self.assertRaises(release_cache.CacheReleaseError):
            self.make_plan()

    def test_candidate_manifest_tampering_is_rejected(self):
        self.make_plan()
        manifest = self.cache_dir / CACHE.MANIFEST_NAME
        with manifest.open("a", encoding="utf-8") as stream:
            stream.write(" ")
        with self.assertRaisesRegex(release_cache.CacheReleaseError, "manifest digest"):
            release_cache.verify_candidate(
                self.cache_dir / "candidate.json", manifest, 215, 12345, self.head_sha,
            )

    def test_selected_run_and_head_must_match_candidate(self):
        self.make_plan()
        with self.assertRaisesRegex(release_cache.CacheReleaseError, "selected successful build run"):
            release_cache.verify_candidate(
                self.cache_dir / "candidate.json",
                self.cache_dir / CACHE.MANIFEST_NAME,
                215,
                99999,
                self.head_sha,
            )
        with self.assertRaisesRegex(release_cache.CacheReleaseError, "PR head SHA"):
            release_cache.verify_candidate(
                self.cache_dir / "candidate.json",
                self.cache_dir / CACHE.MANIFEST_NAME,
                215,
                12345,
                "b" * 40,
            )

    def test_assets_are_split_across_release_shards_at_limit(self):
        for name, payload in (
            ("demo-doc-1.0-2.nawa.tar.zst", b"documentation"),
            ("demo-lang-1.0-2.nawa.tar.zst", b"language"),
        ):
            path = self.out_dir / name
            path.write_bytes(payload)
            os.utime(path, (time.time(), time.time()))
        CACHE.save_cache(
            self.recipes, self.cache_dir, self.out_dir, self.marker, self.report,
        )
        plan = self.make_plan(max_assets=1)
        self.assertEqual(plan["archive_count"], 3)
        shard_tags = [tag for tag in plan["shards"]]
        self.assertEqual(len(shard_tags), 3)
        self.assertTrue(all(tag.startswith("schema-v5-build-pr-215-base-") for tag in shard_tags))


if __name__ == "__main__":
    unittest.main(verbosity=2)
