#!/usr/bin/env python3
"""Regression tests for the schema-v5 recipe metadata audit."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name("audit-schema-v5-metadata.py")
SPEC = importlib.util.spec_from_file_location("audit_schema_v5_metadata", MODULE)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class AuditTests(unittest.TestCase):
    def write_recipe(self, root, name, extra=""):
        directory = root / name
        directory.mkdir(parents=True)
        content = (
            f'[package]\nname = "{name}"\nversion = "1"\n'
            '[depends]\nrun = []\n'
            '[capabilities]\nprovides = []\n'
            '[relations]\nschema = 1\nconflicts = []\n'
            'replaces = []\n'
        )
        if extra:
            content = content.replace('replaces = []\n', extra)
        (directory / "recipe.toml").write_text(content, encoding="utf-8")

    def test_complete_explicit_empty_metadata_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_recipe(root, "alpha")
            report = AUDIT.audit(root)
            self.assertTrue(report["complete"])
            self.assertEqual(report["missing_count"], 0)
            self.assertEqual(report["error_count"], 0)

    def test_missing_declarations_are_not_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "alpha"
            directory.mkdir()
            (directory / "recipe.toml").write_text(
                '[package]\nname="alpha"\nversion="1"\n', encoding="utf-8"
            )
            report = AUDIT.audit(root)
            fields = {item["field"] for item in report["missing_declarations"]}
            self.assertEqual(fields, {
                "depends.run", "capabilities.provides", "relations"
            })

    def test_retired_legacy_replacement_target_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_recipe(root, "systemd", 'replaces = ["eudev"]\n')
            report = AUDIT.audit(root)
            self.assertEqual(report["error_count"], 0)

    def test_unknown_replacement_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_recipe(root, "alpha",
                'replaces = ["missing-package"]\n')
            report = AUDIT.audit(root)
            self.assertIn("unknown-replaces-target",
                          {item["kind"] for item in report["errors"]})


if __name__ == "__main__":
    unittest.main()
