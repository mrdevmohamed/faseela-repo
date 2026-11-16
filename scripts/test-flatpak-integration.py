#!/usr/bin/env python3
"""Regression checks for Flatpak, Flathub and COSMIC Store integration."""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "recipes"

REQUIRED = {
    ("system", "libassuan"),
    ("system", "npth"),
    ("system", "libksba"),
    ("system", "gnupg"),
    ("system", "gpgme"),
    ("gui", "python-pyparsing"),
    ("gui", "libfyaml"),
    ("gui", "libxmlb"),
    ("gui", "appstream"),
    ("gui", "ostree"),
    ("gui", "flatpak"),
}


def recipe(category: str, name: str) -> dict:
    path = RECIPES / category / name / "recipe.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def require_dependencies(data: dict, section: str, names: set[str], package: str) -> None:
    actual = set(data.get("depends", {}).get(section, []))
    missing = names - actual
    assert not missing, f"{package}: missing {section} dependencies: {sorted(missing)}"


found = {
    (p.parent.parent.name, p.parent.name)
    for p in RECIPES.glob("*/*/recipe.toml")
}
assert REQUIRED <= found, f"Flatpak recipe set is incomplete: {sorted(REQUIRED - found)}"

# Every new recipe has matching metadata, an x86_64 target and a pinned source.
for category, name in sorted(REQUIRED):
    data = recipe(category, name)
    pkg = data["package"]
    assert pkg["name"] == name, f"{name}: package name does not match its directory"
    assert pkg["arch"] == ["x86_64"], f"{name}: unexpected architecture list"
    assert pkg.get("license"), f"{name}: license metadata is required"
    assert re.fullmatch(r"[0-9a-f]{64}", pkg.get("sha256", "")), (
        f"{name}: SHA-256 must be pinned"
    )
    assert pkg.get("source", "").startswith("https://"), f"{name}: HTTPS source required"

# OpenPGP verification has a real CLI engine as well as the GPGME library.
require_dependencies(recipe("system", "libassuan"), "run", {"libgpg-error"}, "libassuan")
require_dependencies(recipe("system", "libksba"), "run", {"libgpg-error"}, "libksba")
require_dependencies(recipe("system", "gnupg"), "run", {
    "libgpg-error", "libgcrypt", "libassuan", "libksba", "npth", "gnutls",
}, "gnupg")
require_dependencies(recipe("system", "gpgme"), "run", {
    "libgpg-error", "libassuan", "gnupg",
}, "gpgme")

# AppStream's XML/YAML metadata stack and OSTree's signature/network backends
# must be explicit rather than depending on incidental build-root packages.
require_dependencies(recipe("gui", "libxmlb"), "run", {"glib", "xz", "zstd"}, "libxmlb")
require_dependencies(recipe("gui", "appstream"), "run", {
    "glib", "curl", "libxml2", "libfyaml", "libxmlb", "zstd",
}, "appstream")
ostree = recipe("gui", "ostree")
require_dependencies(ostree, "build", {"libsoup3", "gpgme", "libarchive", "e2fsprogs"}, "ostree")
assert "--with-soup3" in ostree["build"]["configure"]
assert "--with-gpgme" in ostree["build"]["configure"]
assert "--without-libsystemd" in ostree["build"]["configure"]
assert "--without-curl" in ostree["build"]["configure"]

# Flatpak must use existing Faseela sandbox/security components and its
# D-Bus/Polkit system helper, while compiling without systemd.
flatpak = recipe("gui", "flatpak")
flatpak_run = set(flatpak["depends"]["run"])
assert {
    "ostree", "appstream", "gpgme", "gnupg", "bubblewrap",
    "xdg-dbus-proxy", "fuse3", "libseccomp", "polkit", "dbus-system",
} <= flatpak_run
configure = flatpak["build"]["configure"]
for option in (
    "-D systemd=disabled",
    "-D auto_sideloading=false",
    "-D system_helper=enabled",
    "-D system_bubblewrap=/usr/bin/bwrap",
    "-D system_dbus_proxy=/usr/bin/xdg-dbus-proxy",
    "-D system_fusermount=/usr/bin/fusermount3",
    "-D seccomp=enabled",
    "-D wayland_security_context=disabled",
):
    assert option in configure, f"flatpak: missing configure option {option}"
assert "no-systemd" in configure
prepare = flatpak["build"]["prepare"]
assert "SystemdService=" in prepare and "sed -i" in prepare
install = flatpak["build"]["install"]
assert "org.freedesktop.Flatpak.SystemHelper.service" in install
assert "! grep -q '^SystemdService='" in install
assert "no-systemd" in install
assert "/usr/share/flatpak/remotes.d/flathub.flatpakrepo" in install
assert "Url=https://dl.flathub.org/repo/" in install
assert "GPGKey=" in install
assert "/usr/share/flatpak/remotes.d/flathub.flatpakrepo" in install
assert "flatpak" in flatpak["hooks"]["post_install"]
cosmic_readme = (ROOT / "recipes" / "cosmic" / "README.md").read_text(encoding="utf-8")
assert "flatpak remote-add --user --if-not-exists flathub" in cosmic_readme
assert "flatpak --user remotes --show-details" in cosmic_readme
assert "ensure-system-account group flatpak" in flatpak["hooks"]["post_install"]
assert "ensure-system-account user flatpak flatpak" in flatpak["hooks"]["post_install"]
assert "/var/lib/flatpak" in flatpak["hooks"]["post_install"]
assert "/etc/runit/runsvdir/default" not in install
assert "/etc/sv/" not in install

# The COSMIC Store feature is enabled explicitly. PackageKit and systemd
# scope remain disabled; the native user/system Flatpak backends come from
# the same upstream "flatpak" feature.
# COSMIC OSD is the desktop's authentication agent. Its helper path is
# different from the upstream default and must match Faseela's Polkit package.
osd = recipe("cosmic", "cosmic-osd")
assert osd["package"]["rel"] >= 3
assert "polkit" in osd["depends"]["run"]
assert "POLKIT_AGENT_HELPER_1=/usr/lib/polkit-1/polkit-agent-helper-1" in osd["build"]["compile"]

store = recipe("cosmic", "cosmic-store")
store_compile = store["build"]["compile"]
assert store["package"]["rel"] >= 4
assert "flatpak" in store_compile.split("--features", 1)[1].split("--bin", 1)[0].split(",")
assert "flatpak" in store["depends"]["run"]
assert "packagekit" not in store_compile
assert "desktop-systemd-scope" not in store_compile
assert "FuturesUnordered::<tokio::sync::oneshot::Receiver" in store_compile

# The desktop and image still use the established COSMIC group/flavor path.
groups = tomllib.loads((ROOT / "groups.toml").read_text(encoding="utf-8"))
cosmic_group = next(g for g in groups["group"] if g["id"] == "cosmic")
assert "cosmic-store" in cosmic_group["default"]
assert cosmic_group["mandatory"] == ["cosmic-desktop"]

flavors = tomllib.loads((ROOT / "flavors.toml").read_text(encoding="utf-8"))
cosmic_flavor = flavors["flavor"]["iso-cosmic"]
assert "@cosmic" in cosmic_flavor["include"]

print(
    f"test-flatpak-integration: {len(REQUIRED)} recipes, Flathub static remote, "
    "D-Bus helper, and COSMIC Store backend checks passed"
)
