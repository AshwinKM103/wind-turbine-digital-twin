import subprocess
import sys
import pytest

def run_cmd(*args):
    return subprocess.run([sys.executable, "app/tools/thingsboard_admin.py", *args], capture_output=True, text=True)

def test_root_help():
    res = run_cmd("--help")
    assert res.returncode == 0
    assert "thingsboard_admin.py" in res.stdout or "usage:" in res.stdout

@pytest.mark.parametrize("subcmd", ["auth", "entity", "widget", "rulechain", "metadata", "health", "dashboard"])
def test_subcommand_help(subcmd):
    res = run_cmd(subcmd, "--help")
    assert res.returncode == 0
    assert f"{subcmd}" in res.stdout or "usage:" in res.stdout

def test_unknown_command_returns_code_2():
    res = run_cmd("nonexistent-command")
    assert res.returncode == 2
