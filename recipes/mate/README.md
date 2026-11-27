# MATE 1.28 recipes

MATE desktop for Faseela, built from the GitHub release tarballs
(`mate-desktop/<pkg>/releases/download/v<ver>/<pkg>-<ver>.tar.xz`).
`pub.mate-desktop.org/releases/1.28/` returns 404, so the GitHub pattern is
used for every package here.

## Packages

| Package | Version | Purpose |
| --- | --- | --- |
| mate-common | 1.28.0 | Shared autotools macros for the other MATE packages |
| mate-desktop | 1.28.2 | Core library: menus, desktop items, session helpers |
| mate-menus | 1.28.1 | Menu library (libmate-menu, freedesktop spec) |
| libmatekbd | 1.28.0 | Keyboard library + layout indicator widget (libmatekbdui) |
| marco | 1.28.2 | Window manager (Metacity fork) with compositing |
| mate-session-manager | 1.28.2 | Session manager: starts the desktop, manages logout |
| mate-settings-daemon | 1.28.0 | Settings daemon: applies preferences at login |
| caja | 1.28.1 | File manager |
| mate-terminal | 1.28.3 | Terminal emulator (VTE-based) |
| engrampa | 1.28.5 | Archive manager |
| mate-screensaver | 1.28.1 | Screen saver and locker (PAM + systemd) |
| mate-power-manager | 1.28.1 | Power manager: battery, brightness, suspend |
| libmatemixer | 1.28.0 | Audio mixer abstraction (PulseAudio/ALSA) |
| libmateweather | 1.28.2 | Weather library (mate-panel clock applet) |
| atril | 1.28.7 | Document viewer (PDF via poppler) |
| mate-panel | 1.28.7 | Panel: taskbar, applets, menus |
| eom | 1.28.1 | Image viewer (Eye of MATE) |
| pluma | 1.28.1 | Text editor (gtksourceview4, libpeas plugins) |
| mate-media | 1.28.2 | Media utilities: volume control, mixer applets |
| mate-system-monitor | 1.28.1 | System monitor: processes and resources |
| mate-session | 0.1 | Meta-package: the MATE session (LightDM + Xorg wiring) |

## Build order

1. `mate-common` first — the other autotools packages expand its macros.
2. `mate-desktop`, `mate-menus` — everything links one or both.
3. `libmatekbd`, `libmatemixer`, `libmateweather` — leaf libraries.
   `libmateweather` needs the `libsoup2` recipe (libsoup 2.x API).
4. `marco`, `mate-session-manager`, `mate-settings-daemon`, `caja`,
   `mate-terminal`, `engrampa`, `mate-screensaver`, `mate-power-manager`,
   `mate-panel`, `atril`, `eom`, `pluma`, `mate-media`,
   `mate-system-monitor` — in any order once 1–3 are built. `atril`
   needs the `poppler` recipe (PDF support is on); `eom` and `pluma`
   need the `libpeas` recipe; `mate-panel` needs `libmateweather`;
   `mate-media` needs `libmatemixer` and `mate-panel`.
5. `mate-session` last — the meta-package.

## Notes and known gaps

- **Introspection is off everywhere.** MATE's introspection checks are
  non-fatal (or default off), so no `gobject-introspection` dependency is
  needed for this set.
- **Autotools vs meson, per tarball.** `mate-menus`, `libmatekbd`,
  `mate-session-manager`, `mate-settings-daemon`, `caja`,
  `mate-screensaver`, `libmatemixer`, `libmateweather`, `mate-panel`,
  and `pluma` ship a prebuilt `configure` and no `meson.build`.
  `atril`, `engrampa`, and `mate-terminal` ship both, but their meson
  build fetches `mate-submodules` from git (forbidden offline), so they
  use autotools. `marco` and `eom` are meson-only. `mate-desktop`,
  `mate-power-manager`, `mate-media`, and `mate-system-monitor` use the
  maintained meson build.
- **caja has no `--disable-introspection` flag** in 1.28.1; the check is
  non-fatal and stays off on its own.
- **mate-control-center is NOT included (blocked).** It needs an
  AppIndicator library (`appindicator3-0.1` or
  `ayatana-appindicator3-0.1`); its `meson.build` errors when neither is
  present and offers no disable switch, and no `libappindicator` recipe
  exists on this branch yet. It also needs `marco` (libmarco-private).
  Add it — and add it back to `mate-session`'s run list — once
  `libappindicator` lands.
- **Disabled for missing recipes:** eom XMP (no exempi), pluma spell
  checking (no enchant), mate-settings-daemon smartcard support (no NSS
  use), atril djvu/dvi/XPS/PostScript backends (no libspectre, djvulibre,
  libgxps, kpathsea). All of these auto-disable; the flags above just
  make it explicit.
- **mate-system-monitor is 1.28.1, not 1.28.2.** The v1.28.2 tag's
  release asset is actually the 1.28.1 tarball.
- **LightDM is packaged but not pre-enabled** in the session
  meta-package, same as xfce-session.
