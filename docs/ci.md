# Continuous integration

The repository has two main automation paths: validation CI and package build/publishing. Documentation has its own build-and-deploy workflow.

## Repository CI

**.github/workflows/ci.yml** runs on pushes to **main** or **master**, pull requests, and manual dispatch.

The **recipes** job includes:

- Offline parsing and structural checks for every recipe.
- Package build-recipe regression checks.
- Package selection and flavor resolution tests.
- Regression tests for creative recipes, Podman prerequisites, firmware splits, audio, Vulkan, and desktop integration.
- Package archive file-conflict and package-catalog tests.
- Published-archive downloader and distributed-release planner tests.
- Telegram notification regression tests.

The final **CI passed** job fails unless the recipe test job succeeds. This provides one summary check for the full validation job.

## Run checks locally

Run the recipe validator:

~~~sh
python3 -I scripts/check-recipes.py
~~~

Validate all flavors:

~~~sh
python3 -I scripts/flavor.py check
python3 -I scripts/test-flavor.py
~~~

Run the recipe inventory command and compare its number of lines with the recipe files when changing the inventory tooling:

~~~sh
python3 scripts/recipe-ids.py recipes
~~~

Individual regression tests live beside the scripts they exercise. The CI workflow is the authoritative list of the tests currently run on each change.

## Source reachability

The repository validator is deliberately offline. It checks recipe structure, dependencies, and checksum shape; it does not prove that every upstream source URL is currently reachable.

The Faseela ISO build has a separate source-check script for URL reachability. A green offline recipe check should not be described as proof that every upstream server is available.

## Package builds are separate

A green repository CI run does not mean every package has been rebuilt. Package builds and publication are handled by **.github/workflows/packages.yml**, triggered by recipe changes or a manual workflow dispatch.

See [Build and publishing](build-publish.md) for package selection, build environments, and release behavior.
