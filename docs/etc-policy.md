# What packages put under /etc

`/etc` belongs to the administrator and to the machine. A package that ships a
file there makes the administrator's copy and the package's copy compete, and
nawa resolves the competition by keeping the local file and writing the
package's version beside it as `<file>.nawa-new`. That is correct for a file a
person edited. It is noise, and a sign of a wrong design, for a file nobody
edited, such as `resolv.conf`, which every build root, chroot and booted system
replaces with its own.

The rule is therefore:

1. **Vendor defaults live under `/usr`.** The administrator overrides them in
   `/etc`. A package upgrade can always replace a default, and nothing needs
   merging.
2. **Machine state is never shipped.** It is created when the machine is
   installed or booted.
3. **Only what has no other place stays in `/etc`**, and each such path is
   listed, with the reason, in [`etc-policy.toml`](../etc-policy.toml).

## Where things go

| What it is | Where the package puts it | Examples |
|---|---|---|
| Default configuration of a program that reads a vendor directory | the vendor directory under `/usr` | `/usr/lib/NetworkManager/conf.d`, `/usr/lib/udev/rules.d`, `/usr/lib/tmpfiles.d`, `/usr/lib/sysctl.d`, `/usr/lib/systemd/system` |
| Distribution identity | `/usr/lib/os-release`, with `/etc/os-release` as a link | os-release |
| Machine state | nowhere in the package; created by a tmpfiles.d entry, a `post_install` hook that only acts when the file is missing, or the installer | `/etc/resolv.conf`, `/etc/machine-id`, `/etc/localtime` |
| A drop-in for a directory that exists to be extended | a numbered file in that directory | `/etc/profile.d/50-faseela-x.sh`, `/etc/sway/config.d/30-session.conf` |
| Configuration of a program that reads `/etc` only | `/etc`, listed in `etc-policy.toml` as `no-vendor-dir` | `/etc/pam.d/*`, `/etc/greetd/*` |

When two packages could want the same file, use a drop-in directory, not the
main file.

## The check

`scripts/check-etc-policy.py` reads every recipe and compares each
`%{pkgdir}/etc/...` path with `etc-policy.toml`:

- a path matching a `[[forbid]]` entry fails, and the message says what to use
  instead;
- a path matching no `[[allow]]` entry fails;
- a directory is accepted when a file inside it would be.

`scripts/test-etc-policy.py` tests the checker and runs it on the recipe tree;
CI runs both. Run it locally with `python3 -I scripts/check-etc-policy.py`.

The check sees only paths a recipe spells out. A program whose own
`make install` or `meson install` writes into `/etc` (because of
`--sysconfdir=/etc`) is not visible to it. For such programs set the build
option that moves the defaults to `/usr`, or move the files in the recipe's
`install` step.

### Adding an exception

Add an `[[allow]]` entry to `etc-policy.toml` with a category and a reason that
explains why the file cannot live under `/usr` or be created at install or
boot:

| Category | Meaning |
|---|---|
| `identity` | the account databases |
| `seed` | a default for a new system that the administrator owns from then on |
| `link` | a link with no content of its own |
| `drop-in` | a file inside a directory made to be extended |
| `no-vendor-dir` | the program reads `/etc` only |
| `generated` | a build product with a de-facto standard path |

## State of the migration

Moved out of `/etc` so far:

- `/etc/resolv.conf` is no longer shipped (base-files); systemd-units creates
  it at boot.
- `/etc/os-release` is a link to `/usr/lib/os-release` (base-files).
- The DRM render-node udev rule is in `/usr/lib/udev/rules.d` (seatd-systemd).
- NetworkManager's defaults are in `/usr/lib/NetworkManager/conf.d`
  (network-manager).

Listed in the policy but meant to move once they can be verified on a booted
system:

- **PAM stacks** (`/etc/pam.d/*`): Linux-PAM 1.7 can read `/usr/lib/pam.d`
  (`vendordir`). A wrong PAM stack locks everyone out, so this waits for a
  build and a login test of the image.
- **`/etc/hostname`**: systemd falls back to `DEFAULT_HOSTNAME` in
  `os-release`, which would make the file unnecessary.
- **`/etc/fstab`, `/etc/hosts`, `/etc/nsswitch.conf`, `/etc/profile`,
  `/etc/locale.conf`, `/etc/shells`**: seeds of a new system. Whether the
  installer rather than base-files should write them is a separate decision.

## Upgrading an existing system

nawa retires a file a package used to own when the new version stops shipping
it, and it does so even when the administrator edited that file (the removed
copy stays in the undo journal). Moving a file out of `/etc` therefore has two
effects on a system that already has the old package:

- `/etc/resolv.conf` disappears until the next boot (tmpfiles.d) or DHCP lease.
- `/etc/NetworkManager/NetworkManager.conf` disappears, so a local edit stops
  applying until the administrator puts it back as
  `/etc/NetworkManager/conf.d/*.conf` (recoverable with `nawa undo`).

`/etc/os-release` and the udev rule keep their meaning: the first becomes a link
to the vendor copy, the second is read from `/usr/lib/udev/rules.d` instead.

Nothing has been published to `stable-v5` yet, so for now this affects
development installs only. Once the repository is public, a move out of `/etc`
needs a line in the package's release notes.
