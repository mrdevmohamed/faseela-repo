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

## How a build is split (shards and waves)

A full build is longer than one runner may run (6 hours), and the packages used to queue behind one another in a single job. The workflow therefore plans the build first:

1. **plan** removes every package whose archive already exists (published, or saved by an earlier run of the same pull request) and splits the remaining packages into up to eight **waves** along their dependency levels (`scripts/plan-build-shards.py`). A package is always in a later wave than every selected package it needs, at build **or** run time.
2. The packages of one wave form parallel **shards**, one runner each. Packages of a wave that depend on each other share a shard, very slow packages (LLVM, browsers) get a shard of their own, and `scripts/build-times.json` lists the measured minutes used for balancing. A wrong value only costs speed.
3. A shard downloads just the archives of its dependency closure: published ones from the package repository and those that earlier waves built from the **draft build cache** (`scripts/pr-shard-cache.py`). Everything it builds is saved to that cache, even when another package of the shard failed or time ran out.
4. A package whose dependency failed in an earlier wave is skipped, not compiled again. A failing package never stops the other shards.
5. **publish** gathers all archives, runs the checks and, outside pull requests, publishes the signed index.

**Re-run failed jobs** repeats only the failed shards: the other shards' archives are in the cache and the re-run plans only what is missing. Pull requests keep their cache (`schema-v5-build-pr-<N>-*` draft releases) across runs; other runs use `faseela-build-run-<run id>-*`, deleted when the run ends. The job that does the work is defined in **.github/workflows/packages-build.yml** (`mode: shard` or `mode: finalize`).

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

## Bootstrap Toolchain cache

When a run has to rebuild Toolchain recipes, the Stage 1/2/3 bootstrap takes the
better part of an hour. Its final Stage 3 archives are therefore cached with
`actions/cache`, under a key computed by `scripts/toolchain-cache-key.py` from
the tooling revision, every recipe tree (and recursive build dependencies) in the
bootstrap flavor and in `recipes/toolchain`, `flavors.toml`, the isolation mode,
the Stage 3 package selection and the ISO week. On a hit the workflow verifies the
sentinel file and per-archive SHA-256 sums, skips the bootstrap and imports the
archives exactly as a fresh build would; on any verification failure it rebuilds.

- A full Toolchain run (`toolchain = true`) never uses the cache, because its
  self-hosting proofs are the purpose of that run.
- The entry is saved as soon as the Stage 3 archives exist, even if a later
  package fails, so retries do not repeat the bootstrap.
- The key changes weekly, because the seed toolchain is assembled from unpinned
  upstream packages. Caches are scoped per branch/PR by GitHub and expire after
  7 days without use.
- Set the repository variable `TOOLCHAIN_CACHE=off` to disable it.

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
**.github/workflows/publish-schema-v5.yml**. It runs only from **main** with
the explicit **PUBLISH_SCHEMA_V5** confirmation and a **build_run_id** pointing
to a successful, same-repository **Build packages** pull-request run.

The pull-request workflow keeps resumable package caches in draft GitHub
Releases, not Actions artifacts. This avoids relying on the GitHub Free Actions
artifact-storage quota for a complete package set. Each PR has its own draft
manifest release and category shards, with no more than 900 archive assets per
shard (below GitHub's 1,000-asset Release limit). These draft releases are not
referenced by **stable-v3**, **stable-v5**, or any package index.

Each cache entry is bound to the exact current recipe and recursive build
dependency fingerprints and carries SHA-256 digests for the base archive and
any `-doc` / `-lang` split archives. A candidate manifest records the PR
number, build run ID, PR head SHA, manifest digest, and shard list. The
candidate manifest is uploaded last, after all archive shards are present.
On the next PR build run, the workflow validates the candidate and restores
only entries whose recipe fingerprint and archive digest still match. Before
building a relation-bearing package, it invalidates any old schema-v3 archive
with the same package identity so the old payload cannot suppress a required
v5 rebuild.

The v5 publisher independently verifies the selected build run, requires its
PR to have been merged into the current **main**, verifies that the candidate
manifest matches that exact run and final PR head, downloads the draft shards,
and rechecks every archive digest and recipe/build-dependency fingerprint.
It then stages only exact current recipe archive identities. The staging audit
fails unless every current recipe has a matching archive and rejects stale or
extra archives. Nawa creates, signs, and verifies the schema-v5 index before
immutable **packages-v5-NNNN** assets and the **stable-v5** index are uploaded.

This is a build-to-publisher handoff, not a way to reuse old schema-v3 package
archives: the cache must contain newly built archives whose embedded
`.PKGINFO` records carry the current runtime dependencies, capabilities, and
relations. The build run must finish successfully; a run that reports deferred
or failed packages is not an accepted publishing input.

The workflow does not change **stable**, **stable-v3**, or **packages-NNNN**.
It uses the existing **NAWA_SIGN_KEY_B64** secret and the checked-in
**dist/nawa.pub** trust key, which is compared with Faseela's distribution
key before publication. Clients must already trust the corresponding public
key.

### Required release order

1. Complete the recipe metadata audit. Every current recipe must explicitly
   declare `[depends].run`, `[capabilities].provides`, and
   `[relations]` with `schema = 1`. Empty arrays are valid only after the
   package has been reviewed and found to have no entries; missing metadata is
   not an empty declaration.
2. Convert legacy source declarations to the Nawa recipe schema required by
   `[relations]`, preserving source URLs, pinned digests, source working
   directories, and reproducible build inputs. Bump package release identities
   when archive metadata changes.
3. Build the complete current recipe set through the **Build packages**
   pull-request workflow. It may take multiple runs: the draft-release cache
   carries successful outputs forward. Keep the same PR open and use the final
   successful run ID only after the package set is complete.
4. Dispatch **Publish schema-v5** on **main**, enter that successful run ID,
   and provide the exact **PUBLISH_SCHEMA_V5** confirmation. The workflow
   independently verifies every cache entry, complete package coverage,
   signatures, archive digests, and the serialized index before uploading.
5. Keep installed Nawa configurations on **stable-v3** until the signed
   **stable-v5** index is published, the new client is installed, and the v5
   repository has passed end-to-end verification. Switching the default
   endpoint is a separate, reviewed package-recipe release.

### Current readiness

The v5 draft-release build handoff and per-archive cache integrity checks are
implemented in this branch, and all 542 recipes now carry the schema-v5 recipe
form: one `[[package.sources]]` table per upstream file (with the layout
equivalent to the previous `source_dir` behaviour), `[capabilities]`,
`[relations]` with `schema = 1`, and a bumped `rel`. The CI audit runs with
`--strict`, so a recipe without that metadata fails the check.

Relations were derived from real file overlap between the published archives
(none found beyond the four documented replacement cases); every other recipe
declares reviewed-empty `conflicts` and `replaces`. The release is still
**not ready**: the complete package set must be built through the **Build
packages** pull-request workflow, followed by the end-to-end install and
replacement test. Do not merge the metadata PR into the active v3 publisher
or dispatch **Publish schema-v5** until those gates pass.

Nawa's migration security rules remain separate: `runit-services` and its
`/usr/bin/init` ownership are not a generic package replacement. Only the
explicitly approved runit-to-systemd migration may hand off PID 1 and
power-control entry points. The schema-v5 package relations do not bypass
that boundary.

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
