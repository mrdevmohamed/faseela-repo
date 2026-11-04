#!/usr/bin/env python3
"""Test Storytold install sections and the Faseela Wayland launch contract."""
from __future__ import annotations

import os
import socket
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
APP_WAYLAND_VARS = {
    "photocraft": "PHOTOCRAFT_NATIVE_WAYLAND",
    "soundcraft": "SOUNDCRAFT_WAYLAND",
    "lightcraft": "LIGHTCRAFT_WAYLAND",
    "filmcraft": "FILMCRAFT_WAYLAND",
    "designcraft": "DESIGNCRAFT_WAYLAND",
    "vectorcraft": "VECTORCRAFT_NATIVE_WAYLAND",
    "wordcraft": "WORDCRAFT_WAYLAND",
    "deckcraft": "DECKCRAFT_WAYLAND",
    "gridcraft": "GRIDCRAFT_WAYLAND",
    "cadcraft": "CADCRAFT_WAYLAND",
}


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
    binary.write_text(
        "#!/bin/sh\n"
        "if [ -n \"$FASEELA_TEST_OUTPUT\" ]; then\n"
        "    env | sort > \"$FASEELA_TEST_OUTPUT\"\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    desktop = share_dir / "applications" / f"{package_name}.desktop"
    desktop.write_text("[Desktop Entry]\nName=Test\n", encoding="utf-8")
    icon = share_dir / "icons" / "hicolor" / "test.txt"
    icon.write_text("icon fixture\n", encoding="utf-8")
    return binary, desktop


def run_launcher(binary: Path, env: dict[str, str], label: str) -> dict[str, str]:
    result = subprocess.run(
        [str(binary)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode:
        raise AssertionError(f"{binary.name}: {label} failed (exit {result.returncode}):\n{result.stdout}")
    output = Path(env["FASEELA_TEST_OUTPUT"])
    if not output.is_file():
        raise AssertionError(f"{binary.name}: {label} did not reach the upstream executable")
    return dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


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
        upstream_binary = pkgdir / "usr" / "bin" / f"{name}.real"
        installed_desktop = pkgdir / "usr" / "share" / "applications" / f"{name}.desktop"
        installed_icon = pkgdir / "usr" / "share" / "icons" / "hicolor" / "test.txt"
        for installed in (installed_binary, upstream_binary, installed_desktop, installed_icon):
            if not installed.is_file():
                raise AssertionError(f"{recipe.name}: {label} did not install {installed}")
        if upstream_binary.read_bytes() != binary.read_bytes():
            raise AssertionError(f"{recipe.name}: upstream binary changed in {label}")
        for executable in (upstream_binary, installed_binary):
            if executable.stat().st_mode & 0o111 == 0:
                raise AssertionError(f"{recipe.name}: executable bit lost in {label}")
        launcher = installed_binary.read_text(encoding="utf-8")
        for required in (
            "WINIT_UNIX_BACKEND=wayland",
            "FASEELA_CRAFT_USE_XWAYLAND",
            "WAYLAND_DISPLAY",
            "XDG_SESSION_TYPE",
            f'exec "$upstream" "$@"',
        ):
            if required not in launcher:
                raise AssertionError(f"{recipe.name}: launcher missing {required!r} in {label}")
        app_var = APP_WAYLAND_VARS.get(name)
        if app_var and app_var not in launcher:
            raise AssertionError(f"{recipe.name}: launcher does not disable upstream XWayland preference")

        output = root / "launcher-env.txt"
        base = os.environ.copy()
        for key in (
            "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XDG_RUNTIME_DIR", "DISPLAY",
            "XDG_SESSION_TYPE", "WINIT_UNIX_BACKEND", "FASEELA_CRAFT_USE_XWAYLAND",
            *APP_WAYLAND_VARS.values(),
        ):
            base.pop(key, None)
        base["FASEELA_TEST_OUTPUT"] = str(output)

        # A stale DISPLAY in a Wayland login must not make the app try an absent X server.
        no_socket = base.copy()
        no_socket.update({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"})
        no_wayland = subprocess.run(
            [str(installed_binary)],
            env=no_socket,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if no_wayland.returncode == 0 or not any(message in no_wayland.stdout for message in ("Wayland session variables are missing", "this is marked as a Wayland session")):
            raise AssertionError(f"{recipe.name}: stale DISPLAY was not rejected in {label}:\n{no_wayland.stdout}")

        # A live Wayland socket makes the launcher force native Wayland, even when DISPLAY exists.
        runtime_dir = root / "runtime"
        runtime_dir.mkdir(mode=0o700)
        socket_path = runtime_dir / "wayland-test"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(socket_path))
            listener.listen(1)
            wayland_env = base.copy()
            wayland_env.update({
                "XDG_SESSION_TYPE": "wayland",
                "XDG_RUNTIME_DIR": str(runtime_dir),
                "WAYLAND_DISPLAY": socket_path.name,
                "DISPLAY": ":0",
                "WINIT_UNIX_BACKEND": "x11",
            })
            wayland_values = run_launcher(installed_binary, wayland_env, f"{label} native Wayland")
        if wayland_values.get("WINIT_UNIX_BACKEND") != "wayland":
            raise AssertionError(f"{recipe.name}: native Wayland backend was not selected in {label}")
        if "DISPLAY" in wayland_values:
            raise AssertionError(f"{recipe.name}: launcher did not hide stale DISPLAY in native Wayland mode ({label})")
        if app_var and wayland_values.get(app_var) != "1":
            raise AssertionError(f"{recipe.name}: {app_var}=1 was not exported in {label}")

        # The optional XWayland override is explicit and clears native-Wayland preferences.
        xwayland_env = wayland_env.copy()
        xwayland_env.update({
            "FASEELA_CRAFT_USE_XWAYLAND": "1",
            "WINIT_UNIX_BACKEND": "wayland",
        })
        if app_var:
            xwayland_env[app_var] = "1"
        xwayland_values = run_launcher(installed_binary, xwayland_env, f"{label} optional XWayland")
        if xwayland_values.get("WINIT_UNIX_BACKEND") != "x11":
            raise AssertionError(f"{recipe.name}: XWayland override did not select X11 in {label}")
        if xwayland_values.get("DISPLAY") != ":0":
            raise AssertionError(f"{recipe.name}: XWayland override discarded DISPLAY in {label}")
        if app_var and app_var in xwayland_values:
            raise AssertionError(f"{recipe.name}: {app_var} was not cleared for XWayland in {label}")

        # Pure X11 sessions keep the upstream defaults.
        x11_env = base.copy()
        x11_env.update({
            "XDG_SESSION_TYPE": "x11",
            "DISPLAY": ":99",
            "WINIT_UNIX_BACKEND": "x11",
        })
        x11_values = run_launcher(installed_binary, x11_env, f"{label} X11")
        if x11_values.get("WINIT_UNIX_BACKEND") != "x11":
            raise AssertionError(f"{recipe.name}: X11 session was changed in {label}")
        if app_var and app_var in x11_values:
            raise AssertionError(f"{recipe.name}: native-Wayland override leaked into X11 in {label}")

        # A missing socket is an error, not a silent fallback to a stale DISPLAY.
        invalid_env = base.copy()
        invalid_env.update({
            "XDG_SESSION_TYPE": "wayland",
            "XDG_RUNTIME_DIR": str(root),
            "WAYLAND_DISPLAY": "wayland-missing",
            "DISPLAY": ":0",
        })
        invalid = subprocess.run(
            [str(installed_binary)],
            env=invalid_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if invalid.returncode == 0 or "Wayland socket is unavailable" not in invalid.stdout:
            raise AssertionError(f"{recipe.name}: invalid Wayland socket was not diagnosed in {label}")


def main() -> int:
    recipes = sorted(RECIPES.glob("*/recipe.toml"))
    if len(recipes) != 15:
        raise SystemExit(f"expected 15 creative recipes, found {len(recipes)}")
    for recipe in recipes:
        data = tomllib.loads(recipe.read_text(encoding="utf-8"))
        for layout in LAYOUTS:
            check(recipe, data, layout)
    print(f"ok: {len(recipes)} creative recipes x {len(LAYOUTS)} payload layouts; Wayland/X11 launch tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
