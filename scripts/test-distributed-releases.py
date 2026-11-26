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
            "packages-0002\told-1.nawa.tar.zst",
            "packages-0002\told-2.nawa.tar.zst",
            "packages-0002\told-3.nawa.tar.zst",
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

        # Schema-v5 is a separate release namespace. Every archive, including
        # the recipe snapshot, is paired with its detached signature and the
        # asset limit is calculated against both uploaded files.
        for name in names + [recipe]:
            (repo / f"{name}.sig").write_bytes(b"signature")

        v5_releases = [
            {"tag_name": "stable", "assets": [{"name": names[0]}]},
            {"tag_name": "stable-v3", "assets": [{"name": "index.toml"}]},
            {"tag_name": "packages-9999", "assets": [{"name": names[2]}]},
            {"tag_name": "stable-v5", "assets": [{"name": "index.toml"}, {"name": "index.toml.sig"}]},
            {
                "tag_name": "packages-v5-0001",
                "assets": [
                    {"name": names[1]},
                    {"name": names[1] + ".sig"},
                ],
            },
        ]
        metadata.write_text(json.dumps(v5_releases), encoding="utf-8")
        listed_v5 = run(
            "list", "--releases-json", metadata, "--stable-tag", "stable-v5",
            "--index-version", "5",
        ).splitlines()
        assert listed_v5 == [f"packages-v5-0001\t{names[1]}"], listed_v5

        v5_plan_path = root / "plan-v5.json"
        v5_manifest = root / "locations-v5.toml"
        run(
            "plan",
            "--releases-json", metadata,
            "--repo-dir", repo,
            "--repository", "mrdevmohamed/faseela-repo",
            "--stable-tag", "stable-v5",
            "--recipe-file", recipe,
            "--max-assets", "4",
            "--index-version", "5",
            "--output", v5_plan_path,
            "--manifest", v5_manifest,
        )
        v5_plan = json.loads(v5_plan_path.read_text(encoding="utf-8"))
        assert v5_plan["index_version"] == 5
        assert v5_plan["assignments"][names[1]] == "packages-v5-0001"
        assert v5_plan["create_releases"] == ["packages-v5-0002"]
        assert set(v5_plan["uploads"]["packages-v5-0001"]) == {
            names[0], names[0] + ".sig"
        }
        assert set(v5_plan["uploads"]["packages-v5-0002"]) == {
            names[2], names[2] + ".sig", recipe, recipe + ".sig"
        }
        assert v5_plan["cleanup"] == []
        assert v5_plan["legacy_cleanup"] == []
        v5_urls = tomllib.loads(v5_manifest.read_text(encoding="utf-8"))["package_urls"]
        assert "/packages-v5-0001/" in v5_urls[names[1]]
        assert "/packages-v5-0002/" in v5_urls[names[2]]

        # A schema-v5 view fails closed if a published package loses its
        # signature sidecar; it never silently reuses an unsigned archive.
        v5_releases[-1]["assets"] = [{"name": names[1]}]
        metadata.write_text(json.dumps(v5_releases), encoding="utf-8")
        unsigned = subprocess.run(
            [
                "python3", "-I", str(SCRIPT), "list",
                "--releases-json", str(metadata), "--stable-tag", "stable-v5",
                "--index-version", "5",
            ],
            capture_output=True,
            text=True,
        )
        assert unsigned.returncode != 0
        assert "unsigned archive" in unsigned.stderr

    print("distributed release tests: passed")


if __name__ == "__main__":
    main()
