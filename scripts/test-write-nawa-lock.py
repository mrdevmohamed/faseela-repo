#!/usr/bin/env python3
"""Regression tests for writing the bootstrap Nawa lock from multi-source recipes."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).with_name("write-nawa-lock.py")
spec = importlib.util.spec_from_file_location("write_nawa_lock", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

COMMIT = "3e652cf84b1f2963957ab0f446a85118cf70093b"
SHA256 = "a" * 64


def package(**overrides):
    value = {
        "version": "1.0.0",
        "rel": 17,
        "source": "local:/nawa-schema-2-requires-a-newer-nawa",
        "sources": [{
            "name": "nawa",
            "url": f"https://github.com/mrdevmohamed/nawa/archive/{COMMIT}.tar.gz",
            "sha256": SHA256,
            "strip_components": 1,
        }],
    }
    value.update(overrides)
    return value


def expect_error(value, fragment):
    try:
        module.bootstrap_pin(value)
    except ValueError as error:
        assert fragment in str(error), (fragment, str(error))
    else:
        raise AssertionError(f"expected ValueError containing {fragment!r}")


pin = module.bootstrap_pin(package())
assert pin == {
    "repository": "mrdevmohamed/nawa",
    "version": "1.0.0",
    "rel": 17,
    "commit": COMMIT,
    "sha256": SHA256,
}
lock = module.render_lock(pin)
assert f'commit = "{COMMIT}"' in lock
assert f'sha256 = "{SHA256}"' in lock
assert 'rel = 17' in lock

expect_error(package(sources=[]), "exactly one")
expect_error(package(sources=[
    {"name": "other", "url": "https://example.com/a.tar.gz", "sha256": SHA256}
]), "exactly one")
expect_error(package(sources=[
    {"name": "nawa", "url": "local:/not-an-archive", "sha256": SHA256}
]), "unexpected Nawa source URL")
expect_error(package(sources=[
    {"name": "nawa", "url": f"https://github.com/mrdevmohamed/nawa/archive/{COMMIT}.tar.gz", "sha256": "bad"}
]), "sha256")
expect_error(package(rel=0), "positive integer")

print("write-nawa-lock: multi-source and fail-closed marker tests passed")
