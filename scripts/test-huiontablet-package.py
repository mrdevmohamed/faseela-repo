#!/usr/bin/env python3
"""Integration test for the checksum-pinned Huion HS64 control-panel package."""

import hashlib
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE_PATH = ROOT / "recipes/peripherals/huiontablet/recipe.toml"
EXPECTED_SHA256 = "cc563c2358dd0ba13c245f97341d20fecfa8509bfa5c75c8258c895f48b6fa02"
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run():
    if len(sys.argv) != 2:
        raise SystemExit("usage: test-huiontablet-package.py PATH_TO_VENDOR_DEB")

    deb = Path(sys.argv[1]).resolve()
    recipe = tomllib.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    package = recipe["package"]
    install_script = recipe["build"]["install"]

    check(package["name"] == "huiontablet", "recipe package name must be huiontablet")
    check(package["version"] == "15.0.0.193", "unexpected Huion driver version")
    check(package["sha256"] == EXPECTED_SHA256, "recipe checksum does not match inspected vendor archive")
    check(sha256(deb) == EXPECTED_SHA256, "downloaded Huion DEB checksum mismatch")
    check("256c" in install_script and "006f" in install_script,
          "package integration must be scoped to the observed HS64 USB ID")
    check("0666" not in install_script, "broad world-writable device permissions are forbidden")

    url = package["source"].replace("%{version}", package["version"])
    filename = url.rsplit("/", 1)[-1]

    with tempfile.TemporaryDirectory(prefix="faseela-huion-package-") as tmp:
        root = Path(tmp)
        srcdir = root / "src"
        pkgdir = root / "pkg"
        srcdir.mkdir()
        pkgdir.mkdir()
        (srcdir / filename).write_bytes(deb.read_bytes())

        command = (
            install_script
            .replace("%{srcdir}", str(srcdir))
            .replace("%{pkgdir}", str(pkgdir))
            .replace("%{version}", package["version"])
        )
        result = subprocess.run(
            ["bash", "-e", "-c", command],
            cwd=srcdir,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if result.returncode:
            errors.append(
                "recipe install failed:\n"
                + result.stdout[-4000:]
                + result.stderr[-8000:]
            )
            return

        paths = [
            "usr/lib/huiontablet/huiontablet",
            "usr/lib/huiontablet/huionCore",
            "usr/lib/huiontablet/huiontablet.sh",
            "usr/lib/huiontablet/libs/libhuionhid.so",
            "usr/lib/huiontablet/plugins/platforms/libqxcb.so",
            "usr/lib/huiontablet/qml",
            "usr/lib/huiontablet/res",
            "usr/lib/huiontablet/xdotool/xdotool",
            "usr/share/icons/huiontablet.png",
            "usr/share/applications/huiontablet.desktop",
            "usr/lib/udev/rules.d/20-huion.rules",
            "etc/sway/config.d/40-huiontablet.conf",
        ]
        for relative in paths:
            check((pkgdir / relative).exists(), f"missing staged payload: {relative}")

        launcher = pkgdir / "usr/lib/huiontablet/huiontablet.sh"
        launcher_text = launcher.read_text(encoding="utf-8")
        check(
            "LD_LIBRARY_PATH=$dirname/libs:$dirname/xdotool" in launcher_text,
            "launcher must resolve the private xdotool library without global copies",
        )
        check("PATH=$dirname/xdotool:$PATH" in launcher_text,
              "launcher must use the bundled xdotool executable")

        desktop = (pkgdir / "usr/share/applications/huiontablet.desktop").read_text(encoding="utf-8")
        check("Exec=/usr/lib/huiontablet/huiontablet.sh manual_launch" in desktop,
              "desktop entry must launch the Huion control panel")
        sway = (pkgdir / "etc/sway/config.d/40-huiontablet.conf").read_text(encoding="utf-8")
        check("exec /usr/lib/huiontablet/huiontablet.sh autostart" in sway,
              "Sway must autostart the Huion control panel when this optional package is installed")

        udev = (pkgdir / "usr/lib/udev/rules.d/20-huion.rules").read_text(encoding="utf-8")
        check('ATTRS{idVendor}=="256c"' in udev and 'ATTRS{idProduct}=="006f"' in udev,
              "udev rules must match only Huion HS64 USB ID 256c:006f")
        check('GROUP="input"' in udev and 'MODE="0660"' in udev,
              "udev rules must grant restricted input-group access")
        check("0666" not in udev, "udev rules must not grant world-writable access")
        check(not (pkgdir / "usr/bin/xdotool").exists(),
              "do not install vendor xdotool into the global /usr/bin")
        check(not (pkgdir / "usr/lib/libxdo.so.3").exists(),
              "do not install vendor libxdo into the global /usr/lib")

        for relative in (
            "usr/lib/huiontablet/huiontablet",
            "usr/lib/huiontablet/huionCore",
            "usr/lib/huiontablet/huiontablet.sh",
        ):
            target = pkgdir / relative
            check(os.access(target, os.X_OK), f"{relative} must be executable")

        # The official launcher selects the xcb QPA backend. Confirm that the
        # runtime's bundled Qt libraries and the target runner's X11/GL stack
        # resolve, instead of deferring obvious ELF failures until user login.
        library_dir = pkgdir / "usr/lib/huiontablet/libs"
        private_dir = pkgdir / "usr/lib/huiontablet/xdotool"
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = f"{library_dir}:{private_dir}"
        for relative in ("usr/lib/huiontablet/huiontablet", "usr/lib/huiontablet/huionCore"):
            target = pkgdir / relative
            ldd = subprocess.run(
                ["ldd", str(target)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            check(ldd.returncode == 0, f"ldd failed for {relative}: {ldd.stderr}")
            check("not found" not in ldd.stdout, f"unresolved ELF dependency in {relative}")

    for error in errors:
        print("FAIL", error, file=sys.stderr)
    print(
        "Huion Tablet control panel package: "
        + ("OK" if not errors else f"{len(errors)} problem(s)")
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(run())
