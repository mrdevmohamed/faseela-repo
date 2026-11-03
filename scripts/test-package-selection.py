#!/usr/bin/env python3
"""Regression tests for the packages.yml multi-select resolver."""
import os
import subprocess
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
        self.assertEqual(plan["toolchain_packages"], [])

    def test_core_keeps_the_legacy_base_system_boot_extra_scope(self):
        plan = self.resolve(core=True)
        self.assertEqual(set(plan["packages"]), {
            "base-files", "bash", "nawa", "base-devel", "kernel", "runit", "curl",
        })
        self.assertNotIn("sway", plan["packages"])
        self.assertNotIn("docs-tool", plan["packages"])
        self.assertEqual(plan["toolchain_packages"], [])

    def test_multiple_categories_and_exact_packages_are_combined(self):
        plan = self.resolve(categories=["gui", "media"], package_names=["bash", "sway"])
        self.assertEqual(set(plan["packages"]), {"sway", "mpv", "bash"})
        self.assertEqual(plan["package_count"], 3)

    def test_multiple_flavors_are_combined_and_bootstrap_toolchain_is_preserved(self):
        plan = self.resolve(flavor_names=["desktop", "media"])
        self.assertIn("firefox", plan["packages"])
        self.assertIn("mpv", plan["packages"])
        self.assertIn("gcc", plan["toolchain_packages"])
        self.assertIn("rust", plan["toolchain_packages"])
        self.assertNotIn("gcc", plan["packages"])
        self.assertNotIn("rust", plan["packages"])
        self.assertNotIn("base-devel", plan["packages"])
        self.assertNotIn("nawa", plan["packages"])

    def test_exact_toolchain_names_are_routed_away_from_ordinary_packages(self):
        plan = self.resolve(package_names=["bash", "binutils", "gcc"])
        self.assertEqual(set(plan["packages"]), {"bash"})
        self.assertEqual(set(plan["toolchain_packages"]), {"binutils", "gcc"})
        self.assertFalse(plan["toolchain_all"])

    def test_explicit_toolchain_names_and_full_toolchain(self):
        partial = self.resolve(toolchain_package_names=["binutils"])
        self.assertEqual(partial["toolchain_packages"], ["binutils"])
        self.assertEqual(partial["packages"], [])
        full = self.resolve(all_toolchain=True)
        self.assertEqual(set(full["toolchain_packages"]), {"binutils", "gcc", "rust"})
        self.assertTrue(full["toolchain_all"])

    def test_full_toolchain_with_exclusions_becomes_selective(self):
        plan = self.resolve(all_toolchain=True, exclusions=["gcc"])
        self.assertNotIn("gcc", plan["toolchain_packages"])
        self.assertFalse(plan["toolchain_all"])

    def test_toolchain_category_cannot_enter_ordinary_category_selector(self):
        with self.assertRaisesRegex(select_packages.SelectionError, "Bootstrap"):
            self.resolve(categories=["toolchain"])

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

    def test_deleted_recipe_forces_reconciliation_of_current_packages(self):
        plan = select_packages.resolve_changed_selection(
            self.recipes, self.flavors, ["removed-package"],
        )
        expected = {
            name for name, (category, _) in self.recipes.items()
            if category != "toolchain"
        }
        self.assertEqual(set(plan["packages"]), expected)
        self.assertEqual(plan["deleted_recipe_names"], ["removed-package"])
        self.assertEqual(plan["source"], "CHANGED")

    def test_multiple_pushes_are_collected_from_last_successful_commit(self):
        previous_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "ci@example.invalid"], check=True)
            subprocess.run(["git", "config", "user.name", "CI Test"], check=True)
            base_file = self.recipes_dir / "base-files" / "recipe.toml"
            base_file.parent.mkdir(parents=True, exist_ok=True)
            base_file.write_text('[package]\\nname = "base-files"\\n', encoding="utf-8")
            subprocess.run(["git", "add", "recipes"], check=True)
            subprocess.run(["git", "commit", "-qm", "base"], check=True)
            last_successful = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True,
            ).strip()

            bash_file = self.recipes_dir / "base" / "bash" / "recipe.toml"
            bash_file.parent.mkdir(parents=True, exist_ok=True)
            bash_file.write_text('[package]\\nname = "bash"\\n', encoding="utf-8")
            subprocess.run(["git", "add", "recipes"], check=True)
            subprocess.run(["git", "commit", "-qm", "push B"], check=True)

            runit_file = self.recipes_dir / "system" / "runit" / "recipe.toml"
            runit_file.parent.mkdir(parents=True, exist_ok=True)
            runit_file.write_text('[package]\\nname = "runit"\\n', encoding="utf-8")
            subprocess.run(["git", "add", "recipes"], check=True)
            subprocess.run(["git", "commit", "-qm", "push C"], check=True)
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()

            changed = select_packages.changed_recipes(
                Path("recipes"), last_successful, head, cwd=self.root,
            )
            self.assertEqual(changed, ["bash", "runit"])
        finally:
            os.chdir(previous_cwd)


class RealRecipeTreeTests(unittest.TestCase):
    def test_all_is_every_non_toolchain_recipe_in_this_repository(self):
        root = Path(__file__).resolve().parent.parent
        recipes = flavor.load_recipes(root / "recipes")
        flavors = flavor.load_flavors(root / "flavors.toml")
        plan = select_packages.resolve_selection(recipes, flavors, all_packages=True)
        expected = {name for name, (category, _) in recipes.items() if category != "toolchain"}
        self.assertEqual(set(plan["packages"]), expected)
        for category in ("gui", "browser", "media", "creative"):
            self.assertGreater(plan["category_counts"].get(category, 0), 0, category)

    def test_core_is_exactly_base_system_boot_and_extra(self):
        root = Path(__file__).resolve().parent.parent
        recipes = flavor.load_recipes(root / "recipes")
        flavors = flavor.load_flavors(root / "flavors.toml")
        plan = select_packages.resolve_selection(recipes, flavors, core=True)
        expected = {
            name for name, (category, _) in recipes.items()
            if category in ("base", "system", "boot", "extra")
        }
        self.assertEqual(set(plan["packages"]), expected)
        self.assertNotIn("gui", plan["category_counts"])
        self.assertNotIn("browser", plan["category_counts"])
        self.assertNotIn("media", plan["category_counts"])
        self.assertNotIn("creative", plan["category_counts"])
        self.assertEqual(plan["toolchain_packages"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
