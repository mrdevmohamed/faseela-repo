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

        # Split archives bind to their recipe parent and exact current version.
        split_name = "alpha-doc-1.0-1.nawa.tar.zst"
        split_entry = {"file": split_name, "name": "alpha-doc", "version": "1.0", "rel": 1}
        PUBLISHER.validate_index_identities(recipe_map, {split_name: split_entry})
        stale_split_name = "alpha-doc-0.9-1.nawa.tar.zst"
        split_entry["file"] = stale_split_name
        split_entry["version"] = "0.9"
        expect_error(
            lambda: PUBLISHER.validate_index_identities(recipe_map, {stale_split_name: split_entry}),
            "split archive has no matching current recipe identity",
        )
        stale_main = {"file": "alpha-0.9-1.nawa.tar.zst", "name": "alpha", "version": "0.9", "rel": 1}
        expect_error(
            lambda: PUBLISHER.validate_index_identities(recipe_map, {stale_main["file"]: stale_main}),
            "split archive has no matching current recipe identity",
        )

        nawa = setup_nawa(root)
        key = root / "nawa.pub"
        key.write_text("test public key", encoding="utf-8")

        # Planning the delta against the previous signed index.
        two = root / "two-recipes"
        recipe(two, "alpha")
        recipe(two, "beta")
        pair = PUBLISHER.recipes(two)
        alpha, beta = "alpha-1.0-1.nawa.tar.zst", "beta-1.0-1.nawa.tar.zst"
        alpha_doc = "alpha-doc-1.0-1.nawa.tar.zst"
        expect_error(
            lambda: PUBLISHER.plan_delta(pair, {}, {alpha: "packages-v5-0001"}, {}),
            "not published: " + beta,
        )
        published = {alpha: "packages-v5-0001", beta: "packages-v5-0001", alpha_doc: "packages-v5-0001"}
        delta = PUBLISHER.plan_delta(pair, {}, published, {alpha: "x", beta: "y"})
        assert delta.needed == [alpha, alpha_doc, beta] and delta.stragglers == [alpha_doc], vars(delta)
        base = {
            alpha: {"name": "alpha", "file": alpha},
            beta: {"name": "beta", "file": beta},
            "alpha-0.9-1.nawa.tar.zst": {"name": "alpha-old", "file": "alpha-0.9-1.nawa.tar.zst"},
            "gone-1.0-1.nawa.tar.zst": {"name": "gone", "file": "gone-1.0-1.nawa.tar.zst"},
        }
        delta = PUBLISHER.plan_delta(pair, base, published, {})
        assert delta.needed == [alpha_doc] and delta.stragglers == [alpha_doc]
        assert delta.remove == ["alpha-0.9-1.nawa.tar.zst", "gone-1.0-1.nawa.tar.zst"]
        assert delta.drop == ["alpha-old", "gone"], delta.drop
        # a replaced package is removed but not dropped
        replaced = {"alpha-0.9-1.nawa.tar.zst": {"name": "alpha", "file": "alpha-0.9-1.nawa.tar.zst"}}
        delta = PUBLISHER.plan_delta(pair, replaced, published, {})
        assert delta.remove == ["alpha-0.9-1.nawa.tar.zst"] and "alpha" not in delta.drop

        # Index entries are split into blocks and lose their download URL.
        text = (
            '[repository]\nschema = 5\n\n[[package]]\nname = "a"\nfile = "a-1-1.nawa.tar.zst"\nsha256 = "00"\n'
            'download_url = "https://x/a"\n[package.relations]\nschema = 1\n\n'
            '[[package]]\nname = "b"\nfile = "b-1-1.nawa.tar.zst"\nsha256 = "11"\n'
        )
        blocks = PUBLISHER.entry_blocks(text)
        assert len(blocks) == 2 and "[repository]" not in blocks[0]
        assert "download_url" not in PUBLISHER.strip_download_url(blocks[0])
        assert PUBLISHER.block_entry(blocks[0])["relations"] == {"schema": 1}

        # Only complete, uploaded, signed assets count as published holders.
        releases = [
            {"tag_name": "packages-v5-0001", "assets": [
                {"name": alpha, "state": "uploaded"}, {"name": alpha + ".sig", "state": "uploaded"},
                {"name": beta, "state": "uploaded"}, {"name": beta + ".sig", "state": "starter"},
            ]},
            {"tag_name": "packages-0001", "assets": [{"name": "legacy-1-1.nawa.tar.zst"}]},
        ]
        assert PUBLISHER.shard_holders(releases) == {alpha: {"packages-v5-0001"}}

        # Staging keeps only current, not yet published archives.
        built = root / "wave-built"
        built.mkdir()
        (built / alpha).write_bytes(b"published already")
        (built / beta).write_bytes(b"new")
        (built / "stale-1.0-1.nawa.tar.zst").write_bytes(b"not a recipe")
        stage = root / "wave-stage"
        listing = [{"tag_name": "packages-v5-0001", "assets": [{"name": alpha}, {"name": alpha + ".sig"}]}]
        assert PUBLISHER.stage_wave(pair, built, listing, stage, nawa, key) == [beta]
        assert (stage / (beta + ".sig")).is_file() and not (stage / alpha).exists()

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
