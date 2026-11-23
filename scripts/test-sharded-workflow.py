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
uploader = yaml.safe_load((ROOT / ".github/workflows/packages-upload.yml").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("planner", ROOT / "scripts/plan-build-shards.py")
planner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = planner
spec.loader.exec_module(planner)

# PyYAML reads the bare key `on` as True.
declared = called[True]["workflow_call"]["inputs"]
jobs = caller["jobs"]
waves = [f"build-w{n}" for n in range(planner.MAX_WAVES + 1)]
upload_jobs = [f"upload-w{n}" for n in range(planner.MAX_WAVES + 1)]
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
        self.assertEqual(jobs["publish"]["needs"],
                         ["select", "plan", "signer", *waves, *upload_jobs])

    def test_every_wave_uploads_what_it_built_even_when_a_shard_failed(self):
        for number, name in enumerate(upload_jobs):
            job = jobs[name]
            self.assertEqual(job["uses"], "./.github/workflows/packages-upload.yml")
            # follows its build wave, and the previous upload so shard allocation never races
            self.assertIn(f"build-w{number}", job["needs"])
            if number:
                self.assertIn(f"upload-w{number - 1}", job["needs"])
            self.assertIn("!cancelled()", job["if"])
            self.assertNotIn("failure", job["if"])  # a failed shard must not stop the upload
            self.assertIn(f"wave{number}_count != '0'", job["if"])
            self.assertEqual(job["permissions"]["contents"], "write")
        patterns = [jobs[n]["with"]["artifact_pattern"] for n in upload_jobs]
        self.assertEqual(patterns[0], "built-tc")
        self.assertEqual(patterns[1:], [f"built-w{n}s*" for n in range(1, planner.MAX_WAVES + 1)])

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

    def test_signing_key_is_never_in_the_jobs_that_run_recipe_builds(self):
        self.assertNotIn("NAWA_SIGN_KEY_B64", yaml.dump(called))
        allowed = {"signer", "publish", *upload_jobs}
        for name, job in jobs.items():
            if name in upload_jobs:  # the key reaches them through the reusable upload workflow
                continue
            self.assertEqual("NAWA_SIGN_KEY_B64" in yaml.dump(job), name in {"signer", "publish"}, name)
        self.assertIn("NAWA_SIGN_KEY_B64", yaml.dump(uploader))
        self.assertEqual(set(upload_jobs) | {"signer", "publish"}, allowed)

    def test_upload_workflow_signs_before_uploading_and_describes_what_it_uploaded(self):
        text = (ROOT / ".github/workflows/packages-upload.yml").read_text(encoding="utf-8")
        self.assertIn("publish-schema-v5.py stage-wave", text)
        self.assertIn("publish-schema-v5.py derive", text)
        self.assertIn("--clobber", text)
        steps_ = uploader["jobs"]["upload"]["steps"]
        meta = [s_ for s_ in steps_ if str(s_.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertEqual(len(meta), 1)
        self.assertEqual(meta[0]["with"]["name"], "meta-${{ inputs.label }}")
        self.assertIs(meta[0]["with"]["overwrite"], True)  # a re-run replaces it
        self.assertEqual(uploader["jobs"]["upload"]["permissions"], {"contents": "write"})

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

    def test_publish_updates_the_previous_index_without_the_archives(self):
        text = yaml.dump(jobs["publish"], width=10**9)
        self.assertIn("pattern: meta-*", text)
        self.assertIn("publish-schema-v5.py update", text)
        self.assertIn("publish-schema-v5.py catalog", text)
        self.assertIn("--base-index", text)
        self.assertNotIn("pattern: built-*", text)  # the archives themselves are not downloaded
        self.assertNotIn("publish-schema-v5.py prepare", text)
        self.assertEqual(jobs["publish"]["concurrency"]["group"], "publish-stable-v5")
        self.assertIs(jobs["publish"]["concurrency"]["cancel-in-progress"], False)

    def test_the_index_is_published_last(self):
        names = [s_.get("name", "") for s_ in jobs["publish"]["steps"]]
        conflicts = names.index("No two packages of a flavor may ship the same file")
        snapshot = names.index("Publish the recipe snapshot")
        index = names.index("Publish the catalog and the signed stable-v5 index")
        self.assertLess(conflicts, snapshot)
        self.assertLess(snapshot, index)
        self.assertEqual(index, len(names) - 1)

    def test_build_step_stays_inside_the_job_limit(self):
        build = called["jobs"]["build"]
        step = next(s for s in build["steps"] if s.get("id") == "build")
        self.assertLess(step["timeout-minutes"], build["timeout-minutes"])


if __name__ == "__main__":
    unittest.main()
