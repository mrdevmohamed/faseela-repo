# Podman support for Faseela

Status: implementation plan; no Podman package is published yet.

Podman is an optional developer/container feature. It must not enter
`bootstrap`, `rootfs-min`, `iso-nogui`, `iso-gui`, or the default build
closure. Faseela uses **runit**, not systemd. Podman is daemonless, so the
engine itself must not be packaged as a permanently enabled system service.

## Target user experience

After installing the optional container flavor and completing the one-time
rootless setup, both of these must work:

```sh
podman run --rm docker.io/library/hello-world
podman run --rm -p 8080:80 docker.io/library/nginx
```

The first command is the baseline image/pull/runtime test. The second also
checks networking and port forwarding. Rootless operation is a release
requirement, not an optional follow-up.

## Package split

Keep the components separate so they can be upgraded and tested independently:

| Package | Responsibility |
|---|---|
| `podman` | CLI, engine, API client and configuration |
| `containers-common` | runit-compatible engine, storage and registry defaults |
| `conmon` | OCI container monitor |
| `catatonit` | per-container pause/init process and child reaping |
| `crun` | default OCI runtime |
| `netavark` | rootful/rootless network setup and firewall rules |
| `aardvark-dns` | container-name DNS for Netavark networks |
| `passt` | rootless pasta networking and port forwarding |
| `fuse-overlayfs` | rootless overlay storage fallback |
| `libseccomp` | syscall filtering support |
| `libgpg-error`, `libassuan`, `gpgme` | image-signature support where required by the selected build |
| `libbtrfs`, `lvm2` | optional storage backends; do not make Btrfs/Device Mapper mandatory for the overlay default |

Do not add `runc` as a second default runtime unless a concrete compatibility
need is demonstrated. Do not add Docker, dockerd, or a systemd compatibility
layer as Podman dependencies.

## Build and dependency work

The repository already has Go and Rust toolchains. Two compiled source recipes have built successfully through Nawa:
`libseccomp` 2.6.1 (security-fixed upstream release) and `crun` 1.30.1. The
crun recipe explicitly disables systemd integration and links to the declared
libcap, libseccomp and json-c dependencies. A third recipe, `containers-common`,
packages local, version-controlled defaults using Nawa's recipe-local asset
support. It selects `cgroupfs` for the runit host, `crun`, Netavark, rootless
`pasta`, and enforcing short-name resolution. It leaves Netavark's default
rootless network directory under the user's graphroot instead of forcing the
rootful `/etc/containers/networks` path on unprivileged users. Its storage defaults
prefer kernel OverlayFS and leave automatic `fuse-overlayfs` discovery available
rather than forcing FUSE on every host. The config package still needs an end-to-end
install and Podman validation. Netavark, aardvark-dns and fuse-overlayfs now
have checksum-pinned Cargo recipes, but their Nawa builds are not yet confirmed.
The remaining packages to implement are conmon, catatonit and the Podman CLI.
A pinned `passt` recipe now builds both `passt` and `pasta`; its package build and
rootless port-forwarding behavior still need validation.

The initial CLI target is Podman 6.1.4. Its upstream `go.mod` declares Go
1.26.0, while Faseela's opt-in `golang` recipe is 1.27.3. Nawa already has
a dedicated `[fetch.go]` backend: it fetches the locked module graph before
the build and then enforces `GOPROXY=off` during compilation. The Podman
recipe must use that backend rather than run `go mod download` in its build
script or ship a locally maintained vendor directory.

Use the upstream Podman release's dependency versions as a compatibility set.
Netavark and aardvark-dns must use matching major/minor release lines;
the recipes now pin v2.1.0 for both. Their source crates are fetched from
crates.io with checksums verified against the crates.io index, then Cargo
dependencies are fetched from each crate's lockfile through Nawa's locked Cargo
backend. No local `vendor/` tree is maintained. Netavark 2.x is intended for
Podman 6.x and requires Rust 1.88 or newer; Faseela's pinned Rust recipe is
1.96.1 and meets that minimum. Netavark's build script invokes `protoc`
through `tonic-prost-build`, so an opt-in `protobuf-compiler` recipe was
added. It packages the official upstream protoc 36.2 x86_64 release artifact
with its verified SHA-256; it is a prebuilt build tool, not a source-compiled
runtime library. The `fuse-overlayfs` 2.0.0 crate is also pinned from crates.io
and built through the same offline Cargo backend; its upstream MSRV is 1.85.0,
which the Faseela Rust toolchain satisfies. Netavark, Aardvark, fuse-overlayfs and passt
still need actual Nawa package builds and runtime validation.

Every recipe must use Nawa's declared source list/build model, build offline
after source staging, declare all recipe-level build/runtime dependencies,
install only into `%{pkgdir}`, and carry a verified SHA-256. No vendored
dependency tree or unpinned build-time downloads.

## Faseela-specific runtime integration

- No systemd units, generators, socket activation, or systemd libraries as
  mandatory runtime dependencies.
- No always-on Podman daemon. The optional API socket may be started per-user
  with a user-managed runit-compatible mechanism only if a real use case needs it.
- Install documented default `containers.conf`, `storage.conf`,
  `registries.conf`, and signature policy without overwriting administrator
  configuration on upgrades.
- Configure `crun` and `netavark` paths explicitly.
- Package the upstream-required `catatonit` pause process; do not substitute a
  permanent system service or a systemd unit.
- Rootless setup must document subordinate UID/GID ranges and ensure the
  required `newuidmap`/`newgidmap` helpers exist. Do not silently edit
  `/etc/subuid` or `/etc/subgid` for existing users.
- Prefer rootless `pasta` networking. Rootless networking and DNS must be
  verified rather than inferred from successful installation.
- Default storage should use kernel OverlayFS when supported, with
  `fuse-overlayfs` available as a rootless fallback.
- Document required kernel features: user namespaces, namespaces, cgroups
  (prefer unified v2), seccomp, OverlayFS, veth/bridge, and nftables support.

## Rootless provisioning and kernel contract

The Linux recipe now explicitly enables and asserts the kernel features needed
for container isolation and networking: user/PID/network/IPC/UTS namespaces,
cgroup controllers, seccomp filtering, veth, bridge/netfilter, FUSE and
OverlayFS. This is a kernel build-time contract, not proof that the running
kernel exposes every controller or that the host's cgroup hierarchy is
configured correctly.

Faseela's Shadow recipe now enables subordinate-ID support explicitly and
fails its package install if either helper is missing; it also enforces the
root-owned setuid mode. Still verify the installed binaries before enabling
rootless Podman:

```sh
command -v newuidmap newgidmap
stat -c '%A %U:%G %n' "$(command -v newuidmap)" "$(command -v newgidmap)"
```

Both helpers must be installed securely as root-owned setuid programs (normally
mode `4755`). Verify the actual installed package; do not assume that a binary
being present on disk is enough.

Each user needs non-overlapping subordinate UID and GID ranges, normally at
least 65,536 IDs, in `/etc/subuid` and `/etc/subgid`. Inspect existing ranges
before assigning one. For a free range, an administrator can use:

```sh
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 USERNAME
grep '^USERNAME:' /etc/subuid /etc/subgid
```

Replace `USERNAME` with the account name and choose a range that does not
overlap any existing user's allocation or a real system UID/GID. Log out and
back in after changing mappings. Never silently allocate ranges or rewrite
these files during package installation.

On the running system, check the active cgroup v2 mount and controllers:

```sh
findmnt -t cgroup2
cat /sys/fs/cgroup/cgroup.controllers
```

Rootless mode must be tested as an ordinary user, not as root. The kernel
configuration alone cannot guarantee that unprivileged user namespaces are
permitted by host policy, that subordinate ranges are valid, or that the
cgroup controllers are delegated to the user's session.

## Required acceptance tests

1. Offline recipe validation and dependency ordering for every package.
2. Build each source package through the normal Nawa package workflow.
3. Install the optional flavor on a clean Faseela rootfs and verify
   `podman --version`, `podman info`, and the selected OCI runtime/network paths.
4. Rootless pull and run of `hello-world` as an unprivileged user.
5. Rootless port publishing and container DNS using Netavark/Aardvark.
6. Bind mounts, named volumes, image removal and container cleanup.
7. Rootful smoke test as a separate test; it must not substitute for rootless.
8. Verify no Podman-related package installs or enables a systemd service and
   no default ISO/bootstrap flavor gains a container dependency.

Only add a `developer-containers` flavor after all required recipes resolve and
the build/install smoke tests pass. Until then, keep Podman marked Planned in
the developer inventory.
