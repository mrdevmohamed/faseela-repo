# Recipes

Every package in the distribution is described by a declarative
`recipe.toml` file. Layout:

```
recipes/
├── toolchain/   compiler + libc + headers (built first, stage 2)
├── base/        core userland: libs, shells, compressors, interpreters
├── system/      networking, udev, kmod, shadow, runit, man pages, ...
├── boot/        linux kernel, grub, busybox (initramfs/rescue)
├── gui/         optional Wayland desktop: sway, foot, mesa, ... (opt-in)
└── extra/       dev tools, editors, net utils, hw tools, misc libs
```

Current set: 10 toolchain + 39 base + 31 system + 6 boot + 67 extra =
**153 packages**, plus the optional `gui/` category (42 packages, see
[gui/README.md](gui/README.md)); the recipe tree counts 195 recipes in total.
`stage2`/`stage3` build everything **except** `gui/` unless `WITH_GUI=1`.

The first 47 `extra/` recipes are generated from a data table
(`scripts/recipe_data_extra.py`, `scripts/gen-recipes-extra.py`); the generator
overwrites, so newer recipes (and everything in `system/`, `boot/`, `gui/`) are
written by hand and are not in that table.

Recipes added without network access carry an all-zero `sha256` until
`python3 scripts/fill-sha256.py -r <name>` pins it (`check-recipes.py` lists
them). Versions and option names come from upstream knowledge, not a test build.

## Conventions

* `[depends].build` lists **recipe-level** build dependencies only.
  Tools provided by the bootstrap seed (bash, coreutils, sed, gawk,
  python3, curl, ...) are implicit and must NOT be declared. The exception
  is the Rust toolchain: it is the `rust` recipe, so a recipe that needs
  cargo (today only `nawa`) declares `build = ["rust"]`.
* `source` URLs point at proven-reachable mirrors: `mirrors.kernel.org`
  for GNU software, upstream hosts elsewhere. Substitutions used where an
  upstream host is unreachable from the build farm (documented per recipe):
  Debian `.orig` tarballs (file, procps-ng, psmisc, libpipeline, zip,
  unzip, tree, popt, libxml2), uwaterloo nongnu mirror (man-db),
  netfilter.org (libmnl), pyyaml.org (libyaml), tcpdump.org (libpcap).
  The sha256 pin is what guarantees integrity — any official mirror can be
  substituted.
* `%{version}` (and the other placeholders) are expanded in the `source`
  URL itself before downloading.
* `source` may also be a **single file** (not a tarball) — it is staged
  into srcdir as-is; used by `ca-certificates` for the pinned Mozilla CA
  bundle.
* `rel` must be bumped on every recipe change that changes the output.
* nawa slims every package after `install` (strip, cleanup) and splits man/info/doc
  into `<name>-doc` and gettext catalogs into `<name>-lang` — separate archives of
  the same version/rel that depend on `<name>`. Recipes need no changes; to opt out
  add `[slim]` with `strip = false`, `cleanup = false` and/or `split = false`.
* `%{...}` placeholders available in build sections: `name version rel
  arch jobs pkgdir srcdir`.
* `[hooks]` scripts run on the target system (not at build time).

## Build order

**toolchain** — linux-headers → glibc → binutils → m4 → gmp → mpfr →
mpc → gcc → make → pkgconf

**base** — zlib → bzip2 → file → ncurses → readline → pcre2 → libffi →
expat → gdbm → gperf → coreutils → bash → tar → gzip → xz → zstd →
grep → gawk → sed → flex → bison → bc → diffutils → findutils →
gettext → texinfo → util-linux → perl → python → openssl → sqlite →
libunistring → libidn2 → less → rust → nawa (self-hosting)

**system** — libpsl → curl → git → shadow → procps-ng → psmisc →
e2fsprogs → eudev → kmod → libpipeline → groff → man-db → libmnl →
iproute2 → dhcpcd → sysklogd → runit

**boot** — linux → grub → busybox

**extra** — 67 packages across three thematic sets plus a later batch:

* dev/build: autoconf, automake, libtool, patch, ninja, meson, cmake,
  lz4, libarchive, zip, unzip, pigz, brotli, p7zip
* net/editors: openssh, wget, rsync, libpcap, tcpdump, libnftnl,
  iptables, nftables, ethtool, libevent, vim, nano, tmux, htop, screen
* misc/libs/hw: jq, which, time, cpio, tree, popt, logrotate, cronie,
  ca-certificates, libxml2, libyaml, dosfstools, parted, mdadm,
  pciutils, usbutils, libusb, kbd (meson-based)

* later additions — user tools and hardware: lsof, strace, ncdu, socat,
  bash-completion, man-pages, wireguard-tools, exfatprogs, brightnessctl,
  alsa-lib, alsa-utils, zsh, nnn, fastfetch, pv, lua, nasm, libjpeg-turbo,
  valgrind, gdb

**system, later additions** — tzdata (time zones), chrony (NTP, runit service
`chronyd`), libnl → iw and wpa_supplicant (Wi-Fi, runit service
`wpa_supplicant`), lvm2 + cryptsetup (disk encryption, LUKS), smartmontools,
dmidecode, lm-sensors, iperf3. The two services are available but not enabled:
`nawa service enable chronyd` / `nawa service enable wpa_supplicant`.

Cross-group examples: `curl` (system) pulls `pkgconf` (toolchain);
`flex` (base) pulls `m4` (toolchain) and `texinfo` (base);
`linux` (boot) pulls `bison`, `flex`, `perl` (base);
`wget` (extra) pulls `libpsl` (system) + `openssl`, `pcre2` (base);
`kbd` (extra) pulls `meson`, `ninja` (extra).

Verify any chain — or the whole 153-package graph at once — with:

```
nawa --recipes recipes deps <name>
nawa --recipes recipes deps-all        # full-tree topological order
```
