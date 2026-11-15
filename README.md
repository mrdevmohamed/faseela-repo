# faseela-repo

**[Read the documentation](https://mrdevmohamed.github.io/faseela-repo/)** — recipes, package repository, build workflows, and contribution guide.

The package side of the [faseela](https://github.com/mrdevmohamed/faseela)
distribution: the **recipes**, the CI that builds them, and the **published
packages**.

```
recipes/      one recipe.toml per package (toolchain, base, system, boot, extra, gui, cosmic, greeter, browser, media, creative, messaging, networking, security, peripherals, dev)
flavors.toml  build roots and desktop images (bootstrap, seed, rootfs-min, iso-nogui, iso-sway, iso-xfce, iso-cosmic)
scripts/      recipe tooling: check-recipes, recipe-ids, flavor, file-conflicts,
              distributed-releases, pin-nawa-source
.github/workflows/
  ci.yml        validates the recipe tree (required check on main)
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

## Package repository endpoints

The repository uses two endpoints during the schema-v3 migration:

- **`stable`** is the frozen legacy schema-v1 endpoint. It is deliberately
  retained unchanged so installed old Nawa clients do not receive an index
  they cannot parse. It is no longer the endpoint for new Faseela installs.
- **`stable-v3`** is the active schema-v3 endpoint. It contains the signed
  `index.toml` and `index.toml.sig`; package and recipe archives are kept in
  `packages-NNNN` storage Releases. The signed index authenticates each
  archive's URL and SHA-256.

New Faseela installs and upgraded Nawa packages use:

```sh
nawa upgrade --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable-v3
```

### Existing installations

An old Nawa binary cannot parse the schema-v3 index. The package workflow
therefore publishes a standalone signed Nawa archive in the
[`nawa-transition` Release](https://github.com/mrdevmohamed/faseela-repo/releases/tag/nawa-transition).
Download both the `.nawa.tar.zst` archive and its `.sig` sidecar, then install
the local archive with the existing package manager:

```sh
gh release download nawa-transition \
  --repo mrdevmohamed/faseela-repo \
  --pattern '*.nawa.tar.zst' --pattern '*.nawa.tar.zst.sig'
archive="$(find . -maxdepth 1 -type f -name '*.nawa.tar.zst' -print -quit)"
test -n "$archive"
sudo nawa install "./$archive"
```

The upgraded package defaults to the `stable-v3` repository. If
`/etc/nawa/nawa.toml` was customized and is preserved by Nawa's configuration
protection, update its `repo` value manually. The old `stable` endpoint is
kept unchanged as a rollback/compatibility source.

## Publishing

`packages.yml` builds recipes inside the rootfs of the newest Faseela release.
It publishes package and recipe archives to storage shards capped at 900 assets
each, then uploads the signed v3 index to `stable-v3`. It does not rewrite or
delete assets from the old `stable` release. The first run automatically
includes the `nawa` recipe, builds it with the seed rootfs, and publishes the
standalone transition package.

The workflow uses its own `GITHUB_TOKEN` with `contents: write`; no personal
access token is needed. The required secret is `NAWA_SIGN_KEY_B64`
(base64-encoded `nawa.sec`). Optional variables are `PKG_TAG` (legacy tag),
`PKG_V3_TAG`, `NAWA_TRANSITION_TAG`, `DISTRO_REPO` and `DISTRO_REF`.

## ISO

Faseela fetches recipes from `main` at build time
(`bootstrap/fetch-recipes.sh`) and, on a `v*` tag, records the commit it used,
so a release can be rebuilt from the same recipes.

## Developer Edition

See [DEVELOPER-EDITION.md](DEVELOPER-EDITION.md) for the opt-in developer package groups, full package inventory, recipe requirements and implementation order. Developer tools are intentionally kept out of the default ISO and bootstrap.

## Working on a recipe

```sh
python3 -I scripts/check-recipes.py      # validate the tree
python3 scripts/recipe-ids.py recipes    # list category / name / id
```

Whether every source URL is still reachable is checked by the ISO workflow with
`scripts/check-sources.py` of Faseela
(`python3 check-sources.py <path to recipes>`).

A push to `main` that touches `recipes/**` builds the changed packages. To
build others, run *Build packages* by hand (names, `@category` or `ALL`).
To try a recipe change inside the ISO build before merging it, point Faseela at
a branch: `RECIPES_REF=<branch> bootstrap/fetch-recipes.sh`, or use the local
checkout with `RECIPES_DIR=../faseela-repo/recipes`.
