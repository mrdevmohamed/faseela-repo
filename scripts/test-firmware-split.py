#!/usr/bin/env python3
"""scripts/test-firmware-split.py — linux-firmware-lite and linux-firmware-extra
must split the firmware tree: no file in both, no file in neither.

Runs the two recipes' real `install` scripts (with /bin/sh) against a small
fake linux-firmware source tree whose `make install` just copies a fixture,
then compares what each package would ship. No network, no root.
"""
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "recipes" / "boot"

FILES = [  # (path, symlink target or None)
    ("amdgpu/psp.bin", None), ("radeon/r600.bin", None), ("amd-ucode/microcode.bin", None),
    ("i915/skl.bin", None), ("iwlwifi-cc-a0-73.ucode", "intel/iwlwifi/cc-a0-73.ucode"),
    ("intel/iwlwifi/cc-a0-73.ucode", None), ("intel/ibt-18.sfi", None), ("intel/ipu/x.bin", None),
    ("rtl_nic/rtl8168.fw", None), ("brcm/brcmfmac.bin", None), ("regulatory.db", None),
    ("ath10k/WCN3990/hw1.0/wlanmdsp.mbn", None), ("nvidia/ga102/gsp.bin", None),
    ("qcom/adreno/a630.fw", None), ("yamaha/dsp.bin", None), ("WHENCE", None),
]


def tree(root: Path):
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() or p.is_symlink()}


def run_install(name, work: Path, fixture: Path) -> Path:
    r = tomllib.loads((ROOT / name / "recipe.toml").read_text())
    pkgdir = work / f"pkg-{name}"
    src = work / f"src-{name}"
    src.mkdir()
    (src / "Makefile").write_text(
        f"install:\n\tmkdir -p $(DESTDIR)$(FIRMWAREDIR)\n\tcp -a {fixture}/. $(DESTDIR)$(FIRMWAREDIR)/\n")
    script = r["build"]["install"].replace("%{pkgdir}", str(pkgdir))
    res = subprocess.run(["/bin/sh", "-ec", script], cwd=src, capture_output=True, text=True)
    if res.returncode:
        sys.exit(f"{name}: install script failed:\n{res.stderr}")
    return pkgdir / "usr/lib/firmware"


def main():
    with tempfile.TemporaryDirectory() as t:
        work = Path(t)
        fixture = work / "fixture"
        for rel, target in FILES:
            p = fixture / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if target:
                os.symlink(target, p)
            else:
                p.write_text(rel)
        full = tree(fixture)
        lite = tree(run_install("linux-firmware-lite", work, fixture))
        extra = tree(run_install("linux-firmware-extra", work, fixture))
    errors = []
    if lite & extra:
        errors.append(f"in BOTH packages: {sorted(lite & extra)}")
    if full - (lite | extra):
        errors.append(f"in NEITHER package: {sorted(full - (lite | extra))}")
    if not lite or not extra:
        errors.append("a package is empty")
    for e in errors:
        print("FAIL", e)
    print(f"firmware split: {len(lite)} lite + {len(extra)} extra = {len(full)} files "
          f"-> {'OK' if not errors else 'BROKEN'}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
