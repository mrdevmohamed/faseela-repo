# recipes/flatpak — Flatpak application runtime

This optional category supplies Flatpak and the dependencies COSMIC Store
needs to use its native Flatpak backend. It is selected through
`cosmic-store` rather than the generic `@gui` selector, keeping the
Sway/Xfce images free of the additional application-management stack.

## Package layout

| role | recipes |
|---|---|
| OpenPGP stack | `libassuan`, `npth`, `libksba`, `gnupg`, `gpgme` |
| Application metadata | `python-pyparsing`, `libfyaml`, `libxmlb`, `appstream` |
| Repository and installation engine | `ostree`, `flatpak` |

The Flatpak build reuses Faseela's existing Bubblewrap, xdg-dbus-proxy,
FUSE 3, seccomp, D-Bus and Polkit packages. It does not build or install
systemd units, generators, sysusers or tmpfiles. The privileged helper is
activated on demand by the system D-Bus.

Flathub is shipped as a signed system-wide static remote in
`/usr/share/flatpak/remotes.d/flathub.flatpakrepo`. To add the same remote to
a user's own installation:

```sh
flatpak remote-add --user --if-not-exists flathub /usr/share/flatpak/remotes.d/flathub.flatpakrepo
```

COSMIC Store builds with its native `flatpak` Cargo feature, exposing both
the per-user and system installations. System operations use D-Bus and
Polkit; COSMIC OSD provides the authentication agent and is built with the
Polkit helper path used by Faseela.

Inspect the dependency closure:

```sh
python3 scripts/check-recipes.py flatpak
nawa --recipes recipes deps flatpak
```

The recipe CI validates metadata, source pins, dependency declarations and
the Faseela integration contract. A complete clean package build and live
COSMIC session test are still required before considering runtime validation
complete.
