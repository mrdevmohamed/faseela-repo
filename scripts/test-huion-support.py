#!/usr/bin/env python3
"""Guard native Huion HS64 support in Faseela's kernel configuration."""

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
recipe = tomllib.loads(
    (ROOT / "recipes/boot/linux/recipe.toml").read_text(encoding="utf-8")
)
configure = recipe["build"]["configure"]
errors = []

if recipe["package"]["name"] != "linux":
    errors.append("kernel recipe is not named linux")
if recipe["package"]["rel"] < 23:
    errors.append("bump the linux recipe release when changing hardware support")

if not re.search(r"--module\s+HID_UCLOGIC\b", configure):
    errors.append("kernel configure must build HID_UCLOGIC as a module")
if not re.search(r"^require_config CONFIG_HID_UCLOGIC m$", configure, re.M):
    errors.append("kernel configure must assert CONFIG_HID_UCLOGIC=m")
if not re.search(r"--enable\s+HID\b", configure):
    errors.append("kernel HID subsystem must be enabled")
if not re.search(r"--enable\s+USB_HID\b", configure):
    errors.append("USB HID support must remain enabled")

for error in errors:
    print("FAIL", error)

print(f"Huion HS64 kernel support: {'OK' if not errors else f'{len(errors)} problem(s)'}")
sys.exit(1 if errors else 0)
