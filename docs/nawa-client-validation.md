# Nawa client pin validation

**Recorded:** 2026-11-20

**Status:** Compatible client package verified locally; not installed or published.

## Scoped recipe correction

`recipes/base/nawa/recipe.toml` now selects Nawa `1.0.0-33` from committed
source `207fb56fca57632de9a61f509ee709074b8bb41e`, with upstream archive
SHA-256 `0db013358960f286a81c5b4d8ba28852e60d2e83e156461e9a87d2567d8eea60`.
Only release, source URL and source checksum changed. Version, upstream,
build commands, edition 2021 and declared MSRV 1.82 are unchanged.

The actual GitHub archive returned HTTP 200; all 228 file contents and modes
match the committed tree. Dirty Nawa assessment changes were excluded.
Cargo.toml and Cargo.lock are unchanged between the old and new pins.

The recipe's locked/offline build succeeded with Cargo/rustc 1.99.1 and
**isolation explicitly `none`**. This is not sandbox or network-namespace
acceptance. The resulting local archive has SHA-256
`517882e60c59995108671e12d3f8d1e2029b68f6562484607321b45cf67fce1e`.
Its actual archived executable passed eight read-only profile fixtures:
required systemd was accepted; administrator override, malformed/missing or
unsupported profiles, and preferred-only/forbidden-only policy were not
misreported as required systemd. Target paths remained unchanged. Bootstrap
fetch verified the pin; a second fetch was a no-op. These are package/consumer
checks, not firmware or full-suite acceptance.

## Why the old pin was insufficient

The old `1.0.0-32` pin at `66ed2098c6be13db04d0c5dc0904c26fe3d5b233`
lacks `system profile show`. Its shipped executable SHA-256
`8f27bf13f16deba907c33138546d73ad066b47f9ee23bcd7733336f94cae7018`
is byte-identical across package, staged root, original ISO and installed UEFI
disk. Stripping the retained package build reproduced those bytes. A separate
standalone build was not the shipped executable. The old client's actual
command failure explains the failed profile probe; it does not prove the
profile file was absent.

## Still gated

The rel33 archive is unsigned. Authorization for `--allow-unsigned` **only in
a new disposable test root** remains pending. The prepared root still has
rel32; there is no new ISO or UEFI boot. Do not bypass configured keys, copy a
host executable into the root, or treat this recipe commit as installation,
trust, publication or migration approval. `stable` and `stable-v3` remain
unchanged; no `stable-v5` publication or blocker removal is authorized.

This record accompanies only the recipe correction. Pre-existing publisher,
workflow, flavor and `docs/build-publish.md` changes are outside this commit;
their presence is not acceptance. No current hosted CI/full dirty-tree suite
or signed-release validation is claimed.

Cross-repository implementation tracker: `nawa/docs/implementation-progress.md`
in the adjacent Nawa checkout. Durable commands, identities and pending boundary:
`/var/tmp/faseela-integration-validation/nawa-profile-candidate-m41sgifi/CANDIDATE-PREPARED.md`.
The reconciled old chain is recorded in
`/var/tmp/faseela-integration-validation/successor-validation-6DB3Yp/nawa-provenance-cGUQeP/chain.json`.
