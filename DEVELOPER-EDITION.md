# Faseela Developer Edition

This document tracks the developer-tooling package set for Faseela. Recipes remain
the source of truth for build instructions and dependencies; `flavors.toml`
selects installable package sets. Developer groups are opt-in and must never be
added to the default ISO or bootstrap closure.

## Package groups

The groups below are deliberately split by workload. A group may contain only
packages that currently have recipes; pending upstream packages are tracked in
the inventory below and must not be referenced by a flavor until their recipes
pass validation.

| Flavor | Current packages |
|---|---|
| `developer-base` | `base-devel`, `git`, `cmake`, `ninja`, `meson`, `make`, `pkgconf`, `patch`, `autoconf`, `automake`, `libtool` |
| `developer-systems` | `gcc`, `rust`, `llvm`, `gdb`, `nasm`, `lua` |
| `developer-python` | `python` |
| `developer-debugging` | `gdb`, `strace`, `valgrind` |
| `developer-cli` | `neovim`, `jq`, `tree`, `zsh`, `tmux`, `htop`, `ncdu` |

## Full target inventory

Status is based on the recipe tree, not on upstream availability. "Planned" means
a recipe and its dependency closure still need to be implemented and tested.

### Languages and runtimes

| Package | Status |
|---|---|
| `python` | Available |
| `rust` | Available |
| `nodejs`, `golang`, `deno`, `zig`, `openjdk`, `php`, `ruby`, `dotnet-sdk`, `bun` | Planned |
| `lua` | Available |

### C, C++, LLVM and build systems

| Package | Status |
|---|---|
| `gcc`, `llvm`, `cmake`, `ninja`, `meson`, `make`, `pkgconf` | Available |
| `clang`, `clangd`, `lld`, `lldb`, `compiler-rt`, `libcxx`, `ccache`, `gdb`, `valgrind` | Planned except `gdb` and `valgrind`, which are available |

### Python

| Package | Status |
|---|---|
| `python` | Available; current recipe intentionally disables ensurepip |
| `pip`, `pipx`, `uv`, `virtualenv`, `setuptools`, `wheel`, `cython`, `ipython` | Planned |

Python packaging must not overwrite or bypass the distro-managed Python files.
The eventual `pip` integration must preserve a clear distinction between
system-managed packages and user virtual environments. `pipx` must install
applications into isolated environments.

### Web development

| Package | Status |
|---|---|
| `typescript`, `pnpm`, `yarn`, `eslint`, `prettier`, `vite`, `webpack` | Planned |

### Git, DevOps and containers

| Package | Status |
|---|---|
| `git` | Available |
| `git-lfs`, `gh`, `docker`, `podman`, `buildah`, `skopeo`, `kubectl`, `helm`, `terraform`, `ansible` | Planned |

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

Do not add every developer group to `iso-gui`, `iso-nogui`, `bootstrap`,
or `rootfs-min`. Users should opt in with commands such as
`nawa install @developer-base` only after Nawa's group-install syntax is
confirmed; otherwise install the resolved package names explicitly.
