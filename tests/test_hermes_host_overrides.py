"""Explicit local host mappings preserve address selection and unrelated DNS."""
from __future__ import annotations

import socket

import hermes_bootstrap as bootstrap


def test_declared_host_connects_to_verified_local_address(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts.override"
    hosts.write_text("127.0.0.1 relay.example # test relay\n", encoding="utf-8")
    original = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", original)
    bootstrap.install_host_overrides(hosts)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with socket.create_connection(("relay.example", listener.getsockname()[1]), timeout=1) as client:
            assert client.getpeername()[0] == "127.0.0.1"
            peer, _ = listener.accept()
            peer.close()


def test_unmapped_host_and_numeric_addresses_keep_original_resolver(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts.override"
    hosts.write_text("127.0.0.1 relay.example\n", encoding="utf-8")
    original = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", original)
    bootstrap.install_host_overrides(hosts)
    for host in ["localhost", "127.0.0.1"]:
        assert socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM) == original(host, 443, type=socket.SOCK_STREAM)


def test_invalid_mapping_cannot_redirect_name(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts.override"
    hosts.write_text("not-an-ip localhost\n", encoding="utf-8")
    original = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", original)
    bootstrap.install_host_overrides(hosts)
    assert socket.getaddrinfo("localhost", 443) == original("localhost", 443)
