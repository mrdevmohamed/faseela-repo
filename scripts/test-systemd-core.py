#!/usr/bin/env python3
"""Regression checks for the staged systemd core migration."""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def recipe(category: str, name: str) -> dict:
    path = ROOT / "recipes" / category / name / "recipe.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    assert condition, message


systemd = recipe("system", "systemd")
systemd_pkg = systemd["package"]
require(systemd_pkg["name"] == "systemd", "system/systemd package name changed")
require(systemd_pkg["version"] == "261.5", "Review the pinned systemd version and update this test")
require(systemd_pkg["arch"] == ["x86_64"], "systemd must be restricted to the supported architecture")
require(
    re.fullmatch(r"[0-9a-f]{64}", systemd_pkg["sha256"]) is not None,
    "systemd must carry a SHA-256 field",
)

obsolete = {
    "runit", "runit-services", "eudev", "elogind",
    "sysklogd", "dhcpcd", "chrony", "cronie",
}
for kind in ("build", "run"):
    dependencies = set(systemd.get("depends", {}).get(kind, []))
    require(
        not dependencies & obsolete,
        f"systemd {kind} dependencies still contain replaced packages: {sorted(dependencies & obsolete)}",
    )

configure = systemd["build"]["configure"]
for marker in (
    "meson.options",
    'required = ["pam", "kmod", "seccomp", "logind", "networkd", "resolve", "timesyncd"]',
    "Path(\".faseela-meson-args\")",
    "meson setup build",
    "$(cat .faseela-meson-args)",
):
    require(marker in configure, f"systemd configure phase is missing: {marker}")

systemd_install = systemd["build"]["install"]
for path in (
    "usr/lib/systemd/systemd",
    "usr/lib/systemd/systemd-udevd",
    "usr/lib/systemd/systemd-journald",
    "usr/lib/systemd/systemd-logind",
    "usr/lib/systemd/systemd-networkd",
    "usr/lib/systemd/systemd-resolved",
    "usr/lib/systemd/systemd-timesyncd",
    "usr/bin/systemctl",
    "usr/bin/journalctl",
    "usr/bin/loginctl",
    "usr/bin/udevadm",
):
    require(path in systemd_install, f"systemd install phase does not verify {path}")
require(
    "ln -sf ../lib/systemd/systemd %{pkgdir}/usr/bin/init" in systemd_install,
    "systemd must provide the merged-/usr PID 1 entry point",
)

units = recipe("system", "systemd-units")
units_run = set(units["depends"]["run"])
require(
    {"systemd", "linux-pam", "dbus-system"} <= units_run,
    "systemd-units must depend on systemd, Linux-PAM and system D-Bus",
)
require(
    not units_run & obsolete,
    f"systemd-units still depends on replaced packages: {sorted(units_run & obsolete)}",
)
units_install = units["build"]["install"]
for marker in (
    "80-faseela.preset",
    "enable systemd-networkd.service",
    "enable systemd-resolved.service",
    "enable systemd-timesyncd.service",
    "80-faseela-wired.network",
    "80-faseela-wireless.network",
    "L+ /etc/resolv.conf",
    "d /var/log/journal",
    "session   optional pam_systemd.so",
    "sshd.service",
):
    require(marker in units_install, f"systemd-units is missing core integration: {marker}")
require("pam_elogind.so" not in units_install, "systemd-units must use pam_systemd, not pam_elogind")
require("systemctl preset" in units.get("hooks", {}).get("post_install", ""), "systemd presets are not applied")

dbus_system = recipe("gui", "dbus-system")
dbus_run = set(dbus_system["depends"]["run"])
require({"dbus", "base-files"} <= dbus_run, "dbus-system runtime closure is incomplete")
dbus_install = dbus_system["build"]["install"]
for marker in (
    "usr/lib/systemd/system/dbus.service",
    "ExecStart=/usr/bin/dbus-daemon --system --nofork --nopidfile",
    "ExecStartPost=",
):
    require(marker in dbus_install, f"dbus-system is missing its systemd unit integration: {marker}")
require("/etc/sv/dbus" not in dbus_install, "dbus-system must not install a runit service")

print("SYSTEMD CORE INTEGRATION VALIDATION PASSED")
