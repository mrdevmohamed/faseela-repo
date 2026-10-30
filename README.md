# faseela-repo

The package side of the [faseela](https://github.com/mrdevmohamed/faseela)
distribution: the **recipes**, the CI that builds them, and the **published
packages**.

```
recipes/      one recipe.toml per package (toolchain, base, system, boot, gui, extra)
scripts/      recipe tooling: check-recipes, recipe-ids, check-sources, fill-sha256,
              gen-recipes-extra, pin-nawa-source
.github/workflows/
  ci.yml        validates the recipe tree (required check on master)
  packages.yml  builds packages and publishes them
```

See [recipes/README.md](recipes/README.md) for the recipe format and the build
order.

## How the pieces fit

| repository | holds |
|---|---|
| [nawa](https://github.com/mrdevmohamed/nawa) | the package manager |
| **faseela-repo** (this one) | recipes, package builds, the published package repository |
| [faseela](https://github.com/mrdevmohamed/faseela) | bootstrap, profiles, the ISO build |

* **Packages.** `packages.yml` builds recipes inside the rootfs of the newest
  faseela release and publishes the archives, a signed `index.toml` and the
  recipe tree to the `stable` release of this repository. It uses the workflow's
  own `GITHUB_TOKEN`; the only secret is `NAWA_SIGN_KEY_B64`. Clients:

  ```
  nawa upgrade --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable
  ```

* **ISO.** faseela fetches these recipes from `master` at build time
  (`bootstrap/fetch-recipes.sh`) and, on a `v*` tag, records the commit it used,
  so a release can be rebuilt from the same recipes.

* **Setup.** See the header of `.github/workflows/packages.yml` for the
  one-time secret and optional variables (`PKG_TAG`, `DISTRO_REPO`, `DISTRO_REF`).
  Make `CI passed` a required check on `master`: faseela builds from it.

## Working on a recipe

```
python3 -I scripts/check-recipes.py      # validate the tree
python3 scripts/recipe-ids.py recipes    # list category / name / id
```

A push to `master` that touches `recipes/**` builds the changed packages. To
build others, run *Build packages* by hand (names, `@category` or `ALL`).
To try a recipe change inside the ISO build before merging it, point faseela at
a branch: `RECIPES_REF=<branch> bootstrap/fetch-recipes.sh`, or the local
checkout with `RECIPES_DIR=../faseela-repo/recipes`.
