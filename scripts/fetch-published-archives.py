#!/usr/bin/env python3
"""scripts/fetch-published-archives.py - download published package archives.

    fetch-published-archives.py --list published.tsv --repo OWNER/REPO --out DIR
                                [--jobs 4] [--index index.toml]
                                [--base-url https://github.com]

published.tsv is the output of `distributed-releases.py list`: one
`<release tag>\\t<archive name>` per line. Each archive is fetched from
<base-url>/<repo>/releases/download/<tag>/<name>.

Meant for the Phase 0 backfill job of docs/package-repository-design.md and for
any later job that needs published archives. Compared with a bare `curl` loop:

  * concurrency is capped at 4: GitHub's public release CDN answered 12-way
    fan-out with widespread HTTP 504s;
  * retries use exponential backoff with jitter and honour Retry-After, so a
    short CDN incident is not hammered again every few seconds;
  * every download goes to a .part file, is hashed while streaming and is only
    then renamed, so an interrupted run never leaves a truncated archive;
  * with --index, the sha256 and size of every archive that the index lists
    must match; a mismatch is an error and the file is not kept;
  * a failure names the asset, and all failures are reported at the end.

Re-running skips archives that are already present (they are only ever
renamed into place once complete)."""
import argparse
import email.utils
import hashlib
import os
import random
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAX_JOBS = 4
TAG_RE = re.compile(r"(packages-[0-9]{4,}|[A-Za-z0-9._-]+)\Z")
ASSET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*[.]nawa[.]tar[.]zst\Z")
REPO_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class FetchError(Exception):
    """An archive that could not be fetched or did not verify."""


class IntegrityError(FetchError):
    """The bytes arrived but are empty, truncated or not what the index says."""


def backoff_delay(attempt: int, base: float, cap: float, retry_after: float | None, rng=random) -> float:
    """Seconds to wait before retry number `attempt` (1-based)."""
    delay = min(cap, base * (2 ** (attempt - 1)))
    delay *= rng.uniform(0.5, 1.0)  # jitter: spread concurrent workers apart
    if retry_after is not None:
        delay = max(delay, min(retry_after, cap))
    return delay


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def download(url: str, dest: Path, *, attempts: int = 8, base: float = 5.0, cap: float = 120.0,
             timeout: float = 60.0, expect_sha256: str | None = None, expect_size: int | None = None,
             sleep=time.sleep, rng=random) -> str:
    """Fetch url into dest atomically; return the sha256 of what was written."""
    part = dest.with_name(f".{dest.name}.part-{os.getpid()}")
    last = "no attempt was made"
    bad_bytes = 0
    try:
        for attempt in range(1, attempts + 1):
            retry_after = None
            try:
                digest = hashlib.sha256()
                size = 0
                req = urllib.request.Request(url, headers={"User-Agent": "faseela-fetch-published-archives"})
                with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as out:
                    for chunk in iter(lambda: resp.read(1024 * 1024), b""):
                        out.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                if size == 0:
                    raise IntegrityError(f"{dest.name}: downloaded asset is empty")
                if expect_size is not None and size != expect_size:
                    raise IntegrityError(f"{dest.name}: size {size} differs from the index ({expect_size})")
                if expect_sha256 is not None and digest.hexdigest() != expect_sha256:
                    raise IntegrityError(f"{dest.name}: sha256 differs from the index")
                os.replace(part, dest)
                return digest.hexdigest()
            except IntegrityError as exc:
                # a truncated transfer is worth one more try; a repeat means the
                # published asset really differs from the index
                last = str(exc)
                bad_bytes += 1
                if bad_bytes >= 2:
                    raise
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code not in RETRYABLE_HTTP:
                    raise FetchError(f"{dest.name}: {last} from {url}") from exc
                retry_after = parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
            if attempt < attempts:
                sleep(backoff_delay(attempt, base, cap, retry_after, rng))
        raise FetchError(f"{dest.name}: gave up after {attempts} attempt(s), last error: {last}")
    finally:
        if part.exists():
            part.unlink()


def read_manifest(path: Path):
    """-> [(tag, asset)], validated like the publish workflow validates it."""
    items, seen = [], set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2 or not TAG_RE.fullmatch(parts[0]) or not ASSET_RE.fullmatch(parts[1]):
            raise FetchError(f"{path}:{lineno}: unexpected manifest line {line!r}")
        if parts[1] in seen:
            raise FetchError(f"{path}:{lineno}: duplicate archive {parts[1]!r}")
        seen.add(parts[1])
        items.append((parts[0], parts[1]))
    return items


def read_index(path: Path):
    """-> {archive file: (sha256, size)} of a repository index.toml."""
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    return {e["file"]: (e.get("sha256"), e.get("size")) for e in doc.get("package", []) if "file" in e}


def fetch_all(items, repo, out: Path, *, jobs=MAX_JOBS, index=None, base_url="https://github.com",
              log=print, **dl_kwargs):
    """-> (downloaded, skipped, failures[list of messages])."""
    out.mkdir(parents=True, exist_ok=True)
    index = index or {}
    jobs = max(1, min(jobs, MAX_JOBS))

    def one(item):
        tag, asset = item
        dest = out / asset
        sha, size = index.get(asset, (None, None))
        if dest.exists() and dest.stat().st_size > 0:
            return "skipped", None
        url = f"{base_url}/{repo}/releases/download/{tag}/{asset}"
        log(f"Downloading {asset} ({tag})")
        try:
            download(url, dest, expect_sha256=sha, expect_size=size or None, **dl_kwargs)
        except FetchError as exc:
            return "failed", str(exc)
        return "downloaded", None

    downloaded = skipped = 0
    failures = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for status, message in pool.map(one, items):
            if status == "downloaded":
                downloaded += 1
            elif status == "skipped":
                skipped += 1
            else:
                failures.append(message)
    return downloaded, skipped, failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", type=Path, required=True, dest="manifest")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=MAX_JOBS)
    ap.add_argument("--index", type=Path)
    ap.add_argument("--base-url", default="https://github.com")
    a = ap.parse_args(argv)
    if not REPO_RE.fullmatch(a.repo):
        ap.error("--repo must look like OWNER/REPO")
    if not (a.base_url.startswith("https://") or a.base_url.startswith("http://127.0.0.1")):
        ap.error("--base-url must be https:// (http:// only for 127.0.0.1)")
    if a.jobs < 1:
        ap.error("--jobs must be at least 1")
    if a.jobs > MAX_JOBS:
        print(f"Capping --jobs from {a.jobs} to {MAX_JOBS} to avoid release-CDN overload.", file=sys.stderr)
    try:
        items = read_manifest(a.manifest)
        index = read_index(a.index) if a.index else None
    except (FetchError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"fetch-published-archives: {exc}", file=sys.stderr)
        return 2
    downloaded, skipped, failures = fetch_all(items, a.repo, a.out, jobs=a.jobs, index=index,
                                              base_url=a.base_url.rstrip("/"))
    print(f"{downloaded} downloaded, {skipped} already present, {len(failures)} failed "
          f"(of {len(items)} archive(s))")
    for message in failures:
        print(f"FAILED {message}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
