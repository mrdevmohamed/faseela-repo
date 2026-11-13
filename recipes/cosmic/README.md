# recipes/cosmic — COSMIC desktop for Faseela

This category contains 21 recipes from the System76 COSMIC Epoch desktop,
pinned as one coordinated `epoch-1.0.8` snapshot. Rust components use their
committed Cargo lockfiles and Nawa's `[fetch.cargo]` phase; workspace
dependencies such as libcosmic are fetched before the offline build.

## Package layout

| role | recipes |
|---|---|
| Session and shell | `cosmic-comp`, `cosmic-session`, `cosmic-panel`, `cosmic-applets`, `cosmic-launcher`, `cosmic-notifications`, `cosmic-workspaces`, `cosmic-osd`, `cosmic-bg`, `cosmic-idle`, `cosmic-settings`, `cosmic-settings-daemon`, `cosmic-randr` |
| Portal and visual assets | `xdg-desktop-portal-cosmic`, `cosmic-icons`, `cosmic-screenshot` |
| Applications | `cosmic-files`, `cosmic-term`, `cosmic-edit`, `cosmic-store` |
| Optional login (separate `greeter/` category) | `greetd`, `cosmic-greeter` |
| Faseela integration | `cosmic-desktop` |

## Faseela integration

Faseela uses runit as PID 1. COSMIC therefore uses the existing system
infrastructure rather than introducing systemd:

- **Session:** run `start-cosmic` from a tty. The upstream launcher creates a
  private D-Bus session and starts the COSMIC session manager. The desktop
  session entry is installed under `/usr/share/wayland-sessions`.
- **Seat and DRM:** `cosmic-comp` uses libseat with
  `LIBSEAT_BACKEND=seatd`. The shared `seatd-runit` package owns the runit
  service and render-node udev rule used by both COSMIC and Sway.
- **Login/session tracking:** COSMIC's login1 D-Bus calls are served by
  elogind. The compositor and core session do not require systemd.
- **Audio:** `cosmic-desktop` adds an XDG autostart entry that runs the shared
  `faseela-audio-session` helper. The helper keeps PipeWire, WirePlumber and
  pipewire-pulse alive for the COSMIC session.
- **Portals:** the COSMIC backend is activated by the session D-Bus; its
  `cosmic-portals.conf` prefers COSMIC and falls back to GTK, and routes Secret
  requests to GNOME Keyring.
- **Wallpaper:** the default COSMIC background schema points to
  `/usr/share/backgrounds/faseela/`, provided by Faseela branding.

The desktop meta-package is a normal opt-in package. It does not enable a
login manager, take over a virtual terminal, or install a greeter service.

## Optional login greeter

The greeter stack is separate from `cosmic-desktop`. Install it only when
you want greetd to own a virtual terminal:

```sh
sudo nawa install cosmic-greeter
sudo nawa service enable cosmic-greeter
```

The package includes greetd, its COSMIC greeter, PAM integration through
`pam_elogind.so`, and a runit service shipped disabled. The privileged
`cosmic-greeter-daemon` is started on demand by the system D-Bus activation
file, so this path does not depend on a systemd unit. Disable the
`getty-tty1` service first when it owns the selected VT. The package hook
preserves a custom `/etc/greetd/config.toml`; it only replaces the stock
agreety sample.

## Build and install

The `iso-cosmic` flavor selects `@cosmic` plus Firefox. Because the login
packages live in the separate `greeter/` category, the image does not pull in
greetd or the greeter-specific dependency closure (PAM is already in the base system).

Inspect the dependency closure:

```sh
python3 scripts/check-recipes.py cosmic-desktop
nawa --recipes recipes deps cosmic-desktop
```

## Scope and limitations

- The recipes are source-pinned but a complete clean end-to-end package build
  has not yet been recorded. Repository CI validates metadata, dependency
  declarations and Faseela integration contracts; it does not prove upstream
  compilation or runtime behavior.
- Cargo registry dependencies are locked. Cargo git dependencies referenced
  by upstream lockfiles are fetched by Nawa's Cargo fetch phase; they are not
  independently pinned by registry checksums.
- `cosmic-player` is not included because the source tree does not currently
  package the GStreamer stack it requires. Use the existing `mpv` package.

