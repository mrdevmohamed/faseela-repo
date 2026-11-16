# Optional messaging and phone integration

Packages in this category are optional applications. They are not part of
the default desktop images, bootstrap or build roots. Install them
individually through Nawa or through the `messaging` package group.

## NectarLink

`nectarlink` packages the official upstream Linux x86_64 desktop bundle.
It connects an Android phone and a Linux PC over a local, end-to-end encrypted
connection without requiring an account or cloud relay.

Features include file and clipboard transfer, phone notifications, SMS and
call integration, screen mirroring, and camera/audio features. The package
keeps the executable and its private Qt/QML runtime under
`/usr/lib/nectarlink`, and exposes `nectarlink-desktop` on PATH.

Install on an existing Faseela system:

~~~sh
sudo nawa install nectarlink
~~~

Or install the messaging group (NectarLink is its default selection):

~~~sh
sudo nawa group install messaging
~~~

The Android companion app is not part of the Linux package; get it from the
[upstream NectarLink project](https://github.com/thtbee/nectarlink).

The recipe deliberately does not execute the upstream `install.sh`. That
script changes system-wide firewall rules, kernel module loading and udev
permissions, which must not happen as a side effect of installing a Nawa
package. The Faseela package installs the application, its private Qt runtime,
desktop entry, icons and metadata. Optional phone-as-webcam and remote
keyboard/mouse integration require their separate system setup and are not
enabled automatically.

**Updates are managed by Nawa.** Turn off NectarLink's built-in automatic
updates in its Settings and upgrade it with:

~~~sh
sudo nawa upgrade nectarlink
~~~

The upstream tarball updater is not aware of Nawa and can install a separate
copy under `/opt/nectarlink`; do not use it for the Faseela package.

The package is pinned to upstream release `0.1.5` and requires x86_64 with
glibc 2.39 or newer. It is optional and can be installed on either Sway or
Xfce without rebuilding an ISO.

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
