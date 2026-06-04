import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import Mock, patch

import workers.manager as manager
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


def _write_fake_worker(tmp_path: Path) -> Path:
    script = tmp_path / "fake_display_worker.py"
    script.write_text(textwrap.dedent(
        """\
        #!/usr/bin/env python3
        import json
        import os
        import signal
        import socket
        import sys

        display = sys.argv[1]
        sock_path = f"/tmp/taey_worker_{display}.sock"
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(8)

        def _stop(*_args):
            try:
                server.close()
            finally:
                if os.path.exists(sock_path):
                    os.unlink(sock_path)
            sys.exit(0)

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        while True:
            conn, _ = server.accept()
            with conn:
                data = b""
                while b"\\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                if not data:
                    continue
                cmd = json.loads(data.decode().strip())
                if cmd.get("cmd") == "ping":
                    conn.sendall(b'{"status":"alive"}\\n')
                else:
                    conn.sendall(b'{"status":"ok"}\\n')
        """
    ))
    script.chmod(0o755)
    return script


def _count_worker_procs(script: Path) -> int:
    result = subprocess.run(
        ["pgrep", "-af", str(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    return len([line for line in result.stdout.splitlines() if str(script) in line])


def test_worker_restart_does_not_accumulate_processes(tmp_path, monkeypatch):
    fake_script = _write_fake_worker(tmp_path)
    monkeypatch.setattr(manager, "_WORKER_SCRIPT", str(fake_script))
    monkeypatch.setattr(manager, "get_platform_display", lambda platform: "restarttest")
    manager._workers.clear()

    baseline = _count_worker_procs(fake_script)
    try:
        assert manager._spawn_worker("chatgpt", "restarttest") is True
        time.sleep(0.2)
        assert _count_worker_procs(fake_script) == baseline + 1

        result = manager.send_to_worker("chatgpt", {"cmd": "ping"}, timeout=5.0)
        assert result["status"] == "alive"
        assert _count_worker_procs(fake_script) == baseline + 1

        proc = manager._workers["chatgpt"]
        proc.kill()
        proc.wait(timeout=5)

        result = manager.send_to_worker("chatgpt", {"cmd": "ping"}, timeout=5.0)
        assert result["status"] == "alive"
        time.sleep(0.2)
        assert _count_worker_procs(fake_script) == baseline + 1
    finally:
        manager.shutdown_workers()
        time.sleep(0.2)
        assert _count_worker_procs(fake_script) == baseline


def test_worker_dies_when_parent_process_exits(tmp_path):
    fake_script = _write_fake_worker(tmp_path)
    launcher = tmp_path / "launcher.py"
    repo_root = Path(__file__).resolve().parents[1]
    launcher.write_text(textwrap.dedent(
        f"""\
        import sys
        sys.path.insert(0, {str(repo_root)!r})
        import workers.manager as manager

        manager._WORKER_SCRIPT = {str(fake_script)!r}
        manager._workers.clear()
        ok = manager._spawn_worker("chatgpt", "pdeathtest")
        if not ok:
            raise SystemExit(2)
        print(manager._workers["chatgpt"].pid, flush=True)
        """
    ))

    proc = subprocess.run(
        [sys.executable, str(launcher)],
        capture_output=True,
        text=True,
        check=True,
    )
    child_pid = int(proc.stdout.strip())

    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child_pid, signal.SIGKILL)
        raise AssertionError("worker survived parent exit")
