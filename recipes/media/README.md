# recipes/media — ffmpeg, mpv and Vulkan support

**ffmpeg** (convert / probe / stream audio and video), the **mpv** media player
and the Vulkan SDK runtime/build helpers are opt-in packages. 23 packages:

| group | packages |
|---|---|
| tools | ffmpeg mpv |
| decoding / subtitles / rendering | dav1d (AV1) libass (subtitles, OSD text) libplacebo (GPU video rendering) |
| encoders | x264 (H.264) x265 (H.265/HEVC) libvpx (VP8/VP9) opus lame (MP3) |
| hardware video | intel-media-driver gmmlib (Intel VA-API driver; libva and AMD's driver: see gui/ libva, mesa) |
| scripting | lua52 (mpv's on-screen controller, stats, console) |
| Vulkan runtime | vulkan-loader (libvulkan.so.1; Wayland WSI) |
| Vulkan / Mesa build helpers | vulkan-headers, volk, spirv-headers, spirv-tools, glslang, python-ply |
| other build helpers | python-jinja2 python-glad2 (libplacebo generates its GL loader with glad) |

Vulkan-Headers, Volk and Vulkan-Loader are pinned to SDK 1.3.296. The SPIR-V headers
and tools are pinned to the exact commits referenced by glslang's
`vulkan-sdk-1.3.296.0/known_good.json`; glslang is built against those
separately packaged tools rather than missing source submodules.

Everything else comes from the existing categories: `freetype fribidi harfbuzz fontconfig`,
`wayland libxkbcommon mesa libdrm libva` (gui/), `alsa-lib libarchive libjpeg-turbo nasm` (extra/).

> **Build status:** some newly added SDK source archives still have checksum
> placeholders. Run `python3 scripts/fill-sha256.py --dry-run` to list them,
> then `python3 scripts/fill-sha256.py -r spirv-headers spirv-tools glslang vulkan-loader`
> to pin their downloaded sources before building.

## Install / build

```
nawa install mpv ffmpeg --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable
```

Build with *Build packages* → `mpv`, `ffmpeg`, `@media`, or
`flavor:iso-gui-mpv` /`flavor:iso-nogui-ffmpeg` (everything the flavor needs).
`ALL` / `@all` does not include `@media`, same as `@gui` and `@browser`.
The `iso-gui-zed` flavor gets the Vulkan loader and Mesa's lavapipe ICD through
Zed/Mesa runtime dependencies; the SPIR-V and glslang packages are build-only
dependencies and are not pulled into the installed ISO. mpv needs the `gui/` stack (X11 client libraries, Wayland, Mesa), ffmpeg does not.

## First build

1. `python3 scripts/fill-sha256.py --dry-run` — lists every URL with a
   placeholder hash.
2. Pin the new SDK source archives as noted above; review the resulting hashes.
3. Build order for Mesa's Vulkan support is
   `spirv-headers → spirv-tools → glslang → mesa`, plus
   `vulkan-headers → vulkan-loader` and `vulkan-headers → volk → vulkan-tools`; `python-ply` is also pulled into Mesa's
   build closure for Intel ANV. The installed Zed flavor keeps only runtime packages.
4. `python3 scripts/check-recipes.py mpv` prints the mpv build order.
5. Things most likely to need attention on the first build:
   * **Mesa / Lavapipe**: the Clang project is built as part of the `llvm`
     package because Mesa's Vulkan swrast compiler path requires it. The AMDGPU
     target remains enabled for `radeonsi`.
   * **libplacebo**: GitLab's source archives carry no git submodules, so its
     vendored glad is missing; the build uses the `python-glad2` package instead.
   * **mpv**: option names are checked against 0.40's `meson.options`; `Unknown option`
     means a rename, fix it in the `configure` line.
   * **ffmpeg**: `--disable-autodetect` turns every optional library off; a missing
     `--enable-...` shows up as "feature not found" at the end of `configure`.

## Using it

```
mpv file.mkv                    # in XFCE/Xorg or Sway/Wayland: select an EGL GPU context automatically
mpv --vo=drm file.mkv           # straight on a text console, no compositor (user in group video)
mpv --vo=wlshm file.mkv         # no GPU rendering at all: slow, but works anywhere Wayland does
mpv --hwdec=vaapi file.mkv      # hardware decoding (AMD: mesa, Intel: intel-media-driver)
mpv --hwdec=vaapi-copy file.mkv # Intel decode + llvmpipe drawing
ffmpeg -i in.mkv -c:v libx264 -crf 23 -c:a libopus out.mkv
ffmpeg -i in.mkv -vf subtitles=subs.ass -c:v libx265 -crf 28 out.mkv
ffprobe -hide_banner file.mkv
```

On the software-rendering setups of `gui/` (llvmpipe, QEMU) `vo=gpu-next` is
heavy: try `--vo=gpu --profile=fast`, or `--vo=wlshm` for plain playback.

## Limitations / next steps

* **Hardware video (VA-API)**: libva (`gui/`) loads a driver from `/usr/lib/dri`.
  AMD: mesa's `radeonsi_drv_video.so` (mesa builds `radeonsi` and the gallium
  VA driver, which needs LLVM's AMDGPU target). Intel gen8+: `intel-media-driver`
  (`iHD`) + `gmmlib` here. Both need the kernel driver (`amdgpu` / `i915`
  or `xe`, modules in the kernel recipe) and its firmware (`linux-firmware-lite`),
  and the user in group `video`/`render` for `/dev/dri/renderD128`.
  Check with `vainfo` (libva-utils, not packaged) or `ffmpeg -hwaccels`;
  `mpv --hwdec=vaapi` falls back to software if no driver loads.
* **Intel graphics stay on llvmpipe**: mesa's `iris` needs `mesa_clc`
  (clang + libclc), not built. Decoding still runs on the Intel media engine,
  but mpv cannot import the frames into llvmpipe's GL: use `--hwdec=vaapi-copy`
  there. On AMD (radeonsi) `--hwdec=vaapi` imports them directly.
* **`iso-nogui-ffmpeg` has the Intel driver only**: AMD's VA driver is part of
  mesa (with LLVM), which a headless image does not carry: `nawa install mesa` adds it.
* **lua52 is a parallel Lua**: mpv supports 5.1/5.2/LuaJIT, not the 5.4 of the
  `lua` recipe, so `lua52` installs only under 5.2 names
  (`lua5.2`, `luac5.2`, `liblua5.2.a`, `lua5.2.pc`) and never collides
  with `lua`. mpv links it statically.
* **ffmpeg depends on the text stack of gui/** (freetype, fontconfig, fribidi,
  harfbuzz, libass, libdrm) for subtitle burn-in and `drawtext`, so
  `iso-nogui-ffmpeg` carries those too (no compositor needed).
* **ffmpeg encoders**: libx264, libx265, libvpx, libopus, libmp3lame and the
  native ones. Still missing: AV1 encoders (libaom, SVT-AV1) and vdpau.
* **x264 is a git snapshot** (the `stable` branch commit in the recipe): there
  is no release tarball, so a newer x264 means picking a new commit and
  updating `version`, `source`, `source_dir`.
* **x265 is a multilib build** (12- and 10-bit static libs linked into the
  8-bit shared one) in a single recipe; it also passes
  `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` for cmake 4.
* **No audio server** (ALSA only; no PulseAudio/PipeWire output backend).
* **Licenses**: x264 and x265 are GPL, so ffmpeg is built with
  `--enable-gpl --enable-version3` and its binaries are GPL-3.0-or-later
  (drop x264, x265 and `--enable-gpl` for an LGPL-3.0 build). mpv is GPL.
