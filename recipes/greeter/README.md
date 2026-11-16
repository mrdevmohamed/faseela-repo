# recipes/greeter — optional login managers

This category contains login daemons and greeter applications that should not
be pulled into a desktop session merely because its desktop packages are
selected by category.

## COSMIC login

- `greetd` is the small PAM-aware login daemon.
- `cosmic-greeter` supplies the COSMIC greeter UI and its daemon integration.
  It depends on greetd, installs a PAM service using `pam_elogind.so`, and
  ships its runit service disabled.

The `iso-cosmic` image flavor includes this stack and applies its runit
service policy when the image root is assembled: it enables
`cosmic-greeter`, disables `getty-tty1`, and removes an enabled LightDM link
when present. The greeter then owns VT 1 on first boot.

A normal `nawa install cosmic-desktop` remains session-only and does not
silently take over a terminal. On an existing system, install the greeter
explicitly and switch the service links yourself:

```sh
doas nawa install cosmic-greeter
doas nawa service disable lightdm
doas nawa service disable getty-tty1
doas nawa service enable cosmic-greeter
```
