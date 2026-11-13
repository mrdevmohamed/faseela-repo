#!/usr/bin/env python3
"""Regression tests for the COSMIC desktop package set and Faseela integration."""
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
COSMIC = ROOT / "recipes" / "cosmic"
EXPECTED = {
    "cosmic-applets", "cosmic-bg", "cosmic-comp", "cosmic-desktop",
    "cosmic-edit", "cosmic-files", "cosmic-icons",
    "cosmic-idle", "cosmic-launcher", "cosmic-notifications", "cosmic-osd",
    "cosmic-panel", "cosmic-randr", "cosmic-screenshot", "cosmic-session",
    "cosmic-settings", "cosmic-settings-daemon", "cosmic-store", "cosmic-term",
    "cosmic-workspaces", "xdg-desktop-portal-cosmic",
}


def recipe(category: str, name: str) -> dict:
    path = ROOT / "recipes" / category / name / "recipe.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


actual = {p.parent.name for p in COSMIC.glob("*/recipe.toml")}
assert actual == EXPECTED, (
    f"COSMIC recipe inventory differs: missing={sorted(EXPECTED - actual)}, "
    f"unexpected={sorted(actual - EXPECTED)}"
)

# Package metadata, schema-2 marker and reproducible source pins.
for name in sorted(EXPECTED):
    data = recipe("cosmic", name)
    pkg = data["package"]
    assert pkg["name"] == name, f"{name}: package.name must match its directory"
    assert pkg["arch"] == ["x86_64"], f"{name}: unexpected architecture list"
    assert pkg.get("license"), f"{name}: license metadata is required"
    if name == "cosmic-desktop":
        assert not pkg.get("source"), "cosmic-desktop is a source-less integration package"
        continue
    assert pkg.get("source") == "local:/nawa-schema-2-requires-a-newer-nawa", (
        f"{name}: multi-source recipe must fail closed on old Nawa clients"
    )
    sources = pkg.get("sources", [])
    assert len(sources) == 1, f"{name}: expected exactly one pinned source archive"
    assert re.fullmatch(r"[0-9a-f]{64}", sources[0].get("sha256", "")), (
        f"{name}: source SHA-256 must be pinned"
    )
    assert sources[0]["url"].startswith("https://"), f"{name}: source URL must be HTTPS"
    assert "[fetch.cargo]" in (COSMIC / name / "recipe.toml").read_text(
        encoding="utf-8"
    ) or name == "cosmic-icons", f"{name}: Rust sources must use Nawa's Cargo fetch phase"

# Login components live outside @cosmic so an ISO can select the desktop
# without pulling the PAM stack or a second login daemon.
for name in ("cosmic-greeter", "greetd"):
    item = recipe("greeter", name)
    pkg = item["package"]
    assert pkg["name"] == name
    assert pkg["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
    assert re.fullmatch(r"[0-9a-f]{64}", pkg["sources"][0]["sha256"])
    assert "[fetch.cargo]" in (ROOT / "recipes" / "greeter" / name / "recipe.toml").read_text()

desktop = recipe("cosmic", "cosmic-desktop")
desktop_run = set(desktop["depends"]["run"])
assert {"cosmic-session", "cosmic-comp", "seatd-runit", "audio-session",
        "elogind", "dbus-system", "xdg-desktop-portal-cosmic"} <= desktop_run
assert not {"greetd", "cosmic-greeter", "linux-pam"} & desktop_run, (
    "The core COSMIC desktop must not install or enable the optional login stack"
)
desktop_install = desktop["build"]["install"]
assert "LIBSEAT_BACKEND=seatd" in desktop_install
assert "OnlyShowIn=COSMIC;" in desktop_install
assert "faseela-audio-session-cosmic.desktop" in desktop_install
assert "/etc/sv/cosmic-greeter" not in desktop_install

# Native audio system headers and PulseAudio-compatible client ABI are explicit.
applets = recipe("cosmic", "cosmic-applets")
assert "pipewire" in applets["depends"]["build"]
osd = recipe("cosmic", "cosmic-osd")
assert {"pipewire", "libpulse"} <= set(osd["depends"]["build"])
assert "libpulse" in osd["depends"]["run"]

# COSMIC is built without systemd-only features; session login1 calls use elogind.
comp = recipe("cosmic", "cosmic-comp")
assert "--no-default-features" in comp["build"]["compile"]
assert "seatd" in comp["depends"]["run"]
session = recipe("cosmic", "cosmic-session")
assert "elogind" in session["depends"]["run"]
assert "--features autostart" in session["build"]["compile"]
assert "start-cosmic" in session["build"]["install"]

# COSMIC's portal backend is a session-D-Bus activated provider.
portal = recipe("cosmic", "xdg-desktop-portal-cosmic")
portal_install = portal["build"]["install"]
assert "cosmic-portals.conf" in portal_install
assert "org.freedesktop.impl.portal.desktop.cosmic.service" in portal_install

# Optional greeter includes PAM + greetd and ships its service disabled.
greeter = recipe("greeter", "cosmic-greeter")
greeter_run = set(greeter["depends"]["run"])
assert {"greetd", "linux-pam", "elogind", "seatd-runit", "runit"} <= greeter_run
assert "/etc/sv/cosmic-greeter/run" in greeter["build"]["install"]
assert "/etc/runit/runsvdir/default/cosmic-greeter" not in greeter["build"]["install"]
assert "pam_elogind.so" in greeter["build"]["install"]
greeter_install = greeter["build"]["install"]
assert "system-services/com.system76.CosmicGreeter.service" in greeter_install
assert "Name=com.system76.CosmicGreeter" in greeter_install
assert "Exec=/usr/bin/cosmic-greeter-daemon" in greeter_install
assert "User=root" in greeter_install
assert "--features logind,networkmanager,upower -p cosmic-greeter" in greeter["build"]["compile"]
assert "--no-default-features -p cosmic-greeter-daemon" in greeter["build"]["compile"]
assert {"network-manager", "bluez", "upower"} <= greeter_run
assert "ensure-system-account user cosmic-greeter" in greeter["hooks"]["post_install"]
assert 'greeter_uid=$(awk -F: \'$1 == "cosmic-greeter" { print $3; exit }\' /etc/passwd)' in greeter["hooks"]["post_install"]
assert 'video_gid=$(awk -F: \'$1 == "video" { print $3; exit }\' /etc/group)' in greeter["hooks"]["post_install"]
assert 'chown "$greeter_uid:$video_gid" /var/lib/cosmic-greeter' in greeter["hooks"]["post_install"]
assert 'chown "$greeter_uid:$video_gid" /run/cosmic-greeter' in greeter["build"]["install"]
assert "grep -q 'agreety'" in greeter["hooks"]["post_install"]

greetd = recipe("greeter", "greetd")
assert "linux-pam" in greetd["depends"]["run"]

# Shared seatd integration is owned once, not by the Sway or COSMIC session.
seatd = recipe("gui", "seatd-runit")
seatd_install = seatd["build"]["install"]
assert "/etc/runit/runsvdir/default/seatd" in seatd_install
assert "/etc/udev/rules.d/70-faseela-drm.rules" in seatd_install
assert "ensure-system-account group" in seatd["hooks"]["post_install"]
gui_session = recipe("gui", "gui-session")
assert "seatd-runit" in gui_session["depends"]["run"]
assert "/etc/sv/seatd/run" not in gui_session["build"]["install"]
assert "/etc/udev/rules.d/70-faseela-drm.rules" not in gui_session["build"]["install"]

# The shared audio supervisor must remain alive for COSMIC until its session ends.
audio = recipe("gui", "audio-session")
audio_install = audio["build"]["install"]
assert audio["package"]["rel"] >= 3
assert "*COSMIC*|*cosmic*) session_process=cosmic-session ;;" in audio_install

# Group selection and ISO contents keep the login manager opt-in.
groups = tomllib.loads((ROOT / "groups.toml").read_text(encoding="utf-8"))
cosmic_group = next(g for g in groups["group"] if g["id"] == "cosmic")
assert cosmic_group["mandatory"] == ["cosmic-desktop"]
assert cosmic_group["optional"] == ["cosmic-greeter"]

flavors = tomllib.loads((ROOT / "flavors.toml").read_text(encoding="utf-8"))
cosmic_flavor = flavors["flavor"]["iso-cosmic"]
assert "@cosmic" in cosmic_flavor["include"]
assert "cosmic-greeter" not in cosmic_flavor.get("exclude", [])
assert "greetd" not in cosmic_flavor.get("exclude", [])

print(f"test-cosmic-integration: {len(EXPECTED)} COSMIC recipes, 2 optional greeter recipes and Faseela integration checks passed")
