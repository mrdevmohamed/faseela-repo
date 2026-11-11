#!/usr/bin/env python3
"""Guard mpv's X11/EGL, Wayland/EGL, and DRM/KMS output backends."""

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def recipe(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


mpv = recipe("recipes/media/mpv/recipe.toml")
configure = mpv["build"]["configure"]
assert mpv["package"]["rel"] >= 5, "Bump mpv rel when changing its output backends"
for option in (
    "-D x11=enabled",
    "-D egl-x11=enabled",
    "-D wayland=enabled",
    "-D egl-wayland=enabled",
    "-D drm=enabled",
    "-D egl-drm=enabled",
):
    assert option in configure, f"mpv must enable {option}"
assert "-D x11=disabled" not in configure, "mpv must retain its X11 output backend"

x11_runtime = {"libX11", "libXext", "libXScrnSaver", "libXpresent", "libXrandr"}
for section in ("build", "run"):
    missing = x11_runtime - set(mpv["depends"][section])
    assert not missing, f"mpv {section} dependencies missing: {sorted(missing)}"

present = recipe("recipes/gui/libXpresent/recipe.toml")
assert present["package"]["version"] == "1.0.2"
assert present["package"]["sha256"] == (
    "4e5b21b4812206a4b223013606ae31170502c1043038777a1ef8f70c09d37602"
)
assert "libXpresent" in x11_runtime
present_runtime = {"libX11", "libXext", "libXfixes", "libXrandr"}
assert present_runtime <= set(present["depends"]["run"]), (
    f"libXpresent runtime dependencies missing: {sorted(present_runtime - set(present['depends']['run']))}"
)

print("MPV X11/WAYLAND/DRM VALIDATION PASSED")
