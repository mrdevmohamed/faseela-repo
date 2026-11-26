#!/usr/bin/env python3
"""End-to-end test of the incremental schema-v5 publishing with the real `nawa`.

Needs the recipe-pinned nawa and a `zstd` program:

    NAWA_BIN=/path/to/nawa python3 -I scripts/test-publish-incremental.py

It is skipped when NAWA_BIN is not set (CI has no nawa binary; the publish
workflow exercises the same commands). Release uploads are simulated by a
fake release listing, so nothing leaves the machine.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PUBLISH = SCRIPTS / "publish-schema-v5.py"
REPO = "test/repo"
SUFFIX = ".nawa.tar.zst"


def sh(argv, **kw):
    result = subprocess.run([str(a) for a in argv], text=True, capture_output=True, **kw)
    if result.returncode:
        raise AssertionError(f"{argv[:3]} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def publish(*argv, expect_fail: str | None = None):
    result = subprocess.run([sys.executable, "-I", str(PUBLISH), *map(str, argv)], text=True, capture_output=True)
    if expect_fail is not None:
        assert result.returncode != 0 and expect_fail in result.stderr, result.stdout + result.stderr
        return result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def zstd_compress(raw: bytes) -> bytes:
    return subprocess.run(["zstd", "-q", "-c"], input=raw, capture_output=True, check=True).stdout


def make_archive(directory: Path, name: str, version: str, rel: int, payload: str = "") -> Path:
    info = (f"pkgname = {name}\npkgver = {version}\npkgrel = {rel}\narch = x86_64\nrundeps = \nprovides = \n"
            f"size = 1\nrelations_schema = 1\nconflicts = \nreplaces = \n").encode()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for member, data in ((".PKGINFO", info), (f"payload/usr/share/{name}", (payload or f"{name}-{version}").encode())):
            item = tarfile.TarInfo(member)
            item.size, item.mode = len(data), 0o644
            tar.addfile(item, io.BytesIO(data))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-{version}-{rel}{SUFFIX}"
    path.write_bytes(zstd_compress(raw.getvalue()))
    return path


def write_recipe(root: Path, name: str, version: str, rel: int) -> None:
    folder = root / "base" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "recipe.toml").write_text(
        f'[package]\nname = "{name}"\nversion = "{version}"\nrel = {rel}\n\n[depends]\nrun = []\n\n'
        "[capabilities]\nprovides = []\n\n[relations]\nschema = 1\nconflicts = []\nreplaces = []\n",
        encoding="utf-8")


class Fixture:
    def __init__(self, root: Path, nawa: Path):
        self.root, self.nawa = root, nawa
        sh([nawa, "keygen", "--out", root / "keys"])
        self.sec, self.pub = root / "keys" / "nawa.sec", root / "keys" / "nawa.pub"
        self.recipes = root / "recipes"
        self.releases: dict[str, dict[str, bytes]] = {}  # tag -> asset -> bytes
        self.round = 0

    def listing(self) -> Path:
        out = []
        for tag, assets in self.releases.items():
            out.append({"tag_name": tag, "assets": [
                {"name": n, "state": "uploaded", "digest": "sha256:" + hashlib.sha256(b).hexdigest()}
                for n, b in sorted(assets.items())]})
        path = self.root / f"releases-{self.round}.json"
        path.write_text(json.dumps([out]), encoding="utf-8")
        return path

    def wave(self, archives: list[Path], tag: str = "packages-v5-0001") -> Path:
        """What an upload job does: stage + sign, upload (simulated), derive entries and records."""
        self.round += 1
        built = self.root / f"built-{self.round}"
        built.mkdir()
        for a in archives:
            shutil.copy2(a, built / a.name)
        stage = self.root / f"stage-{self.round}"
        publish("stage-wave", "--recipes", self.recipes, "--built-dir", built, "--releases-json", self.listing(),
                "--stage-dir", stage, "--nawa", self.nawa, "--signing-key", self.sec)
        meta = self.root / "meta"
        publish("derive", "--archive-dir", stage, "--repository", REPO, "--nawa", self.nawa, "--signing-key", self.sec,
                "--out-entries", meta / f"entries-r{self.round}.toml", "--records-dir", meta / "records")
        for p in stage.iterdir():
            self.releases.setdefault(tag, {})[p.name] = p.read_bytes()
        return meta

    def update(self, meta: Path | None, base: Path | None, *, stragglers: Path | None = None,
               revision: str = "abc1234", fail: str | None = None, groups: Path | None = None) -> Path:
        self.round += 1
        out = self.root / f"out-{self.round}"
        argv = ["update", "--recipes", self.recipes, "--releases-json", self.listing(), "--nawa", self.nawa,
                "--public-key", self.pub, "--signing-key", self.sec, "--repository", REPO, "--revision", revision,
                "--records-dir", (meta or self.root / "meta") / "records", "--out-dir", out,
                "--plan", self.root / f"plan-{self.round}.json"]
        if meta:
            argv += ["--meta-dir", meta]
        if base:
            argv += ["--base-index", base]
        if stragglers:
            argv += ["--straggler-dir", stragglers]
        if groups:
            argv += ["--groups", groups]
        publish(*argv, expect_fail=fail)
        return out

    def upload_snapshot(self, out: Path) -> None:
        plan = json.loads((self.root / f"plan-{self.round}.json").read_text())
        for tag, names in plan["uploads"].items():
            for n in names:
                self.releases.setdefault(tag, {})[n] = (out / n).read_bytes()


def entries(index: Path) -> dict[str, dict]:
    return {e["file"]: e for e in tomllib.loads(index.read_text())["package"]}


def main() -> int:
    nawa_env = os.environ.get("NAWA_BIN")
    if not nawa_env:
        print("test-publish-incremental: NAWA_BIN not set, skipped")
        return 0
    if not shutil.which("zstd"):
        print("test-publish-incremental: no zstd program, skipped")
        return 0
    with tempfile.TemporaryDirectory(prefix="publish-inc-") as td:
        root = Path(td)
        fx = Fixture(root, Path(nawa_env))
        write_recipe(fx.recipes, "foo", "1.0", 1)
        write_recipe(fx.recipes, "bar", "2.0", 1)
        arch = root / "arch"

        # 1. first publication: nothing published, no base index.
        meta = fx.wave([make_archive(arch, "foo", "1.0", 1), make_archive(arch, "bar", "2.0", 1)])
        groups1 = root / "groups-1.toml"
        groups1.write_text('[[group]]\nschema = 1\nid = "tools"\nname = "Tools"\nmandatory = ["foo"]\n')
        out1 = fx.update(meta, None, groups=groups1)
        idx1 = entries(out1 / "index.toml")
        groups_ref1 = tomllib.loads((out1 / "index.toml").read_text())["groups"]
        assert groups_ref1["file"] == "groups.toml", groups_ref1
        assert groups_ref1["sha256"] == hashlib.sha256(groups1.read_bytes()).hexdigest(), groups_ref1
        assert (out1 / "groups.toml").read_bytes() == groups1.read_bytes()
        assert sorted(idx1) == ["bar-2.0-1" + SUFFIX, "foo-1.0-1" + SUFFIX], sorted(idx1)
        assert all("download_url" in e and "packages-v5-0001" in e["download_url"] for e in idx1.values())
        fx.upload_snapshot(out1)
        cat1 = root / "cat1"
        publish("catalog", "--index", out1 / "index.toml", "--records-dir", meta / "records", "--out-dir", cat1,
                "--nawa", fx.nawa, "--signing-key", fx.sec, "--public-key", fx.pub)
        assert (cat1 / "catalog.toml.sig").is_file()

        # 2. an incomplete set is refused: a recipe without a published archive.
        write_recipe(fx.recipes, "baz", "3.0", 1)
        fx.update(meta, out1 / "index.toml", fail="not published: baz-3.0-1" + SUFFIX)

        # 3. foo is bumped and baz is new; bar is NOT opened, downloaded or rebuilt.
        write_recipe(fx.recipes, "foo", "1.1", 1)
        meta2 = fx.wave([make_archive(arch, "foo", "1.1", 1), make_archive(arch, "baz", "3.0", 1)])
        groups2 = root / "groups-2.toml"
        groups2.write_text(groups1.read_text() + '\n[[group]]\nschema = 1\nid = "more"\nname = "More"\nmandatory = ["bar"]\n')
        out2 = fx.update(meta2, out1 / "index.toml", revision="def5678", groups=groups2)
        groups_ref2 = tomllib.loads((out2 / "index.toml").read_text())["groups"]
        assert groups_ref2["sha256"] == hashlib.sha256(groups2.read_bytes()).hexdigest(), "a changed catalog is republished"
        idx2 = entries(out2 / "index.toml")
        assert sorted(idx2) == ["bar-2.0-1" + SUFFIX, "baz-3.0-1" + SUFFIX, "foo-1.1-1" + SUFFIX], sorted(idx2)
        assert idx2["bar-2.0-1" + SUFFIX] == idx1["bar-2.0-1" + SUFFIX], "an untouched package entry must not change"
        fx.upload_snapshot(out2)
        cat2 = root / "cat2"
        publish("catalog", "--index", out2 / "index.toml", "--records-dir", meta2 / "records", "--base-catalog-dir", cat1,
                "--have-base-index", "--out-dir", cat2, "--nawa", fx.nawa, "--signing-key", fx.sec, "--public-key", fx.pub)
        pointer = tomllib.loads((cat2 / "catalog.toml").read_text())
        assert pointer["catalog_file"].startswith("catalog-")
        publish("catalog", "--index", out2 / "index.toml", "--records-dir", meta2 / "records", "--have-base-index",
                "--out-dir", root / "cat-nobase", "--nawa", fx.nawa, "--signing-key", fx.sec, "--public-key", fx.pub,
                expect_fail="catalog is not")

        # 4. a failed earlier run left an archive published but never indexed.
        write_recipe(fx.recipes, "qux", "4.0", 1)
        orphan_meta = fx.wave([make_archive(arch, "qux", "4.0", 1)])  # uploaded; its entries artifact is lost
        shutil.rmtree(orphan_meta)
        listing = fx.listing()
        listed_file = root / "stragglers.tsv"
        publish("stragglers", "--recipes", fx.recipes, "--releases-json", listing, "--base-index", out2 / "index.toml",
                "--nawa", fx.nawa, "--public-key", fx.pub, "--output", listed_file)
        listed = listed_file.read_text()
        assert listed.split() == ["packages-v5-0001", "qux-4.0-1" + SUFFIX, "packages-v5-0001", "qux-4.0-1" + SUFFIX + ".sig"], listed
        empty_meta = root / "empty-meta"
        (empty_meta / "records").mkdir(parents=True)
        fx.update(empty_meta, out2 / "index.toml", revision="aaa9999", fail="were not downloaded")
        downloaded = root / "downloaded"
        downloaded.mkdir()
        for name, data in fx.releases["packages-v5-0001"].items():
            if name.startswith("qux-"):
                (downloaded / name).write_bytes(data)
        out3 = fx.update(empty_meta, out2 / "index.toml", stragglers=downloaded, revision="aaa9999")
        assert "qux-4.0-1" + SUFFIX in entries(out3 / "index.toml")
        assert list((empty_meta / "records").glob("qux-*")), "the straggler's catalog record is derived from the download"
        fx.upload_snapshot(out3)

        # 5. an archive that is already published is never staged again.
        again = fx.wave([make_archive(root / "rebuilt", "qux", "4.0", 1, payload="different bytes")])
        assert not list((root / f"stage-{fx.round}").iterdir()), "published archives are immutable"
        assert not list(again.glob("entries-r%d.toml" % fx.round)) or not (again / f"entries-r{fx.round}.toml").read_text()

        # 6. a recipe leaves: its package is dropped, the rest stays; a downgrade replaces the entry.
        shutil.rmtree(fx.recipes / "base" / "bar")
        write_recipe(fx.recipes, "foo", "1.0", 1)  # downgrade back to the published 1.0
        # The older archive lost its index entry when 1.1 replaced it, so it is fetched again.
        old_dir = root / "downloaded-foo"
        old_dir.mkdir()
        for name, data in fx.releases["packages-v5-0001"].items():
            if name.startswith("foo-1.0-1"):
                (old_dir / name).write_bytes(data)
        out4 = fx.update(empty_meta, out3 / "index.toml", stragglers=old_dir, revision="bbb0000")
        idx4 = entries(out4 / "index.toml")
        assert sorted(idx4) == ["baz-3.0-1" + SUFFIX, "foo-1.0-1" + SUFFIX, "qux-4.0-1" + SUFFIX], sorted(idx4)

        # 7. a base index signed by another key is refused.
        other = root / "other"
        sh([fx.nawa, "keygen", "--out", other])
        shutil.copy2(out4 / "index.toml", other / "index.toml")
        sh([fx.nawa, "sign", other / "index.toml", "--key", other / "nawa.sec"])
        fx.update(empty_meta, other / "index.toml", revision="ccc1111", fail="command failed")
    print("incremental schema-v5 publishing: end-to-end test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
