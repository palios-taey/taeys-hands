import json
from unittest.mock import patch

from workers.manager import _ipc_call


class _FakeSocket:
    def __init__(self):
        self.timeouts = []
        self.connected = None
        self.sent = []
        self.recv_calls = 0

    def settimeout(self, value):
        self.timeouts.append(value)

    def connect(self, sock_path):
        self.connected = sock_path

    def sendall(self, payload):
        self.sent.append(payload)

    def recv(self, _size):
        self.recv_calls += 1
        if self.recv_calls == 1:
            return b'{"status": "alive"}\n'
        return b""

    def close(self):
        pass


def test_ipc_call_reapplies_socket_timeout_from_deadline():
    fake_socket = _FakeSocket()
    monotonic_values = iter([100.0, 100.1, 100.2, 100.3])

    with patch("workers.manager.socket.socket", return_value=fake_socket), \
         patch("workers.manager.time.monotonic", side_effect=lambda: next(monotonic_values)):
        result = _ipc_call("/tmp/test.sock", {"cmd": "ping"}, timeout=5.0)

    assert result == {"status": "alive"}
    assert fake_socket.connected == "/tmp/test.sock"
    assert json.loads(fake_socket.sent[0].decode().strip()) == {"cmd": "ping"}
    assert len(fake_socket.timeouts) >= 3
    assert fake_socket.timeouts[0] > fake_socket.timeouts[1] > fake_socket.timeouts[2]
