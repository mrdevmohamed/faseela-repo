# recipes/xfce — the Xfce 4.20 desktop (X11)

The complete Xfce desktop on top of the `xorg/` display layer: core
libraries, the desktop components, the applications, the panel plugins and
the session-integration package that ties them to Faseela's services
(PipeWire, NetworkManager, polkit, UPower, runit).

Opt-in: nothing here is built unless you ask for it. Images: `iso-xfce`
(with LightDM) and `iso-xfce-nodm` (startxfce4 from a tty).

## Layout

* **Support libraries** (also used outside Xfce): `vte` 0.76 (GTK 3 terminal
  widget), `libnotify` 0.8, `gtksourceview` 4.8 (GTK 3 syntax highlighting).
* **Xfce core**: `libxfce4util` → `xfconf` → `libxfce4windowing` →
  `libxfce4ui` → `exo` / `garcon` / `tumbler` → `thunar`, `xfwm4`,
  `xfce4-panel`, `xfce4-session`, `xfce4-settings`, `xfdesktop`,
  `xfce4-appfinder`, `xfce4-power-manager`.
* **Applications**: `xfce4-terminal`, `xfce4-notifyd`, `mousepad`,
  `ristretto`, `xfce4-taskmanager`, `xfce4-screenshooter`.
* **Panel plugins**: `xfce4-whiskermenu-plugin`, `xfce4-cpugraph-plugin`,
  `xfce4-netload-plugin`, `xfce4-battery-plugin`,
  `xfce4-pulseaudio-plugin`.
* **Integration**: `xfce4-session-integration` — the Xfce counterpart of
  `gui-session`: run-dependency closure of the session plus the small
  configuration the recipe installs (XDG portal selection, `us,ara`
  keyboard layouts with Alt+Shift switching, font rendering defaults,
  `/etc/profile.d/xfce-session.sh`, the X11 socket preflight).

## Build choices

* Everything is built **X11-only**: the upstream Wayland backends of
  libxfce4ui, xfce4-panel, xfdesktop, xfce4-terminal and xfwm4's wayland
  compositor mode are disabled (`-D wayland=disabled` / `--disable-wayland`).
  The desktop runs on the real Xorg server from `xorg/`.
* `xfce4-panel` and `libxfce4util` need `xdt-gen-visibility`; the release
  tarballs ship it in `xfce4-dev-tools/`, so the configure step prepends
  that directory to `PATH` instead of packaging xfce4-dev-tools.
* Introspection/vala/gir/vapi are off everywhere (gobject-introspection is
  not packaged); gtk-doc, tests and docs are off.
* gvfs, libexif, libstartup-notification, keybinder, accountsservice,
  gspell, libutempter, libsoup and Qt are not packaged: the matching
  features are disabled and noted per recipe.
* intltool (xfce4-settings era recipes that still use autotools +
  IT_PROG_INTLTOOL, and lightdm-gtk-greeter) is satisfied with the same
  source-tree stub trick used by `pcmanfm`/`libfm` in `gui/`.
* Sources come from archive.xfce.org (4.20 series) with pinned sha256.

## Trying it

```
python3 scripts/check-recipes.py xfce4-session-integration   # build order
nawa --recipes recipes deps xfce4-session-integration        # same, via nawa
```

After installing on a running system: add your user to
`video,render,input,audio`, then either run `startxfce4` from a tty or let
the pre-enabled `lightdm` runit service show the GTK greeter.
