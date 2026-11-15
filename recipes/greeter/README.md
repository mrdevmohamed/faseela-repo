# recipes/greeter — optional login managers

This category contains login daemons and greeter applications that should not
be pulled into a desktop session merely because its desktop packages are
selected by category.

## COSMIC login

- `greetd` is the small PAM-aware login daemon.
- `cosmic-greeter` supplies the COSMIC greeter UI and its daemon integration.
  It depends on greetd, installs a PAM service using `pam_elogind.so`, and
  ships its runit service disabled.

Install the COSMIC desktop and greeter separately:

```sh
sudo nawa install cosmic-desktop
sudo nawa install cosmic-greeter
sudo nawa service enable cosmic-greeter
```

Installing `cosmic-desktop` or building the `iso-cosmic` flavor does not
install or enable a login manager. Disable the getty service that owns the
selected VT before enabling greetd.
