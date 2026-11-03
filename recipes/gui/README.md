# recipes/gui — Wayland desktop (sway)

A minimal graphical session: **sway** (i3-compatible Wayland compositor) on
**wlroots 0.18**, **foot** terminal, DejaVu fonts, **seatd** for seat
management (no systemd/logind), supervised by runit. 52 packages (incl. `llvm`,
`libva` and the X11 client libraries).

> **Build status:** these recipes have not all been exercised in one clean
> end-to-end build yet. A few upstream source archives still need their hashes
> pinned; run `python3 scripts/fill-sha256.py --dry-run` and then the script
> itself before building. See "First build" below.

## Zed (opt-in, Vulkan enabled)

`zed` is the upstream prebuilt Zed editor bundle. It is in `gui/` but is
excluded from the standard `iso-gui` flavor. Use `iso-gui-zed` or install
`zed` on a system that already has the Vulkan stack.

The Zed flavor now contains a hardware-capable Vulkan path, with a software fallback:

- `vulkan-loader` provides the Khronos `libvulkan.so.1` loader with Wayland WSI.
- Mesa is built with `-D vulkan-drivers=amd,intel,intel_hasvk,swrast`: RADV for AMD,
  ANV for modern Intel, HasVK for older Intel (Ivy Bridge through Broadwell), and
  lavapipe (`lvp_icd.x86_64.json` / `libvulkan_lvp.so`) as the software fallback.
- The Intel ANV build uses the `python-ply` helper. RADV, ANV and HasVK are
  hardware ICDs; lavapipe remains available for systems without a Vulkan GPU.
- Lavapipe uses LLVM/Clang; the `llvm` recipe builds and retains Clang as well
  as the X86/AMDGPU LLVM targets. Gallium `softpipe` stays enabled.
- The Vulkan SDK helper recipes are pinned as a compatible set: Vulkan-Headers
  and Vulkan-Loader 1.3.296, plus the SPIR-V commits listed by glslang's
  `vulkan-sdk-1.3.296.0/known_good.json`.

On a machine with a supported AMD or Intel GPU and its kernel driver loaded,
Zed can use the matching hardware Vulkan ICD. QEMU guests without a working GPU
passthrough still use lavapipe, which renders on the CPU and is not accelerated.
This does not change the desktop OpenGL path: sway continues to use Mesa's
llvmpipe/virgl drivers as available.

To force the lavapipe ICD for a diagnostic launch only (this disables hardware selection):

```sh
VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.x86_64.json zed
```

## Opt-in

`recipes/gui` is **not** built by `stage2`/`stage3` unless you ask:

```
sudo WITH_GUI=1 ./stage2.sh /mnt/faseela       # also builds the GUI stack
```

Or build it later on a running system:

```
python3 scripts/fill-sha256.py                          # pin remaining source hashes
nawa --recipes recipes deps gui-session                  # show the build order
for p in $(nawa --recipes recipes deps gui-session); do  # build + install
    nawa --recipes recipes --builddir /build build "$p"
    nawa --root / install /build/out/$p-*.nawa.tar.zst
done
```

(`python3 scripts/check-recipes.py gui-session` prints the same order offline.)

For Zed's Vulkan support, request the `iso-gui-zed` flavor (or build/install
`vulkan-loader`, Mesa and Zed with their dependency closure). The regular
`iso-gui` remains unchanged.

## First build

1. `python3 scripts/fill-sha256.py --dry-run` — lists every source URL whose
   hash is still a placeholder.
2. `python3 scripts/fill-sha256.py` — downloads and pins hashes. A 404 means
   the upstream tag/asset changed: fix `source`/`version`, bump `rel`, and
   rerun. Review the resulting diff.
3. Build the Vulkan dependency chain through the normal recipe graph:
   `spirv-headers → spirv-tools → glslang → mesa`; `vulkan-headers → vulkan-loader`.
   If a Meson option is rejected, compare it with the pinned Mesa release's
   `meson_options.txt`.

## Layout

| group | packages |
|---|---|
| text/fonts | libpng freetype fontconfig harfbuzz fribidi glib pixman cairo pango dejavu-fonts |
| X11 client libraries | xorgproto xtrans xcb-proto libXau libxcb libX11 libXext libXrender (what cairo's xlib surface links; no X server) |
| wayland + input | libdrm wayland wayland-protocols xkeyboard-config libxkbcommon libevdev mtdev libinput seatd |
| graphics | mesa (+ python-mako python-markupsafe python-pyyaml python-packaging, glslang and Vulkan-Headers as build helpers), libva (VA-API loader; mesa's AMD video driver) |
| compositor | hwdata libdisplay-info json-c wlroots sway |
| apps | tllist fcft foot swaybg wmenu |
| sway companions | swaylock (setuid, shadow auth) swayidle grim slurp wl-clipboard wlr-randr wlsunset |
| session | gui-session (seatd runit service, `start-sway`, group setup hook) |

## Using it

`gui-session` creates the `seat`, `video` and `input` groups (hook) and enables
the `seatd` service. Then:

```
usermod -aG seat,video,render,input,audio <user> # log out and in again
start-sway                                    # from a text console
```

`start-sway` sets `XDG_RUNTIME_DIR`, `LIBSEAT_BACKEND=seatd` and
`WLR_RENDERER_ALLOW_SOFTWARE=1` (see limitations). The same variables are
exported for every login shell by `/etc/profile.d/gui-session.sh`, so a plain
`sway` works too. The kernel recipe enables DRM (virtio-gpu, bochs, simpledrm)
and evdev/HID input; to try it in QEMU use `-device virtio-vga` (or `-vga std`)
and a USB/PS2 keyboard and mouse.

## Limitations / next steps

* **Mesa graphics**: Gallium provides AMD `radeonsi`, CPU `llvmpipe`/`softpipe`,
  and QEMU `virgl`. Vulkan provides AMD `RADV` (`amd`) and Intel `ANV` (`intel`)
  plus legacy `HasVK` (`intel_hasvk`), with lavapipe (`swrast`) as a CPU fallback.
  The kernel has `amdgpu` and `i915` as modules and firmware is in
  `linux-firmware-lite`. Users need membership in `render` to access DRM render
  nodes such as `/dev/dri/renderD128` (and `video` where the primary node requires it).
* **Intel OpenGL remains software-rendered for now**: Mesa's `iris` Gallium driver
  needs `mesa_clc`/libclc, which this LLVM package does not yet build. This does
  not prevent Intel ANV Vulkan from providing hardware rendering in Zed.
* **NVIDIA Vulkan is not enabled yet**: this Mesa build does not include NVK
  (`nouveau`), which needs additional Rust/bindgen build dependencies. NVIDIA
  users need a separately packaged compatible driver before Zed can use the GPU.
* Hardware **video** decode/encode (VA-API): mesa provides `radeonsi_drv_video.so`
  for AMD (`-D gallium-va`), and `recipes/media/intel-media-driver` provides
  `iHD_drv_video.so` for Intel.
* No X server and no Xwayland (only the X11 *client* libraries, because cairo
  links them), no D-Bus, so no sway tray (`-D tray=disabled`) and no portals.
  The launcher is `wmenu` (`Super+D`, sway's default `wmenu-run`).
* Wallpaper: `swaybg` is packaged (PNG and solid colours only, no gdk-pixbuf).
  sway's stock `output * bg ...` line is commented out by the sway recipe;
  `gui-session` installs `/usr/share/backgrounds/faseela/default.png` and the
  drop-in `/etc/sway/config.d/10-wallpaper.conf` that sets it. To change it,
  edit that drop-in or use `~/.config/sway/config`.
* `foot` is built without grapheme clustering and without a utmp backend.
* pure-python helpers (`python-*`) are copied into `site-packages` without
  dist-info metadata, which is enough for Mesa's build-time import checks.
