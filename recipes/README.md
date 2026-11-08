# Recipes

Every package in the distribution is described by a declarative
`recipe.toml` file. Layout:

```
recipes/
├── toolchain/   compiler + libc + headers (built first, stage 2)
├── base/        core userland: libs, shells, compressors, interpreters
├── system/      networking, udev, kmod, shadow, runit, man pages, ...
├── boot/        linux kernel, efibootmgr, grub, busybox (initramfs/rescue)
├── gui/         optional Wayland desktop: sway, PipeWire, NetworkManager, BlueZ, polkit, ... (opt-in)
├── browser/     optional Firefox/Google Chrome and their GTK3 browser stack (opt-in, on top of gui/)
├── media/       optional ffmpeg, mpv, Vulkan tools and codec/subtitle/render libs (opt-in)
├── creative/    optional Storytold Craft desktop apps for Wayland (opt-in)
├── messaging/  optional messaging apps such as Telegram Desktop (opt-in)
├── networking/ optional proxy/VPN clients such as Nekoray (opt-in)
├── security/   optional ProjectDiscovery reconnaissance and security tools (opt-in)
├── extra/       general tools, editors, net utils, hw tools, misc libs
└── dev/         opt-in developer runtimes and toolchains
```

Current set: 10 toolchain + 39 base + 54 system + 8 boot + 94 extra =
**205 core packages**. Optional categories contain 125 GUI, 16 browser, 23
media, 15 creative, 1 messaging, 1 networking, 12 security and 11 developer
packages. The recipe tree contains **409 recipes** in total.

The normal Stage 2/Stage 3 build uses the core set. The GUI category is added
only when `WITH_GUI=1`; browser, media, creative, messaging, networking,
security and developer packages remain opt-in.

The `dev/` category is opt-in and currently contains Node.js, Go, Deno, pip, pipx and their Python runtime dependencies; it is intentionally not selected by the default ISO flavors. The `llvm` recipe also builds clangd alongside Clang.

The first 47 `extra/` recipes are generated from a data table
(`scripts/recipe_data_extra.py`, `scripts/gen-recipes-extra.py`); the generator
overwrites, so newer recipes (and everything in `system/`, `boot/`, `gui/`, `creative/`, `messaging/`) are
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
* `[hooks]` scripts run on the target system (not at build time). For system users and groups, use `/usr/libexec/faseela/ensure-system-account` from `base-files`; do not assume `useradd`/`groupadd` are installed when a package archive is installed directly.

## Build order

**toolchain** — linux-headers → glibc → binutils → m4 → gmp → mpfr →
mpc → gcc → make → pkgconf

**base** — zlib → bzip2 → file → ncurses → readline → pcre2 → libffi →
expat → gdbm → gperf → coreutils → bash → tar → gzip → xz → zstd →
grep → gawk → sed → flex → bison → bc → diffutils → findutils →
gettext → texinfo → util-linux → perl → python → openssl → sqlite →
libunistring → libidn2 → less → rust → nawa (self-hosting)

**system** — attr → acl (POSIX ACLs), libcap → iputils (ping, arping,
clockdiff, tracepath), liburcu → bind-tools (dig, host, nslookup),
libndp, efivar (UEFI variable libraries and tools), then libpsl → curl → git → shadow → procps-ng →
psmisc → e2fsprogs → eudev → kmod → libpipeline → groff → man-db →
libmnl → iproute2 + net-tools → dhcpcd → sysklogd → runit

**boot** — linux; efibootmgr → grub → busybox

**extra** — 94 general-purpose packages covering development/build
utilities, network diagnostics, editors, hardware inspection, storage tools,
compression and command-line productivity. The live ISO's `iso-nogui` flavor
includes this category; inspect the current inventory with
`python3 scripts/recipe-ids.py recipes`.

**system, later additions** — attr/acl (extended attributes and POSIX ACLs),
libcap (Linux capabilities), iputils (IP diagnostics), tzdata (time zones),
chrony (NTP, runit service
`chronyd`, enabled by default), libnl → iw and wpa_supplicant (Wi-Fi, runit service
`wpa_supplicant`), lvm2 + cryptsetup (disk encryption, LUKS), smartmontools,
dmidecode, lm-sensors, iperf3. `tzdata` defaults to `Africa/Cairo` while preserving
an administrator's existing `/etc/localtime`; choose another zone by linking it
from `/usr/share/zoneinfo`. `wpa_supplicant` remains opt-in:
`nawa service enable wpa_supplicant`.

Cross-group examples: `curl` (system) pulls `pkgconf` (toolchain);
`flex` (base) pulls `m4` (toolchain) and `texinfo` (base);
`linux` (boot) pulls `bison`, `flex`, `perl` (base);
`wget` (extra) pulls `libpsl` (system) + `openssl`, `pcre2` (base);
`kbd` (extra) pulls `meson`, `ninja` (extra);
`iputils` (system) pulls `libcap` (system), `libidn2` (base), `meson`, `ninja`
(extra), and `pkgconf` (toolchain); `bind-tools` pulls `libcap`, `libuv`, `liburcu`, `openssl`
and `perl`; `coreutils` and `tar` pull `acl` + `attr` (system).

**gui, desktop services** — dbus-system → polkit / bluez / network-manager;
pipewire → wireplumber. NetworkManager uses wpa_supplicant and replaces dhcpcd;
PipeWire and WirePlumber start in the user's Sway session.

Verify any dependency chain — or the complete recipe graph — with:

```
nawa --recipes recipes deps <name>
nawa --recipes recipes deps-all        # full-tree topological order
```
