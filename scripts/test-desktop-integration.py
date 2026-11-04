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
assert "default=gtk;wlr" in install_script, (
    "The portal frontend must prefer GTK for the general interfaces and fall "
    "back to the wlr backend for ScreenCast"
)
assert "dbus-update-activation-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE" in install_script

# The frontend must own org.freedesktop.portal.Desktop, and the GTK backend
# must provide the general interfaces without depending on systemd.
portal = recipe("gui", "xdg-desktop-portal")
assert portal["package"]["version"] == "1.18.4"
assert {"fuse3", "json-glib", "gdk-pixbuf", "pipewire", "bubblewrap"} <= set(portal["depends"]["run"])
assert "bubblewrap" in portal["depends"]["build"], "sandboxed image validation needs bwrap at build time"
assert "-D systemd=disabled" in portal["build"]["configure"]
assert "-D sandboxed-image-validation=true" in portal["build"]["configure"]

gtk_portal = recipe("gui", "xdg-desktop-portal-gtk")
assert gtk_portal["package"]["version"] == "1.15.3"
assert {"gtk3", "xdg-desktop-portal"} <= set(gtk_portal["depends"]["run"])
assert "-D wallpaper=disabled" in gtk_portal["build"]["configure"]
assert "-D settings=enabled" in gtk_portal["build"]["configure"], (
    "GTK portal must implement org.freedesktop.portal.Settings for Qt toolkits"
)
assert {"fontconfig", "gsettings-desktop-schemas"} <= set(gtk_portal["depends"]["build"])
assert {"fontconfig", "gsettings-desktop-schemas"} <= set(gtk_portal["depends"]["run"])

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

# --- desktop session packages added with the wlr portal, panel and fonts ----
# Every autostarted program must be a run dependency of the session package:
# the flavor installs only what the recipe graph pulls in.
require_deps("gui", "gui-session", "run", {
    "xdg-desktop-portal-wlr", "mako", "waybar", "xdg-user-dirs",
    "pavucontrol", "noto-fonts", "noto-fonts-arabic", "noto-naskh-arabic", "noto-color-emoji",
})
for program in ("exec mako", "exec waybar", "exec xdg-user-dirs-update"):
    assert program in install_script, f"gui-session must autostart: {program}"

# The ScreenCast backend: basu replaces libsystemd for sd-bus, inih parses
# its config, and the systemd user unit must not be installed.
portal_wlr = recipe("gui", "xdg-desktop-portal-wlr")
assert re.fullmatch(r"[0-9a-f]{64}", portal_wlr["package"]["sha256"])
require_deps("gui", "xdg-desktop-portal-wlr", "run", {"xdg-desktop-portal", "pipewire", "basu", "inih"})
for flag in ("-D sd-bus-provider=basu", "-D systemd=disabled"):
    assert flag in portal_wlr["build"]["configure"], (
        f"xdg-desktop-portal-wlr must build without systemd: {flag}"
    )

basu = recipe("gui", "basu")
assert re.fullmatch(r"[0-9a-f]{64}", basu["package"]["sha256"])
assert "-D audit=false" in basu["build"]["configure"], "basu must not require the audit library"

# The notification daemon and the status bar, both on basu's sd-bus.
mako = recipe("gui", "mako")
assert re.fullmatch(r"[0-9a-f]{64}", mako["package"]["sha256"])
assert "basu" in mako["depends"]["run"], "mako speaks D-Bus through basu's sd-bus"
assert "-D sd-bus-provider=basu" in mako["build"]["configure"]

waybar = recipe("gui", "waybar")
assert re.fullmatch(r"[0-9a-f]{64}", waybar["package"]["sha256"])
for flag in ("-D systemd=disabled", "-D man-pages=disabled", "-D logind=disabled"):
    assert flag in waybar["build"]["configure"], f"waybar must not need systemd: {flag}"
require_deps("gui", "waybar", "run", {"gtk-layer-shell", "fmt", "spdlog", "jsoncpp", "gtkmm"})

# Telegram and other Qt tray clients look up org.kde.StatusNotifierWatcher.
# Waybar's tray module normally owns it; the D-Bus service is the activation
# fallback when the bar has not yet started.
assert '"tray"' in waybar["build"]["install"], "Waybar's packaged config must enable its tray module"
assert "org.kde.StatusNotifierWatcher.service" in install_script
assert "Name=org.kde.StatusNotifierWatcher" in install_script
assert "Exec=/usr/bin/waybar" in install_script
assert session["package"]["rel"] >= 20, "Bump gui-session rel for StatusNotifierWatcher activation"

# --- regression coverage for package build failures seen in CI ------------
# These assertions cover build-time requirements, not just the final session
# dependency graph, so package selection cannot silently omit a required API.
basu = recipe("gui", "basu")
assert "gperf" in basu["depends"]["build"], "basu's Meson configure requires gperf"

deno = recipe("dev", "deno")
assert deno["package"]["source"].endswith(".zip")
assert "unzip" in deno["depends"]["build"]
assert "unzip " in deno["build"]["install"] and "install -Dm755 deno " in deno["build"]["install"]

libxkbfile = recipe("gui", "libxkbfile")
assert libxkbfile["build"]["configure"].startswith("meson setup "), (
    "libxkbfile 1.2.0 uses Meson; do not invoke the removed Autoconf configure script"
)
assert {"meson", "ninja"} <= set(libxkbfile["depends"]["build"])

xkbcommon = recipe("gui", "libxkbcommon")
assert "-D enable-xkbregistry=true" in xkbcommon["build"]["configure"]
require_deps("gui", "waybar", "build", {"libxkbcommon"})
require_deps("gui", "waybar", "run", {"libxkbcommon"})

libpulse = recipe("extra", "libpulse")
assert {"glib"} <= set(libpulse["depends"]["build"])
assert "glib" in libpulse["depends"]["run"]
assert "-D glib=enabled" in libpulse["build"]["configure"]

arabic = recipe("gui", "noto-fonts-arabic")
arabic_install = arabic["build"]["install"]
assert "curl " not in arabic_install and "wget " not in arabic_install, (
    "Arabic font installation must not fetch a second archive inside the offline sandbox"
)
assert "noto-naskh-arabic" in session["depends"]["run"], (
    "Noto Naskh Arabic must be installed through its own pinned recipe"
)

yt_dlp = recipe("extra", "yt-dlp")
yt_install = yt_dlp["build"]["install"]
assert "install -Dm755 yt-dlp" in yt_install
assert "curl " not in yt_install and "wget " not in yt_install, (
    "yt-dlp installation must not download its man page inside the offline sandbox"
)

# Fonts: the session ships Latin/Greek/Cyrillic, Arabic and color emoji, all
# under OFL, all hashed, all refreshing the fontconfig cache on install.
for name in ("noto-fonts", "noto-fonts-arabic", "noto-naskh-arabic", "noto-color-emoji"):
    fonts = recipe("gui", name)
    assert re.fullmatch(r"[0-9a-f]{64}", fonts["package"]["sha256"]), f"{name} sha256 must be pinned"
    assert fonts["package"]["license"] == ["OFL-1.1"]
    assert "fc-cache" in fonts.get("hooks", {}).get("post_install", "")
    assert "fontconfig" in fonts["depends"]["run"]
naskh = recipe("gui", "noto-naskh-arabic")
assert naskh["package"]["version"] == "2.021"
assert re.fullmatch(r"[0-9a-f]{64}", naskh["package"]["sha256"])
assert "NotoNaskhArabic/hinted/ttf/*.ttf" in naskh["build"]["install"]

# Xwayland: wlroots enables the feature and sway picks it up; the session
# inherits it through wlroots' run dependency.
wlroots = recipe("gui", "wlroots")
assert "-D xwayland=enabled" in wlroots["build"]["configure"], "wlroots must build Xwayland support"
assert "xwayland" in wlroots["depends"]["run"], "wlroots must run-depend on the Xwayland server"
sway = recipe("gui", "sway")
assert sway["package"]["rel"] >= 3, "Bump sway rel when wlroots gains Xwayland support"
xwayland = recipe("gui", "xwayland")
assert re.fullmatch(r"[0-9a-f]{64}", xwayland["package"]["sha256"])
for flag in ("-D xdmcp=false", "-D xdm-auth-1=false", "-D systemd_notify=false"):
    assert flag in xwayland["build"]["configure"], f"Xwayland must not need extra daemons: {flag}"

# pavucontrol mixes PipeWire's PulseAudio server on the gtkmm 3 stack.
pavucontrol = recipe("gui", "pavucontrol")
assert re.fullmatch(r"[0-9a-f]{64}", pavucontrol["package"]["sha256"])
require_deps("gui", "pavucontrol", "run", {"gtkmm", "libpulse"})
assert "pavucontrol.desktop" in pavucontrol["build"]["install"]

# xdg-user-dirs ships the update helper the session autostarts.
user_dirs = recipe("gui", "xdg-user-dirs")
assert re.fullmatch(r"[0-9a-f]{64}", user_dirs["package"]["sha256"])

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
