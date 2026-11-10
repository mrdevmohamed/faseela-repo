# Xfce and LightDM on Faseela

## Initial Xorg execution model

The initial Xfce/LightDM integration uses **classic, root-run Xorg**. LightDM is
started by its runit service as root and launches the X server with the
privileges required by this model.

This is an intentional first implementation choice. It does **not** claim that
rootless Xorg is supported, and it does not make LightDM depend on
systemd-logind or systemd.

### Why this model

The current `xorg-server` recipe builds with:

- `-D suid_wrapper=false`
- `-D systemd_logind=false`

Consequently, the installation does not provide `Xorg.wrap`. The first
LightDM bring-up does not rely on that wrapper: LightDM runs as root and starts
the X server through its normal privileged path.

The greeter remains an unprivileged account (`lightdm`). After login, the
selected desktop session runs as the logged-in user.

### Relationship with seatd

The presence of `seatd` and membership in the `seat` group do not, by
themselves, make this Xorg server rootless. The initial root-run Xorg path does
not use seatd as a substitute for systemd-logind. Keep seatd available for
sessions and components that use it (including the existing Wayland setup).

### Service policy

The package installs `/etc/sv/lightdm`, but it must **not** enable the service
automatically during package installation. This keeps a failed display-manager
start from unexpectedly replacing the user's normal TTY login.

Enable LightDM manually only for a controlled test, after confirming that the
Xorg, greeter, PAM, DBus, and XFCE components are installed:

```sh
doas ln -s /etc/sv/lightdm /etc/runit/runsvdir/default/lightdm
doas sv up lightdm
doas sv status lightdm
```

Run this from a local machine with a working TTY and a way to switch back to
another TTY if the graphical login fails. Do not run a second display manager
at the same time.

To stop the test and disable the service:

```sh
doas sv down lightdm
doas rm /etc/runit/runsvdir/default/lightdm
```

Inspect LightDM and Xorg logs before considering automatic enablement. A
successful package build or the existence of `/etc/sv/lightdm` is not proof
that the graphical login works.

## Future rootless Xorg work

Rootless Xorg is a separate follow-up. It requires a deliberately designed and
tested seat-management/privilege path (for example, a suitable libseat
integration or another supported Xorg launch mechanism), correct device
access, and LightDM integration. Do not describe the current implementation as
rootless and do not remove the classic path until the replacement is tested.

## Current validation status

The installed-system inspection confirmed that DBus and seatd are running,
the user belongs to the `seat`, `video`, and `render` groups, Xorg and the
modesetting DDX are installed, and the XFCE session desktop entry is present.
These checks establish prerequisites only; they do not yet confirm a successful
LightDM login. The controlled LightDM test remains required.
