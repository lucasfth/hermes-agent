"""A Termux store interpreter needs its own lib dir on the loader path in the execute_code child."""
import os
import subprocess
import sys

import pytest

from hermes_cli._launchers import _termux_library
from tools.code_execution_env import _build_child_env


@pytest.mark.skipif(_termux_library(sys.executable) is None, reason="needs a Termux-prefix interpreter")
def test_child_env_lets_the_store_interpreter_start(monkeypatch, tmp_path):
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    env = _build_child_env(rpc_endpoint="sock", rpc_token="tok", tmpdir=str(tmp_path), child_python=sys.executable)

    result = subprocess.run([sys.executable, "-c", "print('child-ok')"], env=env,
                            capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "child-ok"
    assert env["LD_LIBRARY_PATH"].split(os.pathsep)[0] == str(_termux_library(sys.executable))
