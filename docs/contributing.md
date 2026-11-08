# Contributing

Changes to recipes affect the packages that Faseela can build and install. Keep each change focused, verifiable, and compatible with the currently pinned Nawa and Faseela tooling.

## Before changing a recipe

1. Find the package under **recipes/<category>/<name>/**.
2. Read its current recipe and the related upstream build documentation.
3. Check whether the source format requires the legacy or new Nawa recipe schema.
4. Inspect existing dependencies and package ownership before adding new ones.
5. Check whether a suitable package already exists elsewhere in the recipe tree.

## Recipe change checklist

- Keep the recipe directory name and **package.name** identical.
- Pin a real upstream version and verified SHA-256 digest.
- Do not submit all-zero placeholder hashes for remote sources.
- Declare recipe-level build and runtime dependencies accurately.
- Use the documented Nawa fetch backends for Go or Cargo inputs when applicable; avoid downloading ecosystem dependencies during the offline build sections.
- Install only into **%{pkgdir}** and use **/usr** as the prefix.
- Bump **rel** whenever the resulting package output changes.
- Add hooks only when necessary, and keep them safe to retry.
- Check package file ownership conflicts and optional flavor membership.
- Keep developer and optional desktop packages out of the default bootstrap or ISO flavors unless that change is explicitly intended.

For packages that need a system account, use **/usr/libexec/faseela/ensure-system-account** from **base-files**; do not rely on **useradd** or **groupadd** being available during direct archive installation.

## Validate locally

Run the offline recipe checks:

~~~sh
python3 -I scripts/check-recipes.py
python3 -I scripts/flavor.py check
python3 -I scripts/test-flavor.py
~~~

Resolve the package dependency order:

~~~sh
nawa --recipes recipes deps <package-name>
~~~

For a new or changed package, also use the Nawa recipe checker:

~~~sh
nawa --recipes recipes recipe check <package-name>
~~~

Then build and install-test the package in a disposable Faseela root filesystem. A recipe passing the offline validator is not proof that the upstream source can be downloaded or that the package works at runtime.

## Pull request expectations

- Explain the package change and why it is needed.
- Include the upstream source/version and any relevant build-option references.
- State whether the package output changes and whether **rel** was bumped.
- Include local validation results and package build/runtime test results when available.
- Call out any change to **flavors.toml**, workflow behavior, or repository publication.

Do not include signing keys, bot tokens, or other secrets in the patch or pull request.

## Updating the Nawa source pin

The **nawa** recipe is also the source of truth for the pinned Nawa source used by the package and bootstrap workflows. Use **scripts/pin-nawa-source.py** to update that pin rather than maintaining a second independent source reference.
