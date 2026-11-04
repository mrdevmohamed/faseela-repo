#!/usr/bin/env python3
"""Guard Mesa Vulkan/OpenGL runtime support and the optional Zed flavor."""

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

assert "libclc" in mesa_build, "Intel ANV's intel_clc build requires the Mesa libclc runtime"
assert "spirv-llvm-translator" in mesa_build, "libclc requires the LLVM-matched llvm-spirv tool"

llvm = recipe("recipes/gui/llvm/recipe.toml")
assert llvm["package"]["version"] == "18.1.8"
llvm_install = llvm["build"]["install"]
assert not re.search(r"find\\s+%\\{pkgdir\\}/usr/bin[\\s\\S]*?-delete", llvm_install), (
    "LLVM must not prune installed tools from /usr/bin; consumers such as libclc "
    "and LLVM's CMake package may require tools beyond the currently known list"
)
assert "rm -rf %{pkgdir}/usr/share/man" in llvm_install
assert "rm -rf %{pkgdir}/usr/share/doc" in llvm_install
assert llvm["package"]["rel"] >= 8, "Bump LLVM rel when changing its installed tool set"

translator = recipe("recipes/gui/spirv-llvm-translator/recipe.toml")
assert translator["package"]["version"] == "18.1.3"
assert {"llvm", "spirv-headers", "spirv-tools"} <= set(translator["depends"]["build"])
assert "llvm-spirv" in translator["build"]["compile"]

libclc = recipe("recipes/gui/libclc/recipe.toml")
assert libclc["package"]["version"] == llvm["package"]["version"], (
    "libclc must be built from the same LLVM release as the installed toolchain"
)
assert {"llvm", "spirv-llvm-translator"} <= set(libclc["depends"]["build"])
assert 'LIBCLC_TARGETS_TO_BUILD="spirv-mesa3d-;spirv64-mesa3d-"' in libclc["build"]["configure"], (
    "libclc must ship the 32-bit and 64-bit Mesa SPIR-V builtin files"
)
assert mesa["package"]["rel"] >= 7, "Bump Mesa rel when changing the shipped graphics ABI"
assert "-D platforms=wayland,x11" in configure, "Mesa must keep Wayland and enable the X11 platform"
assert "-D glx=dri" in configure, "Mesa must build DRI-based GLX and provide libGL.so.1"
assert "-D glx=disabled" not in configure, "Mesa must not drop the legacy libGL.so.1 ABI"

glx_runtime = {"libX11", "libXext", "libXfixes", "libxcb", "libxshmfence"}
assert glx_runtime <= set(mesa["depends"]["build"]), (
    f"Mesa GLX build dependencies missing: {sorted(glx_runtime - set(mesa['depends']['build']))}"
)
assert glx_runtime <= set(mesa["depends"]["run"]), (
    f"Mesa GLX runtime dependencies missing: {sorted(glx_runtime - set(mesa['depends']['run']))}"
)

nekoray = recipe("recipes/networking/nekoray/recipe.toml")
assert "mesa" in set(nekoray["depends"]["run"]), (
    "Nekoray must pull in Mesa's libGL.so.1 provider"
)

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
assert session["package"]["rel"] >= 12, "Bump gui-session rel when changing DRM access rules"
install_script = session["build"]["install"]
assert "70-faseela-drm.rules" in install_script, (
    "gui-session must ship a udev rule for the DRM render group"
)
assert 'SUBSYSTEM=="drm", KERNEL=="renderD*", GROUP="render", MODE="0660"' in install_script, (
    "the udev rule must assign render nodes to the render group"
)

flavors = tomllib.loads((ROOT / "flavors.toml").read_text(encoding="utf-8"))
zed_flavor = flavors["flavor"]["iso-gui-zed"]
assert "zed" in zed_flavor["include"], "iso-gui-zed must continue to install Zed"

print("VULKAN STACK VALIDATION PASSED")
