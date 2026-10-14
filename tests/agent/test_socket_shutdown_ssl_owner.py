"""Cross-thread abort must preserve the SSL object and its file descriptor."""
import socket
import ssl
from threading import Event, Thread
import subprocess

from agent.agent_runtime_helpers import _shutdown_socket


def test_ssl_shutdown_preserves_native_object_and_fd():
    raw, peer = socket.socketpair()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    wrapped = context.wrap_socket(raw, do_handshake_on_connect=False)
    try:
        native = getattr(wrapped, "_sslobj")
        fd = wrapped.fileno()
        worker = Thread(target=_shutdown_socket, args=(wrapped,))
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert getattr(wrapped, "_sslobj") is native
        assert wrapped.fileno() == fd
        peer.settimeout(2)
        assert peer.recv(1) == b""
    finally:
        wrapped.close()
        peer.close()


def test_plain_shutdown_preserves_fd_and_unblocks_peer():
    sock, peer = socket.socketpair()
    try:
        fd = sock.fileno()
        _shutdown_socket(sock)
        assert sock.fileno() == fd
        peer.settimeout(2)
        assert peer.recv(1) == b""
    finally:
        sock.close()
        peer.close()


def test_closed_socket_shutdown_is_benign():
    sock = socket.socket()
    sock.close()
    _shutdown_socket(sock)


def test_abort_unblocks_real_tls_reader_without_destroying_ssl(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
        check=True, capture_output=True, timeout=15,
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_context.check_hostname = False
    client_context.verify_mode = ssl.CERT_NONE
    for _ in range(20):
        left, right = socket.socketpair()
        left.settimeout(3)
        right.settimeout(3)
        server_done, reading = Event(), Event()
        errors = []

        def serve():
            try:
                with server_context.wrap_socket(left, server_side=True) as server:
                    server.sendall(b"ready")
                    server_done.wait(3)
            except Exception as exc:
                errors.append(exc)

        server_thread = Thread(target=serve)
        server_thread.start()
        client = client_context.wrap_socket(right, server_hostname="localhost")
        reader = None
        try:
            assert client.recv(5) == b"ready"
            native, fd = getattr(client, "_sslobj"), client.fileno()

            def read():
                reading.set()
                try:
                    assert client.recv(1) == b""
                except (OSError, ssl.SSLError):
                    pass  # TCP shutdown may surface as a transport error.
                except Exception as exc:
                    errors.append(exc)

            reader = Thread(target=read)
            reader.start()
            assert reading.wait(2)
            _shutdown_socket(client)
            reader.join(3)
            assert not reader.is_alive()
            assert getattr(client, "_sslobj") is native
            assert client.fileno() == fd
        finally:
            server_done.set()
            server_thread.join(4)
            if reader is not None:
                reader.join(4)
            client.close()
        assert not server_thread.is_alive()
        assert not errors
