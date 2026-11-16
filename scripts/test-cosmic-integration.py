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
    "cosmic-idle", "cosmic-launcher", "cosmic-locker", "cosmic-notifications", "cosmic-osk", "cosmic-osd",
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
    if name != "cosmic-desktop":
        assert pkg["version"] == "1.11.0", (
            f"{name}: package version must match COSMIC Epoch 1.11.0"
        )
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
    assert sources[0]["url"].endswith("/refs/tags/epoch-1.11.0"), (
        f"{name}: source must use the coordinated Epoch 1.11.0 tag"
    )
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
    if name == "cosmic-greeter":
        assert pkg["version"] == "1.11.0"
        assert pkg["sources"][0]["url"].endswith("/refs/tags/epoch-1.11.0")
    assert "[fetch.cargo]" in (ROOT / "recipes" / "greeter" / name / "recipe.toml").read_text()

desktop = recipe("cosmic", "cosmic-desktop")
desktop_run = set(desktop["depends"]["run"])
assert {"cosmic-session", "cosmic-osk", "cosmic-comp", "seatd-runit", "audio-session",
        "elogind", "dbus-system", "xdg-desktop-portal-cosmic"} <= desktop_run
assert not {"greetd", "cosmic-greeter", "linux-pam"} & desktop_run, (
    "The core COSMIC desktop must not install or enable the optional login stack"
)
desktop_install = desktop["build"]["install"]
assert "LIBSEAT_BACKEND=seatd" in desktop_install
assert "OnlyShowIn=COSMIC;" in desktop_install
assert "faseela-audio-session-cosmic.desktop" in desktop_install
assert "/etc/sv/cosmic-greeter" not in desktop_install

# GTK/GLib bindings need the GLib development files at build time and the
# matching runtime library after installation.
edit = recipe("cosmic", "cosmic-edit")
assert "glib" in edit["depends"]["build"]
assert "glib" in edit["depends"]["run"]

# Native dav1d is required by the AV1 decoder dependencies in these
# Epoch packages, both while compiling and when loading the shared library.
for category, name in (
    ("cosmic", "cosmic-bg"),
    ("cosmic", "cosmic-locker"),
    ("cosmic", "cosmic-settings"),
):
    item = recipe(category, name)
    assert "dav1d" in item["depends"]["build"]
    assert "dav1d" in item["depends"]["run"]

# Keep the source install manifests aligned with the actual Epoch 1.11.0 trees.
notifications = recipe("cosmic", "cosmic-notifications")
assert "target/release/cosmic-notifications" in notifications["build"]["install"]
assert "CosmicNotifications.desktop" not in notifications["build"]["install"]
bg = recipe("cosmic", "cosmic-bg")
assert "data/v1/all" in bg["build"]["install"]
assert "data/v1/backgrounds" not in bg["build"]["install"]
assert "/usr/share/backgrounds/faseela/default.png" in bg["build"]["install"]
assert "CosmicBackground.desktop" not in bg["build"]["install"]

store = recipe("cosmic", "cosmic-store")
assert "FuturesUnordered::<tokio::sync::oneshot::Receiver" in store["build"]["compile"]
for path in (
    "recipes/cosmic/cosmic-bg/recipe.toml",
    "recipes/greeter/cosmic-greeter/recipe.toml",
    "recipes/cosmic/cosmic-settings/recipe.toml",
    "recipes/cosmic/cosmic-settings-daemon/recipe.toml",
    "recipes/cosmic/cosmic-launcher/recipe.toml",
    "recipes/cosmic/cosmic-notifications/recipe.toml",
    "recipes/cosmic/cosmic-store/recipe.toml",
):
    data = tomllib.loads((ROOT / path).read_text(encoding="utf-8"))
    assert data["package"]["rel"] >= 3, f"{path}: failed package release must be rebuilt"

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
assert "cosmic-locker" in session["depends"]["run"], "cosmic-session must install its regular-user lock UI"
assert "--no-default-features --features logind,autostart" in session["build"]["compile"]
assert "systemd" not in session["build"]["compile"]
assert "start-cosmic" in session["build"]["install"]

# COSMIC's portal backend is a session-D-Bus activated provider.
portal = recipe("cosmic", "xdg-desktop-portal-cosmic")
portal_install = portal["build"]["install"]
assert "cosmic-portals.conf" in portal_install
assert "org.freedesktop.impl.portal.desktop.cosmic.service" in portal_install

# Optional greeter includes PAM + greetd and ships its service disabled.
greeter = recipe("greeter", "cosmic-greeter")
greeter_run = set(greeter["depends"]["run"])
greeter_build = set(greeter["depends"]["build"])
assert {"greetd", "elogind", "seatd-runit", "runit", "cosmic-locker", "eudev"} <= greeter_run
assert "eudev" in greeter_build, "cosmic-greeter daemon's libudev-sys needs libudev.pc"
assert "libinput" in greeter_build, "cosmic-greeter daemon links libinput"
assert "libinput" in greeter_run, "cosmic-greeter daemon dynamically links libinput"
assert "/etc/sv/cosmic-greeter/run" in greeter["build"]["install"]
assert "/etc/runit/runsvdir/default/cosmic-greeter" not in greeter["build"]["install"]
locker = recipe("cosmic", "cosmic-locker")
locker_run = set(locker["depends"]["run"])
locker_install = locker["build"]["install"]
assert {"linux-pam", "elogind", "wayland"} <= locker_run
assert "target/release/cosmic-greeter" in locker_install
assert "pam_elogind.so" in locker_install
assert "class=user type=wayland desktop=COSMIC" in locker_install
assert "cosmic-locker" in greeter_run
assert "install -Dm755 target/release/cosmic-greeter %{pkgdir}/usr/bin/cosmic-greeter" not in greeter["build"]["install"]
assert "pam_elogind.so" not in greeter["build"]["install"]
greeter_install = greeter["build"]["install"]
assert "system-services/com.system76.CosmicGreeter.service" in greeter_install
assert "Name=com.system76.CosmicGreeter" in greeter_install
assert "Exec=/usr/bin/cosmic-greeter-daemon" in greeter_install
assert "User=root" in greeter_install
assert "--features logind,networkmanager,upower -p cosmic-greeter" in locker["build"]["compile"]
assert "--no-default-features -p cosmic-greeter-daemon" in greeter["build"]["compile"]
assert {"network-manager", "bluez", "upower"} <= locker_run
greeter_run_script = greeter["build"]["install"]
greeter_post_install = greeter["hooks"]["post_install"]
assert "ensure-system-account user cosmic-greeter" in greeter_run_script
assert "ensure-system-account group video" in greeter_run_script
assert "set -eu" in greeter_run_script
assert 'while IFS=: read -r account_name _ account_uid _' in greeter_run_script
assert "done < /etc/passwd" in greeter_run_script
assert "video_gid=" in greeter_run_script
assert 'chown "$greeter_uid:$video_gid" /var/lib/cosmic-greeter /run/cosmic-greeter' in greeter_run_script
assert "account provisioning failed" in greeter_run_script
assert "id -u cosmic-greeter" not in greeter_run_script
assert "awk -F:" not in greeter_run_script
assert "ensure-system-account" not in greeter_post_install
assert "account_name _ account_uid" not in greeter_post_install
assert "grep -q 'agreety'" in greeter_post_install

# The shared account helper is POSIX sh: function variables are global, so
# ensure_group must never overwrite ensure_user's account fields. This caught
# the bug that wrote every COSMIC service account as another "video" entry.
base_files = recipe("base", "base-files")
base_install = base_files["build"]["install"]
helper_start = "cat > %{pkgdir}/usr/libexec/faseela/ensure-system-account <<'ACCOUNT'\n"
helper_end = "\nACCOUNT\nchmod 0755 %{pkgdir}/usr/libexec/faseela/ensure-system-account"
assert helper_start in base_install and helper_end in base_install
account_helper = base_install.split(helper_start, 1)[1].split(helper_end, 1)[0]
assert "group_name=$1" in account_helper
assert "group_requested_gid=${2:-}" in account_helper
assert "user_name=$1" in account_helper
assert 'ensure_group "$user_group"' in account_helper
assert 'printf \'%s:x:%s:%s:%s:%s:%s\\n\' "$user_name" "$user_uid" "$user_gid" "$user_gecos" "$user_home" "$user_shell"' in account_helper
assert "    name=$1" not in account_helper
assert 'printf \'%s:x:%s:\\n\' "$name" "$gid"' not in account_helper

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
assert {"@cosmic", "greetd", "cosmic-greeter"} <= set(cosmic_flavor["include"])
assert {"lightdm", "lightdm-gtk-greeter"} <= set(cosmic_flavor["exclude"])
assert {"getty-tty1", "lightdm"} <= set(cosmic_flavor["disable_services"])
assert cosmic_flavor["enable_services"] == ["cosmic-greeter"]

xfce_flavor = flavors["flavor"]["iso-xfce"]
assert {"lightdm", "lightdm-gtk-greeter"} <= set(xfce_flavor["include"])
assert {"greetd", "cosmic-greeter"} <= set(xfce_flavor["exclude"])


# COSMIC Launcher has two executables: a Wayland frontend and its IPC backend.
# The backend must install matching plugin config files and multicall symlinks.
launcher = recipe("cosmic", "cosmic-launcher")
assert "pop-launcher" in launcher["depends"]["run"]
assert "--cfg tokio_unstable" in launcher["build"]["compile"]
pop = recipe("gui", "pop-launcher")
pop_pkg = pop["package"]
assert pop_pkg["version"] == "1.11.0"
assert pop_pkg["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
assert pop_pkg["sources"][0]["url"].endswith("/refs/tags/epoch-1.11.0")
assert re.fullmatch(r"[0-9a-f]{64}", pop_pkg["sources"][0]["sha256"])
assert "pop-launcher-bin" in pop["build"]["compile"]
pop_install = pop["build"]["install"]
assert "desktop_entries files find recent cosmic_toplevel" in pop_install
assert "/usr/lib/pop-launcher/plugins" in pop_install
assert "ln -s /usr/bin/pop-launcher" in pop_install
assert {"fd"} <= set(pop["depends"]["run"])

# Default shortcuts, input-source switching and elogind-native actions.
assert "keybindings.ron" in comp["build"]["install"]
assert "CosmicSettings.Shortcuts/v1/defaults" in comp["build"]["install"]

daemon = recipe("cosmic", "cosmic-settings-daemon")
daemon_install = daemon["build"]["install"]
daemon_build = set(daemon["depends"]["build"])
daemon_run = set(daemon["depends"]["run"])
assert {"dbus", "elogind", "pipewire"} <= daemon_run
assert "pipewire" in daemon_build, "libspa-sys needs PipeWire development metadata"
assert "libinput" in daemon_build, "cosmic-settings-daemon links libinput"
assert "libinput" in daemon_run, "cosmic-settings-daemon dynamically links libinput"
assert "llvm" in daemon_build, "libspa-sys bindgen requires libclang from Faseela's llvm package"
assert "sed 's|systemctl suspend|loginctl suspend|g'" in daemon_install
assert "grep -q 'systemctl'" in daemon_install
assert "busctl --user call" in daemon_install
assert "dbus-send" not in daemon_install, "Faseela's elogind already ships busctl"
assert "loginctl suspend" in daemon_install

desktop = recipe("cosmic", "cosmic-desktop")
assert "CosmicComp/v1/xkb_config" in desktop["build"]["install"]
assert "grp:alt_shift_toggle" in desktop["build"]["install"]

print(f"test-cosmic-integration: {len(EXPECTED)} COSMIC recipes, 2 optional greeter recipes and Faseela integration checks passed")
