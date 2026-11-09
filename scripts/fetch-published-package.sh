#!/usr/bin/env bash
# Download ONE already-published package archive into "$T/build/out".
#
#   usage: fetch-published-package.sh TAG ASSET
#   env:   PKG_REPO (owner/name), T (build root)           required
#          FETCH_VIA_API=1  use `gh release download` (authenticated API)
#                           instead of the public browser URL; needs GH_TOKEN
#
# Never aborts the caller's pool: on failure it removes the partial file,
# names the asset in a workflow warning (curl's own "(22) ... 500" message
# does not) and exits 1 so the caller can queue it for a later retry round.
set -uo pipefail

tag="${1:?tag}"
asset="${2:?asset}"
: "${PKG_REPO:?PKG_REPO is required}" "${T:?T is required}"

out="$T/build/out"
part="$out/$asset.part"
trap 'rm -f "$part"' EXIT

if [[ -n "${FETCH_VIA_API:-}" ]]; then
  echo "Downloading $asset ($tag) via API"
  gh release download "$tag" --repo "$PKG_REPO" \
    --pattern "$asset" --output "$part" --clobber
else
  echo "Downloading $asset ($tag)"
  curl --fail --location --silent --show-error \
    --retry 3 --retry-all-errors --retry-delay 5 --retry-max-time 120 \
    --connect-timeout 30 --max-time 1800 --output "$part" \
    "https://github.com/$PKG_REPO/releases/download/$tag/$asset"
fi
rc=$?

if (( rc != 0 )); then
  echo "::warning::download failed (exit $rc): $asset from release $tag" >&2
  exit 1
fi
if [[ ! -s "$part" ]]; then
  echo "::warning::downloaded asset is empty: $asset from release $tag" >&2
  exit 1
fi

mv -f "$part" "$out/$asset"
trap - EXIT
