#!/usr/bin/env python3
"""Split a package build into dependency-ordered waves of parallel shards.

A single runner has a hard 6 h limit and every package after the slowest one
waits in one long queue, so a full build cannot finish in one job. This planner
turns the selected package list into

    wave 0   Bootstrap Toolchain targets (only when selected)
    wave 1.. packages cut at dependency-level boundaries; the packages of one
             wave are split into shards that GitHub runs in parallel

Rules that keep the result correct, not merely fast:

  * a package is only in a wave after every selected package it depends on
    (build OR run) is in an earlier wave or in the same shard, so a shard never
    needs another shard of its own wave;
  * packages of one wave that depend on each other (directly or through a
    chain inside the wave) always share a shard (connected components);
  * packages whose archive already exists (published, or in the pull request
    cache with a matching build key) are not planned at all;
  * each shard lists the archives it needs from outside (`needs`: every
    transitive dependency, selected or not) so it downloads only those, and
    the selected dependencies built by earlier waves (`waits`) so a shard can
    skip a package whose dependency failed instead of compiling it again.

Subcommands:
  plan      recipes + selection -> plan.json
  emit      plan.json -> $GITHUB_OUTPUT lines (one matrix per wave)
  assets    archive file names of the given packages (what a shard downloads)
  runnable  inside a shard: which of its packages may still be built
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

MAX_WAVES = 8
DEFAULT_MINUTES = 0.4
SETUP_MINUTES = 8.0  # rootfs download + build root preparation of every shard


class PlanError(Exception):
    pass


def load_recipes(root: Path) -> dict[str, dict]:
    recipes: dict[str, dict] = {}
    for path in sorted(root.glob("*/*/recipe.toml")):
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
            pkg = doc["package"]
            name = str(pkg["name"])
        except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
            raise PlanError(f"cannot read {path}: {exc}") from exc
        depends = doc.get("depends", {}) if isinstance(doc.get("depends"), dict) else {}
        deps: set[str] = set()
        for key in ("build", "run"):
            value = depends.get(key, [])
            for item in [value] if isinstance(value, str) else value:
                # "base-files >= 0.4-12": only the package name identifies a recipe
                match = re.match(r"[A-Za-z0-9][A-Za-z0-9._+-]*", str(item).strip())
                if match:
                    deps.add(match.group(0))
        deps.discard(name)
        recipes[name] = {
            "name": name,
            "category": path.parent.parent.name,
            "stem": f"{name}-{pkg['version']}-{pkg.get('rel', 1)}",
            "deps": deps,
            "relations": "relations" in doc,
        }
    return recipes


def closure(recipes: dict[str, dict], names: set[str]) -> set[str]:
    """Transitive build+run dependencies of `names` (not the names themselves)."""
    seen: set[str] = set()
    stack = [d for n in names if n in recipes for d in recipes[n]["deps"]]
    while stack:
        item = stack.pop()
        if item in seen:
            continue
        seen.add(item)
        if item in recipes:
            stack.extend(recipes[item]["deps"])
    return seen - names


def levels(todo: set[str], tdeps: dict[str, set[str]]) -> dict[str, int]:
    """Dependency level inside the todo graph (0 = depends on no todo package).

    `tdeps` holds the TRANSITIVE todo dependencies, so a chain through an
    up-to-date package (A -> done B -> C) still puts C before A."""
    result: dict[str, int] = {}
    active: set[str] = set()

    def visit(name: str) -> int:
        if name in result:
            return result[name]
        if name in active:  # a cycle is reported by recipe checks; do not loop
            return 0
        active.add(name)
        value = 1 + max((visit(d) for d in tdeps[name]), default=-1)
        active.discard(name)
        result[name] = value
        return value

    for name in sorted(todo):
        visit(name)
    return result


def split_waves(by_level: dict[int, list[str]], cost: dict[str, float], max_waves: int,
                max_levels: int | None = None) -> list[list[str]]:
    """Cut the level sequence into at most `max_waves` waves.

    A wave is closed after `max_levels` dependency levels (packages of one wave
    that depend on each other must share a shard, so shallow waves parallelize
    better; by default as few levels per wave as the wave limit allows) or when it holds its share of the total cost. The last wave takes
    whatever is left, so deep graphs still fit the fixed number of wave jobs."""
    ordered = sorted(by_level)
    if max_levels is None:
        # As shallow as the wave limit allows: with few levels every level is
        # its own wave (a chain A -> B -> C must not collapse into one serial shard).
        max_levels = max(1, math.ceil(len(ordered) / max_waves))
    total = sum(cost[n] for lv in ordered for n in by_level[lv])
    waves: list[list[str]] = []
    current: list[str] = []
    taken = 0
    acc = 0.0
    for index, lv in enumerate(ordered):
        current.extend(by_level[lv])
        taken += 1
        acc += sum(cost[n] for n in by_level[lv])
        more_levels = index + 1 < len(ordered)
        if not more_levels or len(waves) + 1 >= max_waves:
            continue
        # Spread the remaining levels over the remaining waves.
        left_levels = len(ordered) - index - 1
        left_waves = max_waves - len(waves) - 1
        fair = math.ceil(left_levels / left_waves) if left_waves else left_levels
        if taken >= max_levels or (acc >= total / max_waves and taken >= 1 and left_levels >= left_waves):
            waves.append(current)
            current, taken, acc = [], 0, 0.0
    if current:
        waves.append(current)
    return waves


def components(wave: list[str], recipes: dict[str, dict]) -> list[list[str]]:
    """Packages of a wave tied together by dependencies (directly or transitively)."""
    members = set(wave)
    parent = {n: n for n in wave}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Link through the FULL closure: A -> (unselected) B -> C joins A and C too,
    # because A's shard would otherwise try to build C's dependent chain itself.
    for name in wave:
        for dep in closure(recipes, {name}) & members:
            parent[find(name)] = find(dep)
    groups: dict[str, list[str]] = defaultdict(list)
    for name in wave:
        groups[find(name)].append(name)
    return [sorted(g) for g in groups.values()]


def pack(groups: list[list[str]], cost: dict[str, float], shard_minutes: float, max_shards: int) -> list[list[str]]:
    weights = [(sum(cost[n] for n in g), g) for g in groups]
    weights.sort(key=lambda item: (-item[0], item[1]))
    total = sum(w for w, _ in weights)
    count = max(1, min(max_shards, len(weights), math.ceil(total / shard_minutes)))
    bins: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(count)]
    for weight, group in weights:
        index = min(range(count), key=lambda i: (bins[i][0], i))
        bins[index] = (bins[index][0] + weight, bins[index][1] + group)
    shards = [sorted(names) for _, names in bins if names]
    shards.sort(key=lambda names: names[0])
    return shards


def plan(
    recipes: dict[str, dict],
    selected: list[str],
    toolchain: list[str],
    done_stems: set[str],
    published_stems: set[str],
    minutes: dict[str, float],
    max_waves: int = MAX_WAVES,
    shard_minutes: float = 60.0,
    max_shards: int = 8,
) -> dict:
    unknown = sorted(n for n in [*selected, *toolchain] if n not in recipes)
    if unknown:
        raise PlanError("selected package(s) have no recipe: " + ", ".join(unknown))

    todo: set[str] = set()
    done: list[str] = []
    for name in sorted(set(selected)):
        recipe = recipes[name]
        stem = recipe["stem"]
        if stem in published_stems or stem in done_stems:
            done.append(name)
        else:
            todo.add(name)

    cost = {n: float(minutes.get(n, DEFAULT_MINUTES)) for n in todo}
    todo_deps_cache = {n: closure(recipes, {n}) & todo for n in todo}
    by_level: dict[int, list[str]] = defaultdict(list)
    for name, level in levels(todo, todo_deps_cache).items():
        by_level[level].append(name)
    waves = split_waves(by_level, cost, max_waves) if todo else []

    out_waves: list[list[dict]] = []
    for number, wave in enumerate(waves, start=1):
        shards = []
        for index, names in enumerate(pack(components(wave, recipes), cost, shard_minutes, max_shards), start=1):
            members = set(names)
            needs = sorted(closure(recipes, members))
            waits = sorted(set().union(*(todo_deps_cache[n] for n in names)) - members)
            shards.append({
                "id": f"w{number}s{index}",
                "wave": number,
                "pkgs": " ".join(names),
                "count": len(names),
                "est_min": round(sum(cost[n] for n in names) + SETUP_MINUTES),
                "needs": " ".join(needs),
                "waits": " ".join(waits),
            })
        out_waves.append(shards)

    # Bootstrap takes about an hour: when the repository already publishes the
    # archive of every requested Toolchain package, wave 0 is not repeated
    # (later waves still install those archives).
    toolchain_done = bool(toolchain) and all(
        recipes[n]["stem"] in done_stems or recipes[n]["stem"] in published_stems for n in set(toolchain))

    return {
        "schema": 1,
        "toolchain": " ".join(sorted(set(toolchain))),
        "toolchain_done": toolchain_done,
        "todo": sorted(todo),
        "done": done,
        "waves": out_waves,
    }


def read_names(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().split("\t")[-1]
        if line:
            result.add(line.removesuffix(".nawa.tar.zst"))
    return result


def cmd_plan(args) -> int:
    recipes = load_recipes(args.recipes)
    minutes: dict[str, float] = {}
    if args.times and args.times.is_file():
        minutes = {k: float(v) for k, v in json.loads(args.times.read_text(encoding="utf-8")).items()
                   if not k.startswith("_")}
    result = plan(
        recipes, args.pkgs.split(), args.toolchain_pkgs.split(),
        read_names(args.cache_valid), read_names(args.published),
        minutes, args.max_waves, args.shard_minutes, args.max_shards,
    )
    args.output.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    shards = [s for wave in result["waves"] for s in wave]
    print(f"plan: {len(result['todo'])} to build, {len(result['done'])} up to date, "
          f"{len(result['waves'])} wave(s), {len(shards)} shard(s)"
          + (f", toolchain: {result['toolchain']}" if result["toolchain"] else ""))
    return 0


def matrix(shards: list[dict]) -> str:
    return json.dumps({"include": shards}, separators=(",", ":"), sort_keys=True)


def cmd_emit(args) -> int:
    value = json.loads(args.plan.read_text(encoding="utf-8"))
    lines = []
    toolchain = []
    if value["toolchain"] and not value.get("toolchain_done"):
        toolchain = [{"id": "tc", "wave": 0, "pkgs": "", "count": 0, "est_min": 0,
                      "needs": "", "waits": "", "toolchain": value["toolchain"]}]
    lines.append(f"wave0={matrix(toolchain)}")
    lines.append(f"wave0_count={len(toolchain)}")
    for number in range(1, MAX_WAVES + 1):
        shards = value["waves"][number - 1] if number <= len(value["waves"]) else []
        lines.append(f"wave{number}={matrix(shards)}")
        lines.append(f"wave{number}_count={len(shards)}")
    lines.append(f"todo={' '.join(value['todo'])}")
    lines.append(f"todo_count={len(value['todo'])}")
    lines.append(f"toolchain_done={'true' if value.get('toolchain_done') else 'false'}")
    text = "\n".join(lines) + "\n"
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as stream:
            stream.write(text)
    else:
        sys.stdout.write(text)
    return 0


def cmd_summary(args) -> int:
    value = json.loads(args.plan.read_text(encoding="utf-8"))
    print("### Build plan")
    print(f"- To build: **{len(value['todo'])}**; already up to date: **{len(value['done'])}**")
    if value["toolchain"]:
        state = "already in the build cache, not repeated" if value.get("toolchain_done") else "built first"
        print(f"- Bootstrap Toolchain (wave 0, {state}): `{value['toolchain']}`")
    for number, shards in enumerate(value["waves"], start=1):
        print(f"- Wave {number}: {sum(s['count'] for s in shards)} package(s) in {len(shards)} parallel shard(s)")
        for shard in shards:
            preview = " ".join(shard["pkgs"].split()[:8]) + (" …" if shard["count"] > 8 else "")
            print(f"  - `{shard['id']}` ~{shard['est_min']} min, {shard['count']} package(s): {preview}")
    return 0


def cmd_assets(args) -> int:
    """Archive file names (main + doc + lang split) of the named packages."""
    recipes = load_recipes(args.recipes)
    for name in sorted(set(args.names.split())):
        recipe = recipes.get(name)
        if recipe is None:
            continue  # not a recipe of this repository: nothing to fetch for it
        stem = recipe["stem"]
        version_rel = stem[len(name) + 1:]
        for file in (stem, f"{name}-doc-{version_rel}", f"{name}-lang-{version_rel}"):
            print(f"{file}.nawa.tar.zst")
    return 0


def cmd_runnable(args) -> int:
    recipes = load_recipes(args.recipes)
    shard = args.pkgs.split()
    waits = set(args.waits.split())
    available = {p.name.removesuffix(".nawa.tar.zst") for p in args.out_dir.glob("*.nawa.tar.zst")}
    todo = set(shard) | waits
    blocked: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for name in shard:
            if name in blocked:
                continue
            for dep in sorted(closure(recipes, {name}) & todo):
                missing = dep in blocked or (dep in waits and recipes[dep]["stem"] not in available)
                if missing:
                    blocked[name] = dep
                    changed = True
                    break
    runnable = [n for n in shard if n not in blocked]
    if args.report:
        with args.report.open("a", encoding="utf-8") as stream:
            for name, dep in sorted(blocked.items()):
                stream.write(f"SKIPPED  {recipes[name]['stem']} (dependency {dep} was not built)\n")
    for name, dep in sorted(blocked.items()):
        print(f"::warning::skipping {name}: dependency {dep} was not built by an earlier wave", file=sys.stderr)
    print(" ".join(runnable))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--recipes", type=Path, required=True)
    p.add_argument("--pkgs", default="")
    p.add_argument("--toolchain-pkgs", default="")
    p.add_argument("--published", type=Path, help="published archive list (one `tag<TAB>asset` or asset per line)")
    p.add_argument("--cache-valid", type=Path, help="extra stems to treat as up to date (optional)")
    p.add_argument("--times", type=Path, help="JSON {package: minutes} for the slow packages")
    p.add_argument("--max-waves", type=int, default=MAX_WAVES)
    p.add_argument("--shard-minutes", type=float, default=25.0)
    p.add_argument("--max-shards", type=int, default=8)
    p.add_argument("--output", type=Path, required=True)

    e = sub.add_parser("emit")
    e.add_argument("--plan", type=Path, required=True)
    e.add_argument("--github-output", type=Path)

    s = sub.add_parser("summary")
    s.add_argument("--plan", type=Path, required=True)

    a = sub.add_parser("assets")
    a.add_argument("--recipes", type=Path, required=True)
    a.add_argument("--names", default="")

    r = sub.add_parser("runnable")
    r.add_argument("--recipes", type=Path, required=True)
    r.add_argument("--pkgs", required=True)
    r.add_argument("--waits", default="")
    r.add_argument("--out-dir", type=Path, required=True)
    r.add_argument("--report", type=Path)

    args = parser.parse_args(argv)
    if getattr(args, "max_waves", 1) > MAX_WAVES or getattr(args, "max_waves", 1) < 1:
        parser.error(f"--max-waves must be 1..{MAX_WAVES} (the workflow has {MAX_WAVES} wave jobs)")
    try:
        return {"plan": cmd_plan, "emit": cmd_emit, "summary": cmd_summary, "assets": cmd_assets, "runnable": cmd_runnable}[args.command](args)
    except (PlanError, OSError, ValueError, KeyError) as exc:
        print(f"::error::plan-build-shards: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
