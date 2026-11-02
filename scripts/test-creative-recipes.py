#!/usr/bin/env python3
"""Smoke-test Storytold recipe install sections against both source layouts."""
from __future__ import annotations

import os
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "recipes" / "creative"


def check(recipe: Path, data: dict, layout: str) -> None:
    package = data["package"]
    script = data.get("build", {}).get("install", "")
    if not script:
        raise AssertionError(f"{recipe}: missing [build].install")

    source_dir = package.get("source_dir") or f"{package['name']}-{package['version']}"
    with tempfile.TemporaryDirectory(prefix=f"nawa-{package['name']}-") as tmp:
        root = Path(tmp)
        extraction = root / "src"
        bundle = extraction / source_dir
        usr_bin = bundle / "usr" / "bin"
        usr_bin.mkdir(parents=True)
        binary = usr_bin / package["name"]
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)

        pkgdir = root / "pkg"
        pkgdir.mkdir()
        cwd = bundle if layout == "package-dir" else extraction
        expanded = script.replace("%{pkgdir}", str(pkgdir))
        result = subprocess.run(
            ["bash", "-e", "-c", expanded],
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode:
            raise AssertionError(
                f"{recipe.name} failed in {layout} layout:\n{result.stdout}"
            )
        installed = pkgdir / "usr" / "bin" / package["name"]
        if not installed.is_file():
            raise AssertionError(
                f"{recipe.name}: {layout} layout did not install {installed}"
            )
        if installed.read_bytes() != binary.read_bytes():
            raise AssertionError(f"{recipe.name}: installed binary differs")


def main() -> int:
    recipes = sorted(RECIPES.glob("*/recipe.toml"))
    if len(recipes) != 15:
        raise SystemExit(f"expected 15 creative recipes, found {len(recipes)}")
    for recipe in recipes:
        data = tomllib.loads(recipe.read_text(encoding="utf-8"))
        for layout in ("package-dir", "archive-root"):
            check(recipe, data, layout)
    print(f"ok: {len(recipes)} creative recipes x 2 source layouts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
