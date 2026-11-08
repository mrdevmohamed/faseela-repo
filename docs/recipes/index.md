# Package recipes

A recipe is a declarative TOML description of how Nawa fetches, builds, and packages one piece of software. The canonical location is:

~~~text
recipes/<category>/<package-name>/recipe.toml
~~~

The repository groups recipes by purpose. See [Repository layout](../repository-layout.md) for the current category list.

## Recipe lifecycle

1. A recipe pins upstream source inputs and their SHA-256 digests.
2. It declares recipe-level build and runtime dependencies.
3. Nawa fetches and verifies the inputs before compilation.
4. Nawa runs the configured build sections and stages installed files into a package directory.
5. The package archive is checked and made available to the publisher.
6. The package workflow builds a signed repository index that references the published archive.

## Two recipe schema styles

Most recipes use the single-source form with **package.source**, **package.sha256**, and optional **package.source_dir** or **package.mirrors**.

Newer recipes can use multiple pinned sources, recipe-local assets, and ecosystem fetch backends such as Go Modules or Cargo. These features require a recent Nawa client and the fail-closed schema marker described in [Writing a recipe](new-recipe.md).

Do not combine the legacy single-source fields with the new **package.sources** form. Follow the Nawa schema documentation for the exact allowed fields.

## References

- [Write a new recipe](new-recipe.md)
- [Build and runtime dependencies](dependencies.md)
- [Nawa recipe format](https://github.com/mrdevmohamed/nawa/blob/master/docs/recipes.md)
- [Nawa build and fetch](https://github.com/mrdevmohamed/nawa/blob/master/docs/build-and-fetch.md)
