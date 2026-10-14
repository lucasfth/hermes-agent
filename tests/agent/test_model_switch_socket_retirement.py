"""Switch commit and rollback unblock old TLS routes without freeing borrowed SSL state."""
import socket
import ssl
from types import SimpleNamespace

import pytest

from agent import agent_runtime_helpers as helpers
from tests.agent.test_switch_model_rollback import _make_agent_openrouter


def _tls_client():
    raw, peer = socket.socketpair()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    wrapped = context.wrap_socket(raw, do_handshake_on_connect=False)
    connection = SimpleNamespace(_network_stream=SimpleNamespace(_sock=wrapped))
    pool = SimpleNamespace(_connections=[connection], _requests=[])
    client = SimpleNamespace(_client=SimpleNamespace(_transport=SimpleNamespace(_pool=pool), _mounts={}))
    return client, wrapped, peer


def _agent(monkeypatch, client, candidate):
    agent = _make_agent_openrouter()
    agent.client = client
    agent._create_openai_client = lambda *a, **kw: candidate
    agent._anthropic_prompt_cache_policy = lambda **kw: (False, False)
    monkeypatch.setattr(helpers, "_resolve_switch_context_length", lambda *a: (None, 128000))
    return agent


def _switch(agent):
    agent.switch_model(new_model="x-ai/grok-4.5", new_provider="openrouter",
                       api_key="test", base_url="https://openrouter.ai/api/v1",
                       api_mode="chat_completions", capabilities={})


def test_successful_switch_unblocks_old_tls_route_without_releasing_fd(monkeypatch):
    old, wrapped, peer = _tls_client()
    candidate = SimpleNamespace()
    agent = _agent(monkeypatch, old, candidate)
    try:
        native, descriptor = wrapped._sslobj, wrapped.fileno()
        _switch(agent)
        peer.settimeout(0.2)
        assert peer.recv(1) == b"", "The replaced route must be shut down before losing its owner"
        assert wrapped._sslobj is native
        assert wrapped.fileno() == descriptor
        assert agent.client is candidate
        assert agent.model == "x-ai/grok-4.5"
    finally:
        wrapped.close()
        peer.close()


def test_post_build_rollback_unblocks_candidate_and_preserves_original(monkeypatch):
    candidate, wrapped, peer = _tls_client()
    old = SimpleNamespace()
    agent = _agent(monkeypatch, old, candidate)
    monkeypatch.setattr(helpers, "sync_credential_pool_entry_id",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("post-build failure")))
    try:
        native, descriptor = wrapped._sslobj, wrapped.fileno()
        with pytest.raises(RuntimeError, match="post-build failure"):
            _switch(agent)
        peer.settimeout(0.2)
        assert peer.recv(1) == b"", "An unused candidate must not remain live after rollback"
        assert wrapped._sslobj is native
        assert wrapped.fileno() == descriptor
        assert agent.client is old
        assert agent.model == "x-ai/grok-4"
    finally:
        wrapped.close()
        peer.close()
