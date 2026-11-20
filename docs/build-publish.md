# Build and publishing

The package build workflow is defined in **.github/workflows/packages.yml**. It builds recipes inside a Faseela root filesystem and publishes the resulting package archives and signed repository index.

## Automatic builds

A push to **main** or **master** that changes files under **recipes/** or changes **groups.toml** triggers the package workflow. The selector identifies recipes changed since the last successful push build. A groups-only change runs a metadata publication without rebuilding current package archives.

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
9. Copies and validates **groups.toml**, then creates the signed schema-v3 repository index with its SHA-256 and size reference.
10. Uploads **groups.toml** to **stable-v3** before the index that authenticates it.
11. Uploads **index.toml** and **index.toml.sig** to **stable-v3**.
12. Publishes or refreshes the standalone Nawa transition package when required, while leaving the legacy **stable** release unchanged.

The index is published after the archive uploads so it does not point at assets that have not yet been uploaded.

## Isolated schema-v5 publishing

Schema-v5 publishing is a separate, manually confirmed workflow in
**.github/workflows/publish-schema-v5.yml**. It accepts runs only from `main`
with the explicit `PUBLISH_SCHEMA_V5` confirmation. It authenticates the
schema-v3 source index, fetches only the current recipe archives it names,
checks the recipe declarations and complete archive coverage, signs and
validates the candidate, uploads immutable assets to **packages-v5-NNNN**, and
publishes **index.toml.sig** before **index.toml** to **stable-v5**. It does
not change **stable**, **stable-v3**, or **packages-NNNN**. The workflow uses
the existing **NAWA_SIGN_KEY_B64** secret; clients must already trust the
corresponding public key. It intentionally fails closed until every recipe has
explicit runtime dependencies, capabilities, and package relations and a
complete matching archive set is available.
The publisher repository's **dist/nawa.pub** is a checked-in mirror of the
Faseela distribution trust key; the workflow compares it with the distribution
repository before using it.
The declaration audit remains incomplete (542 of 1086 recipes); adding this
tooling is not publication or release-readiness acceptance. No schema-v5
publication, signing acceptance, or migration approval is claimed.

### Required release order

The schema-v5 workflow is an **index publisher**, not a package builder. It
imports the exact archive identities named by the current recipes from the
authenticated `stable-v3` index. It must not manufacture a missing archive,
substitute an older version, or silently rebuild from a different recipe.

Use this order:

1. Merge/review Nawa PR #58, whose tested head is
   `28cbfed1b5bb8c6705fdd287cac2b11af9f43457`. The Nawa recipe is now pinned
   to that exact source archive: `nawa-1.0.0-34`, SHA-256
   `20e903a78a0ee3ef90794daaae16bd6f8a1493f27c3b650ef646b849b6367094`.
   The digest was calculated by `scripts/pin-nawa-source.py` from the actual
   GitHub archive, not inferred from the commit ID.
2. Merge this repository PR after its CI and Nawa package build pass. The
   main-branch **Build packages** workflow detects the updated recipe, builds
   Nawa rel=34, publishes the signed pair into `nawa-transition`, and then
   publishes the new signed `stable-v3` index. The installed legacy client
   can use the standalone transition package before relying on the refreshed
   v3 index. Verify that both the archive/signature pair and its v3 index entry
   are present before proceeding.
3. Complete the schema-v5 declaration and matching-archive audit for every
   current recipe/package archive. Every recipe must explicitly declare
   `[depends].run`, `[capabilities].provides`, and `[relations]`; empty
   arrays are valid only when that package genuinely has no entries. The
   publisher intentionally refuses incomplete coverage.
4. Rebuild and publish every package archive whose embedded metadata needs to
   change. A recipe edit alone does not update already-published `.PKGINFO`.
5. Run the publisher's fixture/CI tests, then verify that the signed v3 source
   index has a matching archive for every current recipe. Only after these
   checks pass should an operator dispatch **Publish schema-v5** on `main`
   with the exact `PUBLISH_SCHEMA_V5` confirmation.
6. Keep installed Nawa configurations on `stable-v3` until the signed
   `stable-v5` index is published, the new client is installed, and the v5
   repository has passed end-to-end verification. Switching the default
   endpoint is a separate, reviewed package-recipe release.

The publisher intentionally fails closed when any step is incomplete. Do not
bypass the archive, declaration, signature, or trust checks to make a run
green.

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
