"""A long scratch TMPDIR must fall back to a socket root this user can actually bind in."""
import os
import socket
import tempfile

import pytest

import hermes_constants


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs AF_UNIX sockets")
def test_long_tmpdir_falls_back_to_writable_prefix_tmp_when_slash_tmp_is_not(monkeypatch, tmp_path):
    prefix = tmp_path / "usr"
    (prefix / "tmp").mkdir(parents=True)
    long_tmp = tmp_path / ("scratch-" * 8)
    long_tmp.mkdir()
    # Budget fits $PREFIX/tmp but not the scratch TMPDIR, mirroring Termux's real lengths.
    monkeypatch.setattr(hermes_constants, "SOCKET_TMPDIR_MAX_LEN", len(str(prefix / "tmp")))
    monkeypatch.setattr(tempfile, "tempdir", str(long_tmp))
    monkeypatch.setenv("PREFIX", str(prefix))
    real_access = os.access
    monkeypatch.setattr(os, "access", lambda path, mode: False if os.fspath(path) == "/tmp" else real_access(path, mode))

    root = hermes_constants.socket_safe_tmpdir()

    assert root == str(prefix / "tmp")
    # Bind by relative name: the absolute fixture path may exceed sun_path on deep test roots.
    monkeypatch.chdir(root)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind("hermes_rpc_x.sock")
