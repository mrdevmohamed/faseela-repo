# Storytold Craft apps

This category packages the official Linux x86_64 FHS release archives from
[Storytold](https://github.com/storytold). It currently contains 15 optional
desktop applications. The Linux bundles expose an FHS-style `bin/` and
`share/` payload. The recipes install these as owned files under `/usr/bin`
and `/usr/share` (and also accept a conventional `usr/` payload); they do
not run an application-specific installer or compile the upstream source.

## Supported applications

| Package | Upstream release | Purpose |
|---|---:|---|
| `photocraft` | 0.19.0 | PhotoCraft image editor |
| `pdfcraft` | 0.17.0 | PDFCraft PDF workbench |
| `soundcraft` | 0.16.0 | SoundCraft audio workstation |
| `lightcraft` | 0.17.0 | LightCraft photo manager and RAW developer |
| `filmcraft` | 0.16.0 | FilmCraft video editor |
| `designcraft` | 0.17.0 | DesignCraft page layout and publishing |
| `vectorcraft` | 0.20.0 | VectorCraft vector illustration |
| `effectcraft` | 0.20.0 | EffectCraft motion graphics and visual effects |
| `wordcraft` | 0.14.0 | WordCraft word processor |
| `deckcraft` | 0.14.1 | DeckCraft presentation editor |
| `gridcraft` | 0.15.0 | GridCraft spreadsheet |
| `cadcraft` | 0.16.0 | CADCraft 2D CAD |
| `figcraft` | 0.14.0 | FigCraft interface design and prototyping |
| `craft-anything` | 0.2.0 | Craft Anything software investigation |
| `texturecraft` | 0.2.0 | TextureCraft 3D texture painter |

All source URLs are pinned to a specific GitHub release tag. Each recipe's
`sha256` is the SHA-256 digest reported by GitHub for that exact release
asset, not a mutable `latest` URL. When updating a recipe, update `version`,
`source_dir`, `source`, and `sha256` together; compare the result with the
upstream `SHA256SUMS.txt` asset and bump `rel` if the installed file tree or
packaging script changes.

## Runtime model

These builds target Faseela's **Wayland/Sway** session on x86_64. Upstream
bundles are built for both Wayland and X11, but this initial support targets
Wayland only. The recipes provide `wayland`, `libxkbcommon`, and `mesa`
(EGL/GPU loader), along with `glibc` and `gcc` for the C runtime. Launch the
applications from Faseela's Sway session with `WAYLAND_DISPLAY` set; no X11
server or X11-only libraries are included. Running these packages in an X11
session is outside this initial support.

SoundCraft, FilmCraft, EffectCraft and DeckCraft also depend on `alsa-lib`
and `pipewire`. Faseela's PipeWire build enables the ALSA plugin; start the
normal Faseela GUI session so its PipeWire user services are available.

DesignCraft has a Faseela launcher at `/usr/bin/designcraft`. It verifies that
the Sway Wayland socket is present, sets `WINIT_UNIX_BACKEND=wayland`, and
then runs the upstream binary stored as `/usr/bin/designcraft.real`. This
prevents winit from falling through to an unavailable X11 server and gives a
clear diagnostic when the command is run outside a graphical Wayland session.

The release bundles contain the upstream desktop entries, icons, MIME data
and AppStream metadata under `share/`; the recipes install that content under
`/usr/share` alongside the application binaries in `/usr/bin`.
They do not add an X server, GTK stack, or a second package manager.

## Install and build

Install selected applications through nawa:

```sh
sudo nawa install photocraft pdfcraft soundcraft
```

To print the dependency-first package list for the whole category:

```sh
python3 scripts/flavor.py resolve creative
```

The package workflow can build the category with `@creative`, or the
`creative` flavor with `flavor:creative`. It is intentionally excluded from
`ALL`, the default stage2/stage3 package set and the standard ISO flavors:
these are large optional desktop applications and must not enlarge the base
system or ISO automatically.

## Deliberate exclusions

- **ArtCraft** currently has no official Linux x86_64 FHS release archive in
  its GitHub release; its available assets are not a Linux desktop package.
- **ArtCraft Launcher** is not packaged in this category. It independently
  downloads and installs applications from upstream releases, which would
  bypass nawa's ownership database, signatures and update flow.
- **SolidCraft** has no published GitHub release to pin yet.

These exclusions can be revisited when upstream publishes a suitable Linux
bundle or a nawa-compatible integration.


## Packaging layout

The published Linux tarballs use `bin/` and `share/` directly inside the
release directory, not `usr/bin/`. The install section handles both this
upstream layout and a conventional `usr/` tree, whether nawa starts in the
release directory or the archive extraction root. It copies the files into
Faseela's `/usr/bin` and `/usr/share` so nawa owns and tracks them normally.

The recipe release number is `rel = 3` for this packaging correction.
