#!/usr/bin/env python3
"""Guard the initial Podman prerequisite and keep it out of default images."""

from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def recipe(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))


shadow = recipe("recipes/system/shadow/recipe.toml")
assert shadow["package"]["rel"] == 3
assert "--enable-subids" in shadow["build"]["configure"]
shadow_install = shadow["build"]["install"]
for helper in ("newuidmap", "newgidmap"):
    assert f"/usr/bin/$helper" in shadow_install
assert "chmod 4755" in shadow_install

linux = recipe("recipes/boot/linux/recipe.toml")
assert linux["package"]["rel"] == 22
kernel_config = linux["build"]["configure"]
for option in (
    "PID_NS", "NET_NS", "IPC_NS", "UTS_NS", "CGROUPS", "CGROUP_PIDS",
    "MEMCG", "CGROUP_SCHED", "FAIR_GROUP_SCHED", "CGROUP_CPUACCT",
    "CGROUP_FREEZER", "SECCOMP", "SECCOMP_FILTER", "VETH", "BRIDGE",
    "BRIDGE_NETFILTER",
):
    assert f"--enable {option}" in kernel_config, f"kernel config does not enable {option}"
    assert f"require_config CONFIG_{option} y" in kernel_config, f"kernel config does not assert {option}"

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

common = recipe("recipes/system/containers-common/recipe.toml")
common_pkg = common["package"]
assert common_pkg["name"] == "containers-common"
assert common_pkg["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
assets = common["assets"]["include"]
assert set(assets) == {"containers.conf", "storage.conf", "registries.conf"}
install = common["build"]["install"]
assert "%{assetsdir}" in install and "%{pkgdir}" in install

common_dir = ROOT / "recipes/system/containers-common"
containers_conf = tomllib.loads((common_dir / "containers.conf").read_text(encoding="utf-8"))
storage_conf = tomllib.loads((common_dir / "storage.conf").read_text(encoding="utf-8"))
registries_conf = tomllib.loads((common_dir / "registries.conf").read_text(encoding="utf-8"))
assert containers_conf["engine"]["cgroup_manager"] == "cgroupfs"
assert containers_conf["engine"]["runtime"] == "crun"
assert containers_conf["network"]["network_backend"] == "netavark"
assert containers_conf["network"]["default_rootless_network_cmd"] == "pasta"
assert "/usr/bin" in containers_conf["engine"]["helper_binaries_dir"]
assert "network_config_dir" not in containers_conf["network"], "preserve Netavark rootless per-user network directory"
assert storage_conf["storage"]["driver"] == "overlay"
assert storage_conf["storage"]["runroot"] == "/run/containers/storage"
assert storage_conf["storage"]["graphroot"] == "/var/lib/containers/storage"
assert "mount_program" not in storage_conf["storage"]["options"]["overlay"]
assert registries_conf["unqualified-search-registries"] == ["docker.io"]
assert registries_conf["short-name-mode"] == "enforcing"

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
    assert all(name not in section for name in ("podman", "developer-containers", "containers-common", "crun", "libseccomp"))

docs = (ROOT / "docs/podman-support.md").read_text(encoding="utf-8")
assert "Faseela uses **runit**, not systemd" in docs
assert "Rootless operation is a release" in docs
assert "libseccomp" in docs
assert "\\n" not in docs, "documentation contains literal escaped newline sequences"
for component in ("conmon", "catatonit", "containers-common", "netavark", "aardvark-dns", "passt", "fuse-overlayfs"):
    assert f"| `{component}` |" in docs, f"missing documented component: {component}"

print("PODMAN PREREQUISITE REGRESSION CHECKS PASSED")
