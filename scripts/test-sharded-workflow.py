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


class ShardedWorkflowTests(unittest.TestCase):
    def test_one_job_per_wave_the_planner_can_emit(self):
        self.assertTrue(all(name in jobs for name in waves))
        self.assertNotIn(f"build-w{planner.MAX_WAVES + 1}", jobs)

    def test_wave_jobs_pass_only_declared_inputs_and_all_required_ones(self):
        required = {k for k, v in declared.items() if v.get("required")}
        for name in [*waves, "publish"]:
            passed = set(jobs[name]["with"])
            self.assertLessEqual(passed, set(declared), (name, passed - set(declared)))
            self.assertLessEqual(required, passed, name)

    def test_every_wave_is_a_non_failfast_matrix_over_its_own_output(self):
        for number, name in enumerate(waves):
            job = jobs[name]
            self.assertIs(job["strategy"]["fail-fast"], False)
            self.assertIn(f"needs.plan.outputs.wave{number}", job["strategy"]["matrix"])
            self.assertIn(f"wave{number}_count != '0'", job["if"])
            self.assertEqual(job["with"]["mode"], "shard")

    def test_waves_run_in_order_and_publish_waits_for_all(self):
        for index, name in enumerate(waves):
            self.assertEqual(jobs[name]["needs"], ["select", "plan", *waves[:index]])
        self.assertEqual(jobs["publish"]["needs"], ["select", "plan", *waves])
        self.assertEqual(jobs["publish"]["with"]["mode"], "finalize")

    def test_plan_exposes_every_matrix_the_emitter_writes(self):
        outputs = set(jobs["plan"]["outputs"])
        for number in range(planner.MAX_WAVES + 1):
            self.assertIn(f"wave{number}", outputs)
            self.assertIn(f"wave{number}_count", outputs)
        self.assertIn("cache_prefix", outputs)

    def test_matrix_fields_used_by_the_calls_exist_in_planned_shards(self):
        shard = {"id", "pkgs", "needs", "waits"}
        used = {"id", "pkgs", "needs", "waits"}
        sample = planner.plan({"a": {"name": "a", "category": "x", "stem": "a-1-1", "deps": set(), "relations": False}},
                              ["a"], [], set(), set(), {})["waves"][0][0]
        self.assertLessEqual(used, set(sample))
        self.assertLessEqual(shard, set(sample))

    def test_signing_key_and_publication_belong_to_the_final_job(self):
        for step in called["jobs"]["build"]["steps"]:
            text = yaml.dump(step)
            if "NAWA_SIGN_KEY_B64" in text or step.get("id") == "publish":
                self.assertIn("inputs.mode == 'finalize'", step.get("if", ""), step.get("name"))

    def test_shard_only_steps_never_run_in_the_final_job_and_vice_versa(self):
        for step in called["jobs"]["build"]["steps"]:
            name = step.get("name", "")
            if name.startswith(("Build this shard", "Save this shard", "Collect build logs")):
                self.assertIn("inputs.mode == 'shard'", step["if"], name)
            if name.startswith(("Merge the shard records", "No two packages", "Publish to the")):
                self.assertIn("inputs.mode == 'finalize'", step["if"], name)

    def test_shard_log_artifacts_do_not_collide(self):
        uploads = [s for s in called["jobs"]["build"]["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertEqual(len(uploads), 1)
        self.assertIn("inputs.shard_id", uploads[0]["with"]["name"])

    def test_build_step_stays_inside_the_job_limit(self):
        build = called["jobs"]["build"]
        step = next(s for s in build["steps"] if s.get("id") == "build")
        self.assertLess(step["timeout-minutes"], build["timeout-minutes"])


if __name__ == "__main__":
    unittest.main()
