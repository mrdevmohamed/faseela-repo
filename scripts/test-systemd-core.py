#!/usr/bin/env python3
"""Regression checks for the staged systemd core migration."""

from pathlib import Path
import re
import subprocess
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

require(
    systemd_pkg.get("source_dir") == ".",
    "systemd must start at the extracted archive root and discover its real Meson project directory",
)

configure = systemd["build"]["configure"]
for marker in (
    'Path(".").rglob("meson_options.txt")',
    '(path.parent / "meson.build").is_file()',
    'required = ["pam", "kmod", "seccomp", "logind", "networkd", "resolve", "timesyncd"]',
    'Path(".faseela-meson-args")',
    'Path(".faseela-source-root")',
    'meson setup "$SOURCE_ROOT/build" "$SOURCE_ROOT"',
    '$(cat .faseela-meson-args)',
):
    require(marker in configure, f"systemd configure phase is missing: {marker}")

compile_script = systemd["build"]["compile"]
require(
    'SOURCE_ROOT="$(cat .faseela-source-root)"' in compile_script
    and 'ninja -C "$SOURCE_ROOT/build"' in compile_script,
    "systemd compile phase must use the detected source root",
)

install_script = systemd["build"]["install"]
require(
    'SOURCE_ROOT="$(cat .faseela-source-root)"' in install_script
    and 'meson install -C "$SOURCE_ROOT/build" --no-rebuild' in install_script,
    "systemd install phase must use the same detected source root",
)

for phase_name, phase_script in (
    ("configure", configure),
    ("compile", compile_script),
    ("install", install_script),
):
    syntax = subprocess.run(
        ["bash", "-n"], input=phase_script, text=True, capture_output=True, check=False
    )
    require(
        syntax.returncode == 0,
        f"systemd {phase_name} phase has invalid shell syntax: {syntax.stderr}",
    )

python_block = re.search(r"python3 - <<'PY'\n(.*?)\nPY", configure, re.DOTALL)
require(python_block is not None, "systemd configure phase must contain its Meson option filter")
try:
    compile(python_block.group(1), "systemd-configure-options", "exec")
except SyntaxError as error:
    raise AssertionError(f"systemd Meson option filter has invalid Python syntax: {error}") from error

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
