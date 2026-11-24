#!/usr/bin/env python3
"""Tests for check-etc-policy.py and for the real recipe tree."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_etc_policy", ROOT / "scripts" / "check-etc-policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

POLICY = """
[[forbid]]
pattern = "/etc/resolv.conf"
reason = "machine state"
instead = "tmpfiles"

[[forbid]]
pattern = "/etc/udev/rules.d/*"
reason = "override directory"
instead = "/usr/lib/udev/rules.d"

[[allow]]
pattern = "/etc/profile.d/*"
category = "drop-in"
reason = "sourced by /etc/profile"

[[allow]]
pattern = "/etc/lightdm/*.conf.d/*"
category = "drop-in"
reason = "lightdm drop-ins"

[[allow]]
pattern = "/etc/hosts"
category = "seed"
reason = "localhost entries"
"""


def run_check(install_script):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "policy.toml").write_text(POLICY)
        recipe = tmp / "recipes" / "extra" / "demo"
        recipe.mkdir(parents=True)
        (recipe / "recipe.toml").write_text(f"[build]\ninstall = '''\n{install_script}\n'''\n")
        return policy.check(tmp / "recipes", tmp / "policy.toml")


class PolicyTests(unittest.TestCase):
    def test_allowed_paths_and_their_directories_pass(self):
        self.assertEqual(run_check(
            "install -d %{pkgdir}/etc/profile.d\n"
            "install -d %{pkgdir}/etc/lightdm/lightdm.conf.d\n"
            "echo x > %{pkgdir}/etc/lightdm/lightdm.conf.d/50-faseela.conf\n"
            "echo x > %{pkgdir}/etc/profile.d/demo.sh\n"
            "echo x > %{pkgdir}/etc/hosts\n"), [])

    def test_forbidden_path_names_the_replacement(self):
        problems = run_check("echo nameserver 1.1.1.1 > %{pkgdir}/etc/resolv.conf")
        self.assertEqual(len(problems), 1)
        self.assertIn("forbidden", problems[0])
        self.assertIn("tmpfiles", problems[0])

    def test_udev_rules_in_etc_are_forbidden(self):
        problems = run_check("install -Dm644 x.rules %{pkgdir}/etc/udev/rules.d/70-x.rules")
        self.assertEqual(len(problems), 1)
        self.assertIn("/usr/lib/udev/rules.d", problems[0])

    def test_unlisted_path_fails(self):
        problems = run_check("echo x > %{pkgdir}/etc/demo/demo.conf")
        self.assertEqual(len(problems), 1)
        self.assertIn("not in etc-policy.toml", problems[0])

    def test_shell_variables_stand_for_a_name(self):
        self.assertEqual(run_check('for n in a b; do echo x > %{pkgdir}/etc/profile.d/$n.sh; done'), [])

    def test_removals_and_comments_are_not_writes(self):
        self.assertEqual(run_check(
            "rm -f %{pkgdir}/etc/resolv.conf\n"
            "# %{pkgdir}/etc/demo/demo.conf is not shipped\n"), [])

    def test_policy_entries_need_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.toml"
            bad.write_text('[[allow]]\npattern = "/etc/x"\ncategory = "seed"\n')
            with self.assertRaises(SystemExit):
                policy.load_policy(bad)

    def test_forbidden_entries_need_a_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.toml"
            bad.write_text('[[forbid]]\npattern = "/etc/x"\nreason = "no"\n')
            with self.assertRaises(SystemExit):
                policy.load_policy(bad)


class RealTree(unittest.TestCase):
    def test_every_recipe_follows_the_policy(self):
        self.assertEqual(policy.check(ROOT / "recipes", ROOT / "etc-policy.toml"), [])

    def test_the_policy_file_is_well_formed(self):
        allow, forbid = policy.load_policy(ROOT / "etc-policy.toml")
        self.assertTrue(allow and forbid)
        patterns = [entry["pattern"] for entry in allow + forbid]
        self.assertEqual(len(patterns), len(set(patterns)), "duplicate pattern in etc-policy.toml")

    def test_machine_state_is_never_shipped(self):
        allow, forbid = policy.load_policy(ROOT / "etc-policy.toml")
        for path in ("/etc/resolv.conf", "/etc/machine-id", "/etc/udev/rules.d/70-x.rules"):
            self.assertEqual(policy.classify(path, allow, forbid)[0], "forbidden", path)


if __name__ == "__main__":
    unittest.main()
