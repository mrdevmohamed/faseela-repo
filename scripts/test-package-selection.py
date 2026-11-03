#!/usr/bin/env python3
"""Regression tests for the packages.yml multi-select resolver."""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import flavor  # noqa: E402
import importlib.util  # noqa: E402

_selector_spec = importlib.util.spec_from_file_location("select_packages", SCRIPTS / "select-packages.py")
select_packages = importlib.util.module_from_spec(_selector_spec)
sys.modules[_selector_spec.name] = select_packages
_selector_spec.loader.exec_module(select_packages)


class PackageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.recipes_dir = self.root / "recipes"
        data = {
            "base-files": ("base", {}),
            "bash": ("base", {"run": ["base-files"]}),
            "nawa": ("base", {"build": ["rust"], "run": ["bash"]}),
            "base-devel": ("base", {"run": ["bash"]}),
            "kernel": ("boot", {"build": ["gcc"]}),
            "runit": ("system", {}),
            "curl": ("extra", {"run": ["bash"]}),
            "sway": ("gui", {"run": ["bash"]}),
            "firefox": ("browser", {"run": ["sway"]}),
            "mpv": ("media", {"run": ["sway"]}),
            "creative-app": ("creative", {"run": ["sway"]}),
            "docs-tool": ("docs", {}),
            "binutils": ("toolchain", {}),
            "gcc": ("toolchain", {"run": ["binutils"]}),
            "rust": ("toolchain", {"run": ["gcc"]}),
        }
        for name, (category, deps) in data.items():
            recipe = self.recipes_dir / category / name / "recipe.toml"
            recipe.parent.mkdir(parents=True, exist_ok=True)
            build = ", ".join(f'"{x}"' for x in deps.get("build", []))
            run = ", ".join(f'"{x}"' for x in deps.get("run", []))
            recipe.write_text(
                f'[package]\nname = "{name}"\nversion = "1"\nrel = 1\n'
                f'[depends]\nbuild = [{build}]\nrun = [{run}]\n',
                encoding="utf-8",
            )
        self.recipes = flavor.load_recipes(self.recipes_dir)
        self.flavors_file = self.root / "flavors.toml"
        self.flavors_file.write_text(textwrap.dedent("""
            [flavor.bootstrap]
            include = ["base-devel", "nawa"]
            closure = "build"

            [flavor.desktop]
            extends = ["bootstrap"]
            include = ["firefox"]

            [flavor.media]
            extends = ["bootstrap"]
            include = ["mpv"]
        """), encoding="utf-8")
        self.flavors = flavor.load_flavors(self.flavors_file)

    def tearDown(self):
        self.tmp.cleanup()

    def resolve(self, **kwargs):
        return select_packages.resolve_selection(self.recipes, self.flavors, **kwargs)

    def test_all_includes_every_current_non_toolchain_category(self):
        plan = self.resolve(all_packages=True)
        self.assertEqual(set(plan["packages"]), {
            "base-files", "bash", "nawa", "base-devel", "kernel", "runit", "curl",
            "sway", "firefox", "mpv", "creative-app", "docs-tool",
        })
        self.assertNotIn("gcc", plan["packages"])
        self.assertNotIn("binutils", plan["packages"])
        self.assertIn("docs", plan["category_counts"])

    def test_core_keeps_the_legacy_base_system_boot_extra_scope(self):
        plan = self.resolve(core=True)
        self.assertEqual(set(plan["packages"]), {
            "base-files", "bash", "nawa", "base-devel", "kernel", "runit", "curl",
        })
        self.assertNotIn("sway", plan["packages"])
        self.assertNotIn("docs-tool", plan["packages"])

    def test_multiple_categories_and_exact_packages_are_combined(self):
        plan = self.resolve(categories=["gui", "media"], package_names=["bash", "sway"])
        self.assertEqual(set(plan["packages"]), {"sway", "mpv", "bash"})
        self.assertEqual(plan["package_count"], 3)

    def test_multiple_flavors_are_combined_and_bootstrap_toolchain_is_preserved(self):
        plan = self.resolve(flavor_names=["desktop", "media"])
        self.assertIn("firefox", plan["packages"])
        self.assertIn("mpv", plan["packages"])
        self.assertIn("gcc", plan["packages"])
        self.assertIn("rust", plan["packages"])
        self.assertNotIn("base-devel", plan["packages"])
        self.assertNotIn("nawa", plan["packages"])

    def test_allows_category_and_package_exclusions(self):
        plan = self.resolve(all_packages=True, exclusions=["@creative", "firefox"])
        self.assertNotIn("creative-app", plan["packages"])
        self.assertNotIn("firefox", plan["packages"])
        self.assertIn("sway", plan["packages"])
        self.assertEqual(plan["excluded_count"], 2)

    def test_unknown_category_package_and_flavor_are_errors(self):
        for kwargs in (
            {"categories": ["unknown"]},
            {"package_names": ["not-a-package"]},
            {"flavor_names": ["not-a-flavor"]},
            {"exclusions": ["not-a-package"]},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(select_packages.SelectionError):
                self.resolve(**kwargs)

    def test_empty_manual_selection_is_an_error(self):
        with self.assertRaises(select_packages.SelectionError):
            self.resolve()

    def test_selector_text_supports_commas_spaces_and_newlines(self):
        self.assertEqual(select_packages.split_values("bash, curl\ngit"), ["bash", "curl", "git"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
