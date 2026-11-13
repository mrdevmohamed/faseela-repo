# Recipes

Every package in the distribution is described by a declarative
`recipe.toml` file. Layout:

```
recipes/
├── toolchain/   compiler + libc + headers (built first, stage 2)
├── base/        core userland: libs, shells, compressors, interpreters
├── system/      networking, udev, kmod, shadow, runit, man pages, ...
├── boot/        linux kernel, efibootmgr, grub, busybox (initramfs/rescue)
├── gui/         optional Wayland desktop stack and shared services: Sway, PipeWire, NetworkManager, BlueZ, seatd-runit, ... (opt-in)
├── cosmic/      optional COSMIC Wayland desktop and applications (opt-in)
├── greeter/     optional login daemon and greeter packages (opt-in)
├── browser/     optional Firefox/Google Chrome and their GTK3 browser stack (opt-in, on top of gui/)
├── xfce/        optional Xfce 4.20 desktop, applications, LightDM and greeter (opt-in)
├── xorg/        optional X11 display stack: Xorg server, input driver and client utilities (opt-in)
├── media/       optional ffmpeg, mpv, Vulkan tools and codec/subtitle/render libs (opt-in)
├── creative/    optional Storytold Craft desktop apps for Wayland (opt-in)
├── messaging/  optional messaging apps such as Telegram Desktop (opt-in)
├── networking/ optional proxy/VPN clients such as Nekoray (opt-in)
├── security/   optional ProjectDiscovery reconnaissance and security tools (opt-in)
├── peripherals/ optional hardware integrations such as the Huion tablet control panel (opt-in)
├── extra/       general tools, editors, net utils, hw tools, misc libs
└── dev/         opt-in developer runtimes and toolchains
```

Current set: 10 toolchain + 39 base + 56 system + 8 boot + 96 extra =
**209 core packages**. Optional categories contain 134 GUI, 21 COSMIC, 2 greeter, 16 browser, 45 Xfce, 18 Xorg,
23 media, 15 creative, 1 messaging, 1 networking, 12 security, 1 peripheral
and 15 developer packages. The recipe tree contains **513 recipes** in total.

The normal Stage 2/Stage 3 build uses the core set. The GUI category is added
only when `WITH_GUI=1`; COSMIC, browser, media, creative, messaging, networking,
security, peripheral, developer, Xfce and Xorg packages remain opt-in.

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

**extra** — 95 general-purpose packages covering development/build
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

**gui, desktop services** — dbus-system → elogind → polkit; bluez and
network-manager; pipewire → wireplumber. Elogind provides login1 and PAM
session tracking while runit remains PID 1. NetworkManager uses wpa_supplicant and replaces dhcpcd;
PipeWire and WirePlumber start in the user's Sway session.

Verify any dependency chain — or the complete recipe graph — with:

```
nawa --recipes recipes deps <name>
nawa --recipes recipes deps-all        # full-tree topological order
```

## Optional hardware integrations

The `peripherals/` category contains vendor-specific device applications that
must not enter the default ISO. The optional `huiontablet` package provides
Huion's official HS64 control panel (pen pressure and button configuration)
for USB ID `256c:006f`. It is packaged from a checksum-pinned vendor DEB without
executing its Ubuntu maintainer scripts. The package installs a restricted
udev rule for the HS64, adds a desktop launcher, and starts the Huion tray /
background components in Faseela's Sway session.

Install it directly with `sudo nawa install huiontablet`. It remains an
optional, device-specific application and is deliberately excluded from
the standard Sway and Xfce desktop images.

## The Xfce / Xorg desktop (opt-in)

Two more opt-in categories form a complete X11 desktop, kept strictly out of
the default ISO and the Sway flavor:

* **`xorg/`** — the display layer: `xorg-server` 21.1 (Xorg with glamor/DRI3,
  udev hotplug, setuid-root classic seat path, no systemd), the
  `xf86-input-libinput` input driver, the X client libraries Xfce needs that
  were not already shipped for Xwayland (`libXdmcp`, `libpciaccess`,
  `libXinerama`, `libXmu`, `libXres`, `libXpresent`, `libXt`, and the XCB
  cursor library). Xorg is built without a SUID wrapper; rootless seat
  management still needs libseat integration with Faseela's seatd.
* **`gui/`** — shared storage services: `libblockdev` supplies UDisks2's
  filesystem and partition operations; `udisks2` is activated on demand by
  the system D-Bus and integrates with polkit and eudev without a systemd or
  dedicated runit service.
* **`xfce/`** — the Xfce 4.20 desktop itself: the core libraries
  (`libxfce4util`, `xfconf`, `libxfce4windowing`, `libxfce4ui`, `exo`,
  `garcon`, `tumbler`, plus `vte`, `libnotify`, `gtksourceview`), the desktop
  components (`xfwm4`, `xfce4-panel`, `xfdesktop`, `xfce4-session`,
  `xfce4-settings`, `xfce4-appfinder`, `xfce4-power-manager`, `thunar`), the
  applications and panel plugins. The `xfce-session` meta-package pulls in
  the X11/Xfce core and Faseela's US/Arabic keyboard-layout configuration.
  LightDM 1.33.1 and `lightdm-gtk-greeter` are separate selectable packages;
  they use Linux-PAM with `pam_elogind.so` and no systemd modules. The LightDM runit service is
  shipped but not pre-enabled because its X-server child currently inherits
  the daemon's root UID; rootless LightDM remains pending.

Everything is built X11-only (the upstream Wayland backends of libxfce4ui,
the panel, xfdesktop and the terminal are disabled), reuses the packaged
GTK3/mesa/dbus/polkit/pipewire stack, and needs no systemd: session power
actions go through polkit's shadow backend, UPower and PipeWire keep their
D-Bus/runit activation. Sources come from archive.xfce.org, xorg.freedesktop.org, GNOME and tagged
upstream GitHub releases. SHA-256 pins are recorded in each recipe.

The `iso-xfce` flavor includes Xfce, Xorg, LightDM and the standard desktop
applications. Build order for the session meta-package:

```
python3 scripts/check-recipes.py xfce-session
nawa --recipes recipes deps xfce-session
```


## The COSMIC desktop (opt-in)

The `cosmic/` category contains 21 recipes for the System76 COSMIC Wayland
desktop, all pinned to the `epoch-1.0.8` source snapshot. Each Rust package
uses Nawa's Cargo fetch phase and locked workspace dependency graph.
`cosmic-desktop` is the Faseela integration meta-package: it connects the
session to runit, D-Bus, elogind, PipeWire/WirePlumber, NetworkManager and the
COSMIC portal backend. It uses the shared `seatd-runit` package, which also
owns the seatd service and DRM render-node udev rule used by Sway; the service
is not duplicated in desktop-specific packages.

The `iso-cosmic` flavor selects `@cosmic` plus Firefox. The login stack
(`greetd` + `cosmic-greeter`) lives in the separate `greeter/` category and
remains selectable through the COSMIC package group. This keeps those login
packages and their dependencies out of the ISO and avoids taking over VT 1
during an ordinary package install. To inspect the dependency closure:

```sh
python3 scripts/check-recipes.py cosmic-desktop
nawa --recipes recipes deps cosmic-desktop
```

The uploaded recipe snapshot has not yet been validated by a complete clean
package build; the repository CI checks recipe structure and integration
contracts only.
