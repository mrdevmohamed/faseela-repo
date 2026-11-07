#!/usr/bin/env python3
"""Guard the initial Podman prerequisite and keep it out of default images."""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def recipe(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


crun = recipe("recipes/system/crun/recipe.toml")
crun_pkg = crun["package"]
assert crun_pkg["name"] == "crun"
assert crun_pkg["version"] == "1.30.1"
assert crun_pkg["sha256"] == (
    "99d036d95113552b6df66c7c879432835504bf0e525fc0372745071df129527b"
)
assert "libseccomp" in crun["depends"]["build"]
assert "libcap" in crun["depends"]["build"]
assert "json-c" in crun["depends"]["build"]
assert "--disable-systemd" in crun["build"]["configure"]
assert "systemd" not in crun["depends"].get("run", [])

seccomp = recipe("recipes/system/libseccomp/recipe.toml")
pkg = seccomp["package"]
assert pkg["name"] == "libseccomp"
assert pkg["version"] == "2.6.1", "use the security-fixed upstream release"
assert pkg["source"] == (
    "https://github.com/seccomp/libseccomp/releases/download/"
    "v%{version}/libseccomp-%{version}.tar.gz"
)
assert pkg["sha256"] == (
    "501f66c667225d53791b97e1d7cf85ab764c297d04881f60f38f451c4b0ee1be"
)
assert re.fullmatch(r"[0-9a-f]{64}", pkg["sha256"])
assert "gperf" in seccomp["depends"]["build"]
assert seccomp["build"]["configure"].endswith("--disable-static")
assert "--prefix=/usr" in seccomp["build"]["configure"]
assert "%{pkgdir}" in seccomp["build"]["install"]

flavors = (ROOT / "flavors.toml").read_text(encoding="utf-8")
for default in ("bootstrap", "rootfs-min", "iso-nogui", "iso-gui"):
    section = flavors.split(f"[flavor.{default}]", 1)[1].split("[flavor.", 1)[0]
    assert "podman" not in section and "developer-containers" not in section

docs = (ROOT / "docs/podman-support.md").read_text(encoding="utf-8")
assert "Faseela uses **runit**, not systemd" in docs
assert "Rootless operation is a release" in docs
assert "libseccomp" in docs

print("PODMAN PREREQUISITE REGRESSION CHECKS PASSED")
