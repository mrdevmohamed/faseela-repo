#!/usr/bin/env python3
"""Guard the initial Podman prerequisite and keep it out of default images."""

from pathlib import Path
import re
import json
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
assert linux["package"]["rel"] == 24
kernel_config = linux["build"]["configure"]
for option in (
    "PID_NS", "NET_NS", "IPC_NS", "UTS_NS", "CGROUPS", "CGROUP_PIDS",
    "MEMCG", "CGROUP_SCHED", "FAIR_GROUP_SCHED", "CGROUP_CPUACCT",
    "CGROUP_FREEZER", "SECCOMP", "SECCOMP_FILTER", "VETH", "BRIDGE",
    "BRIDGE_NETFILTER",
):
    assert f"--enable {option}" in kernel_config, f"kernel config does not enable {option}"
    assert f"require_config CONFIG_{option} y" in kernel_config, f"kernel config does not assert {option}"

runit_services = recipe("recipes/system/runit-services/recipe.toml")
assert runit_services["package"]["rel"] == 13
runit_install = runit_services["build"]["install"]
stage1 = runit_install.split("cat > %{pkgdir}/etc/runit/1 <<'EOF'\n", 1)[1].split(
    "\nEOF\ncat > %{pkgdir}/etc/runit/2", 1
)[0]
assert "mkdir -p /sys/fs/cgroup" in stage1
assert "mountpoint -q /sys/fs/cgroup" in stage1
assert "mount -t cgroup2 none /sys/fs/cgroup" in stage1
assert stage1.index("mount -a") < stage1.index("mount -t cgroup2"), (
    "cgroup2 should be mounted after fstab mounts have been processed"
)

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

passt = recipe("recipes/system/passt/recipe.toml")
passt_pkg = passt["package"]
assert passt_pkg["version"] == "2026_07_16.090d739"
assert passt_pkg["sha256"] == "503e1f91cb52a8c0d04e6671a66063475b8a2d5d0b7fd428aad48ad6ef0443ee"
assert passt_pkg["source"].startswith("https://passt.top/passt/snapshot/")
assert {"make", "gcc"} <= set(passt["depends"]["build"])
assert "PAGE_SIZE=4096" in passt["build"]["compile"]
assert "PAGE_SIZE=4096" in passt["build"]["install"]
assert "%{pkgdir}/usr/bin/pasta" in passt["build"]["install"]
assert "%{pkgdir}/usr/bin/passt" in passt["build"]["install"]

fuse_overlayfs = recipe("recipes/system/fuse-overlayfs/recipe.toml")
fuse_pkg = fuse_overlayfs["package"]
assert fuse_pkg["version"] == "2.0.0"
assert fuse_pkg["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
assert fuse_pkg["license"] == ["GPL-2.0-or-later"]
assert fuse_pkg["sources"][0]["sha256"] == "89a46041b603f8ed3393d69be608777fc1f5cba7744afd7542a72e777b91fa36"
assert fuse_overlayfs["fetch"]["cargo"]["dir"] == "."
assert "--locked --offline --bin fuse-overlayfs" in fuse_overlayfs["build"]["compile"]
assert "/usr/bin/fuse-overlayfs" in fuse_overlayfs["build"]["install"]

netavark = recipe("recipes/system/netavark/recipe.toml")
netavark_pkg = netavark["package"]
assert netavark_pkg["version"] == "2.1.0"
assert netavark_pkg["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
assert netavark_pkg["sources"][0]["sha256"] == "a7a69b66f7d6700d0202467820c343e35edade9e115bb2ac6f28f2630f4bb060"
assert netavark_pkg["sources"][0]["strip_components"] == 1
assert netavark["fetch"]["cargo"]["dir"] == "."
assert "protobuf-compiler" in netavark["depends"]["build"]
assert {"aardvark-dns", "nftables"} <= set(netavark["depends"]["run"])
assert "--locked --offline --bin netavark" in netavark["build"]["compile"]
assert "/usr/libexec/podman/netavark" in netavark["build"]["install"]
assert "systemd" not in str(netavark["depends"]).lower()

aardvark = recipe("recipes/system/aardvark-dns/recipe.toml")
aardvark_pkg = aardvark["package"]
assert aardvark_pkg["version"] == "2.1.0"
assert aardvark_pkg["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
assert aardvark_pkg["sources"][0]["sha256"] == "9f766fcc7f3d8e35da54bca2afc3339c3ff60c24d380d706fa18187055e5c818"
assert aardvark["fetch"]["cargo"]["dir"] == "."
assert "--locked --offline --bin aardvark-dns" in aardvark["build"]["compile"]
assert "/usr/libexec/podman/aardvark-dns" in aardvark["build"]["install"]

podman = recipe("recipes/system/podman/recipe.toml")
podman_pkg = podman["package"]
assert podman_pkg["version"] == "6.1.4"
assert podman_pkg["sha256"] == "200fd9b4b6d820cae24fc99d8e290ec945512365cf3cda8283b3905c0c284ea8"
assert "golang" in podman["depends"]["build"]
assert {"libseccomp", "sqlite"} <= set(podman["depends"]["build"])
assert {"ca-certificates", "conmon", "catatonit", "containers-common", "crun", "netavark", "aardvark-dns", "passt", "fuse-overlayfs", "shadow", "nftables"} <= set(podman["depends"]["run"])
assert "fetch" not in podman, "vendored upstream modules need no Go fetch backend"
assert "-mod=vendor" in podman["build"]["compile"]
assert "systemd" not in podman["build"]["compile"].lower()
assert "containers_image_openpgp" in podman["build"]["compile"]
assert "exclude_graphdriver_btrfs" in podman["build"]["compile"]
assert "libsqlite3" in podman["build"]["compile"]
assert "%{pkgdir}/usr/bin/podman" in podman["build"]["install"]

conmon = recipe("recipes/system/conmon/recipe.toml")
conmon_pkg = conmon["package"]
assert conmon_pkg["version"] == "2.2.1"
assert conmon_pkg["sha256"] == "814fb5979a3a4b8576b1f901e606b482bebb41cb7e57926e6d5765ee786b96d3"
assert {"gcc", "make", "pkgconf", "glib", "libseccomp"} <= set(conmon["depends"]["build"])
assert {"glib", "libseccomp"} <= set(conmon["depends"]["run"])
assert "DISABLE_SYSTEMD=1" in conmon["build"]["compile"]
assert "DESTDIR=%{pkgdir}" in conmon["build"]["install"]
assert "LIBEXECDIR=/usr/libexec" in conmon["build"]["install"]
assert "install.podman" in conmon["build"]["install"]

catatonit = recipe("recipes/system/catatonit/recipe.toml")
catatonit_pkg = catatonit["package"]
assert catatonit_pkg["version"] == "0.2.1"
assert catatonit_pkg["sha256"] == "771385049516fdd561fbb9164eddf376075c4c7de3900a8b18654660172748f1"
assert {"autoconf", "automake", "libtool", "make", "gcc"} <= set(catatonit["depends"]["build"])
assert catatonit["build"]["prepare"] == "./autogen.sh"
assert "./configure --prefix=/usr" in catatonit["build"]["configure"]
assert "DESTDIR=%{pkgdir}" in catatonit["build"]["install"]
assert "/usr/libexec/podman/catatonit" in catatonit["build"]["install"]

protoc = recipe("recipes/dev/protobuf-compiler/recipe.toml")
protoc_pkg = protoc["package"]
assert protoc_pkg["name"] == "protobuf-compiler"
assert protoc_pkg["version"] == "36.2"
assert protoc_pkg["source_date_epoch"] == 1789666294
assert protoc_pkg["sha256"] == "121f6c7afe1d4d0e3ea6aab9432038599250134cbf4474cb1167d2c7decd4278"
assert protoc_pkg["source"].endswith("protoc-%{version}-linux-x86_64.zip")
assert "unzip" in protoc["depends"]["build"]
assert "extracted/bin/protoc" in protoc["build"]["install"]
assert "%{pkgdir}/usr/bin/protoc" in protoc["build"]["install"]

common = recipe("recipes/system/containers-common/recipe.toml")
common_pkg = common["package"]
assert common_pkg["name"] == "containers-common"
assert common_pkg["source_date_epoch"] == 1767225600
assert common_pkg["rel"] == 3
assert common_pkg["source"] == "local:/nawa-schema-2-requires-a-newer-nawa"
assets = common["assets"]["include"]
assert set(assets) == {"containers.conf", "storage.conf", "registries.conf", "policy.json"}
install = common["build"]["install"]
assert "%{assetsdir}" in install and "%{pkgdir}" in install
assert "/usr/share/containers/policy.json" in install

common_dir = ROOT / "recipes/system/containers-common"
containers_conf = tomllib.loads((common_dir / "containers.conf").read_text(encoding="utf-8"))
storage_conf = tomllib.loads((common_dir / "storage.conf").read_text(encoding="utf-8"))
registries_conf = tomllib.loads((common_dir / "registries.conf").read_text(encoding="utf-8"))
policy = json.loads((common_dir / "policy.json").read_text(encoding="utf-8"))
assert policy["default"], "policy.json needs a default policy"
assert containers_conf["engine"]["cgroup_manager"] == "cgroupfs"
assert containers_conf["engine"]["runtime"] == "crun"
assert containers_conf["network"]["network_backend"] == "netavark"
assert containers_conf["network"]["default_rootless_network_cmd"] == "pasta"
assert "/usr/bin" in containers_conf["engine"]["helper_binaries_dir"]
assert "network_config_dir" not in containers_conf["network"], "preserve Netavark rootless per-user network directory"
assert storage_conf["storage"]["driver"] == "overlay"
assert "runroot" not in storage_conf["storage"], "runroot breaks rootless users"
assert "graphroot" not in storage_conf["storage"], "graphroot is applied to rootless users and breaks them"
assert "rootless_storage_path" not in storage_conf["storage"], "rootless_storage_path is deprecated"
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
for default in ("bootstrap", "rootfs-min", "iso-nogui", "iso-sway"):
    section = flavors.split(f"[flavor.{default}]", 1)[1].split("[flavor.", 1)[0]
    assert all(name not in section for name in ("podman", "developer-containers", "containers-common", "conmon", "catatonit", "crun", "libseccomp", "protobuf-compiler", "netavark", "aardvark-dns", "fuse-overlayfs", "passt"))

docs = (ROOT / "docs/podman-support.md").read_text(encoding="utf-8")
assert "Faseela uses **runit**, not systemd" in docs
assert "Rootless operation is a release" in docs
assert "libseccomp" in docs
assert "\\n" not in docs, "documentation contains literal escaped newline sequences"
for component in ("conmon", "catatonit", "containers-common", "netavark", "aardvark-dns", "passt", "fuse-overlayfs"):
    assert f"| `{component}` |" in docs, f"missing documented component: {component}"

print("PODMAN PREREQUISITE REGRESSION CHECKS PASSED")
