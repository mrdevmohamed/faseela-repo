# Cinnamon desktop integration smoke tests

This checklist verifies the installed Cinnamon desktop, not just whether its packages
compile. Run it in a disposable VM before declaring a LightDM/Cinnamon integration
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
Use the same architecture and Cinnamon flavor intended for release. Attach a virtual
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

1. Boot the `iso-cinnamon` image. The system reaches the LightDM greeter.
2. The greeter lists the Cinnamon session (`cinnamon.desktop`) and the user.
3. Log in as a user in the `video`, `render`, `input` and `audio` groups.
   The Cinnamon session starts (Muffin window manager, Cinnamon shell, panel).
4. `loginctl` shows the session as `active`, `type=x11`, `class=user`,
   with the seat assigned.

## 2. Desktop shell

1. The Cinnamon panel, menu and window list are present; the menu opens
   and lists installed applications (Nemo, terminal, Firefox).
2. Open Cinnamon Settings (`cinnamon-settings`): every panel opens without
   crashing (Display, Keyboard, Applets, Network, Sound, Backgrounds).
3. Change the keyboard layout to US + Arabic and confirm Alt+Shift toggles
   layouts in a terminal (the Xorg drop-in ships `us,ara`).
4. Open Nemo: the file manager shows the home directory, and the sidebar
   lists removable media when a virtual disk is attached.
5. Lock the screen (cinnamon-screensaver): the lock screen appears and
   unlocks with the user password. The screensaver uses linux-pam.

## 3. Session services

1. `systemctl --user status` shows the Cinnamon session services running
   (`cinnamon-session`, `cinnamon-settings-daemon`).
2. NetworkManager applet shows the virtual network as connected.
3. Volume control (Cinnamon sound applet) shows PipeWire sinks; audio
   plays through the virtual sound device.
4. A Polkit prompt appears when a privileged action is requested
   (for example, changing the date in Cinnamon Settings) and succeeds
   with the user password.
5. `xdg-desktop-portal` and `xdg-desktop-portal-gtk` are running;
   a file chooser opened from Firefox uses the portal.

## 4. JavaScript engine

1. `cjs --version` (or `js128 --version`) runs and reports the 128 line.
2. Cinnamon applets that use JavaScript (menu, window list) work without
   `Cjs` errors in `~/.xsession-errors` or the journal.

## Known limitations (do not treat as test failures)

- js128 is the Firefox 128 ESR line, which is end of life; Cinnamon 6.6
  needs it because cjs 140 requires glib >= 2.86.
- LightDM is packaged but not pre-enabled in the flavor: the graphical
  login stays a manual step until the Xorg privilege path is validated.
- No package in this tree was compiled in the review VM; validation here
  is static until the package-build workflow runs.
