#!/usr/bin/env python3
"""Regression checks for package recipes that failed in CI."""

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def recipe(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


gcr = recipe("recipes/gui/gcr/recipe.toml")
gcr_configure = gcr["build"]["configure"]
assert "ssh_add_path = ''" in gcr_configure
assert "ssh_agent_path = ''" in gcr_configure
assert "sed -i" not in gcr_configure

linux = recipe("recipes/boot/linux/recipe.toml")
linux_configure = linux["build"]["configure"]
assert "require_config CONFIG_MODULES y" in linux_configure
assert "require_config CONFIG_KMOD y" not in linux_configure

xdg = recipe("recipes/gui/xdg-utils/recipe.toml")
xdg_compile = xdg["build"]["compile"]
assert "python" in xdg["depends"]["build"]
assert "xml.etree.ElementTree" in xdg_compile
assert 'local_name(node.tag) == "cmdsynopsis"' in xdg_compile
assert 'Path("scripts/desc")' in xdg_compile
assert "Generated embedded help" in xdg_compile
assert xdg_compile.index("python3 - <<'PY'") < xdg_compile.index("make -C scripts -j%{jobs} scripts")
assert "xmlto" not in xdg_compile

volk = recipe("recipes/media/volk/recipe.toml")
vulkan_tools = recipe("recipes/media/vulkan-tools/recipe.toml")
assert volk["package"]["version"] == vulkan_tools["package"]["version"] == "1.3.296"
assert volk["package"]["sha256"] == (
    "8ffd0e81e29688f4abaa39e598937160b098228f37503903b10d481d4862ab85"
)
assert {"cmake", "ninja", "vulkan-headers"} <= set(volk["depends"]["build"])
assert "volk" in set(vulkan_tools["depends"]["build"])

print("PACKAGE BUILD RECIPE REGRESSION CHECKS PASSED")
