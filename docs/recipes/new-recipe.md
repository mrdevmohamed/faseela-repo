# Writing a recipe

Every package must have a directory under one recipe category and a **recipe.toml** file inside it.

~~~text
recipes/
└── extra/
    └── example/
        └── recipe.toml
~~~

Choose a category that matches the package purpose. Keep the directory name identical to **package.name**.

## Minimal single-source example

This example follows the current zlib recipe pattern. Use the real upstream version and checksum for the package being added; never copy a checksum from an unrelated source archive.

~~~toml
[package]
name = "example"
version = "1.0.0"
rel = 1
arch = ["x86_64"]
summary = "Short package description"
license = ["MIT"]
source = "https://example.org/example-1.0.0.tar.xz"
sha256 = "REPLACE_WITH_THE_VERIFIED_64_CHARACTER_SHA256"
source_dir = "example-1.0.0"

[depends]
build = []
run = []

[build]
configure = "./configure --prefix=/usr"
compile = "make -j%{jobs}"
install = "make DESTDIR=%{pkgdir} install"
~~~

The checksum placeholder is intentionally invalid and must be replaced before the recipe is accepted for publication.

## Package metadata

| Field | Purpose |
|---|---|
| **name** | Package name; must match the recipe directory name. |
| **version** | Upstream/package version. |
| **rel** | Faseela package release number. Increment it when a recipe change changes the resulting package output. |
| **arch** | Supported architecture list. Current recipes target x86_64. |
| **summary** | Short package description. |
| **license** | Upstream license identifier or identifiers. |
| **source** | Source URL, a local source, or empty for recipes that do not use a remote archive. |
| **sha256** | SHA-256 digest of the downloaded source input. |
| **source_dir** | Optional directory inside an extracted source archive. |
| **mirrors** | Optional fallback URLs whose downloaded bytes must match the same SHA-256 digest. |

Source URL placeholders such as **%{version}** are expanded before fetching. A source may be a single file rather than a compressed archive; use the recipe schema supported by the pinned Nawa version.

## Dependencies and build sections

The **[depends]** table separates **build**, **run**, and **check** requirements. See [Dependencies](dependencies.md) before adding them.

The **[build]** table may contain the following shell sections:

| Section | Typical purpose |
|---|---|
| **prepare** | Apply patches or prepare the source tree. |
| **configure** | Configure the upstream build system. |
| **compile** | Compile the software. |
| **check** | Run upstream tests when enabled. |
| **install** | Install staged files into **%{pkgdir}**. |

Use **/usr** as the installation prefix and stage files under **%{pkgdir}**. Do not write directly into the build host or target root during the package build.

Nawa expands only documented placeholders. Common values include **%{version}**, **%{jobs}**, **%{srcdir}**, and **%{pkgdir}**. Refer to Nawa documentation for the placeholder set supported by the active recipe schema.

## Multiple sources and ecosystem fetches

A new-schema recipe can declare several source artifacts using **[[package.sources]]**. Each source has a unique name, URL, and pinned SHA-256 digest. **package.workdir** can select the workspace directory.

Nawa also supports fetch declarations for ecosystem dependencies, including **[fetch.cargo]** and **[fetch.go]**. These fetch steps run before compilation so the build can use the prepared dependency cache offline.

Any recipe that uses the new schema tables must use this exact marker in **[package]**:

~~~toml
source = "local:/nawa-schema-2-requires-a-newer-nawa"
~~~

This marker deliberately causes older Nawa clients to fail closed rather than interpreting the recipe using the legacy schema. Do not use the marker on an otherwise legacy recipe. Do not mix **[[package.sources]]** with legacy **sha256**, **mirrors**, or **source_dir** fields.

For the complete schema and validation rules, use the [Nawa recipe reference](https://github.com/mrdevmohamed/nawa/blob/master/docs/recipes.md) and [fetch-phase design](https://github.com/mrdevmohamed/nawa/blob/master/docs/design/fetch-phase.md).

## Recipe-local assets

Use **[assets]** to include files stored beside the recipe, such as patches or configuration fragments:

~~~toml
[assets]
include = ["patches/fix-build.patch", "config/default.conf"]
~~~

Asset paths are relative to the recipe directory and may not escape it. The files are staged read-only and exposed to the build through **%{assetsdir}**. The new-schema compatibility marker is required.

## Hooks and system accounts

The **[hooks]** table supports target-system package hooks such as **post_install**, **pre_remove**, and **post_remove**. Hooks run during package operations on the target system, not during compilation.

Keep hooks small, safe to retry, and limited to actions that are necessary for the package to function. If a package needs a system user or group, use the helper shipped by **base-files**:

~~~sh
/usr/libexec/faseela/ensure-system-account
~~~

Do not assume **useradd** or **groupadd** is installed when an archive is installed directly.

## Slimming and split packages

Nawa performs post-install slimming and splits documentation and language catalogs into separate packages by default. A recipe can opt out of individual operations with a **[slim]** table, for example:

~~~toml
[slim]
strip = false
cleanup = false
split = false
~~~

Use only the opt-outs required by the package. The split documentation and language packages retain the base package version and release and depend on the base package.

## Before submitting

- Verify the source URL and its SHA-256 digest.
- Declare all recipe-level build and runtime dependencies.
- Increment **rel** when output changes.
- Ensure the install step writes only beneath **%{pkgdir}**.
- Check hooks and file ownership conflicts.
- Run the repository validation and flavor checks in [Contributing](../contributing.md).
