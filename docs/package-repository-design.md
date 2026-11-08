# Incremental package publishing: design

Status: proposal. Phase 0 tooling is implemented; nothing in the publish
workflow uses it yet (see section 14).
Scope: `.github/workflows/packages.yml`, `scripts/check-file-conflicts.py`,
`scripts/distributed-releases.py`, and the `nawa` repository tooling
(`mrdevmohamed/nawa`, `repo-create`).

## 1. Summary

Every package build today downloads **every** previously published archive,
re-reads **every** archive to regenerate the repository index, and re-reads
**every** archive again to check for file conflicts. The cost of one run is
therefore proportional to the *total size of the repository*, not to the
*size of the change*. Building one package costs several gigabytes of
downloads, and any transient GitHub error (for example HTTP 504) is
multiplied across hundreds of requests.

This document proposes a clean-slate publishing model in which the cost of a
run is proportional to the change:

- each archive gets a tiny, immutable **package record** generated once, at
  build time;
- the set of records forms a signed **catalog**;
- the signed repository index is updated **incrementally** from the previous
  signed index plus the new records, without opening any archive;
- builds fetch only the **dependency closure** of what they build, addressed
  by SHA-256 from the signed index;
- file-conflict checking reads file lists from the catalog instead of opening
  archives;
- the current full-scan behaviour is kept, but demoted to a scheduled
  **verification** job that proves the incremental index has not drifted.

No change is made to the archive format, the signature scheme, or the schema
or semantics of the index that end-user `nawa` clients read.

## 2. How publishing works today

All facts below were read from the repository at the time of writing.

### 2.1 Storage layout

- Package and recipe archives live in immutable "storage shard" releases
  named `packages-NNNN` (`scripts/distributed-releases.py`). A shard holds at
  most 900 assets, deliberately below GitHub's 1,000-asset release cap.
- The legacy schema-v1 release `stable` is frozen. It still contains some
  archives, and the workflow prefers a `packages-NNNN` copy over a legacy
  copy when both exist (`list_published`).
- The signed schema-v3 index (`index.toml` + `index.toml.sig`) is published
  in a separate release (`PKG_V3_TAG`, `stable-v3`). Each package entry in the
  index carries an absolute HTTPS `download_url` pointing at its archive in a
  shard.

### 2.2 One run, step by step

1. **Read package release metadata.** One paginated `gh api` call lists all
   releases and assets; `distributed-releases.py list` turns that into a
   list of `(tag, asset)` pairs.
2. **Fetch the packages already published.** Every asset in that list is
   downloaded with `curl --retry 3 --retry-all-errors --retry-delay 2`, using
   12 parallel workers (`PACKAGE_DOWNLOAD_JOBS`), into `build/out`.
   A comment in the workflow states why: the *complete* set is required by
   `repo-create` and by the cross-flavor file-conflict check, and fetching
   only a closure "would silently publish an incomplete repository index".
3. **Build** the selected packages (and the bootstrap toolchain targets).
4. **File-conflict check** (`check-file-conflicts.py build/out`).
5. **Publish.** Copy all archives into a repo directory, optionally prune
   superseded ones (`recipe-ids.py --stale`), plan shard placement
   (`distributed-releases.py plan`), create missing shard releases, run
   `nawa repo-create /repo --index-version 3 --locations ... --sign
   --recipes ... --recipes-rev ...`, upload new archives to their shards,
   and finally upload the signed index.

### 2.3 What `nawa repo-create` actually needs from an archive

`create_index_with_locations` (`src/repo.rs` in `nawa`) iterates over every
`*.zst` archive in the directory and, for each one:

1. reads `.PKGINFO` (`pkgname`, `pkgver`, `pkgrel`, `arch`, `size`);
2. computes the SHA-256 of the whole file;
3. takes the file size;
4. looks up its `download_url` in the locations manifest.

It then keeps only the **newest** version per package name, stamps
`generated`/`expires` (validity is 90 days), validates, writes the TOML
atomically (temporary file plus rename), and optionally signs it.

An index entry (`RepoEntry`) is exactly:
`name, version, rel, arch, file, sha256, download_url, size, installed_size`.
**Every one of those fields can be produced once, at build time, and stored in
a few hundred bytes.** Opening the archive again later adds no information.

### 2.4 What `check-file-conflicts.py` actually needs from an archive

For each flavor (`flavors.toml`) it resolves the package set and install
order, then, for each package, streams the archive through `zstd -dc` and
records every member under `payload/` as either a directory or "other"
(file or symlink). It applies the merged-`/usr` normalisation (`/bin`,
`/sbin`, `/lib`, `/lib64` map to `/usr/...`) and reports:

- a non-directory path shipped by two or more packages of one flavor;
- a path that is a file or symlink in one package and a directory in another
  that is installed *before* it.

So it needs, per package, only `{path: dir | other}`. That is again a small
fact derivable once per archive.

## 3. Problem statement

### 3.1 Measured cost model

At the time of writing the workflow fetches **769 archives** per run
(698 from `packages-0001`, 71 from `stable`). The `packages-0001` shard alone
is 4.37 GiB. The cost of every run is

    cost(run) = O(N archives)  download
              + O(N)           reads in repo-create
              + O(N)           reads in the conflict check

where N is the total number of published archives. N only grows.

### 3.2 Failure amplification

The job log shows repeated `curl: (22) The requested URL returned error: 504`.
With 12 workers each retrying 3 times with a fixed 2 s delay, a short GitHub
CDN incident is retried almost immediately by hundreds of transfers at once.
If any single archive exhausts its retries, the whole step fails, even when
the run only intended to build one small package that does not depend on the
failed archive. The blast radius of a transient error is the entire
repository.

### 3.3 Why simply caching is not enough

Caching archives (`actions/cache`) lowers the number of bytes on warm runs but
keeps the O(N) structure: a cold cache, an evicted cache (GitHub's limit is
10 GB per repository, shared with every other cache) or a new runner image
reverts to downloading everything. It also leaves `repo-create` and the
conflict check scanning every archive. Caching is a mitigation, not a design.

## 4. Goals, non-goals and constraints

Goals:

1. Cost of a run proportional to (new archives) + (dependency closure of what
   is built) + (small metadata), independent of N.
2. A transient download failure fails only the packages that need that
   archive, quickly and with a clear message.
3. The published index remains correct, signed and complete.
4. The old full-scan result remains available as an independent audit.
5. Every migration step is reversible on its own.

Non-goals:

- changing the archive format or the signing scheme;
- changing how end users install packages;
- replacing GitHub Releases as storage.

Constraints that shape the design:

- **Client compatibility.** End-user `nawa` reads the schema-v3 index. It must
  not need to know about records or the catalog. The catalog is a
  CI/publisher-side artifact only.
- **Trust.** Nothing unauthenticated may flow into a signed index. The base
  index used for an incremental update must itself be signature-verified.
- **GitHub limits.** 900-asset shards, a 10 GB cache budget, and an API token
  request budget (the workflow already avoids the per-asset API endpoint for
  this reason and uses public browser URLs for archive bytes).
- **Index expiry.** The index is valid for 90 days from `generated`. Any
  incremental scheme must keep refreshing it.

## 5. Design overview

```
                      build time                           publish time
 recipe ──► nawa build ──► archive (.nawa.tar.zst)
                 │                 │
                 │                 ├──► upload to packages-NNNN shard
                 ▼                 │
        package record (.record.json)  (generated from the archive, once)
                 │
                 ▼
   ┌─────────────────────────┐   base: previous signed index.toml (verified)
   │ nawa repo-update        │◄──────────────────────────────────────────────
   │  base index + records   │
   │  + locations manifest   │──► new signed index.toml (+ .sig)
   └─────────────────────────┘
                 │
                 ▼
   catalog-<sha256>.json.zst  +  catalog.toml (signed pointer)

   later runs:   select packages ─► dependency closure ─► fetch by sha256
                 from the signed index (cache key = sha256)
   conflict check: reads file lists from the catalog, opens no archive
   weekly:       full repo-create from all archives == published index ?
```

## 6. Components

### 6.1 Package record

A record is a small JSON document generated **from the archive itself**
immediately after it is built (so it can never disagree with the archive),
named `<name>-<version>-<rel>.nawa.record.json.zst`, and uploaded next to the
archive in the same shard.

Proposed schema (version 1):

```json
{
  "schema": 1,
  "name": "podman",
  "version": "6.1.4",
  "rel": 1,
  "arch": "x86_64",
  "file": "podman-6.1.4-1.nawa.tar.zst",
  "sha256": "<64 hex chars of the archive>",
  "size": 31457280,
  "installed_size": 88080384,
  "files": [
    {"path": "usr/bin/podman", "kind": "other"},
    {"path": "usr/share/containers", "kind": "dir"}
  ]
}
```

Rules:

- `name/version/rel/arch/installed_size` come from `.PKGINFO` with exactly the
  validation `create_index_with_locations` already applies (for example
  `pkgrel` must parse as a non-zero integer for schema v2 and v3).
- `sha256` and `size` are computed over the archive file as uploaded.
- `files` holds the raw `payload/` paths with `kind` = `dir` or `other`
  (file or symlink). It stores **raw** paths. Merged-`/usr` normalisation is
  applied at check time, so records do not bake in a policy that may change.
- Dependencies are **not** duplicated in records. Dependency resolution
  already comes from the recipe tree (`nawa deps`), which is the source of
  truth and is itself published in the index (`recipes` entry).

Size: tens of bytes per file path before compression. Compressed with zstd, a
record is typically a few kilobytes, orders of magnitude below the archive.

Integrity: a record is derived data and is checked against the archive. The
publisher recomputes `sha256` and `size` from the archive it is about to
upload and refuses a mismatching record. Records are not security-critical
for end users (they never read them); they are critical for the *publisher's*
correctness, which is why the catalog is signed (6.2).

### 6.2 Catalog

The catalog is the set of current records, serialised as one document:

- file name: `catalog-<sha256-of-content>.json.zst` (content addressed,
  therefore immutable and safe to cache forever);
- uploaded to a release as an ordinary asset;
- a small signed **pointer** `catalog.toml`, stored beside `index.toml` in the
  v3 release, says which catalog is current:

```toml
schema = 1
catalog_file   = "catalog-4f2a....json.zst"
catalog_sha256 = "4f2a...."
index_sha256   = "9bc1...."     # sha256 of the index.toml published together
generated      = 1794000000
```

- `catalog.toml` is signed with the same key and mechanism as the index
  (`nawa sign`, producing `catalog.toml.sig`).

Why a pointer instead of a field inside `index.toml`: adding a field to the
index would change the artifact end-user clients parse. Keeping the catalog
outside the index means **zero client-visible schema change**.

Consistency between `index.toml` and `catalog.toml` is checked on read:
`index_sha256` must equal the SHA-256 of the index being used, otherwise the
reader treats the catalog as stale and falls back to the verification path
(6.8). GitHub release uploads are not atomic across two assets, so this check
is what makes a torn read detectable.

Expected size: a few megabytes compressed for the current repository, versus
multiple gigabytes of archives.

### 6.3 Incremental index update: `nawa repo-update`

A new `nawa` subcommand that produces the same index `repo-create` would
produce, from the previous index and a delta, without opening any archive.

```
nawa repo-update
    --base index.toml                 # previous index, signature-checked
    --base-sig index.toml.sig
    --trust-key nawa.pub              # key used to verify the base
    --add records/*.record.json.zst   # new or replaced packages
    --remove <archive-file> ...       # superseded or pruned archives
    --index-version 3
    --locations locations.toml        # download URLs for the added archives
    --recipes <tree> --recipes-rev <rev>
    --out index.toml
    --sign --key nawa.sec
```

Algorithm:

1. Verify `--base` against `--base-sig` with `--trust-key`. **Refuse to
   proceed on failure.** An unverified base must never be merged into a
   signed index.
2. Load the base entries into a map keyed by package name.
3. For each `--remove`, drop the entry whose `file` matches. (This is how
   `recipe-ids.py --stale` pruning is expressed.)
4. For each `--add` record: validate it with the same rules as today (same
   `pkgrel` checks, same filename rules, `download_url` must exist in the
   locations manifest and be an absolute HTTPS URL), build a `RepoEntry` from
   the record, and apply the existing **newest-per-name** rule
   (`vercmp` over `version-rel`) against whatever the map holds.
5. Pack the recipe tree (`pack_recipes`) and set the `recipes` entry exactly
   as `repo-create --recipes` does today.
6. Set a fresh `generated` and `expires` (now + 90 days). This is **required**:
   an incremental scheme that did not refresh expiry would let the index
   expire silently.
7. `index.validate()`, write to a temporary file, rename atomically, sign.

Required invariant (property test in `nawa`):

    repo-update(base = repo-create(A), add = records(B), remove = R)
        ==  repo-create((A \ R) ∪ B)

compared on `package` entries and `recipes`, ignoring `generated`/`expires`.
This one test is what lets the incremental index be trusted: it proves the
two code paths are equivalent.

`repo-create` is unchanged and remains the reference implementation.

### 6.4 Closure-based fetching for builds

Instead of "download everything, build, publish", a run does:

1. **Select** what to build. `scripts/select-packages.py` already exists.
2. **Resolve the closure.** Use the recipe tree (`nawa deps` / `deps-all`) to
   compute the build and runtime dependencies of the selected packages.
3. **Fetch only that closure.** Resolve each needed package through the
   *signed* index to a `(download_url, sha256, size)` triple, download it, and
   verify the SHA-256 against the index. Anything that does not verify is
   rejected.
4. **Cache by content.** Use `actions/cache` with the archive SHA-256 as the
   key. Archives are immutable, so a cache hit is always correct; there is no
   staleness problem and no need for invalidation logic. Only the closure is
   ever cached, which keeps the cache far below the 10 GB limit.

Open point: how the build chroot consumes build dependencies is implemented in
`build-packages-inner.sh`, which comes from the distribution tooling and is
not part of this repository. The assumption here is that it reads dependency
archives from a local directory, in which case only the *preparation* of that
directory changes. This **must be confirmed** before implementation (section
11).

### 6.5 File-conflict checking from the catalog

`check-file-conflicts.py` keeps its semantics and changes only its input:

- today: `read_archive(path)` streams a `.zst` and builds `{path: kind}`;
- proposed: build the same `{path: kind}` mapping from the catalog record of
  the archive that **the current recipe tree names**
  (`name-version-rel` from each `recipe.toml`, exactly as it does today).

Everything after that is unchanged: merged-`/usr` normalisation, flavor
resolution and install order, the two error classes (shared non-directory
path; file-before-directory ordering), and `--strict` (a package without a
record is an error rather than a warning).

Because the catalog is one small document, the check covers **all** flavors
at once for the price of one download, which preserves the guarantee the
original comment cared about ("cross-flavor") without opening archives.

The new package(s) of the current run have no catalog entry yet; their
records are generated at build time and merged into the in-memory view before
the check runs, so the check sees the post-publish state.

A regression test must assert that, for the same set of archives, the
archive-based and the catalog-based checks report identical conflicts.

### 6.6 Download resilience

For the fetches that remain (the closure):

- retry with **exponential backoff and jitter**, honouring `Retry-After` when
  present, rather than a fixed 2 s delay;
- bound total attempts and total time per asset, then fail with a message that
  names the asset;
- keep using public `releases/download` URLs for bytes (the existing rule
  that protects the installation token's request budget);
- **fail fast**: resolve and verify the whole closure *before* spending hours
  building, so a missing dependency stops the job in minutes.

The design's main resilience gain, however, is structural: with a closure of a
handful of archives instead of 769, a transient error affects only the
packages that need that archive instead of every run.

### 6.7 Publish protocol and concurrency

Ordering is kept from the current pipeline because it is already correct:
archives first, signed index last.

1. Upload the new archives and records to their shards. Nothing references
   them yet, so this step is invisible to clients.
2. Run `nawa repo-update` against the last verified base.
3. Upload `catalog-<sha>.json.zst` (immutable, content addressed).
4. **Compare-and-swap check:** immediately before step 5, fetch the currently
   published `index.toml` and compare its SHA-256 with the base used in step 2.
   If they differ, another publish landed in between: re-run step 2 on the
   new base (records are independent, so re-merging is safe) and re-check.
5. Upload `index.toml`, `index.toml.sig`, `catalog.toml`, `catalog.toml.sig`.
6. Re-read and verify what was published (signature valid, `index_sha256`
   matches); fail the run if not.

GitHub releases offer no true atomic compare-and-swap, so the actual
guarantee comes from a **`concurrency:` group on the publish job**, so there
is a single writer, with step 4 as defence in depth.

### 6.8 Verification, expiry refresh and garbage collection

An incrementally maintained index can drift from reality if a bug or a manual
edit slips in. Three scheduled jobs close that gap; none of them runs on the
hot path of a package build.

1. **Drift check (weekly).** Download all archives, run the *existing*
   `repo-create` (the reference implementation), and compare its `package`
   entries and `recipes` with the published index. A difference fails the job
   and prints the diff. Optionally rebuild the catalog from the archives and
   compare it too. This keeps the original full-scan behaviour as an
   independent audit instead of removing it.
2. **Expiry refresh.** Re-sign the published index with a fresh
   `generated`/`expires` window before 90 days have passed, even if nothing
   was built. (Today expiry is refreshed only as a side effect of a build, so
   a quiet period longer than 90 days would expire the index; this is an
   existing risk the new design closes.)
3. **Garbage collection.** Superseded archives (the set `recipe-ids.py --stale`
   already computes) are deleted from shards on a schedule, keeping a defined
   number of previous versions for rollback, instead of inside every publish.

## 7. Migration plan

Each phase is independently reversible and the end-user index is unchanged
throughout.

### Phase 0: backfill (no behaviour change)

- A one-time job reads every existing archive, generates its record, builds
  the catalog, signs `catalog.toml`, and uploads them.
- Exit criterion: the catalog covers 100% of the archives referenced by the
  published index, and the verifier from 6.8 passes.
- Rollback: delete the catalog assets; nothing reads them yet.

### Phase 1: shadow mode

- Every publish still uses today's path (full download, `repo-create`).
  In addition it runs `repo-update` against the previous index and compares
  the result with the real one.
- Exit criterion: N consecutive publishes with an exactly equal `package`
  section and `recipes` entry, plus the property test passing in `nawa` CI.
- Rollback: turn the shadow step off.

### Phase 2: publish with `repo-update`

- The publish step uses `repo-update`. The full-scan `repo-create` becomes
  the weekly drift check (6.8).
- Exit criterion: no drift-check failures across several weeks.
- Rollback: switch the publish step back to `repo-create` (still intact).

### Phase 3: closure-based builds

- Replace "fetch every archive" with the closure fetch (6.4) and move the
  conflict check to the catalog (6.5).
- Exit criterion: the conflict-check equivalence test passes, and a build of a
  single package downloads only its closure.
- Rollback: re-enable the full fetch step (retained behind a workflow input
  during the transition).

The legacy schema-v1 release `stable` stays frozen throughout.

## 8. Failure modes and recovery

| Failure | Detection | Effect | Recovery |
|---|---|---|---|
| Transient 504 on a closure archive | HTTP error after bounded retries | Only the packages that need it fail, before building | Re-run; backoff and cache absorb most cases |
| Record disagrees with its archive | Publisher recomputes sha256/size | Publish refuses | Regenerate the record from the archive |
| Base index fails signature check | Step 1 of `repo-update` | Publish refuses | Investigate; do not merge an unverified base |
| Concurrent publish | `concurrency:` group, CAS check (6.7 step 4) | Second publish waits or re-merges | Automatic re-merge on the new base |
| `index.toml` / `catalog.toml` torn read | `index_sha256` mismatch | Reader falls back to verification path | Re-run publish; weekly check heals it |
| Incremental index drifts | Weekly full `repo-create` comparison | Job fails with a diff | Rebuild index with `repo-create`, fix root cause |
| Catalog lost or corrupt | Pointer sha mismatch | Conflict check cannot run | Rebuild from archives (Phase 0 job) |
| Index expiry reached | Expiry refresh job | Clients would refuse the index | Scheduled re-sign (6.8) |

## 9. Security considerations

- The base index is trusted only after signature verification; the update
  refuses otherwise.
- Archive bytes are always verified against the SHA-256 in the **signed**
  index before use. The catalog is never used to decide what an archive
  contains for installation, only for publisher-side checks.
- The catalog pointer is signed with the same key as the index. The signing
  key is used in the publish job only (as today, via
  `NAWA_SIGN_KEY_B64`); the new scheduled jobs that re-sign (expiry refresh)
  need the same secret and the same protection.
- Downloaded archives and records are untrusted until verified; they are
  parsed with the same validation rules `repo-create` already enforces.
- No change to what end users trust: the same signed index, the same key, the
  same per-archive hashes.

## 10. Expected effect

| Item | Today | After |
|---|---|---|
| Bytes downloaded per run | all archives (769, at least 4.4 GiB) | closure of the packages built (cached by sha256) plus a catalog of a few MB |
| Archives opened by index generation | all | none (weekly verification only) |
| Archives opened by the conflict check | all | none |
| Effect of one transient 504 | can fail the whole run | fails only the packages needing that archive |
| Growth of per-run cost as packages are added | linear | constant for a fixed change |

The sizes of the catalog and closures above are estimates to be measured in
Phase 0 and Phase 3; they are not yet measured.

## 11. Open questions and risks

1. **How the build chroot reads dependencies.** `build-packages-inner.sh` is
   not in this repository. Confirm whether it reads dependency archives from a
   local directory (assumed) or resolves them differently.
2. **`distributed-releases.py plan` currently takes `--repo-dir`** and plans
   shard placement for the full set of archives in that directory. It must
   learn to plan only the *new* archives and derive URLs for existing ones
   from release metadata it already reads (`package-releases.json`). Confirm
   there is no hidden dependency on the full directory.
3. **Catalog size and format.** Measure it in Phase 0. If it grows too large
   for a single document, shard it (for example by first letter) without
   changing the pointer scheme.
4. **Two repositories change in lockstep.** `nawa` (new subcommand, property
   test) and `faseela-repo` (workflow, scripts). The phased migration keeps the
   old path intact until the new one has been proven in shadow mode.
5. **Signing in extra jobs.** The expiry refresh and drift-check jobs need
   access to the signing secret (the drift check does not need to sign).
   Decide which job owns it.
6. **Cache policy.** GitHub's 10 GB limit is shared across the repository.
   The closure cache must be sized and keyed so it does not evict unrelated
   caches.
7. **Toolchain bootstrap targets** follow a separate Stage 1/2/3 pipeline.
   Confirm they can use the closure fetch, or keep them on the full fetch
   until a later phase.

## 12. Work breakdown

In `mrdevmohamed/nawa`:

- `repo-update` subcommand with the algorithm in 6.3;
- record generation (for example `nawa record <archive>`), reusing the
  `.PKGINFO` parsing and validation of `repo-create`;
- property test for the `repo-update` / `repo-create` equivalence invariant;
- optionally a `catalog` helper for merge and verification.

In `mrdevmohamed/faseela-repo`:

- workflow: record generation after build, closure fetch with cache, publish
  with `repo-update`, CAS check, `concurrency:` group, new scheduled jobs
  (drift check, expiry refresh, garbage collection);
- `scripts/check-file-conflicts.py`: catalog-based input plus an equivalence
  regression test against the archive-based path;
- `scripts/distributed-releases.py`: plan placement for new archives only;
- one-time backfill job for Phase 0.

## 13. Testing plan

- **Equivalence (nawa):** the `repo-update` / `repo-create` invariant over
  randomised package sets, including supersession (newest-per-name) and
  removal.
- **Verification (nawa):** `repo-update` rejects an unsigned or tampered base.
- **Conflict-check parity:** for a fixture set of archives, archive-based and
  catalog-based checks produce identical output, including merged-`/usr`
  cases and the file-before-directory ordering error.
- **Record correctness:** a record regenerated from an archive matches the
  stored one byte for byte.
- **Resilience:** inject 5xx responses into the closure fetch and assert
  backoff, bounded attempts and a named failure.
- **End to end (shadow phase):** repeated publishes with exact equality
  against the full-scan index.

## 14. Implementation status

Implemented in `faseela-repo` (no change to the production publish path):

- `scripts/package_catalog.py`: `record`, `build`, `merge` and `verify`
  commands for package records and the catalog (sections 6.1 and 6.2).
  `merge` updates a catalog from records without opening any archive, and
  `verify` compares a catalog with archives and with a repository
  `index.toml`.
- `scripts/check-file-conflicts.py --catalog FILE`: reads file lists from the
  catalog (section 6.5). An archive present in the archive directory still
  wins for the same file name, so packages built by the current run need no
  record.
- `scripts/test-package-catalog.py` (wired into `ci.yml`): record contents,
  rejection of invalid `.PKGINFO`, deterministic content-addressed catalogs,
  the catalog-level equivalent of the `repo-update` invariant (merge equals a
  fresh build), verification, and parity between the archive-based and the
  catalog-based conflict check.

Not implemented yet:

- the signed `catalog.toml` pointer: `package_catalog.py` writes an
  **unsigned** pointer (marked as such) and must never be published as is;
  signing needs the repository key in the publish job;
- `nawa repo-update` (lives in `mrdevmohamed/nawa`);
- the backfill job (Phase 0 exit criteria), shadow mode, closure-based fetch,
  and the scheduled jobs of section 6.8;
- the tests were run against a pass-through `zstd` shim locally; CI exercises
  them with the real `zstd`.
