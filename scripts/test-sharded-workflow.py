#!/usr/bin/env python3
"""Structure checks for the sharded package build (packages.yml + packages-build.yml)."""
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
caller = yaml.safe_load((ROOT / ".github/workflows/packages.yml").read_text(encoding="utf-8"))
called = yaml.safe_load((ROOT / ".github/workflows/packages-build.yml").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("planner", ROOT / "scripts/plan-build-shards.py")
planner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = planner
spec.loader.exec_module(planner)

# PyYAML reads the bare key `on` as True.
declared = called[True]["workflow_call"]["inputs"]
jobs = caller["jobs"]
waves = [f"build-w{n}" for n in range(planner.MAX_WAVES + 1)]
steps = called["jobs"]["build"]["steps"]


class ShardedWorkflowTests(unittest.TestCase):
    def test_one_job_per_wave_the_planner_can_emit(self):
        self.assertTrue(all(name in jobs for name in waves))
        self.assertNotIn(f"build-w{planner.MAX_WAVES + 1}", jobs)

    def test_wave_jobs_pass_only_declared_inputs_and_all_required_ones(self):
        required = {k for k, v in declared.items() if v.get("required")}
        for name in waves:
            passed = set(jobs[name]["with"])
            self.assertLessEqual(passed, set(declared), (name, passed - set(declared)))
            self.assertLessEqual(required, passed, name)

    def test_every_shard_compiles_the_pinned_nawa(self):
        # The rootfs nawa is the previous release's and cannot read schema-v5
        # recipes; there is no transition package to fall back on.
        text = yaml.dump(called)
        self.assertIn("Bootstrapping the selected Nawa source", text)
        self.assertNotIn("nawa-transition", text)
        self.assertNotIn("NAWA_SELECTED", text)

    def test_every_wave_is_a_non_failfast_matrix_over_its_own_output(self):
        for number, name in enumerate(waves):
            job = jobs[name]
            self.assertIs(job["strategy"]["fail-fast"], False)
            self.assertIn(f"needs.plan.outputs.wave{number}", job["strategy"]["matrix"])
            self.assertIn(f"wave{number}_count != '0'", job["if"])

    def test_waves_run_in_order_and_publish_waits_for_all(self):
        for index, name in enumerate(waves):
            self.assertEqual(jobs[name]["needs"], ["select", "plan", *waves[:index]])
        self.assertEqual(jobs["publish"]["needs"], ["select", "plan", *waves])

    def test_plan_exposes_every_matrix_the_emitter_writes(self):
        outputs = set(jobs["plan"]["outputs"])
        for number in range(planner.MAX_WAVES + 1):
            self.assertIn(f"wave{number}", outputs)
            self.assertIn(f"wave{number}_count", outputs)
        self.assertIn("toolchain_done", outputs)

    def test_matrix_fields_used_by_the_calls_exist_in_planned_shards(self):
        used = {"id", "pkgs", "needs", "waits"}
        sample = planner.plan({"a": {"name": "a", "category": "x", "stem": "a-1-1", "deps": set(), "relations": False}},
                              ["a"], [], set(), set(), {})["waves"][0][0]
        self.assertLessEqual(used, set(sample))

    def test_publishing_is_main_only_and_needs_every_job_to_succeed(self):
        condition = jobs["publish"]["if"]
        self.assertIn("github.event_name != 'pull_request'", condition)
        self.assertIn("github.ref == 'refs/heads/main'", condition)
        self.assertIn("!contains(needs.*.result, 'failure')", condition)
        self.assertIn("!contains(needs.*.result, 'cancelled')", condition)

    def test_signing_key_is_only_in_the_publish_job(self):
        self.assertNotIn("NAWA_SIGN_KEY_B64", yaml.dump(called))
        for name, job in jobs.items():
            self.assertEqual("NAWA_SIGN_KEY_B64" in yaml.dump(job), name == "publish", name)

    def test_shard_jobs_cannot_write_releases(self):
        self.assertEqual(called["jobs"]["build"]["permissions"]["contents"], "read")
        for name in waves:
            self.assertEqual(jobs[name]["permissions"]["contents"], "read", name)

    def test_every_shard_uploads_its_own_archive_artifact(self):
        uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")
                   and s["with"]["name"].startswith("built-")]
        self.assertEqual(len(uploads), 1)
        self.assertIn("inputs.shard_id", uploads[0]["with"]["name"])
        self.assertIn("always()", uploads[0]["if"])  # finished work is kept when a package failed

    def test_shard_log_artifacts_do_not_collide(self):
        logs = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")
                and s["with"]["name"].startswith("package-build-logs")]
        self.assertEqual(len(logs), 1)
        self.assertIn("inputs.shard_id", logs[0]["with"]["name"])

    def test_publish_gathers_artifacts_and_published_archives_into_one_set(self):
        text = yaml.dump(jobs["publish"])
        self.assertIn("pattern: built-*", text)
        self.assertIn("merge-multiple: true", text)
        self.assertIn("publish-schema-v5.py prepare", text)
        # the index is published after the immutable archives
        names = [s.get("name", "") for s in jobs["publish"]["steps"]]
        self.assertLess(names.index("Publish immutable package and recipe shards"),
                        names.index("Publish the signed stable-v5 index"))

    def test_build_step_stays_inside_the_job_limit(self):
        build = called["jobs"]["build"]
        step = next(s for s in build["steps"] if s.get("id") == "build")
        self.assertLess(step["timeout-minutes"], build["timeout-minutes"])


if __name__ == "__main__":
    unittest.main()
