#!/usr/bin/env python3
"""Regression tests for scripts/toolchain-cache-key.py and its workflow wiring."""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "toolchain-cache-key.py"
spec = importlib.util.spec_from_file_location("toolchain_cache_key", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def add(root: Path, category: str, name: str, build=(), rel=1) -> Path:
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    deps = ", ".join(f'"{b}"' for b in build)
    (d / "recipe.toml").write_text(
        f'[package]\nname = "{name}"\nversion = "1.0"\nrel = {rel}\n\n[depends]\nbuild = [{deps}]\n',
        encoding="utf-8",
    )
    return d


class ToolchainCacheKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        add(self.tmp, "toolchain", "gcc", build=["gmp"])
        add(self.tmp, "toolchain", "gmp")
        add(self.tmp, "base", "bash")
        add(self.tmp, "gui", "firefox", build=["bash"])  # not in the bootstrap set
        self.flavors = self.tmp / "flavors.toml"
        self.flavors.write_text("[flavor.bootstrap]\n", encoding="utf-8")

    def key(self, bootstrap=("bash", "gcc"), pkgs=("gcc",), rev="r1", iso="sandbox", week="W1"):
        return mod.toolchain_key(self.tmp, list(bootstrap), list(pkgs), self.flavors, rev, iso, week)

    def test_stable_and_order_independent(self):
        self.assertEqual(self.key(pkgs=("gcc", "gmp")), self.key(pkgs=("gmp", "gcc")))
        self.assertEqual(self.key(), self.key())

    def test_each_input_changes_the_key(self):
        base = self.key()
        self.assertNotEqual(base, self.key(rev="r2"))
        self.assertNotEqual(base, self.key(iso="none"))
        self.assertNotEqual(base, self.key(week="W2"))
        self.assertNotEqual(base, self.key(pkgs=("gcc", "gmp")))
        self.flavors.write_text("[flavor.bootstrap]\nx = 1\n", encoding="utf-8")
        self.assertNotEqual(base, self.key())

    def test_build_dependency_and_toolchain_recipe_changes_invalidate(self):
        base = self.key()
        add(self.tmp, "toolchain", "gmp", rel=2)  # build dependency of gcc
        self.assertNotEqual(base, self.key())

    def test_unrelated_recipe_does_not_invalidate(self):
        base = self.key()
        add(self.tmp, "gui", "firefox", build=["bash"], rel=9)
        self.assertEqual(base, self.key())

    def test_bootstrap_recipe_change_invalidates(self):
        base = self.key()
        add(self.tmp, "base", "bash", rel=2)
        self.assertNotEqual(base, self.key())

    def test_missing_recipe_is_an_error(self):
        with self.assertRaises(SystemExit):
            self.key(bootstrap=("bash", "nope"))


class WorkflowWiringTests(unittest.TestCase):
    wf = (ROOT / ".github/workflows/packages.yml").read_text(encoding="utf-8")

    def test_cache_steps_exist_in_order(self):
        order = [
            "name: Compute the Bootstrap Toolchain cache key",
            "uses: actions/cache/restore@v4",
            "name: Build ordinary packages and Bootstrap Toolchain targets",
            "uses: actions/cache/save@v4",
        ]
        positions = [self.wf.index(item) for item in order]
        self.assertEqual(positions, sorted(positions))

    def test_full_toolchain_runs_never_use_the_cache(self):
        self.assertIn("env.TOOLCHAIN_ALL != 'true'", self.wf)

    def test_cache_is_verified_and_saved_only_when_complete(self):
        self.assertIn('sha256sum --check --quiet ../SHA256SUMS', self.wf)
        self.assertLess(self.wf.index('> ../SHA256SUMS'), self.wf.index('> "$tc_dir/complete"'))
        self.assertLess(self.wf.index('> "$tc_dir/complete"'), self.wf.index('tc_cache_save=true'))
        self.assertIn("always() && steps.build.outputs.tc_cache_save == 'true'", self.wf)


if __name__ == "__main__":
    unittest.main(verbosity=0)
