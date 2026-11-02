# recipes/media — ffmpeg and mpv

**ffmpeg** (convert / probe / stream audio and video, plus the `libav*` libraries) and
the **mpv** media player (with its on-screen controller), as an opt-in layer. 15 packages:

| group | packages |
|---|---|
| tools | ffmpeg mpv |
| decoding / subtitles / rendering | dav1d (AV1) libass (subtitles, OSD text) libplacebo (GPU video rendering) |
| encoders | x264 (H.264) x265 (H.265/HEVC) libvpx (VP8/VP9) opus lame (MP3) |
| hardware video | intel-media-driver gmmlib (Intel VA-API driver; libva and AMD's driver: see `gui/` libva, mesa) |
| scripting | lua52 (mpv's on-screen controller, stats, console) |
| build helpers (pure python) | python-jinja2 python-glad2 (libplacebo generates its GL loader with glad) |

Everything else comes from the existing categories: `freetype fribidi harfbuzz fontconfig`,
`wayland libxkbcommon mesa libdrm libva` (gui/), `alsa-lib libarchive libjpeg-turbo nasm` (extra/).

> **Status: written offline, not yet built**, like `gui/` and `browser/`. Every `sha256` is an
> all-zero placeholder, and versions, URLs and configure/meson option names come from upstream
> knowledge, not from a test build. See "First build" below.

## Install / build

```
nawa install mpv ffmpeg --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable
```

Build with *Build packages* → `mpv`, `ffmpeg`, `@media`, or `flavor:iso-gui-mpv` /
`flavor:iso-nogui-ffmpeg` (everything the flavor needs). `ALL` / `@all` does not include
`@media`, same as `@gui` and `@browser`. mpv needs the `gui/` stack (Wayland, mesa), ffmpeg does not.

## First build

1. `python3 scripts/fill-sha256.py -r ffmpeg -r mpv ...` (or without `-r` for the whole tree) pins the hashes;
   a 404 means that version is gone upstream: bump `version` and `rel`.
2. Build order: `python3 scripts/check-recipes.py mpv` prints it.
3. Things most likely to need a touch on the first build:
   * **libplacebo**: GitLab's source archives carry no git submodules, so its vendored glad is
     missing; the build uses the `python-glad2` package instead. If meson still asks for
     `3rdparty/glad`, switch `source` to a release tarball that includes the submodules.
   * **mpv**: option names are checked against 0.40's `meson.options`; `Unknown option` means a
     rename, fix it in the `configure` line.
   * **ffmpeg**: `--disable-autodetect` turns every optional library off, a missing
     `--enable-...` shows up as "feature not found" at the end of `configure`.

## Using it

```
mpv file.mkv                    # in a Wayland session (sway): vo=gpu-next
mpv --vo=drm file.mkv           # straight on a text console, no compositor (user in group video)
mpv --vo=wlshm file.mkv         # no GPU rendering at all: slow, but works anywhere Wayland does
mpv --hwdec=vaapi file.mkv      # hardware decoding (AMD: mesa, Intel: intel-media-driver)
mpv --hwdec=vaapi-copy file.mkv # Intel decode + llvmpipe drawing
ffmpeg -i in.mkv -c:v libx264 -crf 23 -c:a libopus out.mkv
ffmpeg -i in.mkv -vf subtitles=subs.ass -c:v libx265 -crf 28 out.mkv
ffprobe -hide_banner file.mkv
```

On the software-rendering setups of `gui/` (llvmpipe, QEMU) `vo=gpu-next` is heavy: try
`--vo=gpu --profile=fast`, or `--vo=wlshm` for plain playback.

## Limitations / next steps

* **Hardware video (VA-API)**: libva (`gui/`) loads a driver from `/usr/lib/dri`. AMD: mesa's
  `radeonsi_drv_video.so` (mesa builds `radeonsi` and the gallium VA driver since rel 3, which needs
  llvm's AMDGPU target). Intel gen8+: `intel-media-driver` (`iHD`) + `gmmlib` here. Both need the
  kernel driver (`amdgpu` / `i915` or `xe`, modules in the kernel recipe) and its firmware
  (`linux-firmware-lite`), and the user in group `video`/`render` for `/dev/dri/renderD128`.
  Check with `vainfo` (libva-utils, not packaged) or `ffmpeg -hwaccels`; `mpv --hwdec=vaapi`
  falls back to software if no driver loads.
* **Intel graphics stay on llvmpipe**: mesa's `iris` needs `mesa_clc` (clang + libclc), not built.
  Decoding still runs on the Intel media engine, but mpv cannot import the frames into
  llvmpipe's GL: use `--hwdec=vaapi-copy` there. On AMD (radeonsi) `--hwdec=vaapi` imports them directly.
* **`iso-nogui-ffmpeg` has the Intel driver only**: AMD's VA driver is part of mesa (with llvm),
  which a headless image does not carry: `nawa install mesa` adds it.
* **lua52 is a parallel Lua**: mpv supports 5.1/5.2/LuaJIT, not the 5.4 of the `lua` recipe, so
  `lua52` installs only under 5.2 names (`lua5.2`, `luac5.2`, `liblua5.2.a`, `lua5.2.pc`) and
  never collides with `lua`. mpv links it statically.
* **ffmpeg depends on the text stack of `gui/`** (freetype, fontconfig, fribidi, harfbuzz, libass,
  libdrm) for subtitle burn-in and `drawtext`, so `iso-nogui-ffmpeg` carries those too (no compositor needed).
* **ffmpeg encoders**: libx264, libx265, libvpx, libopus, libmp3lame and the native ones. Still
  missing: AV1 encoders (libaom, SVT-AV1) and vdpau/vulkan.
* **x264 is a git snapshot** (the `stable` branch commit in the recipe): there is no release
  tarball, so a newer x264 means picking a new commit and updating `version`, `source`, `source_dir`.
* **x265 is a multilib build** (12- and 10-bit static libs linked into the 8-bit shared one) in a
  single recipe; it also passes `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` for cmake 4.
* **No Vulkan, no audio server** (ALSA only), **no X11 output** (Wayland and DRM only).
* **Licenses**: x264 and x265 are GPL, so ffmpeg is built with `--enable-gpl --enable-version3`
  and its binaries are GPL-3.0-or-later (drop x264, x265 and `--enable-gpl` for an LGPL-3.0 build). mpv is GPL.
