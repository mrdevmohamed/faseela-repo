# Build and runtime dependencies

A recipe dependency is another package recipe in this repository. It is not a list of every tool that happens to be installed in the build root.

## Dependency types

| Field | When it is needed | Included in the flavor closure |
|---|---|---|
| **build** | Required to prepare or compile the package. | Included by **closure = "build"**; not by the default run closure. |
| **run** | Required for the installed program or library to work. | Included by both run and build closures. |
| **check** | Required only when the recipe test section is run. | Not included by the current flavor resolver. |

The bootstrap build environment provides some foundational tools implicitly. The repository conventions therefore avoid declaring those tools as recipe dependencies when they are supplied by the seed environment. Do declare a tool when it is represented by a recipe and is required by the package. For example, a recipe that needs Cargo declares the **rust** recipe as a build dependency.

## Declare dependencies

~~~toml
[depends]
build = ["cmake", "ninja"]
run = ["zlib", "openssl"]
check = ["dejagnu"]
~~~

Use the smallest accurate set. A missing runtime dependency can produce a package that builds successfully but fails after installation. A build-only tool should not become a permanent runtime dependency.

## Inspect dependency order

Ask Nawa to resolve one package and print the dependency order:

~~~sh
nawa --recipes recipes deps curl
~~~

To resolve the complete recipe tree:

~~~sh
nawa --recipes recipes deps-all
~~~

The repository validator checks that build and run dependency names exist and that their graph is acyclic. **flavor.py** separately resolves the dependencies needed by every flavor.

## Common patterns

- A library used by a program belongs in **run** when the installed program needs it.
- A compiler, code generator, or build system needed only to produce the package belongs in **build**.
- A test framework used only by the optional check section belongs in **check**.
- Do not declare bootstrap-provided shell utilities as package dependencies unless the recipe is meant to require a package from the recipe tree.

When uncertain, inspect the upstream build options and the package payload, then test the installed package in a clean Faseela root filesystem.
