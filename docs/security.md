# Repository security

The package repository is a trust boundary. A correct workflow must authenticate repository metadata, verify downloaded bytes, and keep signing credentials out of source control.

## Source integrity

Every remote source input should have a pinned SHA-256 digest in the recipe. Nawa verifies fetched source files against the declared digest before using them.

A source mirror may be substituted only when the downloaded bytes still match the same pinned digest. A URL alone is not an integrity check.

Do not submit a new remote recipe with an all-zero placeholder checksum. The recipe validator reports these placeholders, but the final acceptance process must replace them with a verified digest.

## Signed schema-v3 index

The active **stable-v3** repository index is published as:

- **index.toml**
- **index.toml.sig**

The index authenticates the package metadata, including the HTTPS archive locations and SHA-256 digests. A digest detects byte-level corruption; a signature checked against a trusted public key authenticates the metadata that supplies the digest.

Nawa supports signed repository metadata and a trust store. See the [Nawa repository and security guide](https://github.com/mrdevmohamed/nawa/blob/master/docs/repositories-and-security.md) for key generation, trust configuration, and verification commands.

## Signing-key handling

The package publishing workflow requires the repository secret **NAWA_SIGN_KEY_B64**, which contains the base64-encoded private signing key file.

- Never commit the private key or its base64 value.
- Never put signing material in recipe files, documentation, logs, or pull-request comments.
- Do not print the secret in workflow output.
- Use the Faseela/Nawa public-key trust path for client configuration; distribute only the public key.

The workflow uses its own **GITHUB_TOKEN** with the repository contents permission to publish Releases. A personal access token is not required by the current setup.

## Legacy endpoint

The **stable** schema-v1 release is frozen for older clients. New metadata belongs on **stable-v3**; the publisher deliberately leaves the old release intact.

## Safe package hooks

Package hooks execute on the target system during package operations. Keep them small, predictable, and safe to retry. Never place credentials in hooks or perform unrelated privileged changes during installation.
