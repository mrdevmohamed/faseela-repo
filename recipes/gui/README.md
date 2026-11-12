# recipes/gui — Wayland desktop (sway)

A graphical session: **sway** (i3-compatible Wayland compositor) on
**wlroots 0.18** (with **Xwayland** for X11-only applications), **foot**
terminal, DejaVu **and Noto** fonts (Latin/Greek/Cyrillic, Arabic, Chinese,
Japanese, Korean, and color emoji), **waybar** status bar, **mako** notifications, and **seatd** for seat
management. System services are supervised by runit; user applications use a
per-session D-Bus session bus.

> **Build status:** these recipes have not all been exercised in one clean
> end-to-end build yet. A few upstream source archives still need their hashes
> pinned; run `python3 scripts/fill-sha256.py --dry-run` and then the script
> itself before building. See "First build" below.

## OpenGL/GLX compatibility for desktop applications

Mesa is built with both the `wayland` and `x11` platforms and DRI-based
`glx=dri`. Wayland remains the native desktop path; enabling GLX also ships
the standard `/usr/lib/libGL.so.1` ABI used by older Qt and AppImage clients
(such as Nekoray), including when they run through Xwayland. The Mesa runtime
closure includes the X11/XCB, `libXxf86vm` and shared-memory fence libraries
needed by that GLX implementation. This does not add a separate Xorg server.

## Zed (opt-in, Vulkan enabled)

`zed` is the upstream prebuilt Zed editor bundle. It is in `gui/` but is
excluded from the standard `iso-gui` flavor. Use `iso-gui-zed` or install
`zed` on a system that already has the Vulkan stack.

The Zed flavor now contains a hardware-capable Vulkan path, with a software fallback:

- `vulkan-loader` provides the Khronos `libvulkan.so.1` loader with Wayland WSI.
- Mesa is built with `-D vulkan-drivers=amd,intel,intel_hasvk,swrast`: RADV for AMD,
  ANV for modern Intel, HasVK for older Intel (Ivy Bridge through Broadwell), and
  lavapipe (`lvp_icd.x86_64.json` / `libvulkan_lvp.so`) as the software fallback.
- The Intel ANV build uses `python-ply`, `libclc` and the LLVM-matched
  `spirv-llvm-translator`. The latter two build the Mesa SPIR-V OpenCL-C
  builtins and the `intel_clc` helper used to embed ANV's internal kernels.
  RADV, ANV and HasVK are hardware ICDs; lavapipe remains available for
  systems without a Vulkan GPU.
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
   `llvm → spirv-llvm-translator → libclc → mesa`; `spirv-headers → spirv-tools → glslang → mesa`; `vulkan-headers → vulkan-loader`.
   If a Meson option is rejected, compare it with the pinned Mesa release's
   `meson_options.txt`.

## Layout

| group | packages |
|---|---|
| text/fonts | libpng freetype fontconfig harfbuzz fribidi glib pixman cairo pango dejavu-fonts noto-fonts noto-serif noto-mono noto-fonts-arabic, noto-naskh-arabic noto-cjk noto-color-emoji |
| D-Bus compatibility | dbus-glib (legacy GLib binding used by XFCE screensaver) |
| X11 client libraries and utilities | xorg-util-macros xorgproto xtrans xcb-proto libXau libxcb libX11 libXext libXrender libXtst libXScrnSaver libXpresent libxshmfence xorg-xprop (GTK3 and Chrome client-side libraries; no X server) |
| Xwayland server | xkbcomp xkeyboard-config libfontenc font-util libxkbfile libXfont2 libxshmfence libxcvt xcb-util-wm xwayland (wlroots starts it on demand for X11 applications) |
| wayland + input | libdrm wayland wayland-protocols xkeyboard-config libxkbcommon libevdev mtdev libinput seatd |
| graphics | mesa (+ `libXxf86vm` for X11/GLX, python-mako python-markupsafe python-pyyaml python-packaging, glslang and Vulkan-Headers as build helpers), libva (VA-API loader; mesa's AMD video driver) |
| compositor | hwdata libdisplay-info json-c wlroots sway |
| apps | tllist fcft foot swaybg wmenu |
| sway companions | swaylock (setuid, shadow auth) swayidle grim slurp wl-clipboard wlr-randr wlsunset |
| desktop shell | waybar (+ libdbusmenu GTK 3 StatusNotifier tray, fmt spdlog jsoncpp gtk-layer-shell gtkmm glibmm cairomm pangomm atkmm libsigc++), mako (+ basu inih), xdg-user-dirs |
| desktop integration | xdg-utils (`xdg-open`), xdg-desktop-portal + GTK and wlr backends, bubblewrap, fuse3, json-glib, rsync, gnome-keyring, libgudev, libusb, UPower, GCR/GCK, p11-kit and libgcrypt |
| audio tools | pavucontrol (+ libcanberra GTK 3 plugin, libogg, libvorbis) |
| session | gui-session (seatd runit service, `start-sway`, group setup hook) |

## Using it

`gui-session` creates the `seat`, `video`, `render`, `input` and `audio` groups (hook),
installs the DRM render-node udev rule, and enables the `seatd` service. Then:

```
usermod -aG seat,video,render,input,audio <user> # log out and in again
start-sway                                    # from a text console
```

`start-sway` sets `XDG_RUNTIME_DIR`, `LIBSEAT_BACKEND=seatd` and
`WLR_RENDERER_ALLOW_SOFTWARE=1` (see limitations). The same variables are
exported for every login shell by `/etc/profile.d/gui-session.sh`, so a plain
`sway` works too. The Sway session drop-in also imports the compositor environment into the
session D-Bus activation environment for desktop portals, and starts
`faseela-audio-session`, which brings up PipeWire, WirePlumber and
`pipewire-pulse` for the logged-in user even when Sway is launched directly.
It checks the native and Pulse sockets and avoids starting duplicate daemons. The kernel recipe enables DRM (virtio-gpu, bochs, simpledrm)
and evdev/HID input; to try it in QEMU use `-device virtio-vga` (or `-vga std`)
and a USB/PS2 keyboard and mouse.

## Desktop integration

`gui-session` installs `xdg-utils` (including `xdg-open`), `rsync`,
`gnome-keyring`, and `upower`. Zed uses `rsync` for auto-updates. The Sway launcher starts a
user D-Bus session with `dbus-run-session`. The `xdg-desktop-portal` frontend
owns `org.freedesktop.portal.Desktop` and activates its backends through
D-Bus. The GTK backend is built with its Settings portal enabled and declares the required Fontconfig and GSettings schemas, so Qt/GTK clients can read standard appearance settings instead of receiving `UnknownMethod`. `sway-portals.conf` selects GTK for general interfaces with the wlr
backend as the ScreenCast provider, and explicitly maps
`org.freedesktop.impl.portal.Secret` to `gnome-keyring` for Sway. The keyring
backend is activated on the per-user session bus; it is not a system service. The Sway
session drop-in runs `dbus-update-activation-environment` after the compositor
starts, so the activated backend receives `WAYLAND_DISPLAY` and
`XDG_CURRENT_DESKTOP=sway`. Bubblewrap, user namespaces, and FUSE support are
included for the document portal's sandbox and document mounts. GNOME Keyring installs
`/usr/share/dbus-1/services/org.freedesktop.secrets.service`, so the Secret
Service daemon is activated on demand by D-Bus. This does not require systemd
or a system-wide runit service. UPower is separately activated by the
system D-Bus through
`/usr/share/dbus-1/system-services/org.freedesktop.UPower.service`.
`gui-session` already installs `dbus-system`, which supervises the system bus
with runit. UPower does not need a permanently running runit service; its
`libgudev` and `libusb` dependencies provide device discovery and USB support.

UDisks2 follows the same system-bus activation model for removable storage.
Its D-Bus service descriptor points directly to `/usr/libexec/udisks2/udisksd`;
the systemd-only `SystemdService` key is removed during package installation.
The daemon uses polkit for authorization, libgudev/eudev for device discovery,
and libblockdev's filesystem, partition, loop and swap plugins. It is not installed as an
additional runit service. Xfce's GVfs package enables its UDisks2 volume
monitor, while the Thunar daemon hosts the `thunar-volman` extension.

Waybar's tray module provides the StatusNotifierWatcher used by Qt tray clients. Sway starts one Waybar process for the session; Waybar is not registered for D-Bus activation, because `Exec=waybar` could launch a second independent status bar when the name is not owned yet. Start Telegram after the session bar is running so its tray icon can register with that existing watcher.

The wlr portal backend (ScreenCast through PipeWire), the notification daemon
and the bar all speak D-Bus through **basu**'s sd-bus. The Sway session keeps
using seatd for compositor seat access; elogind is used by the shared Polkit
stack and the optional Xfce session, not as a replacement for seatd. The session autostarts `mako`
(`org.freedesktop.Notifications`), `waybar` (anchored through
gtk-layer-shell) and `xdg-user-dirs-update`; `pavucontrol` mixes the
pipewire-pulse server. X11-only applications run through **Xwayland**:
wlroots enables the feature and spawns the server on demand, so they start
with no extra setup.

The keyring daemon is built without PAM integration, so this supplies the
`org.freedesktop.secrets` service but does not automatically unlock a login
keyring during a tty login.

## Limitations / next steps

* **Mesa graphics**: Gallium provides AMD `radeonsi`, CPU `llvmpipe`/`softpipe`,
  and QEMU `virgl`. Vulkan provides AMD `RADV` (`amd`) and Intel `ANV` (`intel`)
  plus legacy `HasVK` (`intel_hasvk`), with lavapipe (`swrast`) as a CPU fallback.
  The kernel has `amdgpu` and `i915` as modules and firmware is in
  `linux-firmware-lite`. Users need membership in `render` to access DRM render
  nodes such as `/dev/dri/renderD128` (and `video` where the primary node requires it).
* **Intel OpenGL remains software-rendered for now**: the `iris` Gallium driver
  is not part of the selected `gallium-drivers` set. This is separate from
  Intel ANV Vulkan: its internal build-time compiler and libclc SPIR-V builtins
  are now packaged, so ANV remains enabled for hardware Vulkan.
* **NVIDIA Vulkan is not enabled yet**: this Mesa build does not include NVK
  (`nouveau`), which needs additional Rust/bindgen build dependencies. NVIDIA
  users need a separately packaged compatible driver before Zed can use the GPU.
* Hardware **video** decode/encode (VA-API): mesa provides `radeonsi_drv_video.so`
  for AMD (`-D gallium-va`), and `recipes/media/intel-media-driver` provides
  `iHD_drv_video.so` for Intel.
* X11 applications run through **Xwayland** (wlroots' xwayland feature,
  backed by the xwayland recipe and the X11 libraries above): X11-only
  programs start under sway with no extra setup. D-Bus system and per-user
  session buses are available. The GTK portal backend
  supplies general desktop integration (including file chooser) and the wlr
  backend supplies ScreenCast through PipeWire (both on basu's sd-bus).
  The launcher is `wmenu` (`Super+D`,
  sway's default `wmenu-run`).
* Wallpaper: `swaybg` is packaged (PNG and solid colours only, no gdk-pixbuf).
  sway's stock `output * bg ...` line is commented out by the sway recipe;
  `faseela-branding` installs `/usr/share/backgrounds/faseela/default.png` and `gui-session` the
  drop-in `/etc/sway/config.d/10-wallpaper.conf` that sets it. To change it,
  edit that drop-in or use `~/.config/sway/config`.
* `foot` is built without grapheme clustering and without a utmp backend.
* pure-python helpers (`python-*`) are copied into `site-packages` without
  dist-info metadata, which is enough for Mesa's build-time import checks.
