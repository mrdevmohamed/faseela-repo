"""Read a recipe's upstream source in either shape.

Schema-v5 recipes declare `[[package.sources]]`; older ones used the single
`source` / `sha256` / `mirrors` fields. Tools that only need "the primary
upstream file" go through this module so they work on both.
"""
from __future__ import annotations

LOCAL = "local:"


def sources(pkg: dict) -> list[dict]:
    """Every downloadable source: dicts with `url`, `sha256`, optional `mirrors`."""
    declared = pkg.get("sources")
    if declared:
        return [dict(s) for s in declared]
    url = pkg.get("source", "")
    if url and not url.startswith(LOCAL):
        entry = {"url": url, "sha256": pkg.get("sha256", "")}
        if pkg.get("mirrors"):
            entry["mirrors"] = list(pkg["mirrors"])
        return [entry]
    return []


def primary(pkg: dict) -> dict | None:
    found = sources(pkg)
    return found[0] if found else None


def url(pkg: dict) -> str:
    entry = primary(pkg)
    return entry["url"] if entry else ""


def sha256(pkg: dict) -> str:
    entry = primary(pkg)
    return entry.get("sha256", "") if entry else ""
