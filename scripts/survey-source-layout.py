#!/usr/bin/env python3
"""TEMPORARY helper for the schema-v5 migration (delete after the conversion).

For every recipe that still uses the legacy `source` / `sha256` / `source_dir`
fields, record how the upstream file is laid out, using the same content-based
rule nawa's stager uses: a tar stream (plain, gz, xz, bz2, zst) is an archive,
anything else (zip, wheel, deb, ELF, data file) is a plain single file.

nawa's legacy working directory is `src/<source_dir>` (default
`{name}-{version}`) when that directory exists after extraction and `src/`
otherwise. The conversion script needs exactly that fact per recipe, plus
whether the legacy directory is the only top-level entry (so that
`strip_components = 1` is equivalent and survives version bumps).

Output: one `LAYOUT {json}` line per recipe on stdout and the full list in the
JSON file given with --out. Only the first MAX_MEMBERS archive members are read.
"""
import argparse
import concurrent.futures as cf
import json
import sys
import tarfile
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

MAX_MEMBERS = 40000
TIMEOUT = 90
RETRIES = 3
HEADERS = {"User-Agent": "faseela-schema-v5-survey/1"}


def expand(text: str, pkg: dict) -> str:
    return (
        text.replace("%{version}", pkg["version"])
        .replace("%{name}", pkg["name"])
        .replace("%{rel}", str(pkg.get("rel", 1)))
        .replace("%{arch}", "x86_64")
    )


def candidate_urls(pkg: dict) -> list[str]:
    urls = [expand(pkg["source"], pkg)]
    urls += [expand(m, pkg) for m in pkg.get("mirrors", [])]
    for url in list(urls):
        for prefix in ("https://ftp.gnu.org/gnu/", "https://ftpmirror.gnu.org/gnu/"):
            if url.startswith(prefix):
                rest = url[len(prefix):]
                urls += ["https://mirrors.kernel.org/gnu/" + rest, "https://ftpmirror.gnu.org/gnu/" + rest]
    seen, out = set(), []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def components(name: str) -> list[str]:
    parts = [p for p in name.split("/") if p not in ("", ".")]
    return parts


def probe(url: str, legacy_dir: str) -> dict:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        try:
            tar = tarfile.open(fileobj=resp, mode="r|*")
        except tarfile.ReadError:
            return {"kind": "plain"}
        tops: dict[str, bool] = {}
        legacy_parts = components(legacy_dir)
        legacy_exists = False
        seen = 0
        truncated = False
        for member in tar:
            parts = components(member.name)
            if not parts:
                continue
            seen += 1
            top = parts[0]
            tops[top] = tops.get(top, False) or len(parts) > 1 or member.isdir()
            if legacy_parts and parts[: len(legacy_parts)] == legacy_parts:
                if len(parts) > len(legacy_parts) or member.isdir():
                    legacy_exists = True
            if seen >= MAX_MEMBERS:
                truncated = True
                break
        tar.close()
        names = sorted(tops)
        return {
            "kind": "tar",
            "tops": names[:12],
            "top_count": len(names),
            "top_dirs": sorted(n for n, is_dir in tops.items() if is_dir)[:12],
            "legacy_dir_exists": legacy_exists,
            "members_seen": seen,
            "truncated": truncated,
        }


def survey(path: Path, pkg: dict) -> dict:
    legacy_dir = expand(pkg.get("source_dir") or "%{name}-%{version}", pkg)
    record = {
        "name": pkg["name"],
        "path": str(path),
        "legacy_dir": legacy_dir,
        "explicit_source_dir": bool(pkg.get("source_dir")),
    }
    errors = []
    for url in candidate_urls(pkg):
        for attempt in range(RETRIES):
            try:
                record.update(probe(url, legacy_dir))
                record["url"] = url
                return record
            except (urllib.error.URLError, OSError, tarfile.TarError, EOFError) as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
                if isinstance(exc, urllib.error.HTTPError) and exc.code in (403, 404, 410):
                    break
                time.sleep(2 * (attempt + 1))
    record["kind"] = "error"
    record["errors"] = errors[-4:]
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipes", type=Path, default=Path("recipes"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=12)
    args = parser.parse_args()

    work = []
    for path in sorted(args.recipes.glob("*/*/recipe.toml")):
        pkg = tomllib.loads(path.read_text(encoding="utf-8"))["package"]
        source = pkg.get("source", "")
        if pkg.get("sources") or not source or source.startswith("local:"):
            continue
        work.append((path, pkg))

    results = []
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(survey, path, pkg) for path, pkg in work]
        for future in cf.as_completed(futures):
            record = future.result()
            results.append(record)
            print("LAYOUT " + json.dumps(record, sort_keys=True), flush=True)

    results.sort(key=lambda r: r["path"])
    args.out.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    kinds = {}
    for record in results:
        kinds[record["kind"]] = kinds.get(record["kind"], 0) + 1
    print(f"SURVEY-SUMMARY recipes={len(results)} kinds={kinds}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
