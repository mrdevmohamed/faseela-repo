# recipes/xfce — the Xfce 4.20 desktop (X11)

The Xfce desktop, its applications and panel plugins, plus LightDM and its
GTK greeter. The Xorg server and client utilities live in `recipes/xorg/`.
The `xfce-session` meta-package supplies the core X11/Xfce runtime closure,
Faseela's keyboard-layout configuration, shared per-user PipeWire startup,
elogind session tracking, the XFCE Polkit agent, and removable-storage
integration through GVfs and UDisks2.

Everything is opt-in. The supported image is `iso-xfce`, which includes
Xorg, Xfce, LightDM and the standard desktop applications. LightDM is not
required by `xfce-session`; it can be installed separately.

## Layout

* **Support libraries**: `vte` (GTK 3 terminal widget), `libnotify`,
  `gtksourceview4`, `libexif`, and the Xfce libraries.
* **Xfce core**: `libxfce4util`, `xfconf`, `libxfce4windowing`,
  `libxfce4ui`, `exo`, `garcon`, `tumbler`, `thunar`, `xfwm4`,
  `xfce4-panel`, `xfce4-session`, `xfce4-settings`, `xfdesktop`,
  and `xfce4-appfinder`.
* **Applications**: `xfce4-terminal`, `xfce4-notifyd`, `mousepad`,
  `ristretto`, `xfce4-taskmanager`, `xfce4-screenshooter`,
  `xfce4-screensaver` (the default session locker), and `xarchiver`.
* **Panel plugins**: Whisker Menu, PulseAudio, Clipman (clipboard history),
  CPU graph, netload, systemload, battery, genmon, diskperf, and sensors.
* **Network integration**: `network-manager-applet` provides the tray applet
  and connection editor. Its XDG autostart entry launches it in the XFCE
  session; `libnma` and `libsecret` supply its GTK and credential-store
  interfaces.
* **Thunar integration**: `tumbler` provides thumbnails, while
  `thunar-archive-plugin` adds create/extract actions backed by `xarchiver`.
  Archive command-line helpers are declared as Xarchiver runtime dependencies.
* **Display manager**: LightDM 1.33.1 and `lightdm-gtk-greeter` are
  packaged with standalone Linux-PAM. LightDM's runit service is not
  pre-enabled because its current X-server launch path inherits the daemon's
  root UID. Rootless LightDM requires a separate unprivileged X-server
  launcher and Xorg seat-management integration.

## Build choices

* Xfce is built for X11. The Xorg server and `xf86-input-libinput` are
  supplied by the separate `xorg/` category.
* Introspection, Vala bindings, documentation and tests are disabled where
  the upstream project exposes those build options.
* `xfce4-dev-tools` supplies the Xfce build macros needed by the core
  libraries and panel.
* Sources use upstream release archives with pinned SHA-256 checksums.

## Trying it

```
python3 scripts/check-recipes.py xfce-session
nawa --recipes recipes deps xfce-session
```

For Xorg device access, add the user to `video,render,input,audio`.
Installing `lightdm` and `lightdm-gtk-greeter` does not enable the service.
Do not enable LightDM while rootless Xorg integration is pending; start the
Xfce session from a user-owned TTY once Xorg has working seat access.


## Audio and LightDM runtime environment

The Xfce session depends on the shared `audio-session` package. Its XDG
autostart entry starts PipeWire, WirePlumber and `pipewire-pulse` as the
logged-in user; the same supervisor is used by Sway, so the two desktops do
not maintain separate audio startup implementations.

Faseela does not use systemd. LightDM uses the login1 D-Bus API provided by
elogind, and its PAM stacks load `pam_elogind.so` (never `pam_systemd`) to
register the user and greeter sessions. Elogind creates the per-user
`XDG_RUNTIME_DIR` used by PipeWire and Polkit. The Xfce launcher keeps a
private mode-0700 `/tmp/runtime-<uid>` fallback only for sessions started
outside PAM/elogind, such as a direct start from a TTY.

Users who need direct ALSA device access must belong to the `audio` group.
After installing the desktop, add the account to `audio` and log out/in so
the new group membership applies.


## Session tracking and Polkit authentication

LightDM's login1 client discovers seats through the system D-Bus, while
`pam_elogind.so` creates and closes the greeter and user sessions. Elogind is
supervised by runit and also provides D-Bus activation; it does not require
systemd. Polkit is built with `-Dsession_tracking=elogind` and links against
`libelogind`, allowing authorization decisions to identify an active local
desktop session.

Elogind is built with `-Dpolkit=enabled`, so login1 power-off and reboot
requests are checked through PolicyKit. Elogind uses its own D-Bus client for
these checks; its optional `polkit-gobject-1` dependency is only a version probe
for legacy `.pkla` handling, not a link-time dependency. This allows Polkit to
be built with `-Dsession_tracking=elogind` without creating a build cycle.
The `xfce-session` meta-package installs both components in the same desktop
closure. Verify the actual power actions in a disposable installed VM.

The `xfce-polkit` authentication agent is installed in
`/etc/xdg/autostart` with `OnlyShowIn=XFCE;`. XFCE starts it for each user
session, allowing graphical tools such as Thunar/UDisks2 clients to display
PolicyKit authentication prompts.

XFCE session locking is provided by `xfce4-screensaver`. It registers the
`org.xfce.ScreenSaver` session-bus service that `libxfce4ui` and
`xfce4-session` already use. Its PAM service is packaged explicitly with
`pam_unix.so`, matching Faseela local-account authentication rather than the
upstream `system-auth` include that Faseela does not provide.

## Removable storage and D-Bus integration

The Xfce session includes `thunar-volman`, `gvfs`, and `udisks2`.
Thunar is started with `thunar --daemon` by an XDG autostart entry in the
Xfce session; this keeps the Thunar extension host active so the volume-manager
extension can react to devices reported by GVfs.

GVfs is built with its GUdev and UDisks2 volume-monitor backends and FUSE
support. UDisks2 supplies the system storage API and performs authorized
mount, unmount and device operations through polkit. UDisks2 keeps its
upstream session-aware policy: a normal removable-volume mount is allowed
only to the active local session; inactive or remote callers require
administrator authentication. Devices classified by UDisks2 as system
devices (normally fixed, non-removable disks) use the separate
`filesystem-mount-system` action and retain an administrator challenge even
for the active session. No blanket mount permission is added for all users. The system D-Bus daemon
(`dbus-system`) is supervised by runit; it activates `udisksd` on demand
from `org.freedesktop.UDisks2.service`. The package removes the upstream
`SystemdService` activation hint and does not install a systemd unit or a
second runit service.

The Xfce session already starts a per-user D-Bus session with
`dbus-run-session`. GVfs session services are therefore activated on that
bus, while UDisks2 is activated by the system bus. No systemd-logind or
systemd user service is required.

## Desktop autostart and cache handling

The upstream XDG autostart entries start the XFCE power manager,
NetworkManager applet, and Clipman in the desktop session. The notification
daemon and Tumbler are activated on demand by the session D-Bus. The
screenshooter and archive plugin are launched by XFCE/Thunar when requested.

The `desktop-file-utils` package owns the Nawa transaction hook for MIME
and desktop-entry caches. The hook checks that the relevant cache directories
exist and runs after package transactions that change desktop metadata;
`xfce-session` deliberately does not force a second cache rebuild on every
installation.
