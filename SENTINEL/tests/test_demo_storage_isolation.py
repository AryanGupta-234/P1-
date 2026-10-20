"""Regression tests for demo-mode storage isolation."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_demo_selects_user_local_store_before_core_import(tmp_path):
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path)
    env.pop("SENTINEL_HOME", None)
    code = (
        "import os, sys; "
        "sys.argv = ['agent.py', '--demo']; "
        "import agent; "
        "from sentinel import core; "
        "expected = os.path.join(os.environ['LOCALAPPDATA'], 'SentinelDemo'); "
        "assert core.HOME == expected, (core.HOME, expected); "
        "assert os.path.isfile(core.DB_PATH)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr