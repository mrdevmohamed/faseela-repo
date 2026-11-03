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
require_deps("gui", "gui-session", "run", {"xdg-utils", "gnome-keyring", "rsync"})

install_script = session["build"]["install"]
assert "%{pkgdir}/etc/udev/rules.d" in install_script
assert (chr(36) + "{pkgdir}") not in install_script, (
    "Use the recipe %{pkgdir} macro; an unset shell variable breaks package staging"
)
assert "exec dbus-run-session -- sh -c" in install_script, (
    "Sway must run inside a user D-Bus session for Secret Service activation"
)
assert session["package"]["rel"] >= 14, "Bump gui-session rel for PipeWire session autostart"
assert "procps-ng" in session["depends"]["run"], "Audio session helper requires pgrep"
assert "faseela-audio-session" in install_script
assert "exec /usr/bin/faseela-audio-session" in install_script
assert "pipewire-pulse" in install_script
assert "pulse/native" in install_script
assert "pgrep -u" in install_script
assert "wireplumber" in install_script
assert "exec /usr/bin/faseela-audio-session" in install_script

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

print("DESKTOP INTEGRATION VALIDATION PASSED")
