#!/usr/bin/env python3
"""Static guardrails for the documented XFCE runtime smoke-test plan."""

from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "xfce-smoke-tests.md"


def recipe(category: str, name: str) -> dict:
    path = ROOT / "recipes" / category / name / "recipe.toml"
    if not path.is_file():
        raise AssertionError(f"{category}/{name}: recipe file is missing: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def require_deps(category: str, name: str, kind: str, required: set[str]) -> dict:
    item = recipe(category, name)
    actual = set(item.get("depends", {}).get(kind, []))
    missing = required - actual
    assert not missing, (
        f"{category}/{name}: missing {kind} dependencies: {sorted(missing)}"
    )
    return item


def require_text(category: str, name: str, section: str, snippets: set[str]) -> str:
    item = recipe(category, name)
    text = item.get(section, {})
    if isinstance(text, dict):
        text = "\n".join(str(value) for value in text.values())
    missing = sorted(value for value in snippets if value not in text)
    assert not missing, (
        f"{category}/{name}: missing {section} integration entries: {missing}"
    )
    return text


def extract_heredoc(text: str, destination: str, marker: str) -> str:
    pattern = (
        r"cat > %{pkgdir}/"
        + re.escape(destination)
        + r" <<'"
        + re.escape(marker)
        + r"'\n(.*?)\n"
        + re.escape(marker)
    )
    match = re.search(pattern, text, re.DOTALL)
    assert match, f"{destination}: expected {marker} here-document is missing"
    return match.group(1) + "\n"


def check_shell(label: str, script: str) -> None:
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, (
        f"{label}: invalid shell syntax: {result.stderr.strip()}"
    )


# The test plan must distinguish static/build checks from actual VM execution.
assert DOC.is_file(), "docs/xfce-smoke-tests.md: repeatable runtime checklist is missing"
doc = DOC.read_text(encoding="utf-8")
for heading in (
    "## Test layers",
    "## A. Clean-install scenario",
    "### A3. Perform the controlled LightDM login test",
    "### A5. Exercise session services and desktop features",
    "### A6. Check systemd supervision after desktop use",
    "## B. Upgrade scenario",
    "## C. Failure report",
    "## D. Pull-request CI checks",
):
    assert heading in doc, f"docs/xfce-smoke-tests.md: missing section: {heading}"
for required in (
    "disposable VM",
    "systemd",
    "LightDM",
    "systemd-logind",
    "Polkit",
    "UDisks2",
    "PipeWire",
    "notifications",
    "Lock screen",
    "unix_chkpwd",
    "4755",
    "Shutdown and reboot",
    "portals",
    "clean-install",
    "upgrade",
):
    assert required.lower() in doc.lower(), (
        f"docs/xfce-smoke-tests.md: checklist does not cover {required}"
    )
assert "evidence that a graphical login" in doc and "not** evidence" in doc, (
    "The checklist must not conflate CI/package success with runtime validation"
)

# Core XFCE closure: every applet/service exercised by the checklist is part
# of the meta-package runtime dependency graph.
xfce = require_deps("xfce", "xfce-session", "run", {
    "xfce4-session", "xfce4-panel", "xfce4-notifyd", "xfce4-screensaver",
    "xfce4-clipman-plugin", "network-manager-applet",
    "xfce-polkit", "audio-session", "dbus-system",
    "systemd", "polkit", "network-manager", "gvfs",
    "udisks2", "thunar", "thunar-volman", "upower",
    "xdg-desktop-portal", "xdg-desktop-portal-gtk",
})
xfce_install = xfce["build"]["install"]
assert xfce["package"]["rel"] >= 14
assert "xfce-portals.conf" not in xfce_install, (
    "The XFCE portal configuration must be owned only by xfce4-session"
)
audio_desktop = extract_heredoc(
    xfce_install,
    "etc/xdg/autostart/faseela-audio-session.desktop",
    "DESKTOP",
)
thunar_desktop = extract_heredoc(
    xfce_install,
    "etc/xdg/autostart/thunar-daemon.desktop",
    "THUNAR",
)
for label, desktop, exec_line in (
    ("Faseela audio autostart", audio_desktop, "Exec=/usr/bin/faseela-audio-session"),
    ("Thunar volume host autostart", thunar_desktop, "Exec=thunar --daemon"),
):
    assert "[Desktop Entry]" in desktop, f"{label}: missing Desktop Entry group"
    assert "Type=Application" in desktop, f"{label}: wrong desktop entry type"
    assert exec_line in desktop, f"{label}: wrong Exec command"
    assert "OnlyShowIn=XFCE;" in desktop, f"{label}: not scoped to XFCE"

# The Xsession file must point at the Faseela wrapper, which creates a
# user-owned XDG_RUNTIME_DIR before starting the session.
xfce4_session = recipe("xfce", "xfce4-session")
assert xfce4_session["package"]["rel"] >= 9, (
    "Bump xfce4-session rel when changing the XFCE D-Bus activation environment"
)
require_deps("xfce", "xfce4-session", "run", {"dbus", "xfce4-panel"})
xfce4_install = xfce4_session["build"]["install"]
portal_config = extract_heredoc(
    xfce4_install,
    "usr/share/xdg-desktop-portal/xfce-portals.conf",
    "PORTALS",
)
for required in (
    "default=gtk",
    "org.freedesktop.impl.portal.FileChooser=gtk",
    "org.freedesktop.impl.portal.Secret=gnome-keyring",
    "org.freedesktop.impl.portal.Screenshot=none",
    "org.freedesktop.impl.portal.ScreenCast=none",
    "org.freedesktop.impl.portal.RemoteDesktop=none",
):
    assert required in portal_config, (
        f"XFCE portal configuration is missing: {required}"
    )
for required in (
    "usr/share/xsessions/xfce.desktop",
    "Exec=dbus-run-session -- /usr/bin/faseela-start-xfce4",
    "XDG_SESSION_TYPE=x11",
    "XDG_CURRENT_DESKTOP=XFCE",
):
    assert required in xfce4_install, (
        f"xfce/xfce4-session: missing XFCE session integration: {required}"
    )
assert "dbus-update-activation-environment DISPLAY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE XDG_RUNTIME_DIR" in xfce4_install
assert "dbus-update-activation-environment XAUTHORITY" in xfce4_install
check_shell("xfce/xfce4-session install", xfce4_install)

# The native locker must be part of the standard XFCE closure and use
# Faseela's PAM + systemd-logind stack. It exposes the D-Bus name that libxfce4ui
# queries when the XFCE session manager requests a lock.
screensaver = require_deps("xfce", "xfce4-screensaver", "run", {
    "dbus", "dbus-glib", "systemd", "gtk3", "libXScrnSaver",
    "libwnck3", "libxklavier", "libxfce4ui", "linux-pam", "procps-ng",
    "python", "xfconf",
})
screensaver_build = require_deps("xfce", "xfce4-screensaver", "build", {
    "dbus", "dbus-glib", "systemd", "linux-pam", "meson", "ninja", "pkgconf",
})
screensaver_configure = screensaver["build"]["configure"]
for option in (
    "-D x11=enabled",
    "-D wayland=disabled",
    "-D authentication-scheme=pam",
    "-D session-manager=systemd",
):
    assert option in screensaver_configure, (
        f"xfce/xfce4-screensaver: missing configure option: {option}"
    )
screensaver_install = screensaver["build"]["install"]
assert "etc/pam.d/xfce4-screensaver" in screensaver_install
assert "auth required pam_unix.so" in screensaver_install, (
    "xfce/xfce4-screensaver: unlock PAM stack must use Faseela's local-account module"
)

# Nawa's secure archive extraction drops SUID/SGID bits by default. linux-pam
# must restore the one trusted helper that PAM needs for shadow authentication.
linux_pam = require_deps("system", "linux-pam", "run", {"coreutils", "libxcrypt"})
assert linux_pam["package"]["rel"] >= 2, (
    "Bump linux-pam rel when repairing unix_chkpwd's installed SUID mode"
)
linux_pam_install = linux_pam["build"]["install"]
for required in (
    'helper="%{pkgdir}/usr/sbin/unix_chkpwd"',
    'chmod 4755 "$helper"',
    'test -u "$helper"',
):
    assert required in linux_pam_install, (
        f"system/linux-pam: staged unix_chkpwd permissions missing: {required}"
    )
check_shell("system/linux-pam install", linux_pam_install)

linux_pam_hook = linux_pam.get("hooks", {}).get("post_install", "")
for required in (
    "helper=/usr/sbin/unix_chkpwd",
    'chown root:root "$helper"',
    'chmod 4755 "$helper"',
    "stat -c '%u:%g:%a' ",
):
    assert required in linux_pam_hook, (
        f"system/linux-pam: post-install must restore and verify unix_chkpwd: {required}"
    )
check_shell("system/linux-pam post_install", linux_pam_hook)

# LightDM is deliberately shipped as a manual-enable systemd unit until its
# installed-system login path has been tested. Validate PAM and session wiring.
lightdm = require_deps("xfce", "lightdm", "run", {
    "dbus-system", "systemd", "xorg-server", "linux-pam",
})
lightdm_install = lightdm["build"]["install"]
lightdm_unit = extract_heredoc(
    lightdm_install, "usr/lib/systemd/system/lightdm.service", "EOF"
)
for required in ("[Service]", "ExecStart=", "Conflicts=getty@tty7.service", "Alias=display-manager.service"):
    assert required in lightdm_unit, f"xfce/lightdm: unit is missing: {required}"
for required in (
    "etc/pam.d/lightdm",
    "etc/pam.d/lightdm-greeter",
    "etc/pam.d/lightdm-autologin",
    "pam_systemd.so class=user type=x11 desktop=xfce",
    "pam_systemd.so class=greeter type=x11 desktop=lightdm-greeter",
    "etc/lightdm/lightdm.conf.d/50-faseela-xfce.conf",
    "user-session=xfce",
):
    assert required in lightdm_install, (
        f"xfce/lightdm: missing login/PAM/service integration: {required}"
    )
assert "systemctl enable lightdm" not in lightdm_install and "WantedBy=" not in lightdm_unit, (
    "xfce/lightdm: must remain manual-enable until the runtime login test is passed"
)
assert "pam_elogind" not in lightdm_install, (
    "xfce/lightdm: systemd systems must use pam_systemd, not pam_elogind"
)

# systemd owns the persistent system services. Validate each unit file and its
# preset, with package-specific failures.
dbus = require_deps("gui", "dbus-system", "run", {"dbus"})
dbus_install = dbus["build"]["install"]
dbus_unit = extract_heredoc(dbus_install, "usr/lib/systemd/system/dbus.service", "EOF")
for required in (
    "ExecStart=/usr/bin/dbus-daemon --system --nofork --nopidfile",
    "WantedBy=multi-user.target",
):
    assert required in dbus_unit, f"gui/dbus-system: missing unit entry: {required}"

polkit = require_deps("gui", "polkit", "run", {"dbus-system", "systemd"})
polkit_install = polkit["build"]["install"]
polkit_unit = extract_heredoc(polkit_install, "usr/lib/systemd/system/polkit.service", "EOF")
assert "After=dbus.service" in polkit_unit, "gui/polkit: polkit.service must start after D-Bus"
assert "enable polkit.service" in polkit_install, (
    "gui/polkit: polkit.service must be enabled through a preset"
)

nm = require_deps("gui", "network-manager", "run", {"dbus-system", "polkit"})
nm_install = nm["build"]["install"]
nm_unit = extract_heredoc(nm_install, "usr/lib/systemd/system/NetworkManager.service", "EOF")
assert "Conflicts=systemd-networkd.service" in nm_unit, (
    "gui/network-manager: NetworkManager and systemd-networkd must not run together"
)
assert "enable NetworkManager.service" in nm_install, (
    "gui/network-manager: NetworkManager must be enabled through a preset"
)

# D-Bus-activated system daemons must not get duplicate systemd units.
udisks = require_deps("gui", "udisks2", "run", {"dbus-system", "polkit"})
udisks_install = udisks["build"]["install"]
for required in (
    "org.freedesktop.UDisks2.service",
    "Exec=/usr/libexec/udisks2/udisksd",
    "sed -i '/^SystemdService=/d'",
):
    assert required in udisks_install, f"gui/udisks2: missing D-Bus activation setup: {required}"

upower = require_deps("gui", "upower", "run", {"dbus-system", "polkit"})
upower_install = upower["build"]["install"]
for required in (
    "org.freedesktop.UPower.service",
    "Exec=/usr/libexec/upowerd",
):
    assert required in upower_install, f"gui/upower: missing D-Bus activation setup: {required}"

# Per-user audio belongs to the XFCE session, not a system service.
audio = require_deps("gui", "audio-session", "run", {
    "pipewire", "wireplumber", "procps-ng", "coreutils"
})
audio_install = audio["build"]["install"]
for required in ("pipewire-pulse", "wireplumber", "pgrep -u", "*XFCE*) session_process=xfce4-session ;;"):
    assert required in audio_install, f"gui/audio-session: missing per-user audio integration: {required}"
assert "usr/lib/systemd/system" not in audio_install, (
    "gui/audio-session: PipeWire and WirePlumber must run per user, not as system services"
)

# Tray applet and notifications need to be installed into the XFCE graph and
# expose their expected runtime D-Bus/autostart dependencies.
applet = require_deps("gui", "network-manager-applet", "run", {
    "network-manager", "libnma", "libsecret", "dbus", "polkit"
})
applet_install = applet["build"]["install"]
assert "etc/xdg/autostart/nm-applet.desktop" in applet_install
assert "Exec=nm-applet" in applet_install
notifyd = require_deps("xfce", "xfce4-notifyd", "run", {"dbus", "libnotify"})
assert notifyd["package"]["name"] == "xfce4-notifyd"

# Clipboard applet is a panel plugin, not a standalone autostart daemon.
clipman = recipe("xfce", "xfce4-clipman-plugin")
assert "xfce4-clipman-plugin" in xfce["depends"]["run"], (
    "xfce/xfce-session: Clipman plugin is missing from the default desktop closure"
)
assert "xfce4-clipman-plugin" in clipman["package"]["name"]

# GVfs talks to UDisks2 through system D-Bus; it is not a system daemon.
gvfs = require_deps("xfce", "gvfs", "run", {
    "dbus", "udisks2", "libgudev", "fuse3", "gsettings-desktop-schemas"
})
assert "udisks2=true" in gvfs["build"]["configure"]
assert "gudev=true" in gvfs["build"]["configure"]

print("XFCE SMOKE-TEST CHECKLIST VALIDATION PASSED")
