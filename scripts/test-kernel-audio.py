#!/usr/bin/env python3
"""scripts/test-kernel-audio.py — guard the pieces that make sound work on real hardware.

x86_64_defconfig builds the HD-audio controller and NO codec driver, and Intel
laptops with a digital microphone are handed to SOF, which does nothing without
the HDA link, the HDA machine driver and its firmware. Each of those is an option
nothing selects by itself, so dropping a line from the kernel recipe silently
gives back "a sound controller and no sound". This reads the recipes (no kernel
is built) and fails when one of the pieces is no longer requested or asserted.
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []


def recipe(path):
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


def check(cond, msg):
    if not cond:
        errors.append(msg)


linux = recipe("recipes/boot/linux/recipe.toml")
configure = linux["build"]["configure"]
check(linux["package"]["rel"] >= 19, "linux: bump rel when changing the config (audio fix is rel 19)")

# what is requested with scripts/config (--enable X / --module X)
requested = {}
for kind, name in re.findall(r"--(enable|module)\s+([A-Z0-9_]+)", configure):
    requested[name] = kind

# symbol -> how it has to be asked for (bool = enable, tristate = module)
WANT = {
    # HD-audio: controller + every codec family + generic parser
    "SND_HDA_INTEL": "module", "SND_HDA_GENERIC": "module",
    "SND_HDA_CODEC_REALTEK": "module", "SND_HDA_CODEC_HDMI": "module",
    "SND_HDA_CODEC_CONEXANT": "module", "SND_HDA_CODEC_SIGMATEL": "module",
    "SND_HDA_CODEC_VIA": "module", "SND_HDA_CODEC_CIRRUS": "module",
    "SND_HDA_SCODEC_CS35L41_I2C": "module", "SND_HDA_SCODEC_TAS2781_I2C": "module",
    "SND_USB_AUDIO": "module",
    # Intel SOF with HDA links + the machine driver for HDA codecs
    "SND_SOC_SOF_INTEL_TOPLEVEL": "enable", "SND_SOC_INTEL_MACH": "enable",
    "SND_SOC_SOF_HDA_LINK": "enable", "SND_SOC_SOF_HDA_AUDIO_CODEC": "enable",
    "SND_SOC_INTEL_SKL_HDA_DSP_GENERIC_MACH": "module",
    "SND_SOC_INTEL_SOUNDWIRE_SOF_MACH": "module",
    # AMD digital microphone
    "SND_SOC_AMD_YC_MACH": "module", "SND_SOC_AMD_PS_MACH": "module",
    # what touchpads and speaker amplifiers hang off
    "I2C_DESIGNWARE_PLATFORM": "module", "MFD_INTEL_LPSS_PCI": "module",
    "PINCTRL_ALDERLAKE": "module", "PINCTRL_TIGERLAKE": "module", "PINCTRL_AMD": "enable",
    "HID_MULTITOUCH": "module", "BT_HIDP": "module",
    # Wi-Fi chips: naming RTW88/RTW89 alone builds a driver for no chip
    "RTW88_8822CE": "module", "RTW89_8852AE": "module", "MT7921E": "module",
}
for sym, kind in WANT.items():
    check(requested.get(sym) == kind, f"linux: scripts/config must --{kind} {sym}")

# and the build has to FAIL when the result is not what we asked for
for sym in ("SND_HDA_GENERIC", "SND_HDA_CODEC_REALTEK", "SND_HDA_CODEC_HDMI",
            "SND_SOC_SOF_HDA_LINK", "SND_SOC_SOF_HDA_AUDIO_CODEC",
            "SND_SOC_INTEL_SKL_HDA_DSP_GENERIC_MACH", "SND_USB_AUDIO"):
    check(re.search(rf"^require_config CONFIG_{sym} [ym]$", configure, re.M),
          f"linux: missing require_config CONFIG_{sym}")
check(re.search(r"--disable WERROR", configure), "linux: --disable WERROR (wider driver set)")

# firmware the DSP and the speaker amplifiers load
for name in ("linux-firmware-lite", "linux-firmware-extra"):
    keep = re.search(r"KEEP='([^']*)'", recipe(f"recipes/boot/{name}/recipe.toml")["build"]["install"])
    words = keep.group(1).split() if keep else []
    for pat in ("intel/sof*", "amd/sof", "amd/sof-tplg", "cirrus"):
        check(pat in words, f"{name}: KEEP must contain {pat}")

# UCM profiles and topologies next to alsa-lib
alsa = recipe("recipes/extra/alsa-lib/recipe.toml")
for dep in ("alsa-ucm-conf", "alsa-topology-conf"):
    check(dep in alsa["depends"]["run"], f"alsa-lib must depend on {dep} at run time")
    r = recipe(f"recipes/extra/{dep}/recipe.toml")
    check(r["package"]["name"] == dep, f"{dep}: wrong package name")
    check("/usr/share/alsa" in r["build"]["install"], f"{dep}: must install under /usr/share/alsa")

for e in errors:
    print("FAIL", e)
print(f"kernel audio: {len(WANT)} options, {'OK' if not errors else f'{len(errors)} problem(s)'}")
sys.exit(1 if errors else 0)
