# XFCE desktop integration smoke tests

This checklist verifies the installed XFCE desktop, not just whether its packages
compile. Run it in a disposable VM before declaring a LightDM/XFCE integration
change runtime-verified.

Faseela uses **runit** for PID 1 and service supervision. Elogind provides
login1 session tracking; it does not replace runit. UPower and UDisks2 are
activated by the system D-Bus and must not be given duplicate runit daemons.

## Test layers

| Layer | Where it runs | What it proves |
|---|---|---|
| Static/recipe checks | Pull-request CI | Required package dependencies, staged desktop files, PAM/session wiring, runit service scripts and enabled-service links are present and syntactically valid |
| Package build | Package-build workflow | The changed packages build and their install hooks complete |
| Runtime smoke tests | Disposable VM or installed test machine | LightDM login, user session, D-Bus activation, Polkit prompts, storage, audio, notifications, portals and panel interactions actually work |

A green static check or package build is **not** evidence that a graphical login or
runtime service works. Record runtime results separately.

## Before testing

Use a disposable VM with a working virtual console and a snapshot you can restore.
Use the same architecture and XFCE flavor intended for release. Attach a virtual
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

## A. Clean-install scenario

### A1. Install and reach a recovery console

1. Boot the `iso-xfce` image and install Faseela to a disposable VM disk.
2. Create a normal, non-root user during installation (or by the documented
   account-creation process).
3. Boot the installed system to a TTY first. Do not enable LightDM until the
   prerequisite checks below pass.
4. Confirm that PID 1 is runit:

```sh
ps -p 1 -o comm=
```

Expected: `runit`.

### A2. Verify system services and session prerequisites

Run as root or prefix privileged commands with `doas`:

```sh
for service in dbus elogind elogind-userdbd polkitd NetworkManager; do
    printf '\\n===== %s =====\\n' "$service"
    sv status "/etc/sv/$service"
done

for service in dbus elogind elogind-userdbd polkitd NetworkManager; do
    test -L "/etc/runit/runsvdir/default/$service" || {
        echo "Missing enabled runit service: $service" >&2
        exit 1
    }
done

test -x /etc/sv/lightdm/run
test ! -L /etc/runit/runsvdir/default/lightdm
test -s /etc/pam.d/lightdm
test -s /etc/pam.d/lightdm-greeter
test -s /etc/lightdm/lightdm.conf.d/50-faseela-xfce.conf
grep -Fqx 'user-session=xfce' /etc/lightdm/lightdm.conf.d/50-faseela-xfce.conf
grep -q 'pam_elogind.so class=user type=x11 desktop=xfce' /etc/pam.d/lightdm
grep -q 'pam_elogind.so class=greeter type=x11 desktop=lightdm-greeter' /etc/pam.d/lightdm-greeter
! grep -R 'pam_systemd.so' /etc/pam.d/lightdm /etc/pam.d/lightdm-greeter /etc/pam.d/lightdm-autologin
```

Expected:

- The five enabled services report `run:` (or a short, clearly diagnosed
  startup failure that is fixed before proceeding).
- Each enabled service link points into `/etc/sv`.
- LightDM has a runit service definition but is not enabled by package
  installation; this is intentional.
- LightDM's user and greeter PAM stacks use `pam_elogind.so`, not
  `pam_systemd.so`.

Check the installed session entry and desktop integration files:

```sh
test -s /usr/share/xsessions/xfce.desktop
grep -Fqx 'Exec=dbus-run-session -- /usr/bin/faseela-start-xfce4' /usr/share/xsessions/xfce.desktop
test -x /usr/bin/faseela-start-xfce4
test -s /etc/xdg/autostart/faseela-audio-session.desktop
test -s /etc/xdg/autostart/thunar-daemon.desktop
test -s /etc/xdg/autostart/xfce-polkit.desktop
test -s /etc/xdg/autostart/nm-applet.desktop
```

### A3. Perform the controlled LightDM login test

From the VM's TTY/console, enable LightDM manually:

```sh
doas ln -s /etc/sv/lightdm /etc/runit/runsvdir/default/lightdm
doas sv up /etc/sv/lightdm
doas sv status /etc/sv/lightdm
```

Expected: LightDM stays up and displays the GTK greeter. Log in as the normal
test user and confirm that the XFCE desktop loads without returning to the
greeter, a black screen, or a shell.

If the display manager does not start, switch back to the VM console, run
`doas sv down /etc/sv/lightdm`, remove the enable link, and inspect LightDM and
Xorg logs before retrying:

```sh
doas sv down /etc/sv/lightdm
doas rm -f /etc/runit/runsvdir/default/lightdm
```

Do not enable LightDM automatically in the package recipe as a workaround for
a failed test.

### A4. Verify the logged-in XFCE session

Run these commands inside the graphical session as the test user:

```sh
test "$XDG_CURRENT_DESKTOP" = XFCE
test "$XDG_SESSION_TYPE" = x11
test -d "$XDG_RUNTIME_DIR"
test -O "$XDG_RUNTIME_DIR"
pgrep -u "$USER" -x xfce4-session
gdbus call --session --dest org.freedesktop.DBus \\
    --object-path /org/freedesktop/DBus \\
    --method org.freedesktop.DBus.ListNames
gdbus call --system --dest org.freedesktop.DBus \\
    --object-path /org/freedesktop/DBus \\
    --method org.freedesktop.DBus.ListNames
loginctl list-sessions
```

Expected: XFCE reports X11, the runtime directory exists and belongs to the
logged-in user, the session process is present, and both D-Bus commands return
a list of names. Elogind lists the active user session.

### A5. Exercise session services and desktop features

Perform each interaction, not just a process check:

| Area | Action | Expected result |
|---|---|---|
| NetworkManager | Open the network panel applet; connect/disconnect the VM network or a Wi-Fi test adapter; run `nmcli general status` | Applet icon and menu render; device state changes and NetworkManager reports connected/disconnected accurately |
| Polkit | Run `pkexec id` from a terminal | XFCE Polkit agent displays an authentication prompt; after valid authentication the command reports `uid=0(root)`. Cancel once and confirm the action is denied |
| Clipboard / Clipman | Copy several distinct text snippets, open Clipman's panel menu, select an older entry and paste it | Clipman panel icon is visible, history opens, and the selected text is pasted |
| Notifications | Run `notify-send "Faseela XFCE test" "Notification smoke test"` | A visible desktop notification appears; no missing notification-daemon error |
| Audio | Run `pgrep -u "$USER" -x pipewire`, `pgrep -u "$USER" -x wireplumber`, `pgrep -u "$USER" -x pipewire-pulse`, then `pactl info` | All three user processes are present, PulseAudio compatibility connects to PipeWire, and the VM's test audio plays |
| Removable storage | Attach the virtual removable disk, inspect it in Thunar, mount and unmount it | GVfs/Thunar sees the device; UDisks2 mounts and unmounts through the active-session policy without granting blanket access |
| Fixed/system storage policy | Attempt the relevant privileged action on a VM-only fixed test disk | UDisks2 applies its stricter system-device authorization and Polkit shows an administrator challenge |
| Thumbnails and archives | Open a folder containing image files; use Thunar's archive context menu to create and extract a test archive | Thumbnails appear and archive create/extract both work |
| Screenshots | Open the XFCE screenshot tool and save a screenshot | Screenshot UI opens and writes the requested image |
| Desktop portals (conditional) | The current `iso-xfce` flavor does not include the portal packages by default. When testing an image that includes them, confirm `/usr/share/dbus-1/services/org.freedesktop.portal.Desktop.service` exists and run `gdbus introspect --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop` | On portal-enabled images, the D-Bus service activates and introspection succeeds. On the standard XFCE flavor, record this check as N/A rather than a failure; a GTK-native file chooser should still open |
| Power management | Open XFCE power settings and inspect available actions; test suspend only when the VM platform supports it | Power actions are exposed; supported suspend/resume completes without losing the session |

Do not use a real data disk for mount-policy tests. Use disposable virtual
storage only.

### A6. Check runit supervision after desktop use

From a terminal in XFCE:

```sh
doas sv status /etc/sv/dbus
doas sv status /etc/sv/elogind
doas sv status /etc/sv/elogind-userdbd
doas sv status /etc/sv/polkitd
doas sv status /etc/sv/NetworkManager
```

Expected: the services remain supervised by runit. UPower and UDisks2 should
appear through D-Bus activation when requested; do not add separate runit
services for them. PipeWire and WirePlumber are per-user session processes,
not system runit services.

Log out and log back in once. Confirm that the session starts cleanly again and
that the audio, Polkit agent, notification daemon, network applet and Thunar
integration still work.

## B. Upgrade scenario

Use a separate VM snapshot containing the previously released Faseela XFCE
desktop. This scenario catches package replacement and migration regressions.

1. Boot the old installation and record the installed package versions.
2. Verify that the user can log in before the upgrade.
3. Run the normal repository update and package upgrade:

```sh
doas nawa update
doas nawa upgrade
```

4. Save the command output and confirm that package hooks complete without
   errors or unexpected service removal.
5. Reboot the VM.
6. Repeat sections **A2**, **A3**, **A4**, **A5** and **A6**.
7. Confirm that existing user files, panel layout, network configuration and
   clipboard preferences remain present.

Expected: the upgrade reaches the same runtime behavior as a clean install.
A successful package transaction alone is not a passing upgrade smoke test.

## C. Failure report

For every failed check, record:

- Scenario: clean install or upgrade.
- Faseela build and package versions.
- Section/check ID (for example, A3 LightDM login or A5 audio).
- Exact command or UI action and full error output.
- Relevant `sv status` output for runit-managed services.
- Relevant LightDM/Xorg logs and a screenshot when the failure is graphical.
- Whether the issue reproduces after restoring the VM snapshot.

File the failure against the responsible package or integration area (LightDM,
elogind/PAM, D-Bus, Polkit, NetworkManager, GVfs/UDisks2, PipeWire, XFCE panel,
notifications or portals). Do not report a generic “XFCE build failed” when
the package build succeeded and the runtime smoke test failed.

## D. Pull-request CI checks

Run the inexpensive static checks and the focused package build for changed
recipes:

```sh
python3 -I scripts/check-recipes.py
python3 -I scripts/check-groups.py
python3 -I scripts/test-desktop-integration.py
python3 -I scripts/test-xfce-smoke-checklist.py
```

The CI checks validate package metadata and integration wiring. They do not
replace sections A and B. Mark the runtime test matrix as passed only after the
clean-install and upgrade scenarios have been executed in a VM or on a
disposable installed system.
