#!/usr/bin/env python3
"""Regression tests for package requirement parsing in check-recipes.py."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("check_recipes", ROOT / "check-recipes.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

parse = MODULE.requirement_name

for raw, expected in (
    ("base-files", "base-files"),
    ("base-files >= 0.4-12", "base-files"),
    ("libfoo>=2.1-3", "libfoo"),
    ("libfoo <= 2.1-3", "libfoo"),
    ("libfoo != 2.1-3", "libfoo"),
    ("libfoo=2.1-3", "libfoo"),
    ("libfoo>2.1-3", "libfoo"),
    ("libfoo<2.1-3", "libfoo"),
    ("libfoo+compat >= 1.0~rc1-2", "libfoo+compat"),
):
    assert parse(raw) == expected, (raw, expected, parse(raw))

for raw in (
    "",
    "base-files >=",
    "base-files >= 0.4",
    "base-files => 0.4-12",
    "base-files == 0.4-12",
    "../base-files",
    "base-files >= 0.4-0",
    "base-files >= 0.4-12 extra",
):
    try:
        parse(raw)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid dependency requirement was accepted: {raw!r}")

print("CHECK-RECIPES REQUIREMENT TESTS PASSED")
