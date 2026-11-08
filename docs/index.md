# Faseela Package Repository

The package repository for [Faseela](https://github.com/mrdevmohamed/faseela) contains the package recipes, the automation that builds them, and the signed binary repository consumed by [Nawa](https://github.com/mrdevmohamed/nawa).

This repository is the package layer of the distribution. It does not contain the complete operating-system bootstrap or the ISO build system.

## The three projects

| Project | Responsibility |
|---|---|
| [Faseela](https://github.com/mrdevmohamed/faseela) | Bootstrap, system profiles, root filesystem, and ISO build. |
| [Nawa](https://github.com/mrdevmohamed/nawa) | Package manager, recipe/build engine, and repository client. |
| **faseela-repo** | Package recipes, package build automation, and published package metadata and archives. |

## Where to start

- **Using packages:** read [Getting started](getting-started.md) and [Package repository](package-repository.md).
- **Adding or changing a package:** read [Package recipes](recipes/index.md), [Writing a recipe](recipes/new-recipe.md), and [Contributing](contributing.md).
- **Understanding image package sets:** read [Flavors](flavors.md).
- **Understanding CI and publishing:** read [Build and publishing](build-publish.md) and [CI checks](ci.md).

## Repository endpoints

New and upgraded Nawa clients use the signed schema-v3 endpoint:

~~~text
https://github.com/mrdevmohamed/faseela-repo/releases/download/stable-v3
~~~

The old schema-v1 endpoint named **stable** is retained for compatibility with older clients. It is not the active endpoint for new installations.

See [Package repository](package-repository.md) for the storage layout and migration procedure.

## Project status and accuracy

The recipe tree and workflow files in this repository are the source of truth. Package availability, dependency declarations, flavors, and workflow behavior can change as the repository evolves.

Some files under **docs/** are design notes rather than descriptions of shipped behavior. In particular, [Incremental package publishing](package-repository-design.md) is a proposal: its catalog/record tooling exists, but the production publishing workflow does not yet use that incremental design.
