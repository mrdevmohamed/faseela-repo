#!/usr/bin/env python3
"""Regression test for Bash completion in Faseela's default interactive shells."""

from __future__ import annotations

import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes/base/base-files/recipe.toml"
EXPECTED_HOOK = "/etc/profile.d/bash_completion.sh"


def extract_bashrc(install_script: str) -> str:
    target = re.escape("%{pkgdir}/etc/skel/.bashrc")
    match = re.search(
        rf"cat > {target} <<'EOF'\n(.*?)\nEOF",
        install_script,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("base-files no longer creates /etc/skel/.bashrc")
    return match.group(1) + "\n"


def run_interactive_bash(rcfile: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "--noprofile",
            "--rcfile",
            str(rcfile),
            "-ic",
            'printf "%s\\n" "${FASEELA_COMPLETION_TEST:-not-loaded}"',
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def main() -> None:
    recipe = tomllib.loads(RECIPE.read_text(encoding="utf-8"))
    install_script = recipe.get("build", {}).get("install", "")
    bashrc = extract_bashrc(install_script)

    required = (
        "[[ $- == *i* ]]",
        f"[[ -r {EXPECTED_HOOK} ]]",
        f". {EXPECTED_HOOK}",
    )
    missing = [item for item in required if item not in bashrc]
    if missing:
        raise AssertionError(
            "default .bashrc is missing the interactive completion loader: "
            + ", ".join(missing)
        )

    if "cp %{pkgdir}/etc/skel/.bashrc %{pkgdir}/root/.bashrc" not in install_script:
        raise AssertionError("root's .bashrc must be copied from the tested skel file")

    with tempfile.TemporaryDirectory(prefix="faseela-bash-completion-") as tmp:
        tmpdir = Path(tmp)
        hook = tmpdir / "bash_completion.sh"
        rcfile = tmpdir / ".bashrc"

        # Prove that an interactive Bash actually sources the configured hook.
        hook.write_text(
            'export FASEELA_COMPLETION_TEST="loaded"\n',
            encoding="utf-8",
        )
        rcfile.write_text(
            bashrc.replace(EXPECTED_HOOK, str(hook)),
            encoding="utf-8",
        )
        loaded = run_interactive_bash(rcfile)
        if loaded.returncode != 0 or "loaded" not in loaded.stdout.splitlines():
            raise AssertionError(
                "interactive Bash did not source the completion hook; "
                f"exit={loaded.returncode}, stdout={loaded.stdout!r}, "
                f"stderr={loaded.stderr!r}"
            )

        # The loader must remain harmless when bash-completion is not installed.
        missing_hook = tmpdir / "not-installed.sh"
        rcfile.write_text(
            bashrc.replace(EXPECTED_HOOK, str(missing_hook)),
            encoding="utf-8",
        )
        absent = run_interactive_bash(rcfile)
        if absent.returncode != 0 or "not-loaded" not in absent.stdout.splitlines():
            raise AssertionError(
                "interactive Bash failed when the optional completion hook was absent; "
                f"exit={absent.returncode}, stdout={absent.stdout!r}, "
                f"stderr={absent.stderr!r}"
            )

    print("bash-completion integration: ok")


if __name__ == "__main__":
    main()
