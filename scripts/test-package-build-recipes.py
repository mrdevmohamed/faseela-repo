#!/usr/bin/env python3
"""Regression checks for package recipes that failed in CI."""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]

assert not (ROOT / "scripts/write-nawa-lock.py").exists()
assert not (ROOT / "scripts/test-write-nawa-lock.py").exists()


def recipe(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


gcr = recipe("recipes/gui/gcr/recipe.toml")
gcr_configure = gcr["build"]["configure"]
assert "ssh_add_path = ''" in gcr_configure
assert "ssh_agent_path = ''" in gcr_configure
assert "sed -i" not in gcr_configure

linux = recipe("recipes/boot/linux/recipe.toml")
linux_configure = linux["build"]["configure"]
assert "require_config CONFIG_MODULES y" in linux_configure
assert "require_config CONFIG_KMOD y" not in linux_configure

xdg = recipe("recipes/gui/xdg-utils/recipe.toml")
xdg_compile = xdg["build"]["compile"]
assert "python" in xdg["depends"]["build"]
assert "xml.etree.ElementTree" in xdg_compile
assert "def synopsis_text(node):" in xdg_compile
assert "return synopsis_text(node)" in xdg_compile
assert 'Path("scripts/desc")' in xdg_compile
assert "Generated embedded help" in xdg_compile
assert r"\n" in xdg_compile
assert xdg_compile.index("python3 - <<'PY'") < xdg_compile.index("make -C scripts -j%{jobs} scripts")
assert "xmlto" not in xdg_compile

volk = recipe("recipes/media/volk/recipe.toml")
vulkan_tools = recipe("recipes/media/vulkan-tools/recipe.toml")
assert volk["package"]["version"] == vulkan_tools["package"]["version"] == "1.3.296"
assert volk["package"]["sha256"] == (
    "8ffd0e81e29688f4abaa39e598937160b098228f37503903b10d481d4862ab85"
)
assert {"cmake", "ninja", "vulkan-headers"} <= set(volk["depends"]["build"])
assert "volk" in set(vulkan_tools["depends"]["build"])

cjk = recipe("recipes/gui/noto-cjk/recipe.toml")
cjk_install = cjk["build"]["install"]
assert cjk["package"]["sha256"] == (
    "f5dc28a754e17327d99f0a612134d92c8dd6187314ae967cb77f25df60860139"
)
assert "binutils" in cjk["depends"]["build"]
assert "fontconfig" in cjk["depends"]["run"]
for font in (
    "NotoSansCJK-Regular.ttc",
    "NotoSansCJK-Bold.ttc",
    "NotoSerifCJK-Regular.ttc",
    "NotoSerifCJK-Bold.ttc",
):
    assert font in cjk_install
assert "70-fonts-noto-cjk.conf" in cjk_install
assert "etc/fonts/conf.d" in cjk_install
assert "fc-cache -f" in cjk["hooks"]["post_install"]

# Nawa's crates are fetched by the package manager's Cargo backend. There is
# deliberately no vendor tree and no recipe-side cargo fetch command.
nawa = recipe("recipes/base/nawa/recipe.toml")
nawa_text = (ROOT / "recipes/base/nawa/recipe.toml").read_text(encoding="utf-8")
# The commit, release and hash are bumped by scripts/pin-nawa-source.py (and by
# the automation that runs it), so check their shape rather than one pin.
assert nawa["package"]["rel"] >= 19
assert nawa["package"]["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
assert [source["name"] for source in nawa["package"]["sources"]] == ["nawa"]
assert re.fullmatch(
    r"https://github\.com/mrdevmohamed/nawa/archive/[0-9a-f]{40}\.tar\.gz",
    nawa["package"]["sources"][0]["url"],
)
assert re.fullmatch(r"[0-9a-f]{64}", nawa["package"]["sources"][0]["sha256"])
assert nawa["fetch"]["cargo"]["dir"] == "."
assert "rust" not in nawa.get("depends", {}).get("build", [])
assert nawa["build"]["compile"] == "cargo build --release --offline --locked"
assert "vendor/" not in nawa_text
assert "cargo fetch" not in nawa["build"]["compile"]

# A selected Nawa target must be bootstrapped from the pinned source with the
# seed Rust toolchain before the ordinary package loop can parse its recipe.
for workflow_path in (
    ".github/workflows/packages.yml",
    ".github/workflows/packages-experimental.yml",
):
    workflow = (ROOT / workflow_path).read_text(encoding="utf-8")
    assert "write-nawa-lock" not in workflow
    assert "nawa-source.toml" not in workflow
    assert 'RECIPE="$REPO/recipes/base/nawa/recipe.toml"' in workflow
    if workflow_path.endswith("/packages.yml"):
        assert "building nawa from its pinned source requires the seed rootfs" in workflow
        assert "Bootstrapping the selected Nawa source with the seed Rust toolchain." in workflow
        assert "cargo fetch --locked" in workflow
        assert "deps nawa" in workflow
        assert workflow.index("cargo fetch --locked") < workflow.index("bash /faseela/bootstrap/build-packages-inner.sh")

print("PACKAGE BUILD RECIPE REGRESSION CHECKS PASSED")
