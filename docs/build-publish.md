# Build and publishing

The package build workflow is defined in **.github/workflows/packages.yml**. It builds recipes inside a Faseela root filesystem and publishes the resulting package archives and signed repository index.

## Automatic builds

A push to **main** that changes files under **recipes/** or **groups.toml** builds and publishes **stable-v5**; no approval step is involved. The push selects **every** recipe and the planner skips whatever **stable-v5** already publishes, so the run builds exactly the packages whose archive identity (`name-version-rel`) is not published yet. There is no "since the last run" bookkeeping. If the change alters the package output, increment the recipe **rel** value so the archive identity changes.

A pull request builds only the recipes it changes. It verifies them and never publishes.

The workflow publishes only from **main**, and only when no job failed: the signed repository is replaced as a whole (complete, signed set) or not at all, so **stable-v5** is never partial. If a package fails, fix it and push; the next run builds only what is still missing.

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

A full build is longer than one runner may run (6 hours). The workflow therefore plans the build first:

1. **plan** removes every package whose archive **stable-v5** already publishes and splits the remaining packages into up to eight **waves** along their dependency levels (`scripts/plan-build-shards.py`). A package is always in a later wave than every selected package it needs, at build **or** run time.
2. The packages of one wave form parallel **shards**, one runner each. Packages of a wave that depend on each other share a shard, very slow packages (LLVM, browsers) get a shard of their own, and `scripts/build-times.json` lists the measured minutes used for balancing. A wrong value only costs speed.
3. A shard downloads just the archives of its dependency closure: published ones from **stable-v5** and those the earlier waves built (workflow artifacts `built-<shard>`). Everything it builds is uploaded as its own artifact, even when another package of the shard failed.
4. **publish** starts when every wave is done and nothing failed. It builds the recipe-pinned Nawa, gathers the artifacts and the published archives into one complete set, signs and verifies it (`scripts/publish-schema-v5.py prepare`), uploads new archives to the immutable **packages-v5-NNNN** releases and uploads the signed **index.toml** to **stable-v5** last.

**Re-run failed jobs** repeats only the failed shards. The job that builds a shard is defined in **.github/workflows/packages-build.yml**.

## Build environment

The workflow downloads a root filesystem from the latest Faseela release:

- **min** is the smaller package-build environment.
- **seed** is the full seed root filesystem and includes the Rust toolchain needed to build Nawa and Rust packages.
- **auto** selects **seed** when **rust** or **nawa** is among the requested packages; otherwise it selects **min**. It can fall back to **seed** when the smaller root filesystem is not available yet.

Build isolation can be selected as **sandbox**, **env**, **closure**, or **none**. The chosen mode is passed to Nawa for ordinary package builds.

Toolchain packages are never sent through the ordinary package build path. They are rebuilt through the Faseela Bootstrap Stage 1/2/3 pipeline, then imported into the package build root before ordinary packages are compiled.

## Failures and the time budget

With **keep_going** enabled, a failed package does not prevent unrelated packages from being built. Packages that depend on a failed package are skipped. The run ends red and publishes nothing; archives of the successful packages are kept as run artifacts for one day, and a re-run of the failed jobs continues from them.

Each shard stops starting new packages after **budget** minutes (default 270). Packages left over make the run incomplete, so it does not publish; run it again and only those are built.

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

## Publishing

The **publish** job uses the existing **NAWA_SIGN_KEY_B64** secret and the checked-in **dist/nawa.pub** trust key, which is compared with Faseela's distribution key before publication. Before anything is uploaded it verifies: complete package coverage of every current recipe, explicit schema-v5 metadata, every signature, archive digests and sizes, and the serialized index. Archives already hosted in a **packages-v5-NNNN** release are compared byte for byte and never replaced. After publishing, the file-conflict check reports any file owned by two packages of one flavor.

The workflow does not change **stable**, **stable-v3**, or **packages-NNNN**. Installed Nawa configurations move to **stable-v5** with a separate, reviewed package-recipe release, after the end-to-end install and replacement test has passed.

Nawa's migration security rules remain separate: `runit-services` and its `/usr/bin/init` ownership are not a generic package replacement. Only the explicitly approved runit-to-systemd migration may hand off PID 1 and power-control entry points. The schema-v5 package relations do not bypass that boundary.

Superseded archive versions stay in the immutable release storage; they are not pruned.

## Required settings

Configure the repository under **Settings → Secrets and variables → Actions**.

| Name | Type | Required | Purpose |
|---|---|---:|---|
| **NAWA_SIGN_KEY_B64** | Secret | Yes | Base64-encoded private Nawa repository signing key (**nawa.sec**). |
| **DISTRO_REPO** | Variable | No | Faseela repository used to obtain build tooling and root filesystems. |
| **DISTRO_REF** | Variable | No | Faseela branch or ref used by the package workflow. |

The workflow uses its repository **GITHUB_TOKEN** for Releases operations; it does not require a personal access token. Keep the signing secret private and rotate it through a planned key-transition procedure rather than replacing it casually.
