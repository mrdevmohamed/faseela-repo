#!/usr/bin/env python3
"""Unit tests for distributed-release planning (no GitHub calls)."""
import json
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "distributed-releases.py"


def run(*args):
    return subprocess.run(
        ["python3", "-I", str(SCRIPT), *map(str, args)],
        check=True, capture_output=True, text=True,
    ).stdout


def main():
    with tempfile.TemporaryDirectory(prefix="distributed-releases-test-") as td:
        root = Path(td)
        repo = root / "repo"
        repo.mkdir()
        names = [
            "alpha-1.0-1.nawa.tar.zst",
            "beta-2.0-1.nawa.tar.zst",
            "gamma-3.0-1.nawa.tar.zst",
        ]
        for name in names:
            (repo / name).write_bytes(b"archive")

        recipe = "recipes-abcdef123.recipes.tar.zst"
        releases = [
            {
                "tag_name": "stable",
                "assets": [
                    {"name": names[0]},
                    {"name": names[1]},
                    {"name": names[1] + ".sig"},
                    {"name": "index.toml"},
                    {"name": "index.toml.sig"},
                ],
            },
            {
                "tag_name": "packages-0001",
                "assets": [
                    {"name": names[0]},
                    {"name": "keep-1"},
                ],
            },
            {
                "tag_name": "packages-0002",
                "assets": [
                    {"name": "old-1.nawa.tar.zst"}, {"name": "old-2.nawa.tar.zst"}, {"name": "old-3.nawa.tar.zst"},
                ],
            },
        ]
        metadata = root / "releases.json"
        metadata.write_text(json.dumps([releases]), encoding="utf-8")

        listed = run(
            "list", "--releases-json", metadata, "--stable-tag", "stable"
        ).splitlines()
        assert listed == [
            f"packages-0001\t{names[0]}",
            f"stable\t{names[1]}",
        ], listed

        plan_path = root / "plan.json"
        manifest = root / "locations.toml"
        run(
            "plan",
            "--releases-json", metadata,
            "--repo-dir", repo,
            "--repository", "mrdevmohamed/faseela-repo",
            "--stable-tag", "stable",
            "--recipe-file", recipe,
            "--max-assets", "3",
            "--output", plan_path,
            "--manifest", manifest,
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))

        assert plan["assignments"][names[0]] == "packages-0001"
        # packages-0001 had room for one more asset. packages-0002 was full.
        assert plan["assignments"][names[1]] == "packages-0001"
        assert plan["assignments"][names[2]] == "packages-0003"
        assert plan["assignments"][recipe] == "packages-0003"
        assert plan["create_releases"] == ["packages-0003"]
        assert set(plan["uploads"]["packages-0001"]) == {names[1]}
        assert set(plan["uploads"]["packages-0003"]) == {names[2], recipe}
        assert {"tag": "packages-0002", "name": "old-1.nawa.tar.zst"} in plan["cleanup"]
        assert names[1] in plan["legacy_cleanup"]
        assert names[1] + ".sig" in plan["legacy_cleanup"]
        assert names[0] in plan["legacy_cleanup"]

        parsed = tomllib.loads(manifest.read_text(encoding="utf-8"))
        assert parsed["schema"] == 1
        assert parsed["package_urls"][names[0]].endswith(
            f"/packages-0001/{names[0]}"
        )
        assert parsed["recipe_urls"][recipe].endswith(f"/packages-0003/{recipe}")

        uploads = run(
            "uploads", "--plan", plan_path,
            "--repo-dir", repo, "--tag", "packages-0003"
        ).splitlines()
        assert set(uploads) == {str(repo / names[2]), str(repo / recipe)}
        cleanup = run("cleanup", "--plan", plan_path, "--kind", "legacy").splitlines()
        assert f"stable\t{names[1]}" in cleanup

    print("distributed release tests: passed")


if __name__ == "__main__":
    main()
