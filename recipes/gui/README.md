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

The Zed flavor now contains a complete software-capable Vulkan path:

- `vulkan-loader` provides the Khronos `libvulkan.so.1` loader with Wayland WSI.
- Mesa is built with `-D vulkan-drivers=swrast`, which installs the lavapipe ICD
  (`lvp_icd.x86_64.json`) and `libvulkan_lvp.so`.
- Lavapipe uses LLVM/Clang; the `llvm` recipe now builds and retains Clang as
  well as the X86/AMDGPU LLVM targets. Gallium `softpipe` stays enabled.
- The Vulkan SDK helper recipes are pinned as a compatible set: Vulkan-Headers
  and Vulkan-Loader 1.3.296, plus the SPIR-V commits listed by glslang's
  `vulkan-sdk-1.3.296.0/known_good.json`.

This allows Vulkan rendering on QEMU guests without a passed-through Vulkan
GPU. Lavapipe is CPU-rendered, so performance depends on the guest's available
CPU resources. It does not accelerate the desktop's OpenGL path; sway continues
to use Mesa's llvmpipe/virgl drivers as available.

To force the lavapipe ICD for a diagnostic launch:

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
usermod -aG seat,video,input,audio <user>     # log out and in again
start-sway                                    # from a text console
```

`start-sway` sets `XDG_RUNTIME_DIR`, `LIBSEAT_BACKEND=seatd` and
`WLR_RENDERER_ALLOW_SOFTWARE=1` (see limitations). The same variables are
exported for every login shell by `/etc/profile.d/gui-session.sh`, so a plain
`sway` works too. The kernel recipe enables DRM (virtio-gpu, bochs, simpledrm)
and evdev/HID input; to try it in QEMU use `-device virtio-vga` (or `-vga std`)
and a USB/PS2 keyboard and mouse.

## Limitations / next steps

* **Mesa: AMD hardware + software + virgl, with software Vulkan.** Drivers:
  `radeonsi` (AMD GCN/RDNA GPUs; the `llvm` recipe builds the X86 and AMDGPU
  targets), `llvmpipe` (JIT, multithreaded), `softpipe`, `virgl`, and Vulkan
  `swrast` (lavapipe). The Vulkan swrast build uses Clang from the `llvm`
  package. QEMU without a working Vulkan GPU can use lavapipe through the
  Khronos loader. wlroots is built `renderers=gles2` only, so the desktop GL
  path remains llvmpipe/virgl. The kernel has `amdgpu` and `i915` as modules
  and the firmware is in `linux-firmware-lite`. **Intel graphics are still
  llvmpipe**: mesa's `iris` needs `mesa_clc` (clang + libclc), which the
  `llvm` recipe does not build. Hardware **video** decode/encode (VA-API):
  mesa provides `radeonsi_drv_video.so` for AMD (`-D gallium-va`), and
  `recipes/media/intel-media-driver` provides `iHD_drv_video.so` for Intel.
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
