# Nekoray

Nekoray is a Qt-based desktop proxy configuration manager with a sing-box
backend. This package keeps the application name and upstream identity.

## Package status

The recipe currently packages the final upstream Linux AppImage release
(`4.0.1`) as a transitional binary bundle. The Faseela-maintained fork is
being developed at <https://github.com/mrdevmohamed/nekoray>; once that fork
publishes a complete Linux release artifact, this recipe should move to that
artifact and its independently verified checksum.

The AppImage is extracted while building the package. Installed systems run
the preserved upstream `AppRun` bundle through `/usr/bin/nekoray`, so the
system does not need AppImage FUSE support. The recipe deliberately disables
stripping, cleanup and package splitting to preserve the bundled Qt runtime
and upstream notices.

## Install

Install the package with Nawa:

```sh
sudo nawa install nekoray
```

For an ISO containing the GUI and Nekoray, select the optional
`iso-gui-nekoray` flavor. Nekoray is not part of the default Faseela ISO.

The package does not enable a system service. Start Nekoray from the
application menu or by running `nekoray`.
