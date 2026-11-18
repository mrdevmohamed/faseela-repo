# Faseela service policy

## Package payload versus service state

Recipes may ship systemd unit files, socket units, drop-ins, tmpfiles rules,
sysusers declarations, udev rules and vendor preset files. These are package
payload and describe what the distribution makes available.

A package hook is privileged shell code executed as root. It must not call
systemctl, sv, service or rc-service to preset, enable, disable, start, stop,
restart, mask, unmask or otherwise change service state. Hooks are not trusted
migration handlers and must not modify GRUB, initramfs, PID 1 selection or a
migration journal. The recipe checker rejects direct service-manager
mutations in [hooks] fields. It also detects recipes that install files into
Nawa's `/usr/lib/nawa/transaction-hooks.d` directory and scans their build
install scripts and recipe-local `*.sh` assets for the same commands. Nawa
executes these triggers after package-changing transactions, so they share
the same trust boundary. This is a static policy guard, not a sandbox for
arbitrary shell code.

Hooks may still perform narrowly scoped package setup that is not service
control, for example creating a system account or reloading udev rules when
newly installed rules must take effect. Keep such work idempotent and limited
to the package's own integration.

## When vendor presets are applied

The Faseela ISO build is the distribution-owned provisioning boundary. After
the complete target root and all package preset files are present,
bootstrap/mkiso.sh calls the host's systemctl --root=<target-root> preset-all
before creating the read-only SquashFS image. The command operates on the
target filesystem; it does not contact a running service manager and does not
start services.

This applies vendor defaults once to a freshly composed image. Package
installation and package upgrades do not reapply presets and therefore do not
overwrite an administrator's service choices. Preset files remain available
to an administrator who explicitly chooses to run systemctl preset <unit>,
systemctl enable <unit> or systemctl disable <unit> on the installed machine.

## Distribution defaults and flavors

Preset files express vendor defaults. Flavor-specific packages may ship
higher-priority preset files where necessary, such as NetworkManager taking
ownership of DHCP and disabling systemd-networkd. The global provisioning pass
sees all installed preset files together, so package installation order does
not determine which preset wins.

The system profile at /usr/share/nawa/system-profile.toml is separate from
service presets. It declares the distribution's desired init provider for
Nawa's system inspection and transition planner. An administrator may supply
/etc/nawa/system-profile.toml to override distribution defaults without
editing package-owned files.
