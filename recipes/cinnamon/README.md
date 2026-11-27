# Cinnamon 6.6 recipes for Faseela

Cinnamon 6.6 (with cjs 128.1 on mozjs-128) for Faseela. All tarballs are
verified by sha256; see each recipe.toml for its source URL.

## Packages

- `cjs` 128.1 — JavaScript bindings for Cinnamon (SpiderMonkey / mozjs-128)
- `cinnamon` 6.6.9 — Cinnamon desktop environment (shell and settings)
- `muffin` 6.6.3 — Cinnamon window manager and compositor (Mutter fork; vendors its own cogl/clutter)
- `nemo` 6.6.4 — Cinnamon file manager
- `cinnamon-desktop` 6.6.2 — Cinnamon desktop libraries (libcinnamon-desktop, libcvc)
- `cinnamon-menus` 6.6.0 — Cinnamon menu library (libcinnamon-menu-3.0)
- `cinnamon-translations` 6.6.2 — Cinnamon translation catalogues (data only)
- `cinnamon-control-center` 6.6.0 — Cinnamon control center (no colord / ModemManager / libwacom)
- `cinnamon-settings-daemon` 6.6.4 — Cinnamon settings daemon (no color / CUPS / wacom / smartcard)
- `cinnamon-screensaver` 6.6.3 — Cinnamon screen saver and locker
- `cinnamon-session` 6.6.4 — Cinnamon session manager
- `libxapp` 3.4.3 — XApp libraries and services (source repo is `xapps`)
- `gsound` 1.0.3 — Small library for playing system sounds
- `timezonemap` 0.4.6 — Timezone map widget library (Debian source + Debian libsoup3 patch set)
- `cinnamon-desktop-session` 0.1 — Meta-package: Cinnamon X11 session integration
  (Xorg keyboard US+Arabic Alt+Shift, audio autostart, X11 socket dirs;
  LightDM is packaged but NOT pre-enabled)

## Build order

1. glib/gtk3 GIR rebuild (separate work) → gobject-introspection + js128
2. `cinnamon-menus`
3. `cinnamon-desktop`
4. `cinnamon-translations`, `libxapp`, `accountsservice`, `gsound`, `timezonemap`
5. `graphene` + `libgsf` (separate work)
6. `cjs` 128.1
7. `muffin`
8. `cinnamon`, `nemo`, `cinnamon-session`, `cinnamon-screensaver`,
   `cinnamon-settings-daemon`, `cinnamon-control-center`
9. `cinnamon-desktop-session` (meta-package, last)

## Notes and known gaps

- `python-xapp` is NOT needed: nothing in the cinnamon 6.6 sources
  references it. Cinnamon uses the C `libxapp` library through GI.
- `accountsservice` has no recipe on this branch yet (it is part of the
  Unity work); it is listed as a runtime dependency where the session
  needs it.
- `js128` (mozjs-128) has no recipe yet; `cjs` cannot build without it.
- `pygobject` has no recipe yet; `libxapp` cannot configure with
  introspection=true without it, and cinnamon's Python helpers import
  `gi` at runtime. The helpers also import `setproctitle` and `psutil`,
  which have no recipes either.
- `libxdo` is looked up by cinnamon-screensaver but never used, so no
  libxdo recipe was added.
- `keybinder-3.0` and `accountsservice` are runtime-only requirements of
  the `cinnamon` package (the killer daemon imports Keybinder via GI;
  the shell talks to AccountsService over D-Bus), not build dependencies.
- `cinnamon-desktop` does not link accountsservice at build time, and
  `cinnamon-control-center` 6.6 has no keyboard panel (no libgnomekbd)
  and no accountsservice/Online-Accounts build dependency.
- `cinnamon-settings-daemon` does not link NetworkManager in 6.6.4.
- `cinnamon-screensaver` links neither cinnamon-desktop nor libxapp.
- `timezonemap` comes from the Debian libtimezonemap source, not from a
  linuxmint repo (no such repo/tag exists); the 0.4.6 version is taken
  from the tarball name because configure.ac still says 0.4.4.
