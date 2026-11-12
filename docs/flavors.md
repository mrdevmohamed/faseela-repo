# Flavors

Faseela uses **flavors only for build roots and complete system images**.
Individual applications and optional tool collections are installed through
Nawa; they do not create separate ISO variants.

## Image profiles

| Flavor | Purpose |
|---|---|
| `bootstrap` | Internal self-hosting core built in stage 2 and stage 3. |
| `seed` | Full rootfs used to seed a later bootstrap. |
| `rootfs-min` | Small environment used by the package-build workflow. |
| `iso-nogui` | Common live-system base without a desktop. |
| `iso-sway` | Common base plus the Sway Wayland desktop. |
| `iso-xfce` | Common base plus Xfce on Xorg. |

The desktop images extend `iso-nogui`, so core packages, boot support,
networking and command-line tools remain shared. Desktop-specific packages
are selected by each desktop flavor.

Optional applications such as Zed, Telegram Desktop, Nekoray, Huion Tablet,
MPV and FFmpeg are not flavors. Install them with Nawa when needed.

## Flavor fields

| Field | Meaning |
|---|---|
| `summary` | Human-readable description. |
| `include` | Package names or category selectors such as `@base` and `@gui`. |
| `extends` | Inherit packages from another flavor. |
| `exclude` | Package names removed from the resolved result. |
| `closure` | `run` (runtime dependencies) or `build` (build and runtime dependencies). |

An `@category` item expands to every recipe in that category. The default
closure is `run`; bootstrap profiles use `build` to include everything
required to build their selected packages.

## Inspect flavors

List the available profiles:

~~~sh
python3 -I scripts/flavor.py list
~~~

Resolve a profile, with dependencies first:

~~~sh
python3 -I scripts/flavor.py resolve iso-sway
python3 -I scripts/flavor.py resolve iso-xfce
~~~

Check every profile against the current recipes:

~~~sh
python3 -I scripts/flavor.py check
~~~

The same validation runs in repository CI.

## Selection principles

- Keep the bootstrap and rootfs build targets separate from desktop images.
- Keep the common system in `iso-nogui`; desktop flavors inherit it.
- Add a new flavor only for a complete desktop environment or a genuinely
  different system image—not for one optional application.
- Keep applications and tools independently installable through Nawa.

The exact packages in a profile are defined only by `flavors.toml`.
