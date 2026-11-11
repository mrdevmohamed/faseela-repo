#!/usr/bin/env python3
"""Validate Faseela's desktop integration packages and the D-Bus session path."""

from pathlib import Path
import re
import subprocess
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
require_deps("gui", "gui-session", "run", {"xdg-utils", "gnome-keyring", "upower", "rsync", "xdg-desktop-portal-gtk"})

install_script = session["build"]["install"]
assert "%{pkgdir}/etc/udev/rules.d" in install_script
assert (chr(36) + "{pkgdir}") not in install_script, (
    "Use the recipe %{pkgdir} macro; an unset shell variable breaks package staging"
)
assert "exec dbus-run-session -- sh -c" in install_script, (
    "Sway must run inside a user D-Bus session for Secret Service activation"
)
assert session["package"]["rel"] >= 15, "Bump gui-session rel for XDG portal integration"
require_deps("gui", "gui-session", "run", {"audio-session"})
assert "faseela-audio-session" in install_script
assert "exec /usr/bin/faseela-audio-session" in install_script

assert "sway-portals.conf" in install_script
assert "org.freedesktop.impl.portal.Secret=gnome-keyring" in install_script, (
    "Sway must route the Secret portal interface to the session GNOME Keyring backend"
)
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
audio_session = recipe("gui", "audio-session")
audio_install = audio_session["build"]["install"]
assert audio_session["package"]["rel"] >= 2, (
    "Bump audio-session rel when fixing desktop-session lifetime detection"
)
require_deps("gui", "audio-session", "run", {"pipewire", "wireplumber", "procps-ng", "coreutils"})
for required in ("pipewire-pulse", "pulse/native", "pgrep -u", "wireplumber"):
    assert required in audio_install, f"audio-session must manage: {required}"
assert 'case "${XDG_CURRENT_DESKTOP:-}" in' in audio_install
assert "*XFCE*) session_process=xfce4-session ;;" in audio_install, (
    "The audio helper must stay alive for an XFCE session, not look for Sway"
)
assert "*sway*|*Sway*) session_process=sway ;;" in audio_install
assert "unsupported desktop session" in audio_install
assert "exec /usr/bin/faseela-audio-session" in install_script

# XFCE must start the same audio supervisor and establish a private runtime dir
# before the desktop is launched from LightDM (which has no pam_systemd).
xfce_session = recipe("xfce", "xfce-session")
require_deps("xfce", "xfce-session", "run", {"audio-session"})
xfce_install = xfce_session["build"]["install"]
assert "OnlyShowIn=XFCE;" in xfce_install
assert "Exec=/usr/bin/faseela-audio-sess" in xfce_install
xfce4_session = recipe("xfce", "xfce4-session")
assert xfce4_session["package"]["rel"] >= 6
xfce4_install = xfce4_session["build"]["install"]
assert "Exec=startxfce4" in xfce4_install
assert "/tmp/runtime-$uid" in xfce4_install
assert "chmod 700" in xfce4_install
assert "grep -Fqx 'Exec=startxfce4'" in xfce4_install
lightdm = recipe("xfce", "lightdm")
assert not re.search(
    r"^\s*(?:auth|account|password|session)\s+\S+\s+pam_systemd\.so",
    lightdm["build"]["install"],
    re.MULTILINE,
), "LightDM PAM must not load pam_systemd"

# Removable storage is integrated through system D-Bus -> UDisks2 -> GVfs.
libblockdev = recipe("gui", "libblockdev")
assert libblockdev["package"]["version"] == "3.5.0"
assert re.fullmatch(r"[0-9a-f]{64}", libblockdev["package"]["sha256"])
require_deps("gui", "libblockdev", "build", {
    "glib", "eudev", "kmod", "util-linux", "e2fsprogs",
    "libbytesize", "libnvme", "cryptsetup", "keyutils",
})
require_deps("gui", "libblockdev", "run", {
    "glib", "eudev", "kmod", "util-linux", "e2fsprogs",
    "libbytesize", "libnvme", "cryptsetup", "keyutils", "mdadm",
})
libblockdev_configure = libblockdev["build"]["configure"]
for flag in (
    "--with-part", "--with-fs", "--with-loop", "--with-swap",
    "--with-crypto", "--with-mdraid", "--with-nvme", "--without-escrow",
    "--without-lvm",
):
    assert flag in libblockdev_configure, (
        f"libblockdev must enable UDisks2's mandatory plugins and omit escrow/LVM: {flag}"
    )
for flag in (
    "--without-btrfs", "--without-dm", "--without-lvm", "--without-lvm_dbus",
    "--without-mpath", "--without-smart", "--without-smartmontools", "--without-tools",
):
    assert flag in libblockdev_configure, (
        f"libblockdev should keep this optional storage stack disabled: {flag}"
    )
assert "--without-swap" not in libblockdev_configure, (
    "UDisks2 requires libblockdev-swap for its daemon"
)
assert "--without-loop" not in libblockdev_configure, (
    "UDisks2 requires libblockdev-loop for its Loop interface"
)
assert "--without-mdraid" not in libblockdev_configure, (
    "UDisks2 2.11.2 requires libblockdev-mdraid"
)
assert "--without-nvme" not in libblockdev_configure, (
    "UDisks2 2.11.2 requires libblockdev-nvme"
)

libbytesize = recipe("gui", "libbytesize")
assert libbytesize["package"]["version"] == "2.12"
assert re.fullmatch(r"[0-9a-f]{64}", libbytesize["package"]["sha256"])
require_deps("gui", "libbytesize", "build", {"gettext", "pcre2", "python"})
require_deps("gui", "libbytesize", "run", {"pcre2"})

libnvme = recipe("gui", "libnvme")
assert libnvme["package"]["version"] == "1.16.2"
assert re.fullmatch(r"[0-9a-f]{64}", libnvme["package"]["sha256"])
require_deps("gui", "libnvme", "build", {"meson", "ninja", "pkgconf", "json-c"})
require_deps("gui", "libnvme", "run", {"json-c"})

keyutils = recipe("system", "keyutils")
assert keyutils["package"]["version"] == "1.6.3"
assert re.fullmatch(r"[0-9a-f]{64}", keyutils["package"]["sha256"])

udisks2 = recipe("gui", "udisks2")
assert udisks2["package"]["version"] == "2.11.2"
assert re.fullmatch(r"[0-9a-f]{64}", udisks2["package"]["sha256"])
require_deps("gui", "udisks2", "run", {"dbus-system", "polkit", "libblockdev", "libgudev"})
udisks_configure = udisks2["build"]["configure"]
for flag in (
    "--with-systemdsystemunitdir=no", "--with-tmpfilesdir=no",
    "--with-udevdir=/usr/lib/udev", "--disable-smart",
):
    assert flag in udisks_configure, (
        f"UDisks2 must use Faseela's non-systemd paths and avoid unavailable optional SMART: {flag}"
    )
udisks_install = udisks2["build"]["install"]
for required in (
    "org.freedesktop.UDisks2.service",
    "org.freedesktop.UDisks2.conf",
    "org.freedesktop.UDisks2.policy",
    "80-udisks2.rules",
    "Exec=/usr/libexec/udisks2/udisksd",
    "sed -i '/^SystemdService=/d'",
    "! grep -q '^SystemdService='",
):
    assert required in udisks_install, f"UDisks2 install must provide/validate: {required}"
assert "runit" not in udisks2["depends"]["run"], (
    "UDisks2 is activated by dbus-system and must not get a duplicate runit daemon"
)

gvfs = recipe("xfce", "gvfs")
assert gvfs["package"]["version"] == "1.56.3"
assert re.fullmatch(r"[0-9a-f]{64}", gvfs["package"]["sha256"])
require_deps("xfce", "gvfs", "run", {"dbus", "udisks2", "libgudev", "fuse3", "gsettings-desktop-schemas"})
gvfs_configure = gvfs["build"]["configure"]
for flag in ("-D udisks2=true", "-D gudev=true", "-D logind=false",
             "-D systemduserunitdir=no", "-D tmpfilesdir=no"):
    assert flag in gvfs_configure, f"GVfs must provide UDisks2 volume monitoring without systemd: {flag}"

thunar = recipe("xfce", "thunar")
require_deps("xfce", "thunar", "run", {"gvfs"})
thunar_volman = recipe("xfce", "thunar-volman")
require_deps("xfce", "thunar-volman", "run", {"thunar", "gvfs", "udisks2", "dbus"})
require_deps("xfce", "xfce-session", "run", {"thunar", "thunar-volman", "gvfs", "udisks2"})
assert thunar_volman["package"]["rel"] >= 3
xfce_install = xfce_session["build"]["install"]
for required in (
    "thunar-daemon.desktop",
    "Exec=thunar --daemon",
    "TryExec=thunar",
    "OnlyShowIn=XFCE;",
    "chmod 644 %{pkgdir}/etc/xdg/autostart/thunar-daemon.desktop",
):
    assert required in xfce_install, f"Xfce must autostart the Thunar volume-manager host: {required}"
xfce_group = next(group for group in tomllib.loads(
    (ROOT / "groups.toml").read_text(encoding="utf-8")
)["group"] if group["id"] == "xfce")
assert "thunar-volman" in xfce_group["default"]
assert "thunar-volman" not in xfce_group["optional"]

# Parse the actual shell snippets embedded in the affected recipes. This
# catches broken TOML multiline strings and shell quoting before package CI.
for category, package_name in (
    ("gui", "audio-session"),
    ("gui", "udisks2"),
    ("xfce", "xfce-session"),
    ("xfce", "xfce4-session"),
):
    recipe_install_script = recipe(category, package_name)["build"]["install"]
    result = subprocess.run(
        ["bash", "-n"],
        input=recipe_install_script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{package_name} install script has invalid shell syntax: {result.stderr}"
    )


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
# Waybar's tray is optional upstream; require the GTK3 D-Bus menu module so
# Meson cannot silently publish a bar without StatusNotifier support.
dbusmenu = recipe("gui", "libdbusmenu")
assert dbusmenu["package"]["version"] == "18.10.20180917"
assert dbusmenu["package"]["rel"] >= 3
assert re.fullmatch(r"[0-9a-f]{64}", dbusmenu["package"]["sha256"])
assert dbusmenu["package"]["source_dir"] == "libdbusmenu-%{version}~bzr492", (
    "Debian's repacked orig archive extracts under the bzr revision name without +repack1"
)
require_deps("gui", "libdbusmenu", "build", {
    "pkgconf", "glib", "gtk3", "autoconf", "automake", "libtool", "gettext",
})
require_deps("gui", "libdbusmenu", "run", {"glib", "gtk3"})
assert "autoreconf -fi" in dbusmenu["build"]["prepare"], (
    "The Debian orig archive omits generated configure; regenerate it before configure"
)
assert "IT_PROG_INTLTOOL" in dbusmenu["build"]["prepare"]
assert "AM_CONDITIONAL([ENABLE_GTK_DOC], [false])" in dbusmenu["build"]["prepare"], (
    "Keep the disabled gtk-doc conditional defined because tests/Makefile.am references it"
)
require_deps("gui", "waybar", "build", {"libdbusmenu"})
require_deps("gui", "waybar", "run", {"libdbusmenu"})
assert "-D dbusmenu-gtk=enabled" in waybar["build"]["configure"], (
    "Waybar must fail Meson configure when the GTK3 StatusNotifier dependency is missing"
)


# Telegram and other Qt tray clients look up org.kde.StatusNotifierWatcher.
# Waybar's tray module owns the name inside the already-running bar. Do not
# provide a D-Bus activation .service for the watcher: Exec=waybar would launch
# a second independent bar whenever the name was not owned yet.
assert '"tray"' in waybar["build"]["install"], "Waybar's packaged config must enable its tray module"
assert install_script.count("exec waybar") == 1, "Sway must start exactly one Waybar instance"
assert "org.kde.StatusNotifierWatcher.service" not in install_script, (
    "Do not D-Bus-activate Waybar: it can start a duplicate status bar"
)
assert "Exec=/usr/bin/waybar" not in install_script
assert session["package"]["rel"] >= 21, "Bump gui-session rel for single-instance Waybar startup"
assert session["package"]["rel"] >= 22, "Bump gui-session rel when changing Xwayland startup"
assert session["package"]["rel"] >= 27, (
    "Bump gui-session rel when transferring faseela-audio-session ownership"
)
assert "cat > %{pkgdir}/usr/bin/faseela-audio-session" not in install_script, (
    "gui-session must not own the helper now provided by audio-session"
)
assert "xwayland force" in install_script, (
    "Start Xwayland immediately so X11-only Qt applications can use the XCB platform"
)
assert "00-xwayland.conf" in install_script, (
    "gui-session must persist the Xwayland startup setting in the Sway config drop-ins"
)

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
xkbcomp = recipe("gui", "xkbcomp")
assert xkbcomp["package"]["version"] == "1.5.0"
assert re.fullmatch(r"[0-9a-f]{64}", xkbcomp["package"]["sha256"])
assert {"libX11", "libxkbfile"} <= set(xkbcomp["depends"]["run"]), (
    "xkbcomp must ship its X11 and XKB file library runtime dependencies"
)
assert "install" in xkbcomp["build"] and "DESTDIR=%{pkgdir}" in xkbcomp["build"]["install"]

xwayland = recipe("gui", "xwayland")
assert re.fullmatch(r"[0-9a-f]{64}", xwayland["package"]["sha256"])
for flag in ("-D xdmcp=false", "-D xdm-auth-1=false", "-D systemd_notify=false"):
    assert flag in xwayland["build"]["configure"], f"Xwayland must not need extra daemons: {flag}"
assert xwayland["package"]["rel"] >= 2, "Bump Xwayland rel when changing its XKB runtime"
assert {"xkbcomp", "xkeyboard-config"} <= set(xwayland["depends"]["run"]), (
    "Xwayland must install xkbcomp and the XKB rules/layout data it uses at startup"
)

assert session["package"]["rel"] >= 24, "Bump gui-session rel for Secret portal and UPower integration"
for required in (
    "mkdir -p /tmp/.X11-unix",
    "chown root:root /tmp/.X11-unix",
    "chmod 1777 /tmp/.X11-unix",
):
    assert required in session["hooks"]["post_install"], (
        f"gui-session must establish secure X11 socket directory ownership: {required}"
    )

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


gudev = recipe("gui", "libgudev")
assert gudev["package"]["version"] == "238"
assert re.fullmatch(r"[0-9a-f]{64}", gudev["package"]["sha256"])
assert gudev["package"]["sha256"] != "0" * 64, "libgudev source checksum must be pinned"
require_deps("gui", "libgudev", "build", {"meson", "ninja", "pkgconf", "glib", "eudev"})
require_deps("gui", "libgudev", "run", {"glib", "eudev"})
assert "-D gtk_doc=false" in gudev["build"]["configure"]

upower = recipe("gui", "upower")
assert upower["package"]["version"] == "1.91.5"
assert upower["package"]["rel"] >= 2, "Bump UPower rel when fixing build metadata"
assert upower["package"]["source_dir"] == "upower-v%{version}", (
    "UPower GitLab archives extract into upower-v<version>; configure must run from that source tree"
)
assert re.fullmatch(r"[0-9a-f]{64}", upower["package"]["sha256"])
require_deps("gui", "upower", "build", {
    "meson", "ninja", "pkgconf", "glib", "libgudev", "libusb", "polkit",
})
require_deps("gui", "upower", "run", {
    "dbus-system", "glib", "libgudev", "libusb", "polkit",
})
upower_configure = upower["build"]["configure"]
for flag in ("-D gtk-doc=false", "-D man=false", "-D systemdsystemunitdir=no",
             "-D udevrulesdir=/usr/lib/udev/rules.d"):
    assert flag in upower_configure, f"UPower must be built without systemd units: {flag}"
upower_install = upower["build"]["install"]
for required in (
    "usr/share/dbus-1/system-services/org.freedesktop.UPower.service",
    "usr/share/dbus-1/system.d/org.freedesktop.UPower.conf",
    "Name=org.freedesktop.UPower",
    "Exec=/usr/libexec/upowerd",
    "test -x",
):
    assert required in upower_install, f"UPower must ship system D-Bus activation: {required}"
assert "runit" not in upower.get("depends", {}).get("run", []), (
    "UPower is D-Bus-activated on demand; dbus-system, not a dedicated runit service, owns the bus"
)

libusb = recipe("extra", "libusb")
assert libusb["package"]["version"] == "1.0.30"
assert libusb["package"]["rel"] >= 2
assert libusb["package"]["sha256"] == "fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf"

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
for option in ("NAMESPACES", "USER_NS", "FUSE_FS"):
    assert f"--enable {option}" in kernel_config, f"kernel config no longer enables {option}"
first_config_line = next(line for line in kernel_config.splitlines() if "--enable FW_LOADER" in line)
assert first_config_line.endswith("\\\\") is False and first_config_line.endswith("\\"), (
    "Kernel scripts/config command must end with exactly one shell continuation backslash"
)
for option in ("CONFIG_NAMESPACES", "CONFIG_USER_NS", "CONFIG_FUSE_FS"):
    assert f"require_config {option} y" in kernel_config

print("DESKTOP INTEGRATION VALIDATION PASSED")
