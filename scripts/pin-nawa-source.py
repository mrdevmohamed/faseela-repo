#!/usr/bin/env python3
"""scripts/pin-nawa-source.py — pin the `nawa` recipe to one commit of the
nawa repository (github.com/mrdevmohamed/nawa).

The recipe downloads  https://github.com/<REPO>/archive/<commit>.tar.gz  and
verifies it against a sha256. This script writes the commit, the hash, the
package version (read from the tarball's Cargo.toml) and `rel`:

    python3 scripts/pin-nawa-source.py               # commit = origin HEAD of nawa
    python3 scripts/pin-nawa-source.py <40-hex sha>  # an explicit commit

The commit must already be PUSHED to GitHub (the hash is computed from the
tarball GitHub serves). bootstrap/fetch-nawa.sh of the distribution repository
(github.com/mrdevmohamed/faseela) reads the same pin, so the bootstrap and the
recipe can never disagree about which nawa is shipped.
"""
import hashlib
import io
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "mrdevmohamed/nawa"
RECIPE = ROOT / "recipes" / "base" / "nawa" / "recipe.toml"


def sub1(text, pattern, repl, what):
    new, n = re.subn(pattern, lambda m: repl, text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"pin-nawa-source: no `{what}` line in {RECIPE}")
    return new


def main():
    if len(sys.argv) > 2 or sys.argv[1:] in (["-h"], ["--help"]):
        sys.exit(__doc__)
    if len(sys.argv) == 2:
        commit = sys.argv[1].lower()
    else:
        out = subprocess.run(["git", "ls-remote", f"https://github.com/{REPO}", "HEAD"],
                             check=True, capture_output=True, text=True).stdout
        commit = out.split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        sys.exit("pin-nawa-source: the commit must be a full 40-character sha")

    url = f"https://github.com/{REPO}/archive/{commit}.tar.gz"
    print(f"downloading {url}")
    data = urllib.request.urlopen(url, timeout=300).read()
    sha = hashlib.sha256(data).hexdigest()
    top = f"nawa-{commit}"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        cargo = tf.extractfile(f"{top}/Cargo.toml").read().decode()
    version = re.search(r'(?m)^version = "([^"]+)"', cargo).group(1)

    t = RECIPE.read_text(encoding="utf-8")
    old_ver = re.search(r'(?m)^version = "([^"]*)"', t).group(1)
    old_rel = int(re.search(r'(?m)^rel = (\d+)', t).group(1))
    source_block = re.search(r'(?ms)^\[\[package\.sources\]\]\s*\nname = "nawa"\s*\n(.*?)(?=^\[|\Z)', t)
    if not source_block:
        sys.exit(f"pin-nawa-source: no nawa source entry in {RECIPE}")
    old_sha_match = re.search(r'(?m)^sha256 = "([^"]*)"
    RECIPE.write_text(t, encoding="utf-8")
    print(f"nawa: version {version} rel {rel} -> {commit[:12]}  sha256 {sha}")


if __name__ == "__main__":
    main()
, source_block.group(1))
    if not old_sha_match:
        sys.exit(f"pin-nawa-source: no sha256 in nawa source entry in {RECIPE}")
    old_sha = old_sha_match.group(1)
    rel = 1 if old_ver != version else (old_rel if old_sha == sha else old_rel + 1)
    t = sub1(t, r'^version = ".*"
    RECIPE.write_text(t, encoding="utf-8")
    print(f"nawa: version {version} rel {rel} -> {commit[:12]}  sha256 {sha}")


if __name__ == "__main__":
    main()
, f'version = "{version}"', "version")
    t = sub1(t, r'^rel = \d+
    RECIPE.write_text(t, encoding="utf-8")
    print(f"nawa: version {version} rel {rel} -> {commit[:12]}  sha256 {sha}")


if __name__ == "__main__":
    main()
, f"rel = {rel}", "rel")
    t, n = re.subn(r'(?ms)(^\[\[package\.sources\]\]\s*\nname = "nawa"\s*\n.*?^url = ")[^"]+(")', lambda m: m.group(1) + url + m.group(2), t, count=1)
    if n != 1:
        sys.exit(f"pin-nawa-source: no url in nawa source entry in {RECIPE}")
    t, n = re.subn(r'(?ms)(^\[\[package\.sources\]\]\s*\nname = "nawa"\s*\n.*?^sha256 = ")[^"]+(")', lambda m: m.group(1) + sha + m.group(2), t, count=1)
    if n != 1:
        sys.exit(f"pin-nawa-source: no sha256 in nawa source entry in {RECIPE}")
    RECIPE.write_text(t, encoding="utf-8")
    print(f"nawa: version {version} rel {rel} -> {commit[:12]}  sha256 {sha}")


if __name__ == "__main__":
    main()
