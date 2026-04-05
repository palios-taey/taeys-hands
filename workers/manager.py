"""Worker lifecycle management — spawn, health check, restart, IPC.

Used by server.py to manage per-display workers on multi-display (Mira).
On single-display (Thor), workers are not used — tools run directly.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Dict, Optional

from core.platforms import _PLATFORM_DISPLAYS, get_platform_display, is_multi_display

logger = logging.getLogger(__name__)

_WORKER_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'display_worker.py'
)

# Active worker processes: platform -> Popen
_workers: Dict[str, subprocess.Popen] = {}


class _JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return str(obj)
        return super().default(obj)


def _socket_path(display: str) -> str:
    return f'/tmp/taey_worker_{display}.sock'


# ─── Spawn / restart ────────────────────────────────────────────────

def spawn_workers() -> Dict[str, bool]:
    """Spawn all per-display workers. Called at MCP server startup.

    Returns dict of {platform: ready_bool}.
    Only runs on multi-display (PLATFORM_DISPLAYS configured).
    """
    if not is_multi_display():
        return {}

    results = {}
    for platform, display in _PLATFORM_DISPLAYS.items():
        ok = _spawn_worker(platform, display)
        results[platform] = ok

    return results


def _spawn_worker(platform: str, display: str) -> bool:
    """Spawn a single worker process and wait for it to be ready."""
    log_path = f'/tmp/taey_worker_{platform}.log'

    try:
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except OSError as e:
        logger.error("Cannot open log for %s worker: %s", platform, e)
        return False

    try:
        proc = subprocess.Popen(
            [sys.executable, _WORKER_SCRIPT, display, platform],
            stdout=log_fd, stderr=log_fd,
            close_fds=True,
        )
    except Exception as e:
        logger.error("Failed to spawn %s worker: %s", platform, e)
        os.close(log_fd)
        return False

    os.close(log_fd)
    _workers[platform] = proc
    logger.info("Spawned worker %s on %s (PID %d)", platform, display, proc.pid)

    # Wait for ready (socket exists + responds to ping)
    sock_path = _socket_path(display)
    for attempt in range(30):  # 15 seconds max
        if proc.poll() is not None:
            logger.error("Worker %s exited immediately (code=%s)", platform, proc.returncode)
            return False
        if os.path.exists(sock_path):
            try:
                result = _ipc_call(sock_path, {'cmd': 'ping'}, timeout=5.0)
                if result.get('status') == 'alive':
                    logger.info("Worker %s ready (PID %d)", platform, proc.pid)
                    return True
            except Exception:
                pass
        time.sleep(0.5)

    logger.error("Worker %s failed to start within 15s", platform)
    return False


def _restart_worker(platform: str) -> bool:
    """Kill and restart a dead worker."""
    display = get_platform_display(platform)
    if not display:
        return False

    old = _workers.get(platform)
    if old:
        try:
            old.kill()
            old.wait(timeout=5)
        except Exception:
            pass

    logger.warning("Restarting worker %s on %s", platform, display)
    return _spawn_worker(platform, display)


def shutdown_workers():
    """Kill all workers. Called at MCP server shutdown."""
    for platform, proc in _workers.items():
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    _workers.clear()

    # Clean up socket files
    for display in _PLATFORM_DISPLAYS.values():
        sock_path = _socket_path(display)
        if os.path.exists(sock_path):
            try:
                os.unlink(sock_path)
            except Exception:
                pass


# ─── IPC ─────────────────────────────────────────────────────────────

def send_to_worker(platform: str, cmd: dict,
                   timeout: float = 120.0) -> dict:
    """Send command to platform worker via Unix socket, return result.

    Automatically restarts dead workers on first failure.
    Raises RuntimeError if worker is unreachable after restart.
    """
    display = get_platform_display(platform)
    if not display:
        raise RuntimeError(f"No display configured for {platform}")

    sock_path = _socket_path(display)

    # Check worker is alive — restart if dead
    proc = _workers.get(platform)
    if proc and proc.poll() is not None:
        logger.warning("Worker %s died (exit=%s), restarting...",
                       platform, proc.returncode)
        if not _restart_worker(platform):
            raise RuntimeError(f"Worker {platform} restart failed")

    # Try IPC — one retry after restart
    for attempt in range(2):
        try:
            return _ipc_call(sock_path, cmd, timeout)
        except (ConnectionRefusedError, FileNotFoundError) as e:
            if attempt == 0:
                logger.warning("Worker %s unreachable (%s), restarting...",
                               platform, e)
                if _restart_worker(platform):
                    continue
            raise RuntimeError(f"Worker {platform} unreachable: {e}")
        except Exception as e:
            raise RuntimeError(f"Worker IPC failed for {platform}: {e}")

    raise RuntimeError(f"Worker {platform} unreachable after retry")


def _ipc_call(sock_path: str, cmd: dict, timeout: float) -> dict:
    """Low-level Unix socket call: send JSON, receive JSON."""
    deadline = time.monotonic() + timeout

    def _remaining_timeout() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Timed out waiting for worker response after {timeout:.2f}s"
            )
        return remaining

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(_remaining_timeout())
        sock.connect(sock_path)
        payload = json.dumps(cmd, cls=_JSONEncoder) + '\n'
        sock.settimeout(_remaining_timeout())
        sock.sendall(payload.encode())

        # Read response (newline-terminated)
        data = b''
        while b'\n' not in data:
            sock.settimeout(_remaining_timeout())
            chunk = sock.recv(1048576)  # 1MB chunks
            if not chunk:
                break
            data += chunk
            if len(data) > 10 * 1024 * 1024:
                raise RuntimeError("Response too large (>10MB)")

        if not data:
            raise RuntimeError("Empty response from worker")

        return json.loads(data.decode().split('\n')[0])
    finally:
        sock.close()


# ─── Dispatch helper for server.py ──────────────────────────────────

# Map MCP tool names to worker commands
_TOOL_CMD_MAP = {
    'taey_inspect': 'inspect',
    'taey_click': 'click',
    'taey_attach': 'attach',
    'taey_send_message': 'send',
    'taey_quick_extract': 'extract',
    'taey_extract_history': 'extract_history',
    'taey_plan': 'plan',
    'taey_prepare': 'prepare',
    'taey_select_dropdown': 'select_dropdown',
    'taey_list_sessions': 'list_sessions',
    'taey_monitors': 'monitors',
}

# Tools that should NOT be routed to workers (not platform-specific)
_NEVER_ROUTE = {'taey_list_sessions', 'taey_monitors', 'taey_respawn_monitor'}


def should_route_to_worker(tool_name: str, platform: str) -> bool:
    """Check if this tool call should be routed to a worker."""
    if not is_multi_display():
        return False
    if tool_name in _NEVER_ROUTE:
        return False
    if not platform:
        return False
    return get_platform_display(platform) is not None


def route_to_worker(tool_name: str, args: dict) -> dict:
    """Convert MCP tool call to worker command and dispatch.

    Returns the worker's result dict directly.
    """
    platform = args.get('platform', '')
    cmd_name = _TOOL_CMD_MAP.get(tool_name)
    if not cmd_name:
        raise RuntimeError(f"No worker command mapping for {tool_name}")

    # Build worker command from MCP args
    cmd = {'cmd': cmd_name}

    # Pass through all args except 'platform' (worker already knows it)
    for k, v in args.items():
        if k != 'platform':
            cmd[k] = v

    return send_to_worker(platform, cmd)
