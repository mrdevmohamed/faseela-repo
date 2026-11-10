# recipes/xfce — the Xfce 4.20 desktop (X11)

The Xfce desktop, its applications and panel plugins, plus LightDM and its
GTK greeter. The Xorg server and client utilities live in `recipes/xorg/`.
The `xfce-session` meta-package supplies the core X11/Xfce runtime closure
and Faseela's keyboard-layout configuration.

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
