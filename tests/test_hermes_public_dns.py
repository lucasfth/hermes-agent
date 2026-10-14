"""Opt-in public DNS keeps local resolution and SSRF rejection intact."""
import socket
from types import SimpleNamespace

import dns.resolver
import pytest
import hermes_bootstrap as bootstrap


@pytest.fixture
def resolver(monkeypatch, tmp_path):
    queries = []
    answer = SimpleNamespace(addresses_and_families=lambda: [("93.184.216.34", socket.AF_INET)])
    fake = SimpleNamespace(nameservers=[], timeout=0, lifetime=0, cache=None,
                           resolve_name=lambda name, family: queries.append((name, family)) or answer)
    monkeypatch.setattr(dns.resolver, "Resolver", lambda **kw: fake)
    original = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", original)
    path = tmp_path / "dns-resolvers"
    path.write_text("1.1.1.1\n", encoding="utf-8")
    bootstrap.install_public_dns(path)
    return queries, fake, original


def test_public_host_returns_usable_numeric_address(resolver):
    queries, fake, original = resolver
    result = socket.getaddrinfo("public.example", 443, type=socket.SOCK_STREAM)
    assert result == original("93.184.216.34", 443, type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST)
    assert queries == [("public.example", socket.AF_UNSPEC)]
    assert 0 < fake.lifetime <= 3


def test_local_and_numeric_names_do_not_use_public_dns(resolver):
    queries, fake, original = resolver
    for name in ["localhost", "127.0.0.1"]:
        assert socket.getaddrinfo(name, 443) == original(name, 443)
    assert not queries


def test_private_mapping_precedes_public_dns(resolver, tmp_path):
    queries, fake, original = resolver
    hosts = tmp_path / "hosts.override"
    hosts.write_text("127.0.0.1 neo.example\n", encoding="utf-8")
    bootstrap.install_host_overrides(hosts)
    assert socket.getaddrinfo("neo.example", 443)[0][4][0] == "127.0.0.1"
    assert not queries


def test_dns_failure_is_a_resolution_error(resolver):
    queries, fake, original = resolver
    def unavailable(*args):
        raise dns.resolver.LifetimeTimeout(timeout=3, errors=[])
    fake.resolve_name = unavailable
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("public.example", 443)


def test_private_public_dns_answer_remains_ssrf_blocked(resolver):
    queries, fake, original = resolver
    fake.resolve_name = lambda *a: SimpleNamespace(addresses_and_families=lambda: [("127.0.0.1", socket.AF_INET)])
    from tools import url_safety
    url_safety._reset_allow_private_cache()
    url_safety._allow_private_resolved = True
    url_safety._cached_allow_private = False
    assert not url_safety.is_safe_url("https://public.example/")
    url_safety._reset_allow_private_cache()
