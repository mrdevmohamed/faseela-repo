#!/usr/bin/env python3
"""Guard the Vulkan packages and permissions required by the optional Zed flavor."""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def recipe(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


mesa = recipe("recipes/gui/mesa/recipe.toml")
mesa_build = set(mesa["depends"]["build"])
configure = mesa["build"]["configure"]
match = re.search(r"-D vulkan-drivers=([^ ]+)", configure)
assert match, "Mesa must explicitly declare its Vulkan ICD set"
drivers = set(match.group(1).split(","))
required = {"amd", "intel", "intel_hasvk", "swrast"}
assert required <= drivers, f"Mesa Vulkan ICDs missing: {sorted(required - drivers)}"
assert "python-ply" in mesa_build, "Intel ANV requires the python-ply build dependency"
assert mesa["package"]["rel"] >= 5, "Bump Mesa rel when changing the shipped driver set"

ply = recipe("recipes/media/python-ply/recipe.toml")
assert ply["package"]["version"] == "3.11"
assert len(ply["package"]["sha256"]) == 64
assert "python" in ply["depends"]["run"]

zed = recipe("recipes/gui/zed/recipe.toml")
assert {"mesa", "vulkan-loader"} <= set(zed["depends"]["run"]), (
    "Zed must pull in Mesa's ICDs and the Khronos Vulkan loader"
)

session = recipe("recipes/gui/gui-session/recipe.toml")
post_install = session["hooks"]["post_install"]
assert re.search(r"for g in [^\n]*\brender\b", post_install), (
    "gui-session must create the render group"
)
assert "seat,video,render,input,audio" in post_install, (
    "gui-session instructions must add desktop users to render"
)

flavors = tomllib.loads((ROOT / "flavors.toml").read_text(encoding="utf-8"))
zed_flavor = flavors["flavor"]["iso-gui-zed"]
assert "zed" in zed_flavor["include"], "iso-gui-zed must continue to install Zed"

print("VULKAN STACK VALIDATION PASSED")
