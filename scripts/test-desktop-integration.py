#!/usr/bin/env python3
"""Validate Faseela's desktop integration packages and the D-Bus session path."""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def recipe(category: str, name: str) -> dict:
    path = ROOT / "recipes" / category / name / "recipe.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def require_deps(category: str, name: str, kind: str, required: set[str]) -> None:
    actual = set(recipe(category, name).get("depends", {}).get(kind, []))
    missing = required - actual
    assert not missing, f"{name} is missing {kind} dependencies: {sorted(missing)}"


session = recipe("gui", "gui-session")
assert session["package"]["rel"] >= 13, "Bump gui-session rel for desktop integration changes"
require_deps("gui", "gui-session", "run", {"xdg-utils", "gnome-keyring", "rsync", "xdg-desktop-portal-gtk"})

install_script = session["build"]["install"]
assert "%{pkgdir}/etc/udev/rules.d" in install_script
assert (chr(36) + "{pkgdir}") not in install_script, (
    "Use the recipe %{pkgdir} macro; an unset shell variable breaks package staging"
)
assert "exec dbus-run-session -- sh -c" in install_script, (
    "Sway must run inside a user D-Bus session for Secret Service activation"
)
assert session["package"]["rel"] >= 15, "Bump gui-session rel for XDG portal integration"
assert "procps-ng" in session["depends"]["run"], "Audio session helper requires pgrep"
assert "faseela-audio-session" in install_script
assert "exec /usr/bin/faseela-audio-session" in install_script

assert "sway-portals.conf" in install_script
assert "default=gtk" in install_script
assert "dbus-update-activation-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE" in install_script

# The frontend must own org.freedesktop.portal.Desktop, and the GTK backend
# must provide the general interfaces without depending on systemd.
portal = recipe("gui", "xdg-desktop-portal")
assert portal["package"]["version"] == "1.18.4"
assert portal["package"]["rel"] >= 2, "Bump portal rel for the PipeWire 1.6 API compatibility patch"
assert {"fuse3", "json-glib", "gdk-pixbuf", "pipewire", "bubblewrap"} <= set(portal["depends"]["run"])
assert "bubblewrap" in portal["depends"]["build"], "sandboxed image validation needs bwrap at build time"
assert "-D systemd=disabled" in portal["build"]["configure"]
assert "-D sandboxed-image-validation=true" in portal["build"]["configure"]
assert "pw_registry_add_listener ((struct pw_registry*)remote->registry," in portal["build"]["configure"], (
    "xdg-desktop-portal 1.18.4 must cast its registry proxy for PipeWire 1.6 headers"
)

# GTK's FileChooser backend reads GNOME desktop lockdown settings at startup.
# Keep the shared schemas in the runtime closure and recompile them after install.
schemas = recipe("gui", "gsettings-desktop-schemas")
assert schemas["package"]["version"] == "46.1"
assert re.fullmatch(r"[0-9a-f]{64}", schemas["package"]["sha256"])
assert "glib" in schemas["depends"]["run"]
assert "glib-compile-schemas /usr/share/glib-2.0/schemas" in schemas["hooks"]["post_install"]
assert 's:"(/system):"/org/gnome\\\\1:g' in schemas["build"]["configure"]

gtk_portal = recipe("gui", "xdg-desktop-portal-gtk")
assert gtk_portal["package"]["version"] == "1.15.3"
assert gtk_portal["package"]["rel"] >= 2, "Bump GTK portal rel when fixing missing GSettings runtime schemas"
assert {"gtk3", "xdg-desktop-portal", "gsettings-desktop-schemas"} <= set(gtk_portal["depends"]["run"])
assert "-D wallpaper=disabled" in gtk_portal["build"]["configure"]
assert "-D settings=disabled" in gtk_portal["build"]["configure"]

fuse = recipe("gui", "fuse3")
assert fuse["package"]["rel"] >= 2, "Bump fuse3 rel when changing sandbox-safe staging"
fuse_configure = fuse["build"]["configure"]
assert "install_helper.sh" in fuse_configure and "mknod" in fuse_configure, (
    "fuse3 must not try to create /dev/fuse inside the unprivileged package staging root"
)
assert "-D useroot=true" in fuse_configure, (
    "Keep fusermount3 ownership/mode and udev rule installation enabled"
)

for name in ("fuse3", "json-glib", "bubblewrap"):
    assert recipe("gui", name)["package"]["sha256"] == "0" * 64 or re.fullmatch(
        r"[0-9a-f]{64}", recipe("gui", name)["package"]["sha256"]
    ), f"{name} must have a SHA-256 field"
assert "pipewire-pulse" in install_script
assert "pulse/native" in install_script
assert "pgrep -u" in install_script
assert "wireplumber" in install_script
assert "exec /usr/bin/faseela-audio-session" in install_script

# NetworkManager's dispatcher is D-Bus-activated, not a persistent runit
# service. The package install step must validate all three staged artifacts
# and ensure the activation descriptor points at the installed executable.
nm = recipe("gui", "network-manager")
assert nm["package"]["rel"] >= 4, "Bump NetworkManager rel for dispatcher packaging checks"
assert "dbus-system" in nm["depends"]["run"]
nm_install = nm["build"]["install"]
for required in (
    "usr/libexec/nm-dispatcher",
    "usr/share/dbus-1/system-services/org.freedesktop.nm_dispatcher.service",
    "usr/share/dbus-1/system.d/nm-dispatcher.conf",
    "test -x \"$NM_DISPATCHER\"",
    "test -s \"$NM_DISPATCHER_SERVICE\"",
    "Name=org.freedesktop.nm_dispatcher",
    "Exec=/usr/libexec/nm-dispatcher",
    "User=root",
    "test -s \"$NM_DISPATCHER_POLICY\"",
):
    assert required in nm_install, f"NetworkManager install validation is missing: {required}"
assert "nm-dispatcher" not in nm.get("depends", {}).get("run", []), (
    "nm-dispatcher is part of NetworkManager and must not be modeled as a separate service package"
)

xdg = recipe("gui", "xdg-utils")
assert xdg["package"]["version"] == "1.2.1"
assert re.fullmatch(r"[0-9a-f]{64}", xdg["package"]["sha256"])
assert "./configure" in xdg["build"]["configure"]
assert "make DESTDIR=%{pkgdir} install" in xdg["build"]["install"]
assert {"bash", "dbus", "file", "glib"} <= set(xdg["depends"]["run"])

rsync = recipe("extra", "rsync")
assert rsync["package"]["name"] == "rsync"

gkr = recipe("gui", "gnome-keyring")
assert gkr["package"]["version"] == "51.1"
assert re.fullmatch(r"[0-9a-f]{64}", gkr["package"]["sha256"])
assert {"dbus", "glib", "gcr", "libgcrypt", "p11-kit"} <= set(gkr["depends"]["run"])
gkr_configure = gkr["build"]["configure"]
for flag in ("-Dsystemd=disabled", "-Dpam=false", "-Dssh-agent=false"):
    assert flag in gkr_configure, f"gnome-keyring must not require systemd/PAM/SSH agent: {flag}"

gcr = recipe("gui", "gcr")
assert {"glib", "libgcrypt", "p11-kit"} <= set(gcr["depends"]["run"])
assert "-Dsystemd=disabled" in gcr["build"]["configure"]
assert gcr["package"]["rel"] >= 2, "Bump GCR rel for the optional ssh-agent Meson fix"
gcr_configure = gcr["build"]["configure"]
assert "-Dssh_agent=false" in gcr_configure
assert "ssh_add_path = ''" in gcr_configure
assert "ssh_agent_path = ''" in gcr_configure
assert "find_program('ssh-add'" in gcr_configure

p11 = recipe("system", "p11-kit")
assert p11["package"]["version"] == "0.26.5"
assert "-Dsystemd=disabled" in p11["build"]["configure"]
assert "-Dtrust_module=disabled" in p11["build"]["configure"]
assert "libffi" in p11["depends"]["run"]

gcrypt = recipe("system", "libgcrypt")
assert "libgpg-error" in gcrypt["depends"]["run"]
assert re.fullmatch(r"[0-9a-f]{64}", gcrypt["package"]["sha256"])
libgpg = recipe("system", "libgpg-error")
assert re.fullmatch(r"[0-9a-f]{64}", libgpg["package"]["sha256"])

readme = (ROOT / "recipes" / "gui" / "README.md").read_text(encoding="utf-8")
assert "org.freedesktop.secrets.service" in readme
assert "does not automatically unlock" in readme
assert "no D-Bus" not in readme


kernel = recipe("boot", "linux")
assert kernel["package"]["rel"] >= 21, "Bump linux rel when changing portal sandbox requirements"
kernel_config = kernel["build"]["configure"]
assert "--enable NAMESPACES --enable USER_NS --enable FUSE_FS" in kernel_config
first_config_line = next(line for line in kernel_config.splitlines() if "--enable FW_LOADER" in line)
assert first_config_line.endswith("\\\\") is False and first_config_line.endswith("\\"), (
    "Kernel scripts/config command must end with exactly one shell continuation backslash"
)
for option in ("CONFIG_NAMESPACES", "CONFIG_USER_NS", "CONFIG_FUSE_FS"):
    assert f"require_config {option} y" in kernel_config

print("DESKTOP INTEGRATION VALIDATION PASSED")
