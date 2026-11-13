# Repository layout

The repository has three main areas: package recipes, tooling, and GitHub Actions. Published binary archives and the active repository index are stored in GitHub Releases rather than committed to this source tree.

## Top-level structure

~~~text
faseela-repo/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── docs.yml
│       ├── package-catalog-backfill.yml
│       └── packages.yml
├── docs/
├── recipes/
│   ├── toolchain/
│   ├── base/
│   ├── system/
│   ├── boot/
│   ├── extra/
│   ├── gui/
│   ├── cosmic/
│   ├── greeter/
│   ├── xorg/
│   ├── xfce/
│   ├── browser/
│   ├── media/
│   ├── creative/
│   ├── messaging/
│   ├── networking/
│   ├── security/
│   └── dev/
├── scripts/
├── groups.toml
├── flavors.toml
├── DEVELOPER-EDITION.md
├── README.md
├── requirements-docs.txt
└── zensical.toml
~~~

Each package has its own directory containing **recipe.toml**, for example:

~~~text
recipes/
└── base/
    └── zlib/
        └── recipe.toml
~~~

## Recipe categories

| Category | Purpose |
|---|---|
| **toolchain** | Compiler, C library, headers, and the components that form the bootstrap toolchain. |
| **base** | Core userland libraries, shells, interpreters, and fundamental utilities. |
| **system** | System services, hardware and device support, networking, storage, and administration tools. |
| **boot** | Kernel and boot-related packages. |
| **extra** | General-purpose command-line tools, editors, diagnostics, and utilities. |
| **gui** | Optional graphical desktop stack and shared desktop services. |
| **cosmic** | COSMIC Wayland desktop and applications. |
| **greeter** | Optional login daemons and greeter applications. |
| **xorg** | The X.Org server, its input driver, and X11 client utilities. |
| **xfce** | The Xfce desktop, applications, panel plugins, LightDM, GTK greeter, and session integration. |
| **browser** | Optional browser packages and their supporting libraries. |
| **media** | Optional media playback, codecs, and related libraries. |
| **creative** | Optional desktop applications from the Storytold Craft collection. |
| **messaging** | Optional messaging clients. |
| **networking** | Optional proxy and VPN-related desktop clients. |
| **security** | Optional security and reconnaissance tools. |
| **dev** | Optional language runtimes and developer tooling. |

The contents of each category are determined by the current recipe tree. Do not rely on fixed package counts in external documentation.

## Important files

| Path | Role |
|---|---|
| **recipes/<category>/<name>/recipe.toml** | Build metadata, source pins, dependencies, build steps, and optional hooks for one package. |
| **groups.toml** | Published package-group definitions; each group resolves to ordinary recipe names. |
| **flavors.toml** | Named package selections used by the distribution and build workflow. |
| **scripts/check-recipes.py** | Offline structural and dependency validation for the recipe tree. |
| **scripts/recipe-ids.py** | Lists recipes or identifies superseded package archive names. |
| **scripts/select-packages.py** | Resolves package selections for the build workflow. |
| **scripts/flavor.py** | Lists, resolves, and validates package flavors. |
| **scripts/distributed-releases.py** | Plans and manages package archive storage across GitHub Releases shards. |
| **scripts/check-file-conflicts.py** | Checks archive payloads for package file ownership conflicts. |
| **scripts/package_catalog.py** | Generates package records and catalog metadata for the incremental-publishing design. |
| **.github/workflows/ci.yml** | Offline repository checks and regression tests. |
| **.github/workflows/packages.yml** | Package selection, builds, and publication. |
| **.github/workflows/docs.yml** | Documentation validation and GitHub Pages deployment. |

## What is not stored in this tree

Published **.nawa.tar.zst** package archives, their shard placement, and the active signed **stable-v3** index are managed through GitHub Releases. The old **stable** release is a compatibility endpoint and is intentionally left unchanged by the current publisher.

The repository also does not own the Faseela bootstrap implementation or the Nawa package-manager source. Those projects are maintained separately.
