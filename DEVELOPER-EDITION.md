# Faseela Developer Edition

This document tracks the developer-tooling package set for Faseela. Recipes remain
the source of truth for build instructions and dependencies; `flavors.toml`
selects installable package sets. Developer packages are optional and must never be added to desktop images
or the bootstrap closure.

## Suggested package selections

The selections below are an inventory by workload, not image flavors. Install
the required package names individually through Nawa. Pending upstream packages
are tracked separately and must not be selected until their recipes pass validation.

| Workload | Current packages |
|---|---|
| Base tools | `base-devel`, `git`, `cmake`, `ninja`, `meson`, `make`, `pkgconf`, `patch`, `autoconf`, `automake`, `libtool` |
| Systems | `gcc`, `rust`, `llvm` (includes `clangd`), `golang`, `gdb`, `nasm`, `lua` |
| `rust-development` | `rust`, `rust-clippy`, `rustfmt`; optional `rust-analyzer` |
| Python | `python`, `pip`, `pipx` |
| Web | `nodejs`, `deno` |
| Debugging | `gdb`, `strace`, `valgrind` |
| CLI | `neovim`, `jq`, `tree`, `zsh`, `tmux`, `htop`, `ncdu` |

## Full target inventory

Status is based on the recipe tree, not on upstream availability. "Planned" means
a recipe and its dependency closure still need to be implemented and tested.

### Languages and runtimes

| Package | Status |
|---|---|
| `python` | Available |
| `rust` | Available; base compiler and Cargo only |
| `rust-clippy`, `rustfmt`, `rust-analyzer` | Available as version-matched opt-in components of the official Rust 1.96.1 distribution |
| `nodejs` 26.13.0, `golang` 1.27.3, `deno` 2.9.8 | Available as opt-in recipes |
| `zig`, `openjdk`, `php`, `ruby`, `dotnet-sdk`, `bun` | Planned |
| `lua` | Available |

### C, C++, LLVM and build systems

| Package | Status |
|---|---|
| `gcc`, `llvm` (Clang + clangd), `cmake`, `ninja`, `meson`, `make`, `pkgconf` | Available |
| `lld`, `lldb`, `compiler-rt`, `libcxx`, `ccache` | Planned; `clangd` is built inside the `llvm` package |

### Python

| Package | Status |
|---|---|
| `python` | Available; ensurepip enabled to support venv and pipx |
| `pip` 26.3, `pipx` 1.18.7 | Available as opt-in recipes |
| `uv`, `virtualenv`, `setuptools`, `wheel`, `cython`, `ipython` | Planned |

Python packaging must not overwrite or bypass distro-managed Python files.
The `pip` recipe installs into the distro Python site-packages; use virtual
environments for third-party project dependencies. `pipx` installs applications
into isolated per-user environments.

### Web development

| Package | Status |
|---|---|
| `typescript`, `pnpm`, `yarn`, `eslint`, `prettier`, `vite`, `webpack` | Planned |

### Git, DevOps and containers

| Package | Status |
|---|---|
| `git` | Available |
| `git-lfs`, `gh`, `docker`, `podman`, `buildah`, `skopeo`, `kubectl`, `helm`, `terraform`, `ansible` | Planned; Podman integration plan: [docs/podman-support.md](docs/podman-support.md) |

Container engines need service, group, rootless-storage and security integration;
shipping only a binary is not a complete package.

### Editors and CLI utilities

| Package | Status |
|---|---|
| `neovim`, `jq`, `tree`, `zsh`, `tmux`, `htop`, `ncdu` | Available |
| `zed` | Available as a GUI recipe |
| `vscode`, `ripgrep`, `fd`, `fzf`, `yq`, `just`, `direnv`, `starship`, `zoxide` | Planned |

### Databases

| Package | Status |
|---|---|
| `sqlite` | Available |
| `postgresql`, `mariadb`, `redis`, `mongosh` | Planned |

Database server recipes must ship explicit runit service definitions and must
not initialize or enable a database automatically during package installation.

### Debugging, testing and profiling

| Package | Status |
|---|---|
| `gdb`, `strace`, `valgrind` | Available |
| `ltrace`, `perf`, `bpftrace`, `shellcheck`, `shfmt`, `gtest`, `gcov`, `lcov` | Planned |

`perf` must be built against the supported kernel source/version and
`bpftrace` must be gated on the required kernel BPF features.

## Recipe acceptance requirements

Every new package must:

1. Have its own `recipes/<category>/<name>/recipe.toml` and a unique package name.
2. Pin an upstream release and a verified SHA-256; never merge placeholder hashes.
3. Declare recipe-level `build` and `run` dependencies accurately.
4. Build offline after source staging; no unpinned network downloads during build.
5. Install only into `%{pkgdir}`, use `/usr` as the prefix, and pass Nawa lint.
6. Include architecture constraints and upstream license metadata.
7. Avoid collisions with existing package file ownership.
8. Add service hooks only where needed; Faseela uses runit, not systemd.
9. Be tested by the recipe validator, dependency resolver, package build workflow,
   and an install/runtime smoke test before being added to a flavor.

## Recommended implementation order

1. Complete the requested baseline: Node.js, Go, clang/clangd, pip/pipx, Deno.
2. Complete Python and JavaScript ecosystems (uv, pnpm, TypeScript, Bun).
3. Complete C/C++ toolchain (LLD, LLDB, compiler-rt, libc++, ccache).
4. Add remaining language runtimes and developer utilities.
5. Add DevOps/container tooling, databases, then profiling/testing tools.

The `rust-development` group is opt-in; its component recipes are pinned to the same
Rust release as the base `rust` package and do not require Rustup.

Do not add developer packages to `iso-nogui`, `iso-sway`, `iso-xfce`,
`bootstrap`, or `rootfs-min`. Install only the package names required for a
workload; developer tooling must remain independent of desktop image profiles.
