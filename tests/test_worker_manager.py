import json
from unittest.mock import Mock, patch

from workers.manager import _ipc_call, _spawn_worker


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


def test_spawn_worker_readiness_ping_uses_direct_ipc():
    fake_proc = Mock()
    fake_proc.pid = 1234
    fake_proc.poll.return_value = None

    with patch("workers.manager.os.open", return_value=10), \
         patch("workers.manager.os.close"), \
         patch("workers.manager.subprocess.Popen", return_value=fake_proc), \
         patch("workers.manager._socket_path", return_value="/tmp/test.sock"), \
         patch("workers.manager.os.path.exists", return_value=True), \
         patch("workers.manager._ipc_call", return_value={"status": "alive"}) as ipc_call, \
         patch("workers.manager.send_to_worker") as send_to_worker:
        assert _spawn_worker("chatgpt", ":2") is True

    ipc_call.assert_called_once_with("/tmp/test.sock", {"cmd": "ping"}, timeout=5.0)
    send_to_worker.assert_not_called()
