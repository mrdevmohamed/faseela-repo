#!/usr/bin/env python3
"""Test Storytold install sections against their published bin/share payloads."""
from __future__ import annotations

import os
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "recipes" / "creative"
LAYOUTS = (
    ("package-dir-bin-share", False, "bin-share"),
    ("archive-root-bin-share", True, "bin-share"),
    ("package-dir-usr-tree", False, "usr-tree"),
    ("archive-root-usr-tree", True, "usr-tree"),
    ("package-dir-symlink-usr", False, "symlink-usr"),
)


def populate_payload(payload: Path, package_name: str, kind: str) -> tuple[Path, Path]:
    if kind == "bin-share":
        root = payload
    elif kind == "usr-tree":
        root = payload / "usr"
    elif kind == "symlink-usr":
        root = payload / "upstream-usr"
        (payload / "usr").symlink_to(root, target_is_directory=True)
    else:
        raise AssertionError(f"unknown payload kind: {kind}")

    binary_dir = root / "bin"
    share_dir = root / "share"
    binary_dir.mkdir(parents=True)
    (share_dir / "applications").mkdir(parents=True)
    (share_dir / "icons" / "hicolor").mkdir(parents=True)

    binary = binary_dir / package_name
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    desktop = share_dir / "applications" / f"{package_name}.desktop"
    desktop.write_text("[Desktop Entry]\nName=Test\n", encoding="utf-8")
    icon = share_dir / "icons" / "hicolor" / "test.txt"
    icon.write_text("icon fixture\n", encoding="utf-8")
    return binary, desktop


def check(recipe: Path, data: dict, layout: tuple[str, bool, str]) -> None:
    package = data["package"]
    name = package["name"]
    script = data.get("build", {}).get("install", "")
    if not script:
        raise AssertionError(f"{recipe}: missing [build].install")

    source_dir = package.get("source_dir") or f"{name}-{package['version']}"
    label, from_archive_root, kind = layout
    with tempfile.TemporaryDirectory(prefix=f"nawa-{name}-") as tmp:
        root = Path(tmp)
        extraction = root / "src"
        bundle = extraction / source_dir
        bundle.mkdir(parents=True)
        binary, desktop = populate_payload(bundle, name, kind)

        pkgdir = root / "pkg"
        pkgdir.mkdir()
        cwd = extraction if from_archive_root else bundle
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
            raise AssertionError(f"{recipe.name} failed in {label}:\n{result.stdout}")

        installed_binary = pkgdir / "usr" / "bin" / name
        installed_desktop = pkgdir / "usr" / "share" / "applications" / f"{name}.desktop"
        installed_icon = pkgdir / "usr" / "share" / "icons" / "hicolor" / "test.txt"

        if name == "designcraft":
            upstream_binary = pkgdir / "usr" / "bin" / "designcraft.real"
            for installed in (upstream_binary, installed_binary, installed_desktop, installed_icon):
                if not installed.is_file():
                    raise AssertionError(f"{recipe.name}: {label} did not install {installed}")
            if upstream_binary.read_bytes() != binary.read_bytes():
                raise AssertionError(f"{recipe.name}: upstream binary changed in {label}")
            for executable in (upstream_binary, installed_binary):
                if executable.stat().st_mode & 0o111 == 0:
                    raise AssertionError(f"{recipe.name}: executable bit lost in {label}")
            launcher = installed_binary.read_text(encoding="utf-8")
            for required in (
                "no active Wayland session detected",
                "XDG_RUNTIME_DIR",
                "wayland_socket",
                "WINIT_UNIX_BACKEND=wayland",
                'exec "$script_dir/designcraft.real" "$@"',
            ):
                if required not in launcher:
                    raise AssertionError(f"{recipe.name}: launcher is missing {required!r} in {label}")

            # Running outside Sway must fail early with an actionable message,
            # not fall through to the unavailable X11 server.
            no_session_env = os.environ.copy()
            no_session_env.pop("WAYLAND_DISPLAY", None)
            no_session_env.pop("XDG_RUNTIME_DIR", None)
            no_session_env.pop("WINIT_UNIX_BACKEND", None)
            no_session = subprocess.run(
                [str(installed_binary)],
                env=no_session_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if no_session.returncode == 0 or "no active Wayland session detected" not in no_session.stdout:
                raise AssertionError(
                    f"{recipe.name}: missing Wayland session was not diagnosed in {label}:\\n"
                    f"{no_session.stdout}"
                )
        else:
            for installed in (installed_binary, installed_desktop, installed_icon):
                if not installed.is_file():
                    raise AssertionError(f"{recipe.name}: {label} did not install {installed}")
            if installed_binary.read_bytes() != binary.read_bytes():
                raise AssertionError(f"{recipe.name}: binary changed in {label}")
            if installed_binary.stat().st_mode & 0o111 == 0:
                raise AssertionError(f"{recipe.name}: executable bit lost in {label}")

        if installed_desktop.read_bytes() != desktop.read_bytes():
            raise AssertionError(f"{recipe.name}: desktop file changed in {label}")


def main() -> int:
    recipes = sorted(RECIPES.glob("*/recipe.toml"))
    if len(recipes) != 15:
        raise SystemExit(f"expected 15 creative recipes, found {len(recipes)}")
    for recipe in recipes:
        data = tomllib.loads(recipe.read_text(encoding="utf-8"))
        for layout in LAYOUTS:
            check(recipe, data, layout)
    print(f"ok: {len(recipes)} creative recipes x {len(LAYOUTS)} payload layouts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
