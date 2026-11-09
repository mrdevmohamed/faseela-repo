# Package groups

Nawa package groups provide named selections of ordinary package recipes. A
group is metadata, not a package archive: every selected package still uses
the normal dependency planner, repository verification, build selection, and
installer.

## Catalog format

The source of truth is **groups.toml** at the repository root. It contains one
TOML `[[group]]` table per group:

```toml
[[group]]
schema = 1
id = "dev"
name = "Development Tools"
description = "Compilers, runtimes, editors, and debugging utilities."
mandatory = ["git", "base-devel"]
default = ["cmake", "ninja", "neovim"]
optional = ["gdb", "valgrind"]
```

- **mandatory** packages are always selected.
- **default** packages are selected by default.
- **optional** packages are added only with `nawa group install dev --with-optional`.

Group IDs and package names use the same conservative name alphabet as Nawa.
A package may be shared by more than one group. A package name must correspond
to a recipe in this repository; CI validates the entire catalog.

## Signed publication

The package workflow asks Nawa to validate and copy **groups.toml** into the
repository output. Nawa writes a `[groups]` reference into the schema-v3
**index.toml**, including the catalog schema, filename, exact byte size, and
SHA-256 digest. The Ed25519 index signature therefore authenticates the
catalog reference; the client verifies the catalog bytes against that digest
before parsing any group definition.

The publisher uploads **groups.toml** before replacing the signed index in the
**stable-v3** release. A legacy v1 index cannot reference group metadata.

## Client commands

```sh
nawa group list
nawa group info dev
nawa group install dev
nawa group install dev --with-optional
nawa group remove dev
```

Group installation requires a configured repository whose index signature is
trusted by the target system. A group install records the exact selected
package list and the catalog digest locally. A later change to the remote
group definition does not silently rewrite the installed membership.

Packages installed solely as group members are marked with reason `group`,
not `explicit`. Removing a group preserves packages that were explicitly
installed or are still referenced by another installed group. Dependencies
that become unnecessary can be reviewed with `nawa autoremove`.
