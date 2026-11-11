# recipes/xfce — the Xfce 4.20 desktop (X11)

The Xfce desktop, its applications and panel plugins, plus LightDM and its
GTK greeter. The Xorg server and client utilities live in `recipes/xorg/`.
The `xfce-session` meta-package supplies the core X11/Xfce runtime closure,
Faseela's keyboard-layout configuration, shared per-user PipeWire startup,
ConsoleKit2 session tracking, the XFCE Polkit agent, and removable-storage
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
  `ristretto`, `xfce4-taskmanager`, and `xfce4-screenshooter`.
* **Panel plugins**: Whisker Menu, PulseAudio, CPU graph, netload,
  systemload, battery, genmon, clipman, diskperf, and sensors.
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

LightDM is built without systemd-logind and its PAM stack does not load
`pam_systemd`. LightDM registers each login with ConsoleKit2 over the system
D-Bus; ConsoleKit2 provides the per-user `XDG_RUNTIME_DIR` used by the
tracked session and by Polkit's active-session checks. The Xfce launcher
keeps a private mode-0700 `/tmp/runtime-<uid>` fallback for sessions started
outside LightDM. This preserves PipeWire's shared per-user socket location
without introducing a systemd dependency.

Users who need direct ALSA device access must belong to the `audio` group.
After installing the desktop, add the account to `audio` and log out/in so
the new group membership applies.


## Session tracking and Polkit authentication

LightDM creates and closes graphical sessions through ConsoleKit2 on the
system D-Bus. The ConsoleKit2 service is activated on demand; it does not
need a permanent runit service or systemd-logind. Polkit is built with
`-Dsession_tracking=ConsoleKit`, allowing authorization decisions to
identify an active local desktop session.

The `xfce-polkit` authentication agent is installed in
`/etc/xdg/autostart` with `OnlyShowIn=XFCE;`. XFCE starts it for each user
session, allowing graphical tools such as Thunar/UDisks2 clients to display
PolicyKit authentication prompts.

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
