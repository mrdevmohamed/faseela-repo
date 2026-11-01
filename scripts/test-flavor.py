#!/usr/bin/env python3
"""scripts/test-flavor.py — flavor.py on a tiny synthetic tree, then the real one."""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flavor  # noqa: E402


def tree(d: Path, recipes: dict):
    for name, (cat, deps) in recipes.items():
        p = d / "recipes" / cat / name
        p.mkdir(parents=True)
        run = ", ".join(f'"{x}"' for x in deps.get("run", []))
        build = ", ".join(f'"{x}"' for x in deps.get("build", []))
        (p / "recipe.toml").write_text(
            f'[package]\nname = "{name}"\nversion = "1"\n[depends]\nbuild = [{build}]\nrun = [{run}]\n')
    return d / "recipes"


class Flavors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.recipes = flavor.load_recipes(tree(d, {
            "libc": ("base", {}),
            "cc": ("base", {"run": ["libc"]}),
            "rust": ("extra", {"run": ["cc"]}),
            "nawa": ("base", {"build": ["rust"], "run": []}),
            "vim": ("extra", {"run": ["libc"]}),
            "sway": ("gui", {"run": ["libc"]}),
        }))
        (d / "f.toml").write_text(textwrap.dedent("""
            [flavor.boot]
            include = ["nawa"]
            closure = "build"
            [flavor.min]
            include = ["nawa", "vim"]
            [flavor.big]
            extends = ["min"]
            include = ["@gui"]
            exclude = ["vim"]
        """))
        self.flavors = flavor.load_flavors(d / "f.toml")

    def tearDown(self):
        self.tmp.cleanup()

    def r(self, n):
        return flavor.resolve(self.flavors, self.recipes, n)

    def test_run_closure_skips_build_deps(self):
        self.assertEqual(self.r("min"), ["nawa", "libc", "vim"])

    def test_build_closure_adds_build_deps_first(self):
        self.assertEqual(self.r("boot"), ["libc", "cc", "rust", "nawa"])

    def test_extends_include_exclude(self):
        self.assertEqual(self.r("big"), ["nawa", "libc", "sway"])

    def test_unknown_things_are_errors(self):
        for bad in ({"include": ["nope"]}, {"include": ["@nope"]}, {"extends": ["nope"]},
                    {"exclude": ["nope"]}):
            self.flavors["x"] = bad
            with self.assertRaises(flavor.FlavorError, msg=bad):
                self.r("x")

    def test_cycle(self):
        self.flavors["a"] = {"extends": ["b"]}
        self.flavors["b"] = {"extends": ["a"]}
        with self.assertRaises(flavor.FlavorError):
            self.r("a")


class RealTree(unittest.TestCase):
    def test_every_flavor_resolves_and_bootstrap_is_contained(self):
        root = Path(__file__).resolve().parent.parent
        flavors = flavor.load_flavors(root / "flavors.toml")
        recipes = flavor.load_recipes(root / "recipes")
        got = {n: flavor.resolve(flavors, recipes, n) for n in flavors}
        for n in ("iso-nogui", "iso-gui", "rootfs-min"):
            # the bootstrap core must be installable into every image
            self.assertTrue({"base-devel", "nawa"} <= set(got[n]), n)
        self.assertEqual(got["seed"], got["bootstrap"])
        self.assertNotIn("linux-firmware", got["iso-nogui"])
        self.assertIn("sway", got["iso-gui"])
        self.assertNotIn("sway", got["iso-nogui"])


if __name__ == "__main__":
    unittest.main()
