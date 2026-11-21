#!/usr/bin/env python3
"""Regression checks for Faseela's systemd-only core integration."""

from pathlib import Path
import importlib.util
import re
import subprocess
import tempfile
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
require(systemd_pkg["rel"] >= 4, "Bump systemd rel when changing its authenticated package metadata")
require(systemd_pkg["arch"] == ["x86_64"], "systemd must be restricted to the supported architecture")
require(
    systemd_pkg["source"] == "local:/nawa-package-relations-1-requires-a-newer-nawa",
    "systemd relations must use Nawa's fail-closed relations marker",
)
systemd_sources = systemd_pkg.get("sources", [])
require(
    len(systemd_sources) == 1
    and systemd_sources[0]["name"] == "systemd"
    and systemd_sources[0]["url"].startswith("https://sourceforge.net/projects/systemd.mirror/")
    and re.fullmatch(r"[0-9a-f]{64}", systemd_sources[0]["sha256"]) is not None,
    "systemd must keep its verified source pin in the new-schema source table",
)
require(
    not systemd_pkg.get("sha256")
    and not systemd_pkg.get("mirrors")
    and not systemd_pkg.get("source_dir"),
    "systemd must not mix legacy source fields with [[package.sources]]",
)
expected_replacements = {"eudev", "elogind"}
relations = systemd.get("relations", {})
require(
    relations.get("schema") == 1
    and set(relations.get("conflicts", [])) == expected_replacements
    and set(relations.get("replaces", [])) == expected_replacements,
    "systemd must explicitly conflict with and replace the two legacy udev/logind file owners",
)
require(
    systemd.get("capabilities", {}).get("provides") == ["init-system=systemd"],
    "systemd must declare its init-system capability",
)

# These existing recipe comments already describe real supersession behavior.
# Make it solver-visible rather than leaving it as prose only.
for category, name, old_package, expected_workdir in (
    ("system", "iw", "wireless-tools", "iw-6.9"),
    ("gui", "network-manager", "dhcpcd", "NetworkManager-1.58.1"),
):
    package_doc = recipe(category, name)
    package_meta = package_doc["package"]
    require(
        package_meta["source"] == "local:/nawa-package-relations-1-requires-a-newer-nawa",
        f"{name} relations must use the fail-closed relations marker",
    )
    require(
        package_meta.get("workdir") == expected_workdir
        and "%{" not in package_meta.get("workdir", ""),
        f"{name} new-schema workdir must be a literal directory in the staged workspace",
    )
    sources = package_meta.get("sources", [])
    require(
        len(sources) == 1
        and sources[0]["name"] == name
        and re.fullmatch(r"[0-9a-f]{64}", sources[0]["sha256"]) is not None
        and not package_meta.get("sha256")
        and not package_meta.get("source_dir"),
        f"{name} must pin its source in the new-schema source table",
    )
    package_relations = package_doc.get("relations", {})
    require(
        package_relations.get("schema") == 1
        and set(package_relations.get("conflicts", [])) == {old_package}
        and set(package_relations.get("replaces", [])) == {old_package},
        f"{name} must declare its documented replacement of {old_package}",
    )
    require(
        package_doc.get("capabilities", {}).get("provides") == [],
        f"{name} must declare an explicit empty capabilities list",
    )

# Rebuilt USB tooling must stop retaining eudev as a reverse dependency before
# systemd can safely replace eudev. Keep the source generator in sync with the
# checked-in recipes so regenerating extra3 cannot reintroduce the old provider.
libusb = recipe("extra", "libusb")
usbutils = recipe("extra", "usbutils")
for pkg in (libusb, usbutils):
    deps = set(pkg.get("depends", {}).get("build", [])) | set(pkg.get("depends", {}).get("run", []))
    require("systemd" in deps and "eudev" not in deps,
            f"{pkg['package']['name']} must use systemd's libudev provider, not eudev")

# The extra3 generator is the source of truth for these generated recipes.
# Guard both layers so a future regeneration cannot restore the reverse edge.
extra_data_spec = importlib.util.spec_from_file_location(
    "recipe_data_extra", ROOT / "scripts" / "recipe_data_extra.py"
)
require(
    extra_data_spec is not None and extra_data_spec.loader is not None,
    "could not load the extra recipe source data",
)
extra_data = importlib.util.module_from_spec(extra_data_spec)
extra_data_spec.loader.exec_module(extra_data)
generated = {item["name"]: item for item in extra_data.EXTRA}
for name in ("libusb", "usbutils"):
    item = generated[name]
    deps = set(item.get("bdeps", [])) | set(item.get("rdeps", []))
    require("systemd" in deps and "eudev" not in deps,
            f"extra3 generator data for {name} must not reintroduce eudev")


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
    systemd_pkg.get("workdir") == ".",
    "systemd must preserve the legacy source_dir='.' extraction root as workdir='.'",
)

configure = systemd["build"]["configure"]
for marker in (
    'Path(".").rglob("meson_options.txt")',
    '(path.parent / "meson.build").is_file()',
    'required = ["pam", "kmod", "seccomp", "logind", "networkd", "resolve", "timesyncd"]',
    'Path(".faseela-meson-args")',
    '"hibernate": "off", "initrd": "off",',
    '"shared-lib-tag": "lit:261",',
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
    "usr/lib/systemd/libsystemd-core-261.so",
    "usr/lib/systemd/libsystemd-shared-261.so",
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
    "usr/bin/busctl",
    "usr/bin/userdbctl",
    "usr/bin/varlinkctl",
):
    require(path in systemd_install, f"systemd install phase does not verify {path}")
# Init and power-control entry points are not a generic package replacement:
# they remain owned by runit-services until the separately approved migration.
require(
    "ln -sf ../lib/systemd/systemd %{pkgdir}/usr/bin/init" not in systemd_install
    and "ln -s systemctl %{pkgdir}/usr/bin/$c" not in systemd_install
    and "for c in poweroff reboot halt shutdown" not in systemd_install,
    "systemd must not stage init or power-control aliases during an ordinary package install",
)
require(
    "Nawa's explicitly approved runit -> systemd migration" in systemd_install,
    "systemd recipe must document the migration-only init handoff",
)
for path in (
    "etc/udev/udev.conf",
    "usr/include/libudev.h",
    "usr/lib/libudev.so",
    "usr/lib/libudev.so.1",
    "usr/lib/pkgconfig/libudev.pc",
    "usr/lib/udev/ata_id",
    "usr/lib/udev/rules.d/50-udev-default.rules",
):
    require(
        f'test -e "%{{pkgdir}}/$f"' in systemd_install and path in systemd_install,
        f"systemd install phase must verify the eudev replacement file {path}",
    )

base_files = recipe("base", "base-files")
base_install = base_files["build"]["install"]
require(base_files["package"]["rel"] >= 12, "base-files rel must include the system profile and /etc/environment")
require("etc/environment" in base_files["build"]["install"], "base-files must create the target of systemd’s environment.d compatibility symlink")
for marker in (
    "usr/share/nawa/system-profile.toml",
    'distribution = "faseela"',
    'architecture = "x86_64"',
    'init-system = "systemd"',
):
    require(marker in base_install, f"base-files must ship the Nawa system profile: {marker}")

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
require(
    "post_install" not in units.get("hooks", {}),
    "systemd-units must ship preset files, not apply service policy from a package hook",
)

dbus_system = recipe("gui", "dbus-system")
dbus_run = set(dbus_system["depends"]["run"])
require({"dbus", "base-files"} <= dbus_run, "dbus-system runtime closure is incomplete")
dbus_install = dbus_system["build"]["install"]
require("usr/lib/systemd/system" not in dbus_install,
        "dbus-system must not ship its own dbus units: dbus.socket/dbus.service come from dbus")
require("ensure-system-account user messagebus" in dbus_system["hooks"]["post_install"],
        "dbus-system must create the messagebus account")
dbus_pkg = recipe("browser", "dbus")
require("-D systemd=enabled" in dbus_pkg["build"]["configure"], "dbus must be built with systemd support")
require("systemd" in dbus_pkg["depends"]["build"] and "systemd" in dbus_pkg["depends"]["run"],
        "dbus must depend on systemd (libsystemd)")
require("sockets.target.wants/dbus.socket" in dbus_pkg["build"]["install"],
        "dbus install must verify socket activation wiring")

shadow = recipe("system", "shadow")
require("--with-libpam" in shadow["build"]["configure"], "shadow must be built with PAM")
require({"linux-pam"} <= set(shadow["depends"]["build"]) and {"linux-pam", "systemd"} <= set(shadow["depends"]["run"]),
        "shadow must depend on linux-pam (build/run) and systemd (pam_systemd)")
shadow_install = shadow["build"]["install"]
for svc in ("login", "su", "su-l", "passwd", "chfn", "chsh", "chpasswd", "newusers"):
    require(f"etc/pam.d/{svc}" in shadow_install or svc in shadow_install, f"shadow does not ship PAM service {svc}")
require("pam_systemd.so" in shadow_install, "shadow login must register console sessions with pam_systemd")
require("nullok" in shadow_install, "shadow login must accept the live session's empty password (nullok)")
require("chmod 4755" in shadow["hooks"]["post_install"], "shadow must restore SUID on su/passwd")


# Nawa also executes .sh files from /usr/lib/nawa/transaction-hooks.d.
# Verify that the recipe CI guard inspects those sources, not only [hooks].
checker_spec = importlib.util.spec_from_file_location(
    "check_recipes", ROOT / "scripts" / "check-recipes.py"
)
require(
    checker_spec is not None and checker_spec.loader is not None,
    "could not load the recipe policy checker",
)
checker = importlib.util.module_from_spec(checker_spec)
checker_spec.loader.exec_module(checker)

with tempfile.TemporaryDirectory(prefix="faseela-trigger-policy-") as temporary:
    trigger_dir = Path(temporary)
    trigger_recipe_path = trigger_dir / "recipe.toml"
    trigger_recipe_path.write_text(
        """[package]
name = "trigger-fixture"
[build]
install = "install refresh.sh %{pkgdir}/usr/lib/nawa/transaction-hooks.d/refresh.sh"
""",
        encoding="utf-8",
    )
    trigger_asset = trigger_dir / "refresh.sh"
    trigger_asset.write_text(
        """#!/bin/sh
systemctl preset example.service
""",
        encoding="utf-8",
    )
    fixture = {
        "trigger-fixture": {
            "_path": trigger_recipe_path,
            "hooks": {},
            "build": {
                "install": (
                    "install refresh.sh "
                    "%{pkgdir}/usr/lib/nawa/transaction-hooks.d/refresh.sh"
                )
            },
        }
    }
    trigger_errors = checker.service_hook_policy(fixture)
    require(
        any(
            "transaction-trigger source" in error and "systemctl preset" in error
            for error in trigger_errors
        ),
        "recipe policy must reject service-manager calls in transaction-trigger assets",
    )
    trigger_asset.write_text(
        """#!/bin/sh
update-desktop-database -q
""",
        encoding="utf-8",
    )
    require(
        not checker.service_hook_policy(fixture),
        "recipe policy should allow non-service transaction-trigger work",
    )

print("SYSTEMD CORE INTEGRATION VALIDATION PASSED")
