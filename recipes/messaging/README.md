# Optional messaging applications

Packages in this category are optional applications. They are not part of
the default desktop images, bootstrap or build roots. Install them
individually through Nawa when needed.

## Telegram Desktop

`telegram-desktop` packages the official upstream Linux x86_64 release
bundle. The archive and SHA-256 are pinned to the upstream GitHub release.
The package keeps Telegram's private runtime files under
`/usr/lib/telegram-desktop` and exposes `telegram-desktop` on PATH.

Install on an existing Faseela system:

~~~sh
sudo nawa install telegram-desktop
~~~

No Telegram-specific ISO flavor is maintained. The application can be
installed on either Sway or Xfce without rebuilding the desktop image.
