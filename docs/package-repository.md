# Package repository

The binary package repository is published through GitHub Releases. The source repository contains recipes and publisher tooling; it does not store the full set of built archives in Git.

## Active and compatibility endpoints

| Release tag | Index schema | Purpose |
|---|---|---|
| **stable-v3** | Schema v3 | Active endpoint for current Faseela installations and upgraded Nawa clients. |
| **stable** | Schema v1 | Frozen compatibility endpoint for older Nawa clients. |
| **nawa-transition** | Standalone signed Nawa archive | Allows schema-v1 clients to upgrade to a Nawa release that understands schema v3. |
| **packages-NNNN** | Storage releases | Storage shards holding package and recipe snapshot archives. |

The active endpoint is:

~~~text
https://github.com/mrdevmohamed/faseela-repo/releases/download/stable-v3
~~~

The **stable-v3** release contains **index.toml** and its detached signature, **index.toml.sig**. The schema-v3 index points to package archives using absolute HTTPS download URLs. The index contains the SHA-256 digest for each archive.

## Storage shards

Package archives use the **.nawa.tar.zst** suffix. The publisher assigns them to releases named **packages-NNNN**, keeping each shard at or below 900 assets. The lower limit leaves room below the GitHub Releases asset cap.

The publisher uploads new archive assets before publishing the index that refers to them. It publishes the signed index to **stable-v3** only after the referenced assets have been uploaded. Superseded shard assets are cleaned up after the new index has been published.

A recipe snapshot is also published with the package set so the repository revision used by the build can be recorded and synchronized.

## Nawa schema transition

A Nawa client that only supports schema v1 cannot read the schema-v3 index. The transition is intentionally separate from the repository index:

1. The package workflow publishes the Nawa package and detached signature to **nawa-transition**.
2. An older client downloads both files.
3. The existing Nawa installation installs the local archive.
4. The updated Nawa package defaults to the **stable-v3** endpoint.

The **stable** release remains unchanged for old installations and rollback compatibility. Do not publish schema-v3 metadata to the **stable** tag.

## Refresh the active repository

On a current Faseela installation:

~~~sh
nawa upgrade --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable-v3
~~~

For the transition instructions for older clients, see [Getting started](getting-started.md).

## Publisher implementation

The package workflow reads existing release metadata, downloads the published archives needed for repository validation, builds selected packages, checks for file conflicts, plans shard assignments, creates or updates storage releases, and creates a signed schema-v3 index with Nawa.

The incremental catalog design under **docs/package-repository-design.md** is not yet the production publishing path. See the status note in that design document before treating its proposed behavior as implemented.
