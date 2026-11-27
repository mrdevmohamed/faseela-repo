#!/usr/bin/env python3
"""Validate Faseela's Unity 7 desktop recipes, session wiring and iso-unity flavor."""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
UNITY = ROOT / "recipes" / "unity"


def recipe(category: str, name: str) -> dict:
    path = ROOT / "recipes" / category / name / "recipe.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


# --- the Unity category must hold every component the session starts ---------
required = {
    "unity", "unity-session", "unity-desktop", "unity-settings-daemon", "unity-gtk-module",
    "compiz", "nux", "bamf", "zeitgeist", "dee", "libunity", "libunity-misc",
    "ido", "libindicator", "libappindicator", "indicator-application", "indicator-appmenu",
    "ibus", "gnome-desktop3", "accountsservice", "colord", "libgusb",
    "xpathselect", "gsettings-ubuntu-touch-schemas", "dconf",
}
present = {p.parent.name for p in UNITY.glob("*/recipe.toml")}
assert required <= present, f"missing Unity recipes: {sorted(required - present)}"

# Every Unity recipe is schema v5 with a pinned, checksummed source or is a meta package.
for path in sorted(UNITY.glob("*/recipe.toml")):
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    pkg = data["package"]
    assert pkg["source"] == "local:/nawa-package-relations-1-requires-a-newer-nawa", path
    assert pkg["rel"] >= 2, path
    for src in pkg.get("sources", []):
        assert src["url"].startswith("https://"), path
        assert re.fullmatch(r"[0-9a-f]{64}", src["sha256"]), path

# --- session: systemd user manager, no Lomiri, no cinnamon-session -----------
session = recipe("unity", "unity-session")
install = session["build"]["install"]
assert "run-systemd-session" in install
assert "XDG_CURRENT_DESKTOP=\"Unity:Unity7\"" in install
assert "dbus-update-activation-environment --systemd" in install
assert "lightdm.conf.d/50-unity.conf" in install, "LightDM must default to the unity session"
assert "xsessions" in install and "unity.desktop" in install
assert not [l for l in install.splitlines() if "cinnamon" in l and not l.lstrip().startswith("#")]
assert "sleep infinity" in install
assert {"unity", "unity-settings-daemon", "systemd", "dbus"} <= set(session["depends"]["run"])

# --- unity-settings-daemon is started by the session target ------------------
usd = recipe("unity", "unity-settings-daemon")["build"]["install"]
assert "unity-settings-daemon.service" in usd
assert "unity-session.target.wants" in usd
assert "/usr/bin/unity-settings-daemon" in usd

# --- meta package: Xorg input, audio autostart, portals, device groups --------
desktop = recipe("unity", "unity-desktop")
d_install = desktop["build"]["install"]
d_run = set(desktop["depends"]["run"])
assert {"unity-session", "unity", "unity-settings-daemon", "compiz", "bamf", "zeitgeist",
        "audio-session", "xorg-server", "xf86-input-libinput", "polkit", "dbus-system",
        "xdg-desktop-portal-gtk", "xkeyboard-config", "xkbcomp"} <= d_run
assert "XkbLayout" in d_install and "us,ara" in d_install and "grp:alt_shift_toggle" in d_install
assert "OnlyShowIn=Unity;" in d_install
assert "faseela-audio-session" in d_install
assert "unity-portals.conf" in d_install and "default=gtk" in d_install
hook = desktop["hooks"]["post_install"]
assert "/tmp/.X11-unix" in hook and "/tmp/.ICE-unix" in hook
for group in ("video", "render", "input", "audio"):
    assert group in hook

# --- audio-session lifetime detection knows the Unity shell (compiz) ----------
audio = recipe("gui", "audio-session")
assert "*Unity*) session_process=compiz ;;" in audio["build"]["install"]
assert audio["package"]["rel"] >= 5

# --- Unity shell: no GEIS / AppStream, gestures compiled out -----------------
shell = recipe("unity", "unity")
assert (UNITY / "unity" / "patches" / "no-geis-no-appstream.patch").is_file()
assert "-DENABLE_UNIT_TESTS=OFF" in shell["build"]["configure"]
nux = recipe("unity", "nux")
assert "--disable-gestures" in nux["build"]["configure"]

# --- the image flavor ---------------------------------------------------------
flavors = tomllib.loads((ROOT / "flavors.toml").read_text(encoding="utf-8"))["flavor"]
unity_flavor = flavors["iso-unity"]
assert unity_flavor["extends"] == ["iso-nogui"]
assert {"unity-desktop", "lightdm", "lightdm-gtk-greeter"} <= set(unity_flavor["include"])
for forbidden in ("greetd", "cosmic-greeter", "sway"):
    assert forbidden not in unity_flavor["include"]
assert "disable_services" not in unity_flavor  # LightDM stays the login manager

print("Unity integration checks passed")
