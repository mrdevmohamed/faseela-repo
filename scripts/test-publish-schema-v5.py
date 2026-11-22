#!/usr/bin/env python3
"""Offline acceptance tests for schema-v5 candidate validation."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("publish-schema-v5.py")
SPEC = importlib.util.spec_from_file_location("publish_schema_v5", SCRIPT)
PUBLISHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISHER)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recipe(root: Path, name: str = "alpha", *, complete: bool = True) -> Path:
    directory = root / "base" / name
    directory.mkdir(parents=True)
    extra = "\n[depends]\nrun = []\n\n[capabilities]\nprovides = []\n\n[relations]\nschema = 1\nconflicts = []\nreplaces = []\n" if complete else ""
    path = directory / "recipe.toml"
    path.write_text(f'[package]\nname = "{name}"\nversion = "1.0"\nrel = 1\n{extra}', encoding="utf-8")
    return path


def expect_error(call, message: str) -> None:
    try:
        call()
    except PUBLISHER.PublishError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError(f"expected PublishError containing {message!r}")


def setup_nawa(root: Path) -> Path:
    nawa = root / "nawa-test-double"
    nawa.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args[0] == 'sign':\n"
        " p = pathlib.Path(args[1]); pathlib.Path(str(p)+'.sig').write_text(hashlib.sha256(p.read_bytes()).hexdigest())\n"
        "elif args[0] == 'verify':\n"
        " p = pathlib.Path(args[1]); s = pathlib.Path(str(p)+'.sig')\n"
        " if not p.is_file() or not s.is_file() or s.read_text() != hashlib.sha256(p.read_bytes()).hexdigest(): sys.exit(1)\n"
        "else: sys.exit(2)\n",
        encoding="utf-8",
    )
    nawa.chmod(0o755)
    return nawa


def make_index(archive_dir: Path, filename: str, *, package_name: str = "alpha") -> None:
    archive = archive_dir / filename
    recipe_snapshot = archive_dir / "recipes-test.recipes.tar.zst"
    recipe_snapshot.write_bytes(b"snapshot")
    index = archive_dir / "index.toml"
    index.write_text(
        "[repository]\nschema = 5\n\n"
        f"[recipes]\nfile = \"{recipe_snapshot.name}\"\n"
        f"sha256 = \"{digest(recipe_snapshot)}\"\nsize = {recipe_snapshot.stat().st_size}\n"
        f"download_url = \"https://example.invalid/{recipe_snapshot.name}\"\n\n"
        "[[package]]\n"
        f"name = \"{package_name}\"\nversion = \"1.0\"\nrel = 1\n"
        "arch = \"x86_64\"\n"
        f"file = \"{filename}\"\nsha256 = \"{digest(archive)}\"\nsize = {archive.stat().st_size}\n"
        "rundeps = []\nprovides = []\nrelations = { schema = 1, conflicts = [], replaces = [] }\n",
        encoding="utf-8",
    )
    for path in (archive, recipe_snapshot, index):
        (archive_dir / f"{path.name}.sig").write_text(digest(path), encoding="utf-8")


def make_v3_index(path: Path, archive: bytes, *, url: str | None = None) -> str:
    filename = "alpha-1.0-1.nawa.tar.zst"
    download_url = url or (
        "https://github.com/test/repo/releases/download/packages-0001/" + filename
    )
    path.write_text(
        "[repository]\nschema = 3\narchive_location = \"per-package-url\"\n"
        "archive_auth = \"signed-index\"\nhash_algorithm = \"sha256\"\n"
        "index_signature = \"nawa-sig-v1\"\n\n"
        "[[package]]\nname = \"alpha\"\nversion = \"1.0\"\nrel = 1\n"
        "arch = \"x86_64\"\n"
        f"file = \"{filename}\"\nsha256 = \"{hashlib.sha256(archive).hexdigest()}\"\n"
        f"size = {len(archive)}\ndownload_url = \"{download_url}\"\n",
        encoding="utf-8",
    )
    signature = path.with_name(path.name + ".sig")
    signature.write_text(digest(path), encoding="utf-8")
    return filename


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="publish-v5-tests-") as td:
        root = Path(td)
        recipes_root = root / "recipes"
        recipe(recipes_root)
        recipe_map = PUBLISHER.recipes(recipes_root)

        # The recipe model defaults omitted depends.run to [], and Nawa writes
        # that resolved empty list to archive .PKGINFO as rundeps = "".
        default_run_root = root / "default-run"
        default_run_path = recipe(default_run_root, "default-run")
        default_run_text = default_run_path.read_text(encoding="utf-8")
        default_run_path.write_text(
            default_run_text.replace("\n[depends]\nrun = []\n", ""),
            encoding="utf-8",
        )
        assert "default-run-1.0-1.nawa.tar.zst" in PUBLISHER.recipes(default_run_root)

        filename = "alpha-1.0-1.nawa.tar.zst"
        archive_dir = root / "archives"
        archive_dir.mkdir()
        (archive_dir / filename).write_bytes(b"signed package bytes")

        # Capabilities and relations must be explicit; runtime dependencies
        # default to [] in Nawa and are always serialized into the archive.
        assert len(PUBLISHER.audit_archives(recipe_map, archive_dir)) == 1
        expect_error(lambda: PUBLISHER.audit_archives(recipe_map, root / "missing"), "does not exist")
        incomplete = root / "incomplete"
        incomplete.mkdir()
        expect_error(lambda: PUBLISHER.audit_archives(recipe_map, incomplete), "missing recipe archives")
        (archive_dir / "alpha-0.9-1.nawa.tar.zst").write_bytes(b"stale")
        expect_error(lambda: PUBLISHER.audit_archives(recipe_map, archive_dir), "stale or non-recipe archives")
        (archive_dir / "alpha-0.9-1.nawa.tar.zst").unlink()

        missing_declarations = root / "missing-declarations"
        recipe(missing_declarations, complete=False)
        expect_error(lambda: PUBLISHER.recipes(missing_declarations), "schema-v5 recipe declaration problem")

        # Stage the exact current package set from a build directory with old leftovers.
        build_dir = root / "build"
        build_dir.mkdir()
        (build_dir / filename).write_bytes(b"current")
        (build_dir / "alpha-0.9-1.nawa.tar.zst").write_bytes(b"stale")
        staged = root / "staged"
        assert [p.name for p in PUBLISHER.stage_archives(recipe_map, build_dir, staged)] == [filename]

        # Split archives bind to their recipe parent and exact current version.
        split_name = "alpha-doc-1.0-1.nawa.tar.zst"
        split_entry = {"file": split_name, "name": "alpha-doc", "version": "1.0", "rel": 1}
        PUBLISHER.validate_index_identities(recipe_map, [archive_dir / split_name], {split_name: split_entry})
        stale_split_name = "alpha-doc-0.9-1.nawa.tar.zst"
        split_entry["file"] = stale_split_name
        split_entry["version"] = "0.9"
        expect_error(
            lambda: PUBLISHER.validate_index_identities(
                recipe_map, [archive_dir / stale_split_name], {stale_split_name: split_entry}
            ),
            "split archive has no matching current recipe identity",
        )

        # Generated index coverage, identity, archive/index digest, and signatures are all checked.
        nawa = setup_nawa(root)
        key = root / "nawa.pub"
        key.write_text("test public key", encoding="utf-8")
        valid_dir = root / "valid-index"
        valid_dir.mkdir()
        (valid_dir / filename).write_bytes(b"signed package bytes")
        make_index(valid_dir, filename)
        PUBLISHER.verify_index(valid_dir, nawa, key, recipe_map)

        (valid_dir / f"{filename}.sig").write_text("incorrect", encoding="utf-8")
        expect_error(lambda: PUBLISHER.verify_index(valid_dir, nawa, key, recipe_map), "command failed")
        make_index(valid_dir, filename, package_name="beta")
        expect_error(
            lambda: PUBLISHER.verify_index(valid_dir, nawa, key, recipe_map),
            "archive/index identity differs",
        )
        make_index(valid_dir, filename)
        index = valid_dir / "index.toml"
        index.write_text("package = []\n\n" + index.read_text(encoding="utf-8").split("[[package]]\n")[0], encoding="utf-8")
        (valid_dir / "index.toml.sig").write_text(digest(index), encoding="utf-8")
        expect_error(lambda: PUBLISHER.verify_index(valid_dir, nawa, key, recipe_map), "index/archive membership differs")

        # Reused immutable archives require matching bytes and valid signatures remotely and locally.
        local_dir = root / "reused-local"
        remote_dir = root / "reused-remote" / "packages-v5-0001"
        local_dir.mkdir()
        remote_dir.mkdir(parents=True)
        remote = remote_dir / filename
        remote.write_bytes(b"same bytes")
        remote_sig = remote_dir / f"{filename}.sig"
        remote_sig.write_text(digest(remote), encoding="utf-8")
        (local_dir / filename).write_bytes(remote.read_bytes())
        (local_dir / f"{filename}.sig").write_text(remote_sig.read_text(encoding="utf-8"), encoding="utf-8")
        plan = root / "plan.json"
        plan.write_text(json.dumps({"reused": [{"tag": "packages-v5-0001", "name": filename}]}), encoding="utf-8")
        PUBLISHER.verify_reused(plan, local_dir, root / "reused-remote", nawa, key)
        remote_sig.write_text("bad", encoding="utf-8")
        expect_error(lambda: PUBLISHER.verify_reused(plan, local_dir, root / "reused-remote", nawa, key), "immutable release asset differs")
        remote_sig.unlink()
        expect_error(lambda: PUBLISHER.verify_reused(plan, local_dir, root / "reused-remote", nawa, key), "missing or empty")

        # Source archives are selected by exact recipe identity, authenticated
        # by the v3 index signature and checked against its digest and size.
        source_bytes = b"authenticated schema-v3 archive"
        v3_index = root / "v3-index.toml"
        v3_name = make_v3_index(v3_index, source_bytes)
        fetched_dir = root / "fetched-v3"
        real_urlopen = PUBLISHER.urlopen
        PUBLISHER.urlopen = lambda url, timeout: io.BytesIO(source_bytes)
        try:
            fetched = PUBLISHER.fetch_v3(
                v3_index, fetched_dir, recipes_root, nawa, key, "test/repo"
            )
        finally:
            PUBLISHER.urlopen = real_urlopen
        assert [item.name for item in fetched] == [v3_name]
        assert (fetched_dir / v3_name).read_bytes() == source_bytes

        bad_url_index = root / "v3-bad-url.toml"
        make_v3_index(
            bad_url_index,
            source_bytes,
            url="https://attacker.example/packages-0001/alpha-1.0-1.nawa.tar.zst",
        )
        expect_error(
            lambda: PUBLISHER.fetch_v3(
                bad_url_index, root / "bad-url-output", recipes_root, nawa, key, "test/repo"
            ),
            "unsafe or unexpected archive URL",
        )

        bad_bytes_index = root / "v3-bad-bytes.toml"
        make_v3_index(bad_bytes_index, source_bytes)
        PUBLISHER.urlopen = lambda url, timeout: io.BytesIO(b"tampered archive")
        try:
            expect_error(
                lambda: PUBLISHER.fetch_v3(
                    bad_bytes_index, root / "bad-bytes-output", recipes_root, nawa, key, "test/repo"
                ),
                "downloaded archive differs from signed schema-v3 index",
            )
        finally:
            PUBLISHER.urlopen = real_urlopen
        assert not list((root / "bad-bytes-output").iterdir())

        oversized_index = root / "v3-oversized.toml"
        make_v3_index(oversized_index, source_bytes)
        PUBLISHER.urlopen = lambda url, timeout: io.BytesIO(source_bytes + b"extra")
        try:
            expect_error(
                lambda: PUBLISHER.fetch_v3(
                    oversized_index, root / "oversized-output", recipes_root, nawa, key, "test/repo"
                ),
                "download exceeds signed index size",
            )
        finally:
            PUBLISHER.urlopen = real_urlopen
        assert not list((root / "oversized-output").iterdir())

        print("schema-v5 publisher acceptance tests: passed")


if __name__ == "__main__":
    main()
