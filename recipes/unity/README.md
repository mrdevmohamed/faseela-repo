# recipes/unity — the Unity 7 desktop (X11)

Classic Unity 7 as maintained by the Ubuntu Unity community: the Compiz-based
shell, its libraries and its supporting services, plus the libraries those need
that no other Faseela category provides. The supported image is `iso-unity`.

Nothing here is selected by another flavor; the category is opt-in.

## Sources

The sandbox that builds recipes reaches Ubuntu's archive, so Unity-specific
components use the upstream tarballs that Ubuntu packages (`orig.tar.*`), pinned by
SHA-256. Debian/Ubuntu patches that the build needs are vendored as recipe assets.

## Layout

* **Build foundations** (this change): `vala`, `boost`, `glewmx`, `libglu`,
  `protobuf`, `libgtop`, `startup-notification`, `dconf`.

The remaining layers (Unity libraries, Nux, Compiz, the shell and the session)
are added in follow-up changes, each built and published before the next.
