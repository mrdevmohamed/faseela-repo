#!/usr/bin/env python3
"""Regression checks for the optional WebKitGTK 4.1 / Telegram Web Apps stack."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "recipes"


def recipe(category: str, name: str) -> dict:
    path = RECIPES / category / name / "recipe.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def require_deps(category: str, name: str, kind: str, required: set[str]) -> None:
    actual = set(recipe(category, name).get("depends", {}).get(kind, []))
    missing = required - actual
    assert not missing, f"{name} is missing {kind} dependencies: {sorted(missing)}"


telegram = recipe("messaging", "telegram-desktop")
assert telegram["package"]["rel"] >= 2, "Bump telegram-desktop rel when adding WebKitGTK"
require_deps("messaging", "telegram-desktop", "run", {"webkit2gtk-4.1"})

webkit = recipe("browser", "webkit2gtk-4.1")
assert webkit["package"]["version"] == "2.54.2"
assert webkit["package"]["source"].endswith("webkitgtk-%{version}.tar.xz")
assert re.fullmatch(r"[0-9a-f]{64}", webkit["package"]["sha256"])
require_deps("browser", "webkit2gtk-4.1", "build", {
    "cmake", "ninja", "ruby", "which", "gtk3", "glib", "cairo", "icu",
    "harfbuzz", "fontconfig", "freetype", "mesa", "libdrm", "libgudev",
    "libsoup3", "libwebp", "lcms2", "openjpeg", "sqlite", "libxml2",
    "libxslt", "zlib", "brotli", "libpng", "libjpeg-turbo", "gdk-pixbuf",
    "libepoxy", "at-spi2-core", "libxkbcommon", "wayland", "wayland-protocols",
    "libX11", "libXext", "libXrender", "libxcb", "openssl", "glib-networking",
})
require_deps("browser", "nghttp2", "build", set())
nghttp2 = recipe("browser", "nghttp2")["package"]
assert nghttp2["version"] == "1.71.0"
assert re.fullmatch(r"[0-9a-f]{64}", nghttp2["sha256"])
require_deps("browser", "libsoup3", "build", {"nghttp2"})
require_deps("browser", "libsoup3", "run", {"nghttp2"})
require_deps("browser", "gnutls", "build", {"pkgconf", "nettle", "libtasn1", "libidn2", "p11-kit"})
gnutls_configure = recipe("browser", "gnutls")["build"]["configure"]
assert "PKG_CONFIG_PATH=/usr/lib64/pkgconfig" in gnutls_configure, (
    "GnuTLS must search Faseela's /usr/lib64/pkgconfig directory for Nettle"
)
networking = recipe("browser", "glib-networking")
require_deps("browser", "glib-networking", "build", {"gsettings-desktop-schemas"})
networking_configure = networking["build"]["configure"]
assert "PKG_CONFIG_PATH=/usr/lib64/pkgconfig" in networking_configure, (
    "glib-networking must resolve GnuTLS' Nettle/Hogweed pkg-config requirements"
)
for required in ("-D gnutls=enabled", "-D openssl=disabled", "-D libproxy=disabled"):
    assert required in networking_configure, (
        f"glib-networking is missing Meson option: {required}"
    )
assert "-D tests=" not in networking_configure, (
    "glib-networking 2.80.1 has no Meson 'tests' option"
)
require_deps("browser", "webkit2gtk-4.1", "run", {
    "gtk3", "glib", "cairo", "icu", "harfbuzz", "fontconfig", "freetype",
    "mesa", "libdrm", "libgudev", "libsoup3", "glib-networking", "gnutls",
    "libtasn1", "nettle", "libwebp", "lcms2", "openjpeg", "sqlite",
    "libxml2", "libxslt", "zlib", "brotli", "libpng", "libjpeg-turbo",
    "gdk-pixbuf", "libepoxy", "at-spi2-core", "libxkbcommon", "wayland",
    "libX11", "libXext", "libXrender", "libxcb", "bubblewrap", "openssl",
    "gcc", "glibc",
})

configure = webkit["build"]["configure"]
for required in (
    "-DPORT=GTK",
    "-DUSE_GTK4=OFF",
    "-DENABLE_BUBBLEWRAP_SANDBOX=ON",
    "-DENABLE_VIDEO=OFF",
    "-DENABLE_WEB_RTC=OFF",
    "-DENABLE_WEB_AUDIO=OFF",
    "-DENABLE_MEDIA_RECORDER=OFF",
):
    assert required in configure, f"WebKitGTK is missing build option: {required}"
assert "ninja -C build -j2" == webkit["build"]["compile"], (
    "Keep WebKitGTK builds capped at two jobs for hosted-runner memory limits"
)
assert webkit.get("slim", {}).get("strip") is False, (
    "Do not strip the large WebKitGTK shared libraries"
)

for category, package_name, min_version in (
    ("dev", "ruby", (4, 0, 9)),
    ("extra", "cmake", (4, 4, 5)),
    ("gui", "cairo", (1, 18, 6)),
    ("extra", "which", (2, 25)),
):
    package = recipe(category, package_name)["package"]
    version = tuple(int(part) for part in package["version"].split(".")[:3])
    assert version >= min_version, f"{package_name} is too old for WebKitGTK"
    assert re.fullmatch(r"[0-9a-f]{64}", package["sha256"]), (
        f"{package_name} source checksum must be pinned"
    )

# No user-facing ISO or bootstrap profile should silently absorb this large stack.
import sys
sys.path.insert(0, str(ROOT / "scripts"))
import flavor

recipes = flavor.load_recipes(RECIPES)
flavors = flavor.load_flavors(ROOT / "flavors.toml")
for flavor_name in ("bootstrap", "seed", "rootfs-min", "iso-nogui", "iso-sway", "iso-xfce"):
    resolved = set(flavor.resolve(flavors, recipes, flavor_name))
    assert "webkit2gtk-4.1" not in resolved, (
        f"WebKitGTK unexpectedly entered the {flavor_name} flavor"
    )
    assert "telegram-desktop" not in resolved, (
        f"Telegram unexpectedly entered the {flavor_name} flavor"
    )

print("WEBKITGTK / TELEGRAM WEB APPS VALIDATION PASSED")
