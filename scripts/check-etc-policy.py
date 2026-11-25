#!/usr/bin/env python3
"""Check which /etc paths recipes write against etc-policy.toml.

    check-etc-policy.py [--recipes DIR] [--policy FILE]

Exit status 1 when a recipe writes a forbidden path, or a path the policy does
not list. Only paths a recipe spells out as `%{pkgdir}/etc/...` can be seen
here; files an upstream `make install` drops into /etc are not (they would
need an archive audit).
"""
import argparse
import fnmatch
import re
import sys
import tomllib
from pathlib import Path

# %{pkgdir}/etc, optionally followed by path components made of the characters
# recipes use (shell variables and globs included).
PATH_RE = re.compile(r"%\{pkgdir\}(/etc(?:/[A-Za-z0-9_.@+*${}\-]+)*)")
# Lines that only remove a path never put it in the archive.
REMOVAL_RE = re.compile(r"^\s*(?:\S+\s+)?rm\s")


def load_policy(path):
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    allow = data.get("allow", [])
    forbid = data.get("forbid", [])
    for kind, entries in (("allow", allow), ("forbid", forbid)):
        for entry in entries:
            if not entry.get("pattern", "").startswith("/etc/") and entry.get("pattern") != "/etc/opt":
                raise SystemExit(f"{path}: [[{kind}]] pattern {entry.get('pattern')!r} is not under /etc")
            if not entry.get("reason"):
                raise SystemExit(f"{path}: [[{kind}]] {entry['pattern']} has no reason")
    for entry in allow:
        if entry.get("category") not in {"identity", "seed", "link", "drop-in", "no-vendor-dir", "generated"}:
            raise SystemExit(f"{path}: [[allow]] {entry['pattern']} has an unknown category {entry.get('category')!r}")
    for entry in forbid:
        if not entry.get("instead"):
            raise SystemExit(f"{path}: [[forbid]] {entry['pattern']} says nothing about what to do instead")
    return allow, forbid


def recipe_paths(recipe_file):
    """Yield (line number, /etc path) for every path the recipe writes."""
    for number, line in enumerate(Path(recipe_file).read_text().splitlines(), 1):
        if line.lstrip().startswith("#") or REMOVAL_RE.match(line):
            continue
        for match in PATH_RE.finditer(line):
            yield number, match.group(1).rstrip("/")


def classify(path, allow, forbid):
    """Return ("forbidden"|"allowed"|"unlisted", entry or None)."""
    # `$svc` and friends stand for a name; the glob below must still match.
    probe = re.sub(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", "x", path)
    for entry in forbid:
        if fnmatch.fnmatchcase(probe, entry["pattern"]):
            return "forbidden", entry
    for entry in allow:
        if fnmatch.fnmatchcase(probe, entry["pattern"]):
            return "allowed", entry
    # `install -d /etc/pam.d` is fine when files below it are allowed.
    if probe == "/etc":
        return "allowed", None
    for entry in allow:
        # a directory is fine when a file inside it would be allowed
        if entry["pattern"].startswith(probe + "/") or fnmatch.fnmatchcase(probe + "/x", entry["pattern"]):
            return "allowed", entry
    return "unlisted", None


def check(recipes_dir, policy_file):
    allow, forbid = load_policy(policy_file)
    problems = []
    for recipe in sorted(Path(recipes_dir).glob("*/*/recipe.toml")):
        for number, path in recipe_paths(recipe):
            verdict, entry = classify(path, allow, forbid)
            where = f"{recipe}:{number}"
            if verdict == "forbidden":
                problems.append(f"{where}: {path} is forbidden ({entry['reason']}); use: {entry['instead']}")
            elif verdict == "unlisted":
                problems.append(
                    f"{where}: {path} is not in etc-policy.toml. Ship vendor defaults under /usr and "
                    "create machine state at install or boot; if the file really must live in /etc, "
                    "add an [[allow]] entry with the reason (docs/etc-policy.md)"
                )
    return problems


def main(argv=None):
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipes", default=str(root / "recipes"))
    parser.add_argument("--policy", default=str(root / "etc-policy.toml"))
    args = parser.parse_args(argv)
    problems = check(args.recipes, args.policy)
    for problem in problems:
        print(f"::error::{problem}" if "GITHUB_ACTIONS" in __import__("os").environ else problem)
    if problems:
        print(f"{len(problems)} /etc policy violation(s)", file=sys.stderr)
        return 1
    print("etc policy: every /etc path written by a recipe is allowed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
