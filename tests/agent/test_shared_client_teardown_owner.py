"""Session teardown cannot hard-close TLS state borrowed by another thread."""
import threading
import socket
import ssl
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from run_agent import AIAgent


def make_agent() -> Any:
    agent = AIAgent.__new__(AIAgent)
    agent.client = Mock()
    agent._client_lock = threading.RLock()
    for name in ("shutdown_memory_provider", "_close_task_resources", "_close_active_children",
                 "_close_request_clients", "_close_codex_session", "_trim_process_memory",
                 "_finalize_owned_session_row"):
        setattr(agent, name, Mock())
    agent._retire_shared_openai_client = Mock()
    agent._close_openai_client = Mock()
    return agent


def test_full_close_retires_shared_client_without_native_close():
    agent = make_agent()
    client = agent.client
    worker = threading.Thread(target=agent.close)
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    agent._retire_shared_openai_client.assert_called_once_with(client, reason="agent_close")
    agent._close_openai_client.assert_not_called()
    assert agent.client is None
    agent.close()
    assert agent._retire_shared_openai_client.call_count == 1


def test_concurrent_teardown_detaches_client_before_retirement():
    agent = make_agent()
    client = agent.client
    entered, finish = threading.Event(), threading.Event()
    calls = []

    def retire(value):
        calls.append(value)
        entered.set()
        assert finish.wait(2)

    first = threading.Thread(target=agent._drop_shared_client, args=(retire,))
    first.start()
    try:
        assert entered.wait(1)
        agent._drop_shared_client(calls.append)
        assert agent.client is None
        assert calls == [client]
    finally:
        finish.set()
        first.join(2)
    assert not first.is_alive()


def test_full_close_preserves_real_ssl_object_and_descriptor():
    raw, peer = socket.socketpair()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    wrapped = context.wrap_socket(raw, do_handshake_on_connect=False)
    agent = make_agent()
    del agent._retire_shared_openai_client  # Exercise the actual retirement and socket walker.
    connection = SimpleNamespace(_network_stream=SimpleNamespace(_sock=wrapped))
    pool = SimpleNamespace(_connections=[connection], _requests=[])
    agent.client = SimpleNamespace(
        _client=SimpleNamespace(_transport=SimpleNamespace(_pool=pool), _mounts={}),
        close=wrapped.close,
    )
    try:
        native, descriptor = getattr(wrapped, "_sslobj"), wrapped.fileno()
        worker = threading.Thread(target=agent.close)
        worker.start()
        worker.join(2)
        assert not worker.is_alive()
        assert getattr(wrapped, "_sslobj") is native
        assert wrapped.fileno() == descriptor
        peer.settimeout(2)
        assert peer.recv(1) == b""
        assert agent.client is None
    finally:
        wrapped.close()
        peer.close()
