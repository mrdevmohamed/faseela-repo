# Optional messaging applications

Packages in this category are optional applications. They are not part of
the default desktop images, bootstrap or build roots. Install them
individually through Nawa when needed.

## Telegram Desktop

`telegram-desktop` packages the official upstream Linux x86_64 release
bundle. The archive and SHA-256 are pinned to the upstream GitHub release.
The package keeps Telegram's private runtime files under
`/usr/lib/telegram-desktop` and exposes `telegram-desktop` on PATH.

The recipe declares **WebKitGTK 4.1** as a runtime dependency. Nawa therefore
installs the GTK3 WebKit engine and its HTTPS/TLS runtime closure together
with Telegram, enabling Telegram Mini Apps and Web Apps without requiring a
separate manual WebKit installation.

Install on an existing Faseela system:

~~~sh
sudo nawa install telegram-desktop
~~~

WebKitGTK is intentionally not part of the default Sway or Xfce ISO flavors.
Its build is opt-in and resource-intensive; it is pulled in only when Telegram
is selected. The current WebKitGTK recipe disables GStreamer, video, WebRTC,
Web Audio and MediaRecorder to keep its build and runtime closure smaller.
JavaScript, HTML rendering and HTTPS networking remain enabled.

No Telegram-specific ISO flavor is maintained. The application can be
installed on either Sway or Xfce without rebuilding the desktop image.
