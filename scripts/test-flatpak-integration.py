#!/usr/bin/env python3
"""Regression checks for Flatpak, COSMIC Store, and Faseela's systemd auth stack."""
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "recipes"


def recipe(category: str, name: str) -> dict:
    path = RECIPES / category / name / "recipe.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


flatpak = recipe("flatpak", "flatpak")
pkg = flatpak["package"]
assert pkg["name"] == "flatpak"
assert pkg["version"] == "1.18.4"
assert re.fullmatch(r"[0-9a-f]{64}", pkg["sources"][0]["sha256"])
assert pkg["sources"][0]["url"].startswith("https://github.com/flatpak/flatpak/releases/")
assert "assets/flathub.flatpakrepo" in flatpak["assets"]["include"]

build = set(flatpak["depends"]["build"])
run = set(flatpak["depends"]["run"])
assert {
    "glib", "libarchive", "curl", "libxml2", "libcap", "json-glib",
    "appstream", "ostree", "gpgme", "fuse3", "libseccomp", "polkit",
    "bubblewrap", "xdg-dbus-proxy", "p11-kit", "zstd",
} <= build
assert {
    "glib", "libarchive", "curl", "libxml2", "libcap", "json-glib",
    "appstream", "ostree", "gpgme", "gnupg", "fuse3", "libseccomp",
    "polkit", "dbus-system", "bubblewrap", "xdg-dbus-proxy", "p11-kit",
    "zstd",
} <= run

configure = flatpak["build"]["configure"]
for option in (
    "-Dsystemd=disabled",
    "-Dsystemdsystemunitdir=no",
    "-Dsystemduserunitdir=no",
    "-Dsystemdsystemenvgendir=no",
    "-Dsystemduserenvgendir=no",
    "-Dsystem_helper=enabled",
    "-Dsystem_install_dir=/var/lib/flatpak",
    "-Dsystem_bubblewrap=bwrap",
    "-Dsystem_dbus_proxy=xdg-dbus-proxy",
    "-Dsystem_fusermount=/usr/bin/fusermount3",
    "-Ddbus_config_dir=/usr/share/dbus-1/system.d",
):
    assert option in configure, f"Flatpak configure is missing {option}"
assert "systemd" not in configure.replace("nosystemd", "").replace("-Dsystemd=disabled", "").replace(
    "-Dsystemdsystemunitdir=no", ""
).replace("-Dsystemduserunitdir=no", "").replace(
    "-Dsystemdsystemenvgendir=no", ""
).replace("-Dsystemduserenvgendir=no", ""), "unexpected systemd option"

install = flatpak["build"]["install"]
assert "flatpak-system-helper" in install
assert "SystemdService=" in install and "sed -i" in install
assert "org.freedesktop.Flatpak.SystemHelper" in install
assert "/usr/share/dbus-1/system-services" in install
assert "/usr/share/flatpak/remotes.d/flathub.flatpakrepo" in install
assert "rm -rf" in install and "systemd-disabled" in install
post = flatpak["hooks"]["post_install"]
assert "ensure-system-account user flatpak flatpak" in post
# The hook also runs inside image-build chroots that have no /proc or /dev, where
# OSTree cannot create a repository: it must not invoke flatpak at all.
assert "remote-add" not in post and not any(
    line.startswith("flatpak ") for line in post.splitlines()
)
assert "/var/lib/flatpak" in post

# The Flathub descriptor is upstream's signed source metadata, not a URL-only
# remote with signature verification disabled.
flathub_path = ROOT / "recipes/flatpak/flatpak/assets/flathub.flatpakrepo"
flathub = flathub_path.read_text(encoding="utf-8")
assert "[Flatpak Repo]" in flathub
assert "Title=Flathub" in flathub
assert "Url=https://dl.flathub.org/repo/" in flathub
assert "GPGKey=mQIN" in flathub

# OSTree is the Flatpak storage engine. It must not pull libsystemd or units.
ostree = recipe("flatpak", "ostree")
assert "--without-libsystemd" in ostree["build"]["configure"]
assert "libsystemd" not in ostree["depends"]["run"]

# The existing Faseela authorization stack remains the only privileged path:
# system D-Bus activation -> Flatpak helper -> Polkit -> systemd-logind sessions.
polkit = recipe("gui", "polkit")
assert "-Dsession_tracking=logind" in polkit["build"]["configure"]
assert "/usr/lib/systemd/system/polkit.service" in polkit["build"]["install"]
dbus_system = recipe("gui", "dbus-system")
assert "dbus.socket and dbus.service" in dbus_system["build"]["install"]

# COSMIC Store compiles the upstream libflatpak backend for both scopes.
store = recipe("cosmic", "cosmic-store")
assert store["package"]["rel"] >= 4
assert "flatpak" in store["depends"]["build"]
assert "flatpak" in store["depends"]["run"]
store_compile = store["build"]["compile"]
assert "--no-default-features" in store_compile
assert "--features dbus-config,desktop,flatpak,logind,notify,single-instance,wgpu,wayland,xdg-portal" in store_compile
assert "desktop-systemd" not in store_compile
assert "packagekit" not in store_compile

desktop = recipe("cosmic", "cosmic-desktop")
assert desktop["package"]["rel"] >= 4
assert "flatpak" in desktop["depends"]["run"]
assert "mate-polkit" in desktop["depends"]["run"]
agent = recipe("flatpak", "mate-polkit")
assert "polkit" in agent["depends"]["run"]
assert "gtk3" in agent["depends"]["run"]
assert "s/^OnlyShowIn=MATE;$/OnlyShowIn=COSMIC;/" in agent["build"]["prepare"]

# AppStream and its XML/YAML dependencies are packaged, rather than relying on
# the pure-Rust catalog parser alone or host libraries from the build runner.
appstream = recipe("flatpak", "appstream")
assert "python-pyparsing" in flatpak["depends"]["build"]
assert "libxmlb" in appstream["depends"]["build"]
assert "libfyaml" in appstream["depends"]["build"]
assert "systemd=false" in appstream["build"]["configure"]
for category, name in (
    ("flatpak", "libxmlb"),
    ("flatpak", "libfyaml"),
    ("flatpak", "appstream"),
    ("flatpak", "libassuan"),
    ("flatpak", "libksba"),
    ("flatpak", "npth"),
    ("flatpak", "gnupg"),
    ("flatpak", "gpgme"),
    ("flatpak", "ostree"),
    ("flatpak", "python-pyparsing"),
    ("flatpak", "flatpak"),
    ("flatpak", "mate-polkit"),
):
    item = recipe(category, name)
    sources = item["package"]["sources"]
    assert sources and all(re.fullmatch(r"[0-9a-f]{64}", src["sha256"]) for src in sources), (
        f"{name}: source SHA-256 is not pinned"
    )

# All shell sections introduced here must parse before package CI attempts a build.
for label, script in (
    ("Flatpak install", install),
    ("Flatpak post-install", post),
):
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, f"{label} shell syntax error: {result.stderr}"

print("test-flatpak-integration: Flatpak/libflatpak, Flathub, D-Bus/Polkit/systemd-logind, and COSMIC Store checks passed")
