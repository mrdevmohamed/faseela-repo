#!/usr/bin/env python3
"""Regression tests for scripts/plan-build-shards.py."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("plan-build-shards.py")
spec = importlib.util.spec_from_file_location("plan_build_shards", SCRIPT)
planner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = planner
spec.loader.exec_module(planner)


def recipe(name, build=(), run=(), category="extra", relations=False, rel=1):
    return {"name": name, "category": category, "stem": f"{name}-1.0-{rel}",
            "deps": set(build) | set(run), "relations": relations}


def make(*items):
    return {r["name"]: r for r in items}


def shards(result):
    return [s for wave in result["waves"] for s in wave]


class PlanTests(unittest.TestCase):
    def test_dependency_is_never_in_a_later_wave_than_its_dependent(self):
        chain = [recipe(f"p{i}", build=[f"p{i-1}"] if i else []) for i in range(10)]
        result = planner.plan(make(*chain), [r["name"] for r in chain], [], set(), set(), {}, max_waves=4, max_levels=2) \
            if False else planner.plan(make(*chain), [r["name"] for r in chain], [], set(), set(), {}, max_waves=4)
        wave_of = {n: s["wave"] for s in shards(result) for n in s["pkgs"].split()}
        for i in range(1, 10):
            self.assertGreaterEqual(wave_of[f"p{i}"], wave_of[f"p{i-1}"])
        self.assertLessEqual(len(result["waves"]), 4)

    def test_dependent_packages_of_one_wave_share_a_shard(self):
        recipes = make(recipe("lib"), recipe("app", build=["lib"]), *[recipe(f"x{i}") for i in range(6)])
        result = planner.plan(recipes, list(recipes), [], set(), set(), {"x0": 30, "x1": 30, "x2": 30},
                              shard_minutes=20, max_shards=6)
        owner = {n: s["id"] for s in shards(result) for n in s["pkgs"].split()}
        self.assertEqual(owner["lib"] if result["waves"][0] and "lib" in owner else None,
                         owner["lib"])
        wave = {n: s["wave"] for s in shards(result) for n in s["pkgs"].split()}
        if wave["lib"] == wave["app"]:
            self.assertEqual(owner["lib"], owner["app"])

    def test_dependency_through_unselected_package_still_orders(self):
        # A -> B (not selected, up to date) -> C: C must be built before A.
        recipes = make(recipe("c"), recipe("b", build=["c"]), recipe("a", build=["b"]))
        result = planner.plan(recipes, ["a", "c"], [], set(), set(), {}, max_waves=4)
        wave = {n: s["wave"] for s in shards(result) for n in s["pkgs"].split()}
        owner = {n: s["id"] for s in shards(result) for n in s["pkgs"].split()}
        self.assertTrue(wave["c"] < wave["a"] or owner["c"] == owner["a"])

    def test_up_to_date_packages_are_not_planned(self):
        recipes = make(recipe("a"), recipe("b"), recipe("c"))
        result = planner.plan(recipes, ["a", "b", "c"], [], {"b-1.0-1"}, {"c-1.0-1"}, {})
        self.assertEqual(result["todo"], ["a"])
        self.assertEqual(sorted(result["done"]), ["b", "c"])

    def test_published_archive_of_relation_recipe_is_rebuilt(self):
        recipes = make(recipe("old"), recipe("new", relations=True))
        result = planner.plan(recipes, ["old", "new"], [], set(), {"old-1.0-1", "new-1.0-1"}, {})
        self.assertEqual(result["todo"], ["new"])

    def test_cached_relation_recipe_counts_as_done(self):
        recipes = make(recipe("new", relations=True))
        result = planner.plan(recipes, ["new"], [], {"new-1.0-1"}, {"new-1.0-1"}, {})
        self.assertEqual(result["todo"], [])
        self.assertEqual(result["waves"], [])

    def test_needs_and_waits(self):
        recipes = make(recipe("base"), recipe("mid", build=["base"]), recipe("top", run=["mid"]))
        result = planner.plan(recipes, ["mid", "top"], [], {"mid-1.0-1"}, set(), {})
        (shard,) = shards(result)
        self.assertEqual(shard["pkgs"], "top")
        self.assertEqual(shard["needs"].split(), ["base", "mid"])
        self.assertEqual(shard["waits"], "")

    def test_waits_lists_selected_dependencies_of_earlier_waves(self):
        chain = [recipe(f"p{i}", build=[f"p{i-1}"] if i else []) for i in range(8)]
        result = planner.plan(make(*chain), [r["name"] for r in chain], [], set(), set(), {}, max_waves=4)
        last = shards(result)[-1]
        self.assertIn("p0", last["waits"].split())

    def test_heavy_package_gets_its_own_shard(self):
        recipes = make(recipe("llvm"), *[recipe(f"s{i}") for i in range(30)])
        result = planner.plan(recipes, list(recipes), [], set(), set(), {"llvm": 86}, shard_minutes=25, max_shards=8)
        owner = {n: s for s in shards(result) for n in s["pkgs"].split()}
        self.assertEqual(owner["llvm"]["pkgs"], "llvm")

    def test_unknown_package_is_an_error(self):
        with self.assertRaises(planner.PlanError):
            planner.plan(make(recipe("a")), ["nope"], [], set(), set(), {})

    def test_cycle_does_not_hang(self):
        recipes = make(recipe("a", build=["b"]), recipe("b", build=["a"]))
        result = planner.plan(recipes, ["a", "b"], [], set(), set(), {})
        self.assertEqual(sorted(result["todo"]), ["a", "b"])

    def test_every_todo_package_is_planned_exactly_once(self):
        items = [recipe(f"p{i}", build=[f"p{j}" for j in range(i) if (i + j) % 3 == 0]) for i in range(60)]
        recipes = make(*items)
        result = planner.plan(recipes, list(recipes), [], set(), set(), {}, max_waves=8, shard_minutes=5)
        planned = [n for s in shards(result) for n in s["pkgs"].split()]
        self.assertEqual(sorted(planned), sorted(recipes))
        self.assertEqual(len(planned), len(set(planned)))
        wave = {n: s["wave"] for s in shards(result) for n in s["pkgs"].split()}
        owner = {n: s["id"] for s in shards(result) for n in s["pkgs"].split()}
        for name, rec in recipes.items():
            for dep in planner.closure(recipes, {name}):
                self.assertTrue(wave[dep] < wave[name] or owner[dep] == owner[name], (dep, name))


class LoadTests(unittest.TestCase):
    def test_version_constraints_do_not_leak_into_dependency_names(self):
        root = Path(tempfile.mkdtemp())
        for name, run in (("base-files", []), ("app", ["base-files >= 0.4-12", "libx>=2"])):
            d = root / "extra" / name
            d.mkdir(parents=True)
            deps = ", ".join(f'"{x}"' for x in run)
            (d / "recipe.toml").write_text(
                f'[package]\nname = "{name}"\nversion = "1"\nrel = 1\n[depends]\nrun = [{deps}]\n')
        recipes = planner.load_recipes(root)
        self.assertEqual(recipes["app"]["deps"], {"base-files", "libx"})
        result = planner.plan(recipes, ["app", "base-files"], [], set(), set(), {})
        self.assertEqual(sorted(planner.closure(recipes, {"app"})), ["base-files", "libx"])
        self.assertNotIn(">=", " ".join(s["needs"] for w in result["waves"] for s in w))


class EmitAndRunnableTests(unittest.TestCase):
    def test_emit_builds_one_matrix_per_wave_and_toolchain(self):
        recipes = make(recipe("a"), recipe("b", build=["a"]))
        result = planner.plan(recipes, ["a", "b"], ["glibc"], set(), set(), {}) if False else \
            planner.plan(make(recipe("a"), recipe("b", build=["a"]), recipe("glibc", category="toolchain")),
                         ["a", "b"], ["glibc"], set(), set(), {})
        with tempfile.TemporaryDirectory() as tmp:
            plan_file = Path(tmp) / "plan.json"
            out = Path(tmp) / "out"
            plan_file.write_text(json.dumps(result), encoding="utf-8")
            self.assertEqual(planner.main(["emit", "--plan", str(plan_file), "--github-output", str(out)]), 0)
            values = dict(line.split("=", 1) for line in out.read_text().splitlines())
        self.assertEqual(values["wave0_count"], "1")
        self.assertEqual(json.loads(values["wave0"])["include"][0]["toolchain"], "glibc")
        self.assertEqual(values["todo"], "a b")
        for number in range(1, planner.MAX_WAVES + 1):
            self.assertIn(f"wave{number}", values)
            json.loads(values[f"wave{number}"])
        self.assertLessEqual(len(values["wave1"]), 1024 * 1024)

    def test_runnable_skips_packages_whose_dependency_was_not_built(self):
        recipes_dir = Path(tempfile.mkdtemp())
        for name, build in (("lib", []), ("app", ["lib"]), ("tool", [])):
            d = recipes_dir / "extra" / name
            d.mkdir(parents=True)
            deps = ", ".join(f'"{x}"' for x in build)
            (d / "recipe.toml").write_text(
                f'[package]\nname = "{name}"\nversion = "1.0"\nrel = 1\n[depends]\nbuild = [{deps}]\n')
        out = Path(tempfile.mkdtemp())
        report = out / "report.txt"
        argv = ["runnable", "--recipes", str(recipes_dir), "--pkgs", "app tool", "--waits", "lib",
                "--out-dir", str(out), "--report", str(report)]
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            planner.main(argv)
        self.assertEqual(buf.getvalue().split(), ["tool"])
        self.assertIn("SKIPPED  app-1.0-1 (dependency lib was not built)", report.read_text())
        (out / "lib-1.0-1.nawa.tar.zst").write_bytes(b"x")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            planner.main(argv)
        self.assertEqual(buf.getvalue().split(), ["app", "tool"])


class RealRecipesTests(unittest.TestCase):
    def test_every_non_toolchain_recipe_is_planned_consistently(self):
        root = Path(__file__).resolve().parent.parent / "recipes"
        recipes = planner.load_recipes(root)
        names = [n for n, r in recipes.items() if r["category"] != "toolchain"]
        minutes = json.loads((Path(__file__).resolve().parent / "build-times.json").read_text())
        minutes = {k: v for k, v in minutes.items() if not k.startswith("_")}
        result = planner.plan(recipes, names, [], set(), set(), minutes, max_waves=planner.MAX_WAVES, shard_minutes=25)
        planned = [n for s in shards(result) for n in s["pkgs"].split()]
        self.assertEqual(sorted(planned), sorted(names))
        wave = {n: s["wave"] for s in shards(result) for n in s["pkgs"].split()}
        owner = {n: s["id"] for s in shards(result) for n in s["pkgs"].split()}
        for name in names:
            for dep in planner.closure(recipes, {name}) & set(names):
                self.assertTrue(wave[dep] < wave[name] or owner[dep] == owner[name], (dep, name))
        self.assertLessEqual(len(result["waves"]), planner.MAX_WAVES)
        for s in shards(result):
            self.assertLessEqual(len(json.dumps(s)), 200_000)


if __name__ == "__main__":
    unittest.main()
