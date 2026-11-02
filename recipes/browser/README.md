# recipes/browser — Firefox

**Firefox ESR** (Mozilla's official binary) and the GTK3 stack it runs on. The
browser recipes remain a separate category, but Firefox is included in the standard
`iso-gui` image. 12 packages:

| group | packages |
|---|---|
| browser | firefox |
| toolkit | gtk3 gdk-pixbuf libepoxy at-spi2-core dbus |
| X11 client libraries | libXfixes libXi libXcursor libXrandr libXcomposite libXdamage |

(libX11, libxcb, libXau, libXext and libXrender are in `gui/`: cairo links them.)

> **Status: written offline, not yet built**, like `gui/`. Every `sha256` is an
> all-zero placeholder and versions, URLs and meson option names come from
> upstream knowledge, not from a test build. See "First build" below.

## Why a separate category

The GTK3/browser recipes stay under `recipes/browser/`, keeping `@gui` limited to
the desktop stack. The `iso-gui` flavor explicitly includes `firefox`, so its
runtime dependency closure (GTK3 and the required X11 client libraries) is installed
in the standard GUI ISO. The package workflow builds everything required by
`flavor:iso-gui`; use `@browser` when you need to build just the browser category.

For an already-installed system, Firefox can also be installed directly:

```
nawa install firefox --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable
```

`ALL` / `@all` still does not include `@browser` or `@gui`.

## Why the official binary

Firefox from source needs clang, nodejs, cbindgen, the whole GTK/X11/NSS/ICU stack and
16+ GB of RAM and 30+ GB of disk for the link step: out of reach for a hosted runner,
and the `llvm` recipe is X86-only shared libraries without clang. So `firefox` is a
prebuilt upstream binary pinned by sha256, the same trust boundary as the `rust`
recipe. It follows the **ESR** branch (security fixes only); the download URL and file
name carry the `esr` suffix that `version` does not.

## Why GTK3 with an X11 backend in a Wayland-only distro

Mozilla's official build is one binary for X11 and Wayland: it is a GTK3 build with
X11 support compiled in, so `libxul.so` links libgdk-3 and the X11 client libraries
(libX11, libxcb, Xext, Xrender, Xrandr, ...) even when it runs on Wayland. Those
libraries must exist for it to load, though nothing ever talks to an X server.
So the stack ships the X11 **client** libraries and GTK3 with both backends; in a sway
session without Xwayland, GDK and Firefox pick Wayland on their own. Which libraries
exactly are needed is decided by the `ldd` guard of the `firefox` recipe (below), not by
this list. cairo is rebuilt
once for it (`glib=enabled` → libcairo-gobject, `xlib=enabled`): there can only be one cairo.

## First build

1. `python3 scripts/fill-sha256.py -r firefox` and `python3 scripts/fill-sha256.py` for
   the rest. Compare Firefox's hash with its line in
   `https://ftp.mozilla.org/pub/firefox/releases/<version>esr/SHA256SUMS`
   (`linux-x86_64/en-US/firefox-<version>esr.tar.xz`). A 404 means the point release is
   gone: bump `version` (and `rel`).
2. Expect to fix a meson option here and there (`at-spi2-core`, `gdk-pixbuf`, `gtk3` and
   `dbus` have the most), as in `gui/`.
3. **The `firefox` build checks itself.** Its `install` step runs `ldd` on `firefox`,
   `firefox-bin` and every bundled `.so` and fails with the list of missing libraries.
   If it names one (libXt, libXtst, libasound...), add a recipe for it and list it in
   `[depends]` of `firefox` — that is the intended way to find out, not a bug.
4. `xcb-proto` installs its python module under `/usr/lib/python3.X/site-packages`:
   when the `python` recipe changes minor version, bump `xcb-proto` and rebuild `libxcb`.

## Using it

```
dbus-run-session -- sway      # a session bus: "firefox <url>" reaches the running window
firefox
```

* The content sandbox needs user namespaces and seccomp; the `linux` recipe enables both.
* Updates come from nawa: `distribution/policies.json` sets `DisableAppUpdate`.
* Software rendering through mesa's llvmpipe works; give the VM several cores and 2 GB+
  of RAM (see `gui/README.md`, "Limitations").

## Limitations

* English (en-US) only. Language packs are separate downloads from Mozilla
  (`.../linux-x86_64/xpi/<lang>.xpi`) and are not packaged.
* No system D-Bus service, no `messagebus` user or portals. The Sway session starts
  PipeWire and WirePlumber per-user; `pipewire-pulse` provides the PulseAudio-compatible
  socket used by Firefox through `libpulse`. There is no separate PulseAudio daemon.
* No icon theme and no `shared-mime-info` (GTK dialogs show placeholder icons, file
  types are guessed by Firefox itself). `hicolor-icon-theme` and `adwaita-icon-theme`
  are the natural next recipes.
* GSettings schemas are compiled by `gtk3`'s post-install hook; a package installed
  later that ships schemas needs the same hook.
