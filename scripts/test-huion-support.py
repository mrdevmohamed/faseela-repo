#!/usr/bin/env python3
"""Guard Huion HS64 (256c:006f) support in Faseela's Linux 6.10 kernel."""

import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
recipe = tomllib.loads(
    (ROOT / "recipes/boot/linux/recipe.toml").read_text(encoding="utf-8")
)
build = recipe["build"]
configure = build["configure"]
prepare = build.get("prepare", "")
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


check(recipe["package"]["name"] == "linux", "kernel recipe must be named linux")
check(recipe["package"]["rel"] >= 24, "bump linux rel when changing Huion support")
check(bool(prepare), "kernel recipe must backport Huion PID 0x006f support")
check(bool(re.search(r"--module\s+HID_UCLOGIC\b", configure)),
      "kernel configure must build HID_UCLOGIC as a module")
check(bool(re.search(r"^require_config CONFIG_HID_UCLOGIC m$", configure, re.M)),
      "kernel configure must assert CONFIG_HID_UCLOGIC=m")
check(bool(re.search(r"--enable\s+HID\b", configure)),
      "kernel HID subsystem must be enabled")
check(bool(re.search(r"--enable\s+USB_HID\b", configure)),
      "USB HID support must remain enabled")

# Exercise the actual prepare script against small fixtures copied from the
# pinned Linux 6.10 source context. This catches stale anchors and bad escaping
# without building the kernel in CI.
fixtures = {
    "drivers/hid/hid-ids.h": (
        "#define USB_DEVICE_ID_HUION_TABLET2\t0x006d\n"
    ),
    "drivers/hid/hid-uclogic-core.c": (
        "\t{ HID_USB_DEVICE(USB_VENDOR_ID_HUION,\n"
        "\t\t\t\tUSB_DEVICE_ID_HUION_TABLET2) },\n"
    ),
    "drivers/hid/hid-uclogic-params.c": (
        "\tcase VID_PID(USB_VENDOR_ID_HUION,\n"
        "\t\t     USB_DEVICE_ID_HUION_TABLET2):\n"
    ),
}

if prepare:
    try:
        with tempfile.TemporaryDirectory(prefix="faseela-huion-test-") as tmp:
            root = Path(tmp)
            for relative, text in fixtures.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")

            for _ in range(2):
                subprocess.run(
                    ["bash", "-e", "-c", prepare],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            ids = (root / "drivers/hid/hid-ids.h").read_text(encoding="utf-8")
            core = (root / "drivers/hid/hid-uclogic-core.c").read_text(encoding="utf-8")
            params = (root / "drivers/hid/hid-uclogic-params.c").read_text(encoding="utf-8")
            check(ids.count("#define USB_DEVICE_ID_HUION_TABLET4\t0x006f") == 1,
                  "Huion PID 0x006f must be defined exactly once")
            check(core.count("USB_DEVICE_ID_HUION_TABLET4) },") == 1,
                  "Huion PID 0x006f must be registered in the HID match table")
            check(params.count("USB_DEVICE_ID_HUION_TABLET4):") == 1,
                  "Huion PID 0x006f must use Huion parameter initialization")
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        errors.append(f"Huion 0x006f prepare backport failed: {detail.strip()}")

for error in errors:
    print("FAIL", error)

print(f"Huion HS64 256c:006f support: {'OK' if not errors else f'{len(errors)} problem(s)'}")
sys.exit(1 if errors else 0)
