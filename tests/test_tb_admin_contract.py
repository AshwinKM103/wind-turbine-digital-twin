"""Contract test suite for the thingsboard_admin CLI entry point.

Verifies CLI argument parsing, root help flags, subcommand help displays,
and proper error exit codes on unrecognized subcommands.

Exported Functions:
    run_cmd: Helper executing thingsboard_admin.py subprocesses.
    test_root_help: Verifies root --help returns 0.
    test_subcommand_help: Verifies subcommand --help displays across all registered subcommands.
    test_unknown_command_returns_code_2: Verifies error code 2 on unknown commands.
"""

from __future__ import annotations

import subprocess
import sys
import pytest


def run_cmd(*args: str) -> subprocess.CompletedProcess[str]:
    """Executes thingsboard_admin.py with specified arguments in a subprocess.

    Args:
        *args: Command line arguments to pass to the script.

    Returns:
        CompletedProcess instance containing stdout, stderr, and returncode.
    """
    return subprocess.run([sys.executable, "app/tools/thingsboard_admin.py", *args], capture_output=True, text=True)


def test_root_help() -> None:
    """Verifies that invoking thingsboard_admin.py with --help exits cleanly."""
    res = run_cmd("--help")
    assert res.returncode == 0
    assert "thingsboard_admin.py" in res.stdout or "usage:" in res.stdout


@pytest.mark.parametrize("subcmd", ["auth", "entity", "widget", "rulechain", "metadata", "health", "dashboard"])
def test_subcommand_help(subcmd: str) -> None:
    """Verifies that each registered subcommand responds to --help with status 0.

    Args:
        subcmd: Name of the subcommand under test.
    """
    res = run_cmd(subcmd, "--help")
    assert res.returncode == 0
    assert f"{subcmd}" in res.stdout or "usage:" in res.stdout


def test_unknown_command_returns_code_2() -> None:
    """Verifies that unknown subcommands exit with argparse error code 2."""
    res = run_cmd("nonexistent-command")
    assert res.returncode == 2

