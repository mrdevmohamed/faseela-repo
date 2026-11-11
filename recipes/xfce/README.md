# recipes/xfce — the Xfce 4.20 desktop (X11)

The Xfce desktop, its applications and panel plugins, plus LightDM and its
GTK greeter. The Xorg server and client utilities live in `recipes/xorg/`.
The `xfce-session` meta-package supplies the core X11/Xfce runtime closure,
Faseela's keyboard-layout configuration, and shared per-user PipeWire startup.

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

LightDM is built without systemd-logind and its PAM stack does not create
`XDG_RUNTIME_DIR`. The Xfce session entry therefore launches
`faseela-start-xfce4`, which reuses `/run/user/<uid>` when it exists and
otherwise creates a private mode-0700 `/tmp/runtime-<uid>` directory before
starting `startxfce4`. This gives PipeWire and desktop clients a shared
per-user socket location without introducing a systemd dependency.

Users who need direct ALSA device access must belong to the `audio` group.
After installing the desktop, add the account to `audio` and log out/in so
the new group membership applies.
