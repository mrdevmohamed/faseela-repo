# Flavors

A flavor is a named package selection in **flavors.toml**. Faseela uses flavors to define the package sets for its bootstrap, root filesystems, ISO variants, and optional developer environments.

Recipes describe how to build packages; flavors describe which packages belong in a particular image or environment.

## Flavor fields

| Field | Meaning |
|---|---|
| **summary** | Human-readable description. |
| **include** | Package names or category selectors such as **@base** and **@gui**. |
| **extends** | Other flavors whose selections are inherited. |
| **exclude** | Package names removed from the resolved result. |
| **closure** | Dependency policy: **run** or **build**. |

The default closure is **run**. It adds runtime dependencies recursively. A **build** closure includes both build and runtime dependencies recursively. When flavors are extended, a build closure is retained if any inherited flavor requires it.

An **@category** item expands to every recipe in that category. Package names and category selectors can be combined in the same **include** list.

## Examples

A minimal optional flavor:

~~~toml
[flavor.example-tools]
summary = "A small collection of example tools"
include = ["jq", "tree"]
~~~

A flavor that extends another selection:

~~~toml
[flavor.example-desktop]
summary = "Base desktop plus a browser"
extends = ["iso-gui"]
include = ["firefox"]
~~~

## Inspect flavors

List the available flavor names and summaries:

~~~sh
python3 -I scripts/flavor.py list
~~~

Resolve a flavor, with dependencies first:

~~~sh
python3 -I scripts/flavor.py resolve iso-gui
~~~

Check every flavor against the current recipes:

~~~sh
python3 -I scripts/flavor.py check
~~~

The same full flavor validation is part of the repository CI workflow.

## Current selection principles

- **bootstrap** and **seed** use a build dependency closure to produce the self-hosting base.
- **rootfs-min** is a smaller package-build environment.
- **iso-nogui** selects the non-graphical system package set.
- **iso-gui** extends the non-GUI image with the graphical stack.
- Media, creative, messaging, networking, security, and developer groups are maintained as optional selections.

The exact packages in a flavor are defined only by the current **flavors.toml**. Do not infer image contents from category names alone.
