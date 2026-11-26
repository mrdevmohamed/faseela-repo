# Xfce and LightDM on Faseela

## Initial Xorg execution model

The initial Xfce/LightDM integration uses **classic, root-run Xorg**. LightDM is
started by its systemd unit as root and launches the X server with the
privileges required by this model.

This is an intentional first implementation choice. It does **not** claim that
rootless Xorg is supported. LightDM and Polkit use systemd-logind's login1
interface for session tracking, while Xorg remains independent of logind.

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
not use seatd as a substitute for systemd-logind session tracking. Keep seatd available for
sessions and components that use it (including the existing Wayland setup).

### Service policy

The package installs `lightdm.service`, but it must **not** enable the service
automatically during package installation. This keeps a failed display-manager
start from unexpectedly replacing the user's normal TTY login.

Enable LightDM manually only for a controlled test, after confirming that the
Xorg, greeter, PAM, DBus, and XFCE components are installed:

```sh
doas systemctl enable --now lightdm.service
doas systemctl status --no-pager lightdm.service
```

Run this from a local machine with a working TTY and a way to switch back to
another TTY if the graphical login fails. Do not run a second display manager
at the same time.

To stop the test and disable the service:

```sh
doas systemctl disable --now lightdm.service
```

Inspect LightDM and Xorg logs before considering automatic enablement. A
successful package build or the existence of `lightdm.service` is not proof
that the graphical login works.

## systemd-logind session tracking and PolicyKit

Faseela uses **systemd 261.5** for PID 1, service supervision and as its login1
session and seat manager (`systemd-logind`). The `org.freedesktop.login1` bus
name is activated by systemd's own D-Bus service file. `lightdm.service` is
shipped disabled; `dbus`, `polkit` and `NetworkManager` are enabled through
presets.

LightDM 1.33.1 already contains a login1 D-Bus client for seat discovery and
session activation. Its PAM service stacks load `pam_systemd.so` (shipped by the
systemd package in `/usr/lib/security`) to register the greeter and user
sessions:

- `lightdm` and `lightdm-autologin` create `class=user`,
  `type=x11`, `desktop=xfce` sessions.
- `lightdm-greeter` creates a separate `class=greeter` session.

`pam_systemd` asks logind to create the session and `XDG_RUNTIME_DIR` under
`/run/user/<uid>`. No `pam_elogind.so` module exists on the system.

Polkit is built with `-Dsession_tracking=logind` against libsystemd, so it can
identify the active local session when authorizing desktop requests. The
`xfce-polkit` authentication agent is installed as an XDG autostart entry
scoped to `OnlyShowIn=XFCE;`; it starts inside the logged-in user's desktop
session and displays authentication prompts.

systemd-logind's power actions (shutdown, reboot) are authorized through Polkit.
The actual power actions still require validation in an installed XFCE session.

UDisks2 keeps its upstream PolicyKit distinction: normal removable-volume
mounts are available to the active local session, while inactive or remote
callers require administrator authentication. Devices classified by UDisks2
as system devices (normally fixed, non-removable disks) retain the stricter
administrator challenge even for an active session. The XFCE agent presents
that challenge; no blanket mount permission is added.

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
