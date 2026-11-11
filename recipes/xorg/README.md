# recipes/xorg — the X11 display stack

The Xorg server and its client utilities for X11 sessions. The LightDM
display manager and GTK greeter are maintained in `recipes/xfce/`, not
in this category.

Everything here is opt-in and remains outside the default ISO and Sway
flavor. The `iso-xfce` flavor selects the Xorg runtime through
`xfce-session` dependencies.

## Contents

| Package | Purpose |
|---|---|
| `xorg-server` | Xorg 21.1 server with glamor/DRI3 and udev hotplug |
| `xf86-input-libinput` | libinput keyboard, pointer and touchpad driver |
| `xorg-iceauth` | X11 ICE session authority utility |
| `libXdmcp` | X Display Manager Control Protocol client library |
| `libXinerama` | Xinerama extension library |
| `libXmu` | X11 miscellaneous utility library |
| `libXpresent` | X Present extension library |
| `libXres` | X Resource extension library |
| `libXt` | X Toolkit Intrinsics library |
| `libpciaccess` | User-space PCI bus access library |
| `xcb-util-cursor` | XCB cursor library |
| `xorg-setxkbmap` | XKB layout configuration utility |
| `xorg-xauth` | X authority cookie utility |
| `xorg-xhost` | X server access-control utility |
| `xorg-xmodmap` | X key and pointer modifier-map utility |
| `xorg-xrandr` | X display configuration utility |
| `xorg-xrdb` | X resource database utility |
| `xorg-xset` | X user preference utility |

## Runtime model

* Xorg is built with `suid_wrapper=false`: no SUID `Xorg.wrap` is installed,
  and the server is intended to run with the logged-in user's privileges.
* Faseela uses runit and seatd, but upstream Xorg does not currently use
  libseat to acquire active-seat DRM/input/VT resources. Device discovery via
  udev alone does not grant an unprivileged process those permissions; a
  reviewed libseat integration is still required for reliable rootless Xorg.
* The display manager is optional and lives under `recipes/xfce/`.
  LightDM uses Linux-PAM services without `pam_systemd` and ships a runit
  service, but it is not pre-enabled: the current LightDM daemon launches
  its X server under the daemon's root UID. Do not enable it until a
  non-root X-server launcher and seat-management integration are in place.
* An X11 session itself does not require a display manager.
