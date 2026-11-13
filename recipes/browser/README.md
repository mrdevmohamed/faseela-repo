# recipes/browser — Firefox, Google Chrome and WebKitGTK

**Firefox ESR**, official **Google Chrome Stable**, the GTK3 browser stack,
and optional **WebKitGTK 4.1** for applications that embed a web view.
The browser recipes remain a separate category. Firefox is included in the
standard `iso-sway` image; Google Chrome and WebKitGTK stay opt-in. 26 packages:

| group | packages |
|---|---|
| browser applications | firefox google-chrome |
| WebKitGTK engine | webkit2gtk-4.1 |
| WebKit dependencies | icu libsoup3 glib-networking gnutls nettle libtasn1 lcms2 libwebp openjpeg |
| Chrome runtime libraries | nspr nss libcups |
| toolkit | gtk3 gdk-pixbuf libepoxy at-spi2-core dbus |
| X11 client libraries | libXfixes libXi libXcursor libXrandr libXcomposite libXdamage |

(libX11, libxcb, libXau, libXext and libXrender are in `gui/`: cairo links them.)
Ruby, in `dev/`, is used as a WebKitGTK build tool and is pulled in by its build
dependency graph; it is not part of the normal browser runtime.

> The original GTK3 recipes still need their first full build/CI verification.
> The NSPR, NSS and libcups source hashes are pinned. Google Chrome is an
> install-time downloader: its proprietary .deb is fetched from Google and
> SHA-256 verified on the target machine; it is not redistributed by Faseela.

## Why a separate category

The GTK3/browser recipes stay under `recipes/browser/`, keeping `@gui` limited
to the desktop stack. The `iso-sway` flavor explicitly includes `firefox`, so
its runtime dependency closure (GTK3 and the required X11 client libraries)
is installed in the standard Sway ISO. Google Chrome and WebKitGTK are not
added to that ISO; install them only on systems that need them. The package
workflow builds everything required by `flavor:iso-sway`; use `@browser`
when you need to build the browser category.

For an already-installed system, Firefox can also be installed directly:

```
nawa install firefox --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable
```

Install the genuine Google browser (not Chromium) with:

```
sudo nawa install google-chrome
```

The first installation downloads Google's official x86_64 package (about
141 MiB) from `dl.google.com`, verifies its pinned SHA-256, and extracts the
browser. It does not add Google's APT repository or updater. The wrapper and
desktop launcher are managed by Nawa; future Chrome updates are delivered by
updating this recipe.

`ALL` / `@all` still does not include `@browser` or `@gui`.

## WebKitGTK 4.1 for Telegram Mini Apps

The `webkit2gtk-4.1` recipe builds the GTK3 WebKit API from the official
WebKitGTK 2.54.2 source release. It uses GTK3 (`USE_GTK4=OFF`) and keeps
the WebKit WebProcess bubblewrap sandbox enabled.

The initial minimal feature set keeps HTML rendering, JavaScript and HTTPS
networking. GnuTLS and `glib-networking` provide the GIO TLS backend used by
libsoup3. GStreamer, video, WebRTC, Web Audio, MediaRecorder, spellchecking,
speech synthesis and other optional features are disabled for this Telegram
Web Apps use case. As a result, embedded web video, calls and media capture
are not provided by this build.

WebKitGTK is large and must be built with the recipe's conservative two-job
limit. It is deliberately not selected by any ISO flavor. Installing
`telegram-desktop` pulls it in through the declared runtime dependency.

## Google Chrome package

The Chrome recipe is an install-time bootstrap package. The repository contains
only the small wrapper and installer hook, not Google's proprietary browser
payload. The hook pins the upstream version and checksum, retries interrupted
downloads, and skips the download when the same version is already installed.
It extracts only the browser, launcher, desktop file and icons; it does not
install Google's APT configuration or scheduled update jobs. The downloaded
package is licensed under Google's Chrome terms.

## Why the official Firefox binary

Firefox from source needs clang, nodejs, cbindgen, the whole GTK/X11/NSS/ICU
stack and 16+ GB of RAM and 30+ GB of disk for the link step: out of reach for
a hosted runner, and the `llvm` recipe is X86-only shared libraries without
clang. So `firefox` is a prebuilt upstream binary pinned by sha256, the same
trust boundary as the `rust` recipe. It follows the **ESR** branch (security
fixes only); the download URL and file name carry the `esr` suffix that
`version` does not.

## Why GTK3 with an X11 backend in a Wayland-only distro

Mozilla's official build is one binary for X11 and Wayland: it is a GTK3 build
with X11 support compiled in, so `libxul.so` links libgdk-3 and the X11 client
libraries (libX11, libxcb, Xext, Xrender, Xrandr, ...) even when it runs on
Wayland. Those libraries must exist for it to load, though nothing ever talks
to an X server. So the stack ships the X11 **client** libraries and GTK3 with
both backends; in a sway session without Xwayland, GDK and Firefox pick
Wayland on their own. Which libraries exactly are needed is decided by the
`ldd` guard of the `firefox` recipe (below), not by this list. cairo is
built once with its GTK-compatible Xlib and GLib surfaces.

## First build

1. Run `python3 scripts/fill-sha256.py -r firefox` and
   `python3 scripts/fill-sha256.py` for the rest. Compare Firefox's hash with
   its line in Mozilla's `SHA256SUMS` for the matching ESR release.
2. Expect to fix a meson option here and there (`at-spi2-core`,
   `gdk-pixbuf`, `gtk3` and `dbus` have the most), as in `gui/`.
3. **The `firefox` build checks itself.** Its install step runs `ldd` on
   `firefox`, `firefox-bin` and every bundled `.so` and fails with the
   list of missing libraries. Add any missing shared-library recipe to
   Firefox's `[depends]`.
4. Build WebKitGTK separately with:
   `python3 scripts/check-recipes.py webkit2gtk-4.1`, then select
   `webkit2gtk-4.1` in **Actions → Build packages → Run workflow**.
   Its `ninja -j2` setting is intentional: WebKit's C++ compilation is
   memory-intensive on hosted runners.

## Using it

```
dbus-run-session -- sway      # a session bus: "firefox <url>" reaches the running window
firefox
```

* Firefox's content sandbox needs user namespaces and seccomp; the `linux`
  recipe enables both. WebKitGTK's WebProcess uses bubblewrap.
* Updates come from nawa: `distribution/policies.json` sets `DisableAppUpdate`.
* Software rendering through Mesa's llvmpipe works; give the VM several cores
  and 2 GB+ of RAM (see `gui/README.md`, "Limitations").

## Limitations

* Firefox is English (en-US) only. Language packs are separate downloads from
  Mozilla (`.../linux-x86_64/xpi/<lang>.xpi`) and are not packaged.
* The Sway session starts PipeWire and WirePlumber per-user;
  `pipewire-pulse` provides the PulseAudio-compatible socket used by Firefox
  through `libpulse`. There is no separate PulseAudio daemon.
* `hicolor-icon-theme` and `adwaita-icon-theme` provide standard icon
  fallbacks for GTK dialogs.
* GSettings schemas are compiled by GTK3's post-install hook; a package
  installed later that ships schemas needs the same hook.
