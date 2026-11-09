# Getting started

This page covers the two common ways to use faseela-repo: installing packages on Faseela, and working on package recipes.

## Use the published repository

On a current Faseela installation with a Nawa client that supports schema v3, refresh the package repository with:

~~~sh
nawa upgrade --repo https://github.com/mrdevmohamed/faseela-repo/releases/download/stable-v3
~~~

The active repository endpoint is **stable-v3**. It serves a signed schema-v3 index; package archives are stored in the **packages-NNNN** GitHub Releases.

### Older Nawa installations

Older Nawa clients that only understand schema v1 cannot parse the schema-v3 index. Upgrade Nawa first using the standalone signed package in the **nawa-transition** release.

Download the archive and detached signature:

~~~sh
gh release download nawa-transition \
  --repo mrdevmohamed/faseela-repo \
  --pattern '*.nawa.tar.zst' \
  --pattern '*.nawa.tar.zst.sig'
~~~

Install the downloaded local archive with the currently installed package manager:

~~~sh
archive="$(find . -maxdepth 1 -type f -name '*.nawa.tar.zst' -print -quit)"
test -n "$archive"
sudo nawa install "./$archive"
~~~

The upgraded Nawa package defaults to **stable-v3**. If **/etc/nawa/nawa.toml** was customized and preserved during the upgrade, check its **repo** value and change it to the schema-v3 endpoint when appropriate. The old **stable** release remains frozen for compatibility; it is not the place to publish new package metadata.

## Work on the recipes

Clone the repository and run the offline checks:

~~~sh
git clone https://github.com/mrdevmohamed/faseela-repo.git
cd faseela-repo

python3 -I scripts/check-recipes.py
python3 -I scripts/flavor.py check
~~~

List recipes and their categories:

~~~sh
python3 scripts/recipe-ids.py recipes
~~~

Inspect the dependency order for one package:

~~~sh
nawa --recipes recipes deps zlib
~~~

Before opening a pull request, read [Writing a recipe](recipes/new-recipe.md), [Dependencies](recipes/dependencies.md), and [Contributing](contributing.md).

## Preview the documentation locally

Python 3.11 or newer is required by the pinned documentation toolchain.

~~~sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-docs.txt
zensical serve
~~~

Open the local address printed by Zensical. To run the same strict build used by CI:

~~~sh
zensical build --clean --strict
~~~

The generated site is written to **site/**, which is ignored by Git.
