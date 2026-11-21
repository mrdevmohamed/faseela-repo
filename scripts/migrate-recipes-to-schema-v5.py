#!/usr/bin/env python3
"""One-shot migration of every recipe to the schema-v5 recipe form.

Kept in history for review; safe to delete once the migration is merged.

For each recipe that does not declare `[relations]` yet it

  * converts the legacy `source` / `sha256` / `mirrors` / `source_dir` fields to
    one `[[package.sources]]` table (or, for recipes that already use the new
    source tables or recipe-local assets, only swaps the schema marker) and sets
    the fail-closed relations marker in `package.source`;
  * pins `source_date_epoch` where the build has no archive to derive it from
    (meta packages and recipes whose sources are all plain files);
  * adds the reviewed `[capabilities]` and `[relations]` tables;
  * bumps `rel`, because the archive metadata changes.

The legacy working directory is `src/<source_dir or name-version>` when that
directory exists after extraction and `src/` otherwise. The upstream archive
layouts, surveyed by scripts/survey-source-layout.py, decide the equivalent:

  * the legacy directory is the only top-level entry  -> strip_components = 1
    (version independent: a version bump needs no workdir edit);
  * other top-level entries exist, or it is a sub-path -> literal workdir;
  * the legacy directory does not exist (fallback)     -> workspace root;
  * not a tar stream (zip, wheel, deb, binary, data)   -> unpack = false.

Text is edited in place so comments and formatting survive. After each edit the
recipe is parsed again and every table the migration must not touch is compared
with the original.
"""
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

RELATIONS_MARKER = "local:/nawa-package-relations-1-requires-a-newer-nawa"
SCHEMA_MARKER = "local:/nawa-schema-2-requires-a-newer-nawa"
EPOCH = 1767225600  # same constant faseela-branding and containers-common already pin

HEADER = re.compile(r"^\[\[?[A-Za-z0-9_.\"-]+\]\]?\s*(#.*)?$")


def scan_tables(lines: list[str]) -> list[tuple[str, int, int]]:
    """(header, first line, end line exclusive) of every table; the preamble is ''."""
    tables = []
    current, start = "", 0
    in_ml = None
    for i, line in enumerate(lines):
        if in_ml is None and HEADER.match(line):
            tables.append((current, start, i))
            current, start = line.split("#")[0].strip(), i
            continue
        for delim in ("'''", '"""'):
            if in_ml is None:
                if line.count(delim) % 2 == 1:
                    in_ml = delim
                    break
            elif in_ml == delim and line.count(delim) % 2 == 1:
                in_ml = None
                break
    tables.append((current, start, len(lines)))
    return tables


def find_table(tables, header):
    for t in tables:
        if t[0] == header:
            return t
    return None


def source_name(package: str) -> str:
    name = re.sub(r"[^a-z0-9._-]", "-", package.lower())
    return name.strip("-._") or "src"


def toml_list(items) -> str:
    return "[" + ", ".join(json.dumps(i) for i in items) + "]"


def strip_blank_tail(block: list[str]) -> list[str]:
    while block and not block[-1].strip():
        block = block[:-1]
    return block


def layout_for(pkg: dict, record: dict | None):
    """-> (unpack, strip_components, workdir) for a legacy recipe."""
    if record is None:
        raise SystemExit(f"no layout record for {pkg['name']}")
    if record["kind"] == "plain":
        return False, 0, ""
    if record["kind"] != "tar":
        raise SystemExit(f"layout of {pkg['name']} unknown: {record.get('errors')}")
    legacy = record["legacy_dir"]
    if not record["legacy_dir_exists"] or legacy in (".", ""):
        return None, 0, ""
    # A truncated listing cannot prove the legacy directory is the only top-level
    # entry, and strip_components would merge several top directories together,
    # so those recipes get the literal (always equivalent) workdir instead.
    if record["top_count"] == 1 and record["tops"] == [legacy] and not record["truncated"]:
        return None, 1, ""
    return None, 0, legacy


def convert_text(text: str, data: dict, record: dict | None, relations: dict) -> str:
    pkg = data["package"]
    name = pkg["name"]
    lines = text.split("\n")
    tables = scan_tables(lines)
    package_tab = find_table(tables, "[package]")
    if package_tab is None:
        raise SystemExit(f"{name}: no [package] table")
    _, p_start, p_end = package_tab

    legacy = bool(pkg.get("source")) and not pkg["source"].startswith("local:") and not pkg.get("sources")
    new_sources = bool(pkg.get("sources"))
    unpack = None
    strip = 0
    workdir = ""
    if legacy:
        unpack, strip, workdir = layout_for(pkg, record)

    # ---- rewrite the [package] table ----
    body = lines[p_start:p_end]
    out = []
    moved_comments: list[str] = []
    i = 0
    pending_comments: list[str] = []
    saw_source = False
    while i < len(body):
        line = body[i]
        key = re.match(r"^([A-Za-z0-9_]+)\s*=", line)
        k = key.group(1) if key else None
        if line.lstrip().startswith("#") and k is None and out and pending_comments is not None:
            pending_comments.append(line)
            i += 1
            continue
        if k in ("sha256", "source_dir", "mirrors", "source") and legacy:
            moved_comments += pending_comments if k == "source" else []
            pending_comments = []
            if k == "mirrors":
                depth = line.count("[") - line.count("]")
                while depth > 0:
                    i += 1
                    depth += body[i].count("[") - body[i].count("]")
            if k == "source":
                saw_source = True
                out.append(f'source = "{RELATIONS_MARKER}"')
            i += 1
            continue
        if k == "source" and not legacy:
            saw_source = True
            pending_comments_flush = pending_comments
            pending_comments = []
            out += pending_comments_flush
            out.append(f'source = "{RELATIONS_MARKER}"')
            i += 1
            continue
        out += pending_comments
        pending_comments = []
        out.append(line)
        i += 1
    out += pending_comments

    # a legacy comment block that sat on the removed `source` line goes with the new table
    if legacy and not saw_source:
        raise SystemExit(f"{name}: legacy recipe without a source line")

    # meta packages: add the marker after `license`
    if not legacy and not new_sources and not saw_source:
        idx = max((n for n, l in enumerate(out) if re.match(r"^license\s*=", l)), default=None)
        if idx is None:
            idx = max(n for n, l in enumerate(out) if re.match(r"^[A-Za-z0-9_]+\s*=", l))
        out.insert(idx + 1, f'source = "{RELATIONS_MARKER}"')

    # rel bump
    bumped = False
    for n, l in enumerate(out):
        m = re.match(r"^rel\s*=\s*(\d+)\s*(#.*)?$", l)
        if m:
            out[n] = f"rel = {int(m.group(1)) + 1}" + (f"  {m.group(2)}" if m.group(2) else "")
            bumped = True
            break
    if not bumped:
        idx = max(n for n, l in enumerate(out) if re.match(r"^version\s*=", l))
        out.insert(idx + 1, "rel = 2")

    # source_date_epoch where nothing can be derived from an archive
    plain_only = (legacy and unpack is False) or (
        new_sources and all(s.get("unpack") is False for s in pkg["sources"])
    )
    needs_epoch = (not legacy and not new_sources) or plain_only
    if needs_epoch and "source_date_epoch" not in pkg:
        idx = max((n for n, l in enumerate(out) if re.match(r"^arch\s*=", l)), default=None)
        if idx is None:
            idx = max(n for n, l in enumerate(out) if re.match(r"^rel\s*=", l))
        out.insert(idx + 1, f"source_date_epoch = {EPOCH}")

    if workdir:
        idx = max(n for n, l in enumerate(out) if re.match(r"^[A-Za-z0-9_]+\s*=", l))
        out.insert(idx + 1, f"workdir = {json.dumps(workdir)}")

    out = strip_blank_tail(out)
    if legacy:
        out.append("")
        out += moved_comments
        out.append("[[package.sources]]")
        out.append(f'name = "{source_name(name)}"')
        out.append(f"url = {json.dumps(pkg['source'])}")
        out.append(f'sha256 = "{pkg["sha256"].lower()}"')
        if pkg.get("mirrors"):
            out.append("mirrors = [")
            out += [f"  {json.dumps(m)}," for m in pkg["mirrors"]]
            out.append("]")
        if unpack is False:
            out.append("unpack = false")
        if strip:
            out.append(f"strip_components = {strip}")
    out.append("")

    new_lines = lines[:p_start] + out + lines[p_end:]
    text2 = "\n".join(new_lines)

    # ---- capabilities / relations after [depends] (or after the package block) ----
    tables = scan_tables(text2.split("\n"))
    lines2 = text2.split("\n")
    anchor = find_table(tables, "[depends]")
    if anchor is None:
        # after the last table that belongs to the package block
        pkgs = [t for t in tables if t[0].startswith("[package") or t[0] == "[assets]"]
        anchor = pkgs[-1]
    _, a_start, a_end = anchor
    block = strip_blank_tail(lines2[a_start:a_end])
    provides = relations.get("provides", [])
    conflicts = relations.get("conflicts", [])
    replaces = relations.get("replaces", [])
    extra = [
        "",
        "[capabilities]",
        f"provides = {toml_list(provides)}",
        "",
        "[relations]",
        "schema = 1",
        f"conflicts = {toml_list(conflicts)}",
        f"replaces = {toml_list(replaces)}",
        "",
    ]
    lines3 = lines2[:a_start] + block + extra + lines2[a_end:]
    text3 = "\n".join(lines3)
    # keep one blank line between tables and a single trailing newline
    text3 = re.sub(r"\n{3,}(?=\[)", "\n\n", text3)
    return text3.rstrip("\n") + "\n"


def verify(old: dict, new: dict, legacy: bool, name: str) -> None:
    for table in set(old) | set(new):
        if table in ("package", "capabilities", "relations"):
            continue
        if old.get(table) != new.get(table):
            raise SystemExit(f"{name}: table [{table}] changed unexpectedly")
    op, np = old["package"], new["package"]
    for key in set(op) | set(np):
        if key in ("source", "sha256", "mirrors", "source_dir", "rel", "sources", "workdir", "source_date_epoch"):
            continue
        if op.get(key) != np.get(key):
            raise SystemExit(f"{name}: [package].{key} changed unexpectedly")
    if np["rel"] != op.get("rel", 1) + 1:
        raise SystemExit(f"{name}: rel not bumped by exactly one")
    if np["source"] != RELATIONS_MARKER:
        raise SystemExit(f"{name}: relations marker missing")
    if legacy:
        src = np["sources"]
        if len(src) != 1 or src[0]["url"] != op["source"] or src[0]["sha256"] != op["sha256"].lower():
            raise SystemExit(f"{name}: converted source differs from the original")
        if src[0].get("mirrors", []) != op.get("mirrors", []):
            raise SystemExit(f"{name}: mirrors differ")
    elif op.get("sources") != np.get("sources"):
        raise SystemExit(f"{name}: sources changed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipes", type=Path, default=Path("recipes"))
    ap.add_argument("--layout", type=Path, required=True, help="JSON from survey-source-layout.py")
    ap.add_argument("--relations", type=Path, required=True, help="JSON {package: {conflicts, replaces, provides}}")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    layout = {r["name"]: r for r in json.loads(args.layout.read_text(encoding="utf-8"))}
    decisions = json.loads(args.relations.read_text(encoding="utf-8"))
    changed = skipped = 0
    for path in sorted(args.recipes.glob("*/*/recipe.toml")):
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        name = data["package"]["name"]
        if "relations" in data:
            skipped += 1
            continue
        legacy = bool(data["package"].get("source")) and not data["package"]["source"].startswith("local:") \
            and not data["package"].get("sources")
        new_text = convert_text(text, data, layout.get(name), decisions.get(name, {}))
        try:
            new_data = tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(f"{name}: converted recipe does not parse: {exc}")
        verify(data, new_data, legacy, name)
        if args.write:
            path.write_text(new_text, encoding="utf-8")
        changed += 1
    print(f"converted {changed} recipe(s), left {skipped} that already declare [relations]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
