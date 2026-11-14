#!/usr/bin/env python3
"""Pin the existing Faseela COSMIC recipes to the coordinated Epoch 1.11.0 sources.

The archive digest is calculated from the actual codeload response; never use
Git object IDs or guessed checksums as source SHA-256 values.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = "epoch-1.11.0"
RECIPES = sorted(
    path for path in (ROOT / "recipes" / "cosmic").glob("*/recipe.toml")
    if path.parent.name != "cosmic-desktop"
)
greeter = ROOT / "recipes" / "greeter" / "cosmic-greeter" / "recipe.toml"
if greeter.is_file():
    RECIPES.append(greeter)

URL_RE = re.compile(
    r'^(\s*url\s*=\s*")https://codeload\.github\.com/'
    r'(pop-os/[A-Za-z0-9_.-]+)/tar\.gz/refs/tags/([^"]+)(".*)$',
    re.MULTILINE,
)
SHA_RE = re.compile(r'^(\s*sha256\s*=\s*")[0-9a-f]{64}(".*)$', re.MULTILINE)
VERSION_RE = re.compile(r'^(version\s*=\s*")[^"]+(".*)$', re.MULTILINE)
REL_RE = re.compile(r'^(rel\s*=\s*)(\d+)(\s*(?:#.*)?)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Faseela-COSMIC-source-updater/1.0"}
    )
    h = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            h.update(chunk)
    if total == 0:
        raise RuntimeError(f"{url}: empty source archive")
    return h.hexdigest()


def update(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    matches = list(URL_RE.finditer(original))
    if not matches:
        raise RuntimeError(f"{path.relative_to(ROOT)}: no supported pinned pop-os source URL")
    if len(matches) != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: expected exactly one source URL")

    match = matches[0]
    repo = match.group(2)
    old_tag = match.group(3)
    tag_changed = old_tag != TAG

    new_url = f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{TAG}"
    new_sha = digest(new_url)
    content = original[:match.start()] + (
        match.group(1) + new_url + match.group(4)
    ) + original[match.end():]

    content, version_count = VERSION_RE.subn(r'\g<1>1.11.0\g<2>', content, count=1)
    if version_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: package version field not found")

    content, sha_count = SHA_RE.subn(r'\g<1>' + new_sha + r'\g<2>', content, count=1)
    if sha_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: source SHA-256 field not found")

    if "VERGEN_GIT_SHA=" in content:
        commit_date, commit_sha = vergen_metadata(repo)
        content, date_count = VERGEN_DATE_RE.subn(
            lambda m: m.group(1) + commit_date, content, count=1
        )
        content, vergen_sha_count = VERGEN_SHA_RE.subn(
            lambda m: m.group(1) + commit_sha, content, count=1
        )
        if date_count != 1 or vergen_sha_count != 1:
            raise RuntimeError(
                f"{path.relative_to(ROOT)}: expected one Vergen commit date and SHA pin"
            )

    if not REL_RE.search(content):
        raise RuntimeError(f"{path.relative_to(ROOT)}: package rel field not found")
    if tag_changed:
        content = REL_RE.sub(
            lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}",
            content,
            count=1,
        )

    if content == original:
        print(f"verified {path.relative_to(ROOT)}: {TAG}; sha256={new_sha}")
        return False

    path.write_text(content, encoding="utf-8")
    print(f"updated {path.relative_to(ROOT)}: {old_tag} -> {TAG}; sha256={new_sha}")
    return True


def main() -> int:
    if not RECIPES:
        print("no COSMIC recipes found", file=sys.stderr)
        return 1
    changed = 0
    for recipe in RECIPES:
        changed += update(recipe)
    print(f"COSMIC Epoch source update complete: {changed} recipe(s) changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
, re.MULTILINE)
VERGEN_DATE_RE = re.compile(r'^(export VERGEN_GIT_COMMIT_DATE=)[^\n]+
    request = urllib.request.Request(
        url, headers={"User-Agent": "Faseela-COSMIC-source-updater/1.0"}
    )
    h = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            h.update(chunk)
    if total == 0:
        raise RuntimeError(f"{url}: empty source archive")
    return h.hexdigest()


def update(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    matches = list(URL_RE.finditer(original))
    if not matches:
        raise RuntimeError(f"{path.relative_to(ROOT)}: no supported pinned pop-os source URL")
    if len(matches) != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: expected exactly one source URL")

    match = matches[0]
    repo = match.group(2)
    old_tag = match.group(3)
    tag_changed = old_tag != TAG

    new_url = f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{TAG}"
    new_sha = digest(new_url)
    content = original[:match.start()] + (
        match.group(1) + new_url + match.group(4)
    ) + original[match.end():]

    content, version_count = VERSION_RE.subn(r'\g<1>1.11.0\g<2>', content, count=1)
    if version_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: package version field not found")

    content, sha_count = SHA_RE.subn(r'\g<1>' + new_sha + r'\g<2>', content, count=1)
    if sha_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: source SHA-256 field not found")

    if not REL_RE.search(content):
        raise RuntimeError(f"{path.relative_to(ROOT)}: package rel field not found")
    if tag_changed:
        content = REL_RE.sub(
            lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}",
            content,
            count=1,
        )

    if content == original:
        print(f"verified {path.relative_to(ROOT)}: {TAG}; sha256={new_sha}")
        return False

    path.write_text(content, encoding="utf-8")
    print(f"updated {path.relative_to(ROOT)}: {old_tag} -> {TAG}; sha256={new_sha}")
    return True


def main() -> int:
    if not RECIPES:
        print("no COSMIC recipes found", file=sys.stderr)
        return 1
    changed = 0
    for recipe in RECIPES:
        changed += update(recipe)
    print(f"COSMIC Epoch source update complete: {changed} recipe(s) changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
, re.MULTILINE)
VERGEN_SHA_RE = re.compile(r'^(export VERGEN_GIT_SHA=)[0-9a-f]{40}
    request = urllib.request.Request(
        url, headers={"User-Agent": "Faseela-COSMIC-source-updater/1.0"}
    )
    h = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            h.update(chunk)
    if total == 0:
        raise RuntimeError(f"{url}: empty source archive")
    return h.hexdigest()


def update(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    matches = list(URL_RE.finditer(original))
    if not matches:
        raise RuntimeError(f"{path.relative_to(ROOT)}: no supported pinned pop-os source URL")
    if len(matches) != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: expected exactly one source URL")

    match = matches[0]
    repo = match.group(2)
    old_tag = match.group(3)
    tag_changed = old_tag != TAG

    new_url = f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{TAG}"
    new_sha = digest(new_url)
    content = original[:match.start()] + (
        match.group(1) + new_url + match.group(4)
    ) + original[match.end():]

    content, version_count = VERSION_RE.subn(r'\g<1>1.11.0\g<2>', content, count=1)
    if version_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: package version field not found")

    content, sha_count = SHA_RE.subn(r'\g<1>' + new_sha + r'\g<2>', content, count=1)
    if sha_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: source SHA-256 field not found")

    if not REL_RE.search(content):
        raise RuntimeError(f"{path.relative_to(ROOT)}: package rel field not found")
    if tag_changed:
        content = REL_RE.sub(
            lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}",
            content,
            count=1,
        )

    if content == original:
        print(f"verified {path.relative_to(ROOT)}: {TAG}; sha256={new_sha}")
        return False

    path.write_text(content, encoding="utf-8")
    print(f"updated {path.relative_to(ROOT)}: {old_tag} -> {TAG}; sha256={new_sha}")
    return True


def main() -> int:
    if not RECIPES:
        print("no COSMIC recipes found", file=sys.stderr)
        return 1
    changed = 0
    for recipe in RECIPES:
        changed += update(recipe)
    print(f"COSMIC Epoch source update complete: {changed} recipe(s) changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
, re.MULTILINE)


def github_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Faseela-COSMIC-source-updater/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def vergen_metadata(repo: str) -> tuple[str, str]:
    ref = github_json(f"https://api.github.com/repos/{repo}/git/ref/tags/{TAG}")
    obj = ref["object"]
    if obj["type"] == "tag":
        obj = github_json(
            f"https://api.github.com/repos/{repo}/git/tags/{obj['sha']}"
        )["object"]
    if obj["type"] != "commit":
        raise RuntimeError(f"{repo}:{TAG}: tag does not resolve to a commit")
    sha = obj["sha"]
    commit = github_json(f"https://api.github.com/repos/{repo}/commits/{sha}")
    date = commit["commit"]["committer"]["date"]
    return date, sha


def digest(url: str) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Faseela-COSMIC-source-updater/1.0"}
    )
    h = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            h.update(chunk)
    if total == 0:
        raise RuntimeError(f"{url}: empty source archive")
    return h.hexdigest()


def update(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    matches = list(URL_RE.finditer(original))
    if not matches:
        raise RuntimeError(f"{path.relative_to(ROOT)}: no supported pinned pop-os source URL")
    if len(matches) != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: expected exactly one source URL")

    match = matches[0]
    repo = match.group(2)
    old_tag = match.group(3)
    tag_changed = old_tag != TAG

    new_url = f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{TAG}"
    new_sha = digest(new_url)
    content = original[:match.start()] + (
        match.group(1) + new_url + match.group(4)
    ) + original[match.end():]

    content, version_count = VERSION_RE.subn(r'\g<1>1.11.0\g<2>', content, count=1)
    if version_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: package version field not found")

    content, sha_count = SHA_RE.subn(r'\g<1>' + new_sha + r'\g<2>', content, count=1)
    if sha_count != 1:
        raise RuntimeError(f"{path.relative_to(ROOT)}: source SHA-256 field not found")

    if not REL_RE.search(content):
        raise RuntimeError(f"{path.relative_to(ROOT)}: package rel field not found")
    if tag_changed:
        content = REL_RE.sub(
            lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}",
            content,
            count=1,
        )

    if content == original:
        print(f"verified {path.relative_to(ROOT)}: {TAG}; sha256={new_sha}")
        return False

    path.write_text(content, encoding="utf-8")
    print(f"updated {path.relative_to(ROOT)}: {old_tag} -> {TAG}; sha256={new_sha}")
    return True


def main() -> int:
    if not RECIPES:
        print("no COSMIC recipes found", file=sys.stderr)
        return 1
    changed = 0
    for recipe in RECIPES:
        changed += update(recipe)
    print(f"COSMIC Epoch source update complete: {changed} recipe(s) changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
