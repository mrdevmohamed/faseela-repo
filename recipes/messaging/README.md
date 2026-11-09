# Optional messaging applications

Packages in this category are opt-in and are not part of the default ISO,
bootstrap, or GUI flavor. They can be installed individually with Nawa or
selected through a dedicated flavor.

## Telegram Desktop

`telegram-desktop` packages the official upstream Linux x86_64 release
bundle. The archive and SHA-256 are pinned to the upstream GitHub release.
The package keeps Telegram's private runtime files under
`/usr/lib/telegram-desktop` and exposes `telegram-desktop` on PATH.

Install on an existing Faseela system:

```sh
sudo nawa install telegram-desktop
```

Build an ISO that includes Telegram Desktop with the
`iso-gui-telegram` flavor.
