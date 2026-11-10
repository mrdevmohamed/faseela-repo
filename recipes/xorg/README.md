# recipes/xorg — the X11 display stack

The display layer for the optional Xfce desktop (and for any other X11
session): the **Xorg server** with the libinput input driver, the X client
libraries Xfce needs beyond what Xwayland already pulls in, and the
**LightDM** display manager with its GTK 3 greeter.

Everything here is opt-in: nothing in this category is built by the default
ISO or the Sway flavor. The Xfce flavor (`iso-xfce`) includes `@xorg` plus
`@xfce`.

## Contents

| package | what it is |
|---|---|
| `xorg-server` | Xorg 21.1: the real X server (glamor/DRI3 via Mesa, udev hotplug, setuid-root classic seat path, no systemd, no logind) |
| `xf86-input-libinput` | the X input driver over libinput (keyboard, touchpad, mouse) |
| `libXdmcp` | X Display Manager Control Protocol library (LightDM links it) |
| `libpciaccess` | user-space PCI bus access (the server's bus enumeration) |
| `libXres` | X-Resource extension client library (per-client memory, libwnck) |
| `libXpresent` | Present extension client library (vsync page flips for xfwm4) |
| `libwnck` | window manager library for tasklists/pagers (GTK 3) |
| `libxklavier` | XKB keyboard-layout management (xfce4-settings, LightDM greeter) |
| `lightdm` | the display manager: daemon + liblightdm-gobject + tools, runit service, lightdm.conf for the xfce session |
| `lightdm-gtk-greeter` | the GTK 3 greeter (login screen) |

## Conventions

* No systemd, no PAM-specific integration: LightDM's runit service waits for
  the system D-Bus socket; the X server is setuid root (no suid wrapper).
* The `lightdm` recipe pre-enables its service in
  `/etc/runit/runsvdir/default` like other system services in this tree.
* Sources: xorg.freedesktop.org individual tarballs; LightDM 1.32.0 and the
  greeter from Debian `.orig` tarballs because the launchpad download URLs
  were retired (sha256 pins guarantee integrity).
