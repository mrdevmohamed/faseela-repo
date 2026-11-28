#!/usr/bin/env python3
"""scripts/test-kernel-live-media.py — guard what the live ISO needs from the kernel.

bootstrap/mkiso.sh (in the faseela repo) packs the root into an xz SquashFS and
the initramfs mounts it under an overlayfs, from a CD, a dd-written stick or an ISO
file loop-mounted from a partition (Ventoy). The kernel has to carry all of that
without a module, and the SquashFS driver has to understand what mksquashfs wrote:
without SQUASHFS_XATTR every live boot logged "SQUASHFS error: Xattrs in filesystem,
these will be ignored" and the extended attributes (file capabilities, ACLs) of the
live root were dropped. This reads the recipe (no kernel is built) and fails when an
option is no longer requested with scripts/config or no longer asserted by
require_config.
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []

linux = tomllib.loads((ROOT / "recipes/boot/linux/recipe.toml").read_text(encoding="utf-8"))
configure = linux["build"]["configure"]
if linux["package"]["rel"] < 27:
    errors.append("linux: bump rel when changing the config (SQUASHFS_XATTR is rel 27)")

requested = dict((name, kind) for kind, name in re.findall(r"--(enable|module)\s+([A-Z0-9_]+)", configure))
asserted = set(re.findall(r"^require_config CONFIG_([A-Z0-9_]+) y\b", configure, re.M))

# built in: the initramfs may not have the module yet when it looks for the medium
LIVE_MEDIA = (
    "SQUASHFS", "SQUASHFS_ZLIB", "SQUASHFS_XZ", "SQUASHFS_ZSTD", "SQUASHFS_XATTR",
    "XZ_DEC_X86", "OVERLAY_FS", "ISO9660_FS", "BLK_DEV_LOOP",
)
for name in LIVE_MEDIA:
    if requested.get(name) != "enable":
        errors.append(f"linux: scripts/config does not --enable {name} (live ISO)")
    if name not in asserted:
        errors.append(f"linux: require_config CONFIG_{name} y is missing (live ISO)")

if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print(f"kernel live media: {len(LIVE_MEDIA)} options, OK")
