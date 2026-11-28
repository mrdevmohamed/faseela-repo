# Unity 7 desktop integration smoke tests

This checklist verifies the installed Unity 7 desktop, not just whether its
packages compile. Run it in a disposable VM before declaring a LightDM/Unity
integration change runtime-verified.

Faseela uses **systemd** for PID 1, service supervision and login1 session
tracking (`systemd-logind`, registered through `pam_systemd`). UPower and
UDisks2 are activated by the system D-Bus and must not be given duplicate
systemd units.

Unity 7 here is the classic Compiz + Nux shell on Xorg, with LightDM and
Unity's own `unity-greeter` — not Lomiri, and not the GTK greeter.
Gestures/GEIS and AppStream are compiled out. GObject introspection is
enabled (gobject-introspection + glib-gir) for the lenses and the shell's
GIR chain. The Dash ships all five lenses plus the home scope, the panel
ships the four Unity indicators, and notifications go through Unity's own
`notify-osd`. The HUD and `unity-tweak-tool` are intentionally not shipped:
the HUD needs a Qt5 stack the repo does not have, and the tweak tool is
not part of the default desktop.

## Test layers

| Layer | Where it runs | What it proves |
|---|---|---|
| Static/recipe checks | Pull-request CI | Required package dependencies, staged desktop files, PAM/session wiring, systemd unit files and presets are present and syntactically valid |
| Package build | Package-build workflow | The changed packages build and their install hooks complete |
| Runtime smoke tests | Disposable VM or installed test machine | LightDM login, Unity session, Compiz, indicators, settings daemon, D-Bus activation, Polkit prompts, storage, audio, notifications and portals actually work |

A green static check or package build is **not** evidence that a graphical
login or runtime service works. Record runtime results separately.

## Before testing

Use a disposable VM with a working virtual console and a snapshot you can
restore. Use the same architecture and Unity flavor intended for release.
Attach a virtual network adapter and, for storage tests, a removable virtual
disk. Keep a second TTY or the VM console available before enabling LightDM.

Record the test environment:

- Faseela release/build identifier:
- ISO or installed-system image:
- VM platform and firmware mode:
- Test date:
- Test snapshot name:
- Tester:

Do not perform the LightDM service test on a machine that is already using
another display manager.

## A. Clean-install scenario

### A1. Install and reach a recovery console

1. Boot the `iso-unity` image and install Faseela to a disposable VM disk.
2. Create a normal, non-root user during installation (or by the documented
   account-creation process).
3. Boot the installed system to a TTY first. Do not enable LightDM until the
   prerequisite checks below pass.
4. Confirm that PID 1 is systemd:

```sh
ps -p 1 -o comm=
```

Expected: `systemd`.

### A2. Verify system services and session prerequisites

Run as root or prefix privileged commands with `doas`:

```sh
for service in dbus systemd-logind polkit NetworkManager; do
    printf '\n===== %s =====\n' "$service"
    systemctl status --no-pager "$service.service" || true
done

for service in dbus polkit NetworkManager; do
    systemctl is-enabled --quiet "$service.service" || {
        echo "Service is not enabled: $service" >&2
        exit 1
    }
done

test -s /usr/lib/systemd/system/lightdm.service
! systemctl is-enabled --quiet lightdm.service
test -s /etc/pam.d/lightdm
test -s /etc/pam.d/lightdm-greeter
test -s /usr/share/lightdm/lightdm.conf.d/50-unity.conf
grep -Fqx 'user-session=unity' /usr/share/lightdm/lightdm.conf.d/50-unity.conf
grep -q 'pam_systemd.so class=user type=x11 desktop=unity' /etc/pam.d/lightdm
! grep -R 'pam_elogind.so' /etc/pam.d/

# PAM shadow-password authentication requires this helper to retain SUID.
test -f /usr/sbin/unix_chkpwd
test "$(stat -c '%u:%g:%a' /usr/sbin/unix_chkpwd)" = "0:0:4755"
```

Expected:

- The four services report `active (running)` (or a short, clearly diagnosed
  startup failure that is fixed before proceeding).
- `systemctl is-enabled` succeeds for dbus, polkit and NetworkManager; they are
  enabled by presets (`systemctl preset`), not by hand-made links.
- LightDM has a unit file but is not enabled by package installation; this is
  intentional.
- LightDM's user and greeter PAM stacks use `pam_systemd.so`; no `pam_elogind.so`
  remains anywhere under `/etc/pam.d`.
- `/usr/sbin/unix_chkpwd` is owned by `root:root` and has mode `4755`.
  Nawa intentionally strips SUID/SGID bits while extracting package archives;
  linux-pam restores this required helper mode in its post-install hook.

Check the installed session entry and desktop integration files:

```sh
test -s /usr/share/xsessions/unity.desktop
grep -Fqx 'Exec=/usr/bin/unity-session' /usr/share/xsessions/unity.desktop
grep -Fqx 'TryExec=/usr/bin/unity' /usr/share/xsessions/unity.desktop
test -x /usr/bin/unity-session
test -x /usr/bin/unity
test -s /usr/lib/systemd/user/unity-session.target
test -s /usr/lib/systemd/user/unity-session.service
test -s /usr/lib/systemd/user/unity-settings-daemon.service
test -L /usr/lib/systemd/user/unity-session.target.wants/unity-settings-daemon.service
test -s /usr/share/glib-2.0/schemas/21_ubuntu-unity.gschema.override
test -s /etc/xdg/autostart/faseela-audio-session-unity.desktop
grep -Fqx 'OnlyShowIn=Unity;' /etc/xdg/autostart/faseela-audio-session-unity.desktop
test -s /usr/share/xdg-desktop-portal/unity-portals.conf
grep -Fqx 'default=gtk' /usr/share/xdg-desktop-portal/unity-portals.conf
test -s /etc/X11/xorg.conf.d/00-faseela-unity-keyboard.conf
test -e /usr/lib/compiz/libunityshell.so

Check Unity's own greeter, the Dash lenses, the indicators, the
control-center and the notification daemon are installed:

```sh
test -x /usr/sbin/unity-greeter
test -s /usr/share/lightdm/lightdm.conf.d/50-unity-greeter.conf
test -s /usr/share/xgreeters/unity-greeter.desktop
test -s /usr/share/unity-greeter/logo.png
test -x /usr/bin/unity-control-center
test -x /usr/libexec/notify-osd
test -s /usr/share/dbus-1/services/org.freedesktop.Notifications.service
test -s /usr/share/unity/scopes/applications/applications.scope
test -s /usr/share/unity/scopes/home.scope
test -s /usr/share/unity/scopes/photos/shotwell.scope
test -s /usr/share/unity/scopes/video/local.scope
test -s /usr/lib/unity/unity-scope-applications.so
test -s /usr/libexec/unity-lens-files/unity-files-daemon
test -s /usr/libexec/unity-lens-music/unity-music-daemon
test -s /usr/libexec/unity-lens-video/unity-video-lens-daemon
test -s /usr/libexec/unity-scope-home/unity-scope-home
for indicator in sound session datetime power; do
    test -s "/usr/share/unity/indicators/com.canonical.indicator.$indicator"
    test -s "/usr/lib/systemd/user/indicator-$indicator.service"
done
```

### A3. Perform the controlled LightDM login test

From the VM's TTY/console, enable LightDM manually:

```sh
systemctl enable lightdm.service
systemctl start lightdm.service
```

Expected:

- Unity's own greeter appears, offers the **Unity** session, and logs
  the test user in.
- After login, Compiz is running (`compiz` is the session process), the Unity
  launcher, top panel and Dash appear, and `unity-settings-daemon` is running
  as a user service.
- Logging out returns to the greeter; the `unity-session.service` leader
  (`sleep infinity`) stops with the session.

If the greeter does not appear, check `journalctl -u lightdm` and
`systemctl status lightdm` from a TTY before changing anything else.

### A4. Check the session from inside Unity

As the logged-in user, in a terminal (`xfce4-terminal` in the default image):

```sh
echo "$XDG_CURRENT_DESKTOP $XDG_SESSION_DESKTOP $XDG_SESSION_TYPE"
loginctl show-session "$XDG_SESSION_ID" -p Type -p Desktop -p State
systemctl --user status unity-session.target unity-settings-daemon.service
pgrep -a compiz
pgrep -a unity-settings-daemon
```

Expected: `XDG_CURRENT_DESKTOP` contains `Unity`, `XDG_SESSION_TYPE` is
`x11`, the logind session is active, and both the session target and the
settings daemon are active.

### A5. Exercise session services and desktop features

- Open the Dash and launch an application; open the file manager (Thunar)
  and confirm removable-storage volumes appear via GVfs/UDisks2.
- Open the Dash and check the five lenses: Applications, Files, Music,
  Photos (Shotwell only) and Video (local only) all return results, and the
  home scope aggregates them. The applications lens searches installed apps
  only — there is no Software Center / apt search and no ratings.
- Confirm the four Unity indicators are in the top panel: sound, session,
  date/time (with the Evolution calendar backend) and power. Open
  `unity-control-center` and confirm its panels open (the Network and Wacom
  panels are intentionally absent).
- Send a test notification (for example `notify-send "test"`) and confirm
  Unity's `notify-osd` bubble appears instead of the Xfce notifier.
- Play audio through PipeWire (the `faseela-audio-session` autostart entry,
  `OnlyShowIn=Unity;`, starts it per session) and confirm volume control
  works.
- Confirm the NetworkManager applet appears in the indicator area and can
  list connections.
- Trigger a Polkit prompt (for example, mounting a system device) and confirm
  the authentication dialog appears.
- Open a file chooser from Firefox and confirm the GTK portal backend answers
  it (`unity-portals.conf` selects `default=gtk`).
- Change the keyboard layout with Alt+Shift (US + Arabic, from
  `00-faseela-unity-keyboard.conf`) and confirm the layout switches.

### A6. Check systemd supervision after desktop use

```sh
systemctl --user status unity-session.target
systemctl status dbus systemd-logind polkit NetworkManager
journalctl --user -u unity-settings-daemon.service --no-pager | tail -20
```

Expected: no failed units related to the Unity session, and no duplicate
activation of UDisks2, UPower or the portal backends.

## B. Upgrade scenario

1. Install an earlier `iso-unity` build, then upgrade the Unity packages
   with Nawa.
2. Log in again and repeat A4–A5. The session entry, LightDM drop-in and
   GSettings override must survive the upgrade; a stale
   `21_ubuntu-unity.gschema.override` must be recompiled by the
   `unity-session` post-install hook (`glib-compile-schemas`).

## C. Failure report

Record, for every failure: the step, the exact command and output, the
relevant `journalctl` lines, and whether the failure reproduces after a
reboot from a clean snapshot. Do not mark the change runtime-verified until
A3–A5 pass on a clean install.

## D. Pull-request CI checks

Static checks for a Unity change (all must pass in CI):

```sh
python3 -I scripts/check-recipes.py
python3 -I scripts/test-schema-v5-recipes.py
python3 -I scripts/check-groups.py
python3 -I scripts/flavor.py check
python3 -I scripts/test-flavor.py
python3 -I scripts/test-unity-integration.py
python3 -I scripts/test-desktop-integration.py
```

`test-unity-integration.py` also guards the `unity` package group in
`groups.toml` and the contents of `docs/unity-smoke-tests.md`.
