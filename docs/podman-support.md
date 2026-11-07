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
| `containers-common` | shared registries, storage, policy and default configuration |
| `conmon` | OCI container monitor |
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

The repository currently has Go and Rust toolchains, but does not yet have the
complete container dependency closure. Before adding the Podman recipe, add
and validate missing prerequisites (at minimum the selected versions of
libseccomp, conmon, containers-common, crun, Netavark, aardvark-dns, passt and
fuse-overlayfs, plus any required image/signature libraries).

Use the upstream Podman release's dependency versions as a compatibility set.
In particular, Netavark and aardvark-dns major/minor release lines must match;
do not independently select arbitrary latest versions. The Netavark 2.x line
is intended for Podman 6.x and requires Rust 1.88 or newer. The Faseela Rust
recipe and the pinned upstream component versions must be checked before
selecting that line.

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
- Rootless setup must document subordinate UID/GID ranges and ensure the
  required `newuidmap`/`newgidmap` helpers exist. Do not silently edit
  `/etc/subuid` or `/etc/subgid` for existing users.
- Prefer rootless `pasta` networking. Rootless networking and DNS must be
  verified rather than inferred from successful installation.
- Default storage should use kernel OverlayFS when supported, with
  `fuse-overlayfs` available as a rootless fallback.
- Document required kernel features: user namespaces, namespaces, cgroups
  (prefer unified v2), seccomp, OverlayFS, veth/bridge, and nftables support.

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
