# MATE desktop integration smoke tests

This checklist verifies the installed MATE desktop, not just whether its packages
compile. Run it in a disposable VM before declaring a LightDM/MATE integration
change runtime-verified.

Faseela uses **systemd** for PID 1, service supervision and login1 session
tracking (`systemd-logind`, registered through `pam_systemd`). UPower and UDisks2
are activated by the system D-Bus and must not be given duplicate systemd units.

## Test layers

| Layer | Where it runs | What it proves |
|---|---|---|
| Static/recipe checks | Pull-request CI | Required package dependencies, staged desktop files, PAM/session wiring, systemd unit files and presets are present and syntactically valid |
| Package build | Package-build workflow | The changed packages build and their install hooks complete |
| Runtime smoke tests | Disposable VM or installed test machine | LightDM login, user session, D-Bus activation, Polkit prompts, storage, audio, notifications, portals and panel interactions actually work |

A green static check or package build is **not** evidence that a graphical login or
runtime service works. Record runtime results separately.

## Before testing

Use a disposable VM with a working virtual console and a snapshot you can restore.
Use the same architecture and MATE flavor intended for release. Attach a virtual
network adapter and, for storage tests, a removable virtual disk. Keep a second
TTY or the VM console available before enabling LightDM.

Record the test environment:

- Faseela release/build identifier:
- ISO or installed-system image:
- VM platform and firmware mode:
- Test date:
- Test snapshot name:
- Tester:

Do not perform the LightDM service test on a machine that is already using
another display manager.

## 1. Boot and LightDM login

1. Boot the `iso-mate` image. The system reaches the LightDM greeter.
2. The greeter lists the MATE session (`mate.desktop`) and the user.
3. Log in as a user in the `video`, `render`, `input` and `audio` groups.
   The MATE session starts (Marco window manager, mate-panel, Caja desktop).
4. `loginctl` shows the session as `active`, `type=x11`, `class=user`,
   with the seat assigned.

## 2. Desktop shell

1. The top and bottom MATE panels are present with the Applications,
   Places and System menus, clock, and notification area.
2. Open MATE Control Center (`mate-control-center`): every capplet opens
   without crashing (Display, Keyboard, Mouse, Network, Sound, Windows).
   The Network and User Accounts capplets show the AppIndicator and
   accountsservice integration working.
3. Change the keyboard layout to US + Arabic and confirm Alt+Shift toggles
   layouts in a terminal (the Xorg drop-in ships `us,ara`).
4. Open Caja: the file manager shows the home directory, and the sidebar
   lists removable media when a virtual disk is attached.
5. Open Atril: it opens and renders a PDF
   (poppler support). (Pluma and Eye of MATE join the session in stage 3.)
6. Lock the screen (mate-screensaver): the lock screen appears and
   unlocks with the user password.

## 3. Session services

1. `systemctl --user status` shows the MATE session services running
   (`mate-session-manager`, `mate-settings-daemon`).
2. NetworkManager applet shows the virtual network as connected.
3. Volume control (mate-volume-control) shows PipeWire sinks; audio
   plays through the virtual sound device.
4. A Polkit prompt appears when a privileged action is requested
   (for example, changing the date in MATE Control Center) and succeeds
   with the user password.
5. `xdg-desktop-portal` and `xdg-desktop-portal-gtk` are running;
   a file chooser opened from Firefox uses the portal.

## Known limitations (do not treat as test failures)

- LightDM is packaged but not pre-enabled in the flavor: the graphical
  login stays a manual step until the Xorg privilege path is validated.
- No package in this tree was compiled in the review VM; validation here
  is static until the package-build workflow runs.
