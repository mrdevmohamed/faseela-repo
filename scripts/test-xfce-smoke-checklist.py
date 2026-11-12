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
    "### A6. Check runit supervision after desktop use",
    "## B. Upgrade scenario",
    "## C. Failure report",
    "## D. Pull-request CI checks",
):
    assert heading in doc, f"docs/xfce-smoke-tests.md: missing section: {heading}"
for required in (
    "disposable VM",
    "runit",
    "LightDM",
    "elogind",
    "Polkit",
    "UDisks2",
    "PipeWire",
    "notifications",
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
    "xfce4-session", "xfce4-panel", "xfce4-notifyd",
    "xfce4-clipman-plugin", "network-manager-applet",
    "xfce-polkit", "audio-session", "dbus-system",
    "elogind", "polkit", "network-manager", "gvfs",
    "udisks2", "thunar", "thunar-volman", "upower",
})
xfce_install = xfce["build"]["install"]
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
require_deps("xfce", "xfce4-session", "run", {"dbus", "xfce4-panel"})
xfce4_install = xfce4_session["build"]["install"]
for required in (
    "usr/share/xsessions/xfce.desktop",
    "Exec=dbus-run-session -- /usr/bin/faseela-start-xfce4",
    "XDG_SESSION_TYPE=x11",
    "XDG_CURRENT_DESKTOP=XFCE",
):
    assert required in xfce4_install, (
        f"xfce/xfce4-session: missing XFCE session integration: {required}"
    )
check_shell("xfce/xfce4-session install", xfce4_install)

# LightDM is deliberately shipped as a manual-enable runit service until its
# installed-system login path has been tested. Validate PAM and session wiring.
lightdm = require_deps("xfce", "lightdm", "run", {
    "dbus-system", "elogind", "xorg-server", "linux-pam",
})
lightdm_install = lightdm["build"]["install"]
lightdm_run = extract_heredoc(
    lightdm_install, "etc/sv/lightdm/run", "RUN"
)
check_shell("xfce/lightdm runit service", lightdm_run)
for required in (
    "etc/pam.d/lightdm",
    "etc/pam.d/lightdm-greeter",
    "etc/pam.d/lightdm-autologin",
    "pam_elogind.so class=user type=x11 desktop=xfce",
    "pam_elogind.so class=greeter type=x11 desktop=lightdm-greeter",
    "etc/lightdm/lightdm.conf.d/50-faseela-xfce.conf",
    "user-session=xfce",
    "etc/sv/lightdm/run",
):
    assert required in lightdm_install, (
        f"xfce/lightdm: missing login/PAM/service integration: {required}"
    )
assert "ln -s /etc/sv/lightdm" not in lightdm_install, (
    "xfce/lightdm: must remain manual-enable until the runtime login test is passed"
)
assert "pam_systemd.so" not in lightdm_install, (
    "xfce/lightdm: runit systems must use pam_elogind, not pam_systemd"
)

# runit owns the persistent system services. Validate both service scripts
# and the explicit default runsvdir links, with package-specific failures.
dbus = require_deps("gui", "dbus-system", "run", {"dbus", "runit"})
dbus_install = dbus["build"]["install"]
dbus_run = extract_heredoc(dbus_install, "etc/sv/dbus/run", "RUN")
check_shell("gui/dbus-system runit service", dbus_run)
for required in (
    "etc/sv/dbus/run",
    "exec dbus-daemon --system --nofork --nopidfile",
    "ln -s /etc/sv/dbus %{pkgdir}/etc/runit/runsvdir/default/dbus",
):
    assert required in dbus_install, f"gui/dbus-system: missing runit entry: {required}"

elogind = require_deps("gui", "elogind", "run", {"dbus-system", "runit"})
elogind_install = elogind["build"]["install"]
for service, destination, marker in (
    ("elogind", "etc/sv/elogind/run", "RUN"),
    ("elogind-userdbd", "etc/sv/elogind-userdbd/run", "RUN"),
):
    run_script = extract_heredoc(elogind_install, destination, marker)
    check_shell(f"gui/elogind {service} runit service", run_script)
    assert f"/etc/runit/runsvdir/default/{service}" in elogind_install, (
        f"gui/elogind: {service} is missing its default runsvdir link"
    )

polkit = require_deps("gui", "polkit", "run", {"dbus-system", "elogind"})
polkit_install = polkit["build"]["install"]
polkit_run = extract_heredoc(polkit_install, "etc/sv/polkitd/run", "RUN")
check_shell("gui/polkitd runit service", polkit_run)
assert "ln -s /etc/sv/polkitd %{pkgdir}/etc/runit/runsvdir/default/polkitd" in polkit_install, (
    "gui/polkit: polkitd must be enabled through runit"
)

nm = require_deps("gui", "network-manager", "run", {"dbus-system", "polkit"})
nm_install = nm["build"]["install"]
nm_run = extract_heredoc(nm_install, "etc/sv/NetworkManager/run", "RUN")
check_shell("gui/NetworkManager runit service", nm_run)
assert "ln -s /etc/sv/NetworkManager %{pkgdir}/etc/runit/runsvdir/default/NetworkManager" in nm_install, (
    "gui/network-manager: NetworkManager must be enabled through runit"
)

# D-Bus-activated system daemons must not have duplicate runit service entries.
udisks = require_deps("gui", "udisks2", "run", {"dbus-system", "polkit"})
assert "runit" not in udisks["depends"]["run"], (
    "gui/udisks2: D-Bus-activated UDisks2 must not install a duplicate runit daemon"
)
udisks_install = udisks["build"]["install"]
for required in (
    "org.freedesktop.UDisks2.service",
    "Exec=/usr/libexec/udisks2/udisksd",
    "sed -i '/^SystemdService=/d'",
):
    assert required in udisks_install, f"gui/udisks2: missing D-Bus activation setup: {required}"

upower = require_deps("gui", "upower", "run", {"dbus-system", "polkit"})
assert "runit" not in upower["depends"]["run"], (
    "gui/upower: D-Bus-activated UPower must not install a duplicate runit daemon"
)
upower_install = upower["build"]["install"]
for required in (
    "org.freedesktop.UPower.service",
    "Exec=/usr/libexec/upowerd",
):
    assert required in upower_install, f"gui/upower: missing D-Bus activation setup: {required}"

# Per-user audio belongs to the XFCE session, not a system runit service.
audio = require_deps("gui", "audio-session", "run", {
    "pipewire", "wireplumber", "procps-ng", "coreutils"
})
audio_install = audio["build"]["install"]
for required in ("pipewire-pulse", "wireplumber", "pgrep -u", "*XFCE*) session_process=xfce4-session ;;"):
    assert required in audio_install, f"gui/audio-session: missing per-user audio integration: {required}"
assert "etc/sv/" not in audio_install, (
    "gui/audio-session: PipeWire and WirePlumber must run per user, not as system runit services"
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

# GVfs talks to UDisks2 through system D-Bus; it is not a runit daemon.
gvfs = require_deps("xfce", "gvfs", "run", {
    "dbus", "udisks2", "libgudev", "fuse3", "gsettings-desktop-schemas"
})
assert "udisks2=true" in gvfs["build"]["configure"]
assert "gudev=true" in gvfs["build"]["configure"]

print("XFCE SMOKE-TEST CHECKLIST VALIDATION PASSED")
