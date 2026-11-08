# Build and publishing

The package build workflow is defined in **.github/workflows/packages.yml**. It builds recipes inside a Faseela root filesystem and publishes the resulting package archives and signed repository index.

## Automatic builds

A push to **main** or **master** that changes files under **recipes/** triggers the package workflow. The selector identifies recipes changed since the last successful push build and adds the required package targets.

A package change that does not affect the built output should not cause a new package payload. If the change alters the package output, increment the recipe **rel** value so the archive identity changes.

## Manual builds

Open **Actions → Build packages → Run workflow**. The workflow accepts additive selectors:

| Selector | Meaning |
|---|---|
| **all** | All non-toolchain recipe categories. |
| **core** | Core categories: **base**, **system**, **boot**, and **extra**. |
| Category checkboxes | Select packages from the chosen categories. |
| **packages** | Exact package recipe names. |
| **flavors** | One or more flavor names from **flavors.toml**. |
| **exclude** | Package names or **@category** selectors to remove from selected targets. |
| **toolchain** | Rebuild the complete Toolchain through the Faseela Bootstrap pipeline. |
| **toolchain_packages** | Rebuild selected Toolchain recipes through the Bootstrap pipeline. |

The package selector accepts more than one package or flavor name. Selectors can be combined. Use **dry_run** to resolve and display a package plan without starting a build.

The workflow UI does not provide a dynamic checkbox for every recipe. Use the text inputs to select exact package names or flavors.

## Build environment

The workflow downloads a root filesystem from the latest Faseela release:

- **min** is the smaller package-build environment.
- **seed** is the full seed root filesystem and includes the Rust toolchain needed to build Nawa and Rust packages.
- **auto** selects **seed** when **rust** or **nawa** is among the requested packages; otherwise it selects **min**. It can fall back to **seed** when the smaller root filesystem is not available yet.

Build isolation can be selected as **sandbox**, **env**, **closure**, or **none**. The chosen mode is passed to Nawa for ordinary package builds.

Toolchain packages are never sent through the ordinary package build path. They are rebuilt through the Faseela Bootstrap Stage 1/2/3 pipeline, then imported into the package build root before ordinary packages are compiled.

## Resumable builds

A build run has a configurable time budget. When the budget is reached, the workflow publishes packages already built and can start a continuation run for the remaining targets.

With **keep_going** enabled, a failed package does not prevent unrelated packages from being built. Packages that depend on a failed package are skipped. The final workflow run reports failures even when other successfully built packages were published.

The workflow can prune superseded package archive versions after publishing. Review the manual inputs before changing pruning behavior.

## Publishing sequence

At a high level, the publisher:

1. Resolves selected package and Toolchain targets.
2. Fetches and verifies a suitable Faseela build root filesystem.
3. Ensures the build root has a Nawa client that understands the current recipe and repository schemas.
4. Fetches existing published package archives for index and file-conflict validation.
5. Builds ordinary package recipes and any selected Toolchain outputs.
6. Checks package payloads for conflicting file ownership.
7. Plans release shard assignments and creates any required **packages-NNNN** releases.
8. Uploads new package and recipe snapshot archives.
9. Creates the signed schema-v3 repository index using Nawa.
10. Uploads **index.toml** and **index.toml.sig** to **stable-v3**.
11. Publishes or refreshes the standalone Nawa transition package when required, while leaving the legacy **stable** release unchanged.

The index is published after the archive uploads so it does not point at assets that have not yet been uploaded.

## Required settings

Configure the repository under **Settings → Secrets and variables → Actions**.

| Name | Type | Required | Purpose |
|---|---|---:|---|
| **NAWA_SIGN_KEY_B64** | Secret | Yes | Base64-encoded private Nawa repository signing key (**nawa.sec**). |
| **PKG_TAG** | Variable | No | Legacy schema-v1 release tag; defaults to **stable**. |
| **PKG_V3_TAG** | Variable | No | Active schema-v3 index release tag; defaults to **stable-v3**. |
| **NAWA_TRANSITION_TAG** | Variable | No | Standalone Nawa transition release tag; defaults to **nawa-transition**. |
| **DISTRO_REPO** | Variable | No | Faseela repository used to obtain build tooling and root filesystems. |
| **DISTRO_REF** | Variable | No | Faseela branch or ref used by the package workflow. |

The workflow uses its repository **GITHUB_TOKEN** for Releases operations; it does not require a personal access token. Keep the signing secret private and rotate it through a planned key-transition procedure rather than replacing it casually.
