#!/usr/bin/env python3
"""Guard Mesa Vulkan/OpenGL runtime support and keep Zed optional."""

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
assert not re.search(r"find\s+%\{pkgdir\}/usr/bin[\s\S]*?-delete", llvm_install), (
    "LLVM must not prune installed tools from /usr/bin; consumers such as libclc "
    "and LLVM's CMake package may require tools beyond the currently known list"
)
assert "rm -rf %{pkgdir}/usr/share/man" not in llvm_install
assert "rm -rf %{pkgdir}/usr/share/doc" not in llvm_install
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
assert mesa["package"]["rel"] >= 10, "Bump Mesa rel when changing Mesa runtime dependency metadata or graphics ABI"
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

assert "spirv-tools" in set(mesa["depends"]["run"]), (
    "Mesa Vulkan ICDs require libSPIRV-Tools.so at runtime"
)

nekoray = recipe("recipes/networking/nekoray/recipe.toml")
assert "mesa" in set(nekoray["depends"]["run"]), (
    "Nekoray must pull in Mesa's libGL.so.1 provider"
)

double_conversion = recipe("recipes/extra/double-conversion/recipe.toml")
assert double_conversion["package"]["version"] == "3.4.0"
assert "-DBUILD_SHARED_LIBS=ON" in double_conversion["build"]["configure"], (
    "double-conversion must install the shared library required by Nekoray"
)
assert "double-conversion" in set(nekoray["depends"]["run"]), (
    "Nekoray must pull in the package providing libdouble-conversion.so.3"
)
assert "libXxf86vm" in set(nekoray["depends"]["run"]), (
    "Nekoray must pull in libXxf86vm.so.1 for its bundled Qt/X11 runtime"
)

qt_xcb_runtime = {
    "libSM", "xcb-util-image", "xcb-util-keysyms",
    "xcb-util-renderutil", "libxkbcommon",
}
missing_qt_runtime = qt_xcb_runtime - set(nekoray["depends"]["run"])
assert not missing_qt_runtime, (
    f"Nekoray Qt/XCB runtime dependencies missing: {sorted(missing_qt_runtime)}"
)

ice = recipe("recipes/gui/libICE/recipe.toml")
sm = recipe("recipes/gui/libSM/recipe.toml")
assert "libICE" in set(sm["depends"]["run"]), "libSM must pull in libICE.so.6"

for package in ("xcb-util-image", "xcb-util-keysyms", "xcb-util-renderutil"):
    xcb_recipe = recipe(f"recipes/gui/{package}/recipe.toml")
    assert "libxcb" in set(xcb_recipe["depends"]["run"]), (
        f"{package} must pull in the core XCB runtime"
    )

for package in ("xcb-util-image", "xcb-util-keysyms", "xcb-util-renderutil"):
    xcb_recipe = recipe(f"recipes/gui/{package}/recipe.toml")
    assert "xcb-util" in set(xcb_recipe["depends"]["run"]), (
        f"{package} must pull in the shared xcb-util runtime"
    )

xkbcommon = recipe("recipes/gui/libxkbcommon/recipe.toml")
assert "-D enable-x11=true" in xkbcommon["build"]["configure"], (
    "libxkbcommon must build libxkbcommon-x11.so.0 for Qt's XCB platform"
)
assert "libxcb" in set(xkbcommon["depends"]["build"])
assert "libxcb" in set(xkbcommon["depends"]["run"])
assert nekoray["package"]["rel"] >= 5, (
    "Bump Nekoray rel when changing the extracted application runtime"
)
assert "export QT_QPA_PLATFORM=xcb" in nekoray["build"]["install"], (
    "Nekoray must select its bundled XCB QPA plugin under Wayland/XWayland sessions"
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
assert "seat,video,render,input,audio" in post_install, (
    "gui-session instructions must add desktop users to render"
)
assert session["package"]["rel"] >= 28, "Bump gui-session rel when changing shared seatd integration"
seatd_runit = recipe("recipes/gui/seatd-runit/recipe.toml")
seatd_post_install = seatd_runit["hooks"]["post_install"]
assert "for group in seat video render input; do" in seatd_post_install, (
    "seatd-runit must create the shared DRM and input groups"
)
seatd_install = seatd_runit["build"]["install"]
assert "70-faseela-drm.rules" in seatd_install, (
    "seatd-runit must ship the shared udev rule for the DRM render group"
)
assert 'SUBSYSTEM=="drm", KERNEL=="renderD*", GROUP="render", MODE="0660"' in seatd_install, (
    "the udev rule must assign render nodes to the render group"
)

flavors = tomllib.loads((ROOT / "flavors.toml").read_text(encoding="utf-8"))
for desktop in ("iso-nogui", "iso-sway", "iso-xfce"):
    assert "zed" not in flavors["flavor"][desktop].get("include", []), (
        f"Zed must remain an optional application, not part of {desktop}"
    )

print("VULKAN STACK VALIDATION PASSED")
