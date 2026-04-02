#!/usr/bin/env python3
"""Per-display consultation worker for multi-display MCP server.

Each worker owns one platform on one X11 display with its own D-Bus/AT-SPI
bus. The MCP server dispatches tool calls to the correct worker via Unix
socket IPC. Workers hold cached AT-SPI references across commands — same
code path as hmm_bot on Thor.

Usage (spawned by server.py, not run directly):
    python3 workers/display_worker.py :2 chatgpt

Environment is set up BEFORE any AT-SPI imports:
    DISPLAY=:2
    AT_SPI_BUS_ADDRESS=<from /tmp/a11y_bus_:2>
    DBUS_SESSION_BUS_ADDRESS=<same>
    GTK_USE_PORTAL=0
"""

import json
import logging
import os
import signal
import socket
import sys
import time
import traceback

# ─── MUST set display env before any AT-SPI/GTK imports ─────────────
def _setup_display_env(display: str):
    """Configure process environment for this display's AT-SPI bus."""
    os.environ['DISPLAY'] = display
    os.environ['GTK_USE_PORTAL'] = '0'

    # Worker IS the display — don't route through subprocess scanning.
    # Without this, find_firefox_for_platform() sees PLATFORM_DISPLAYS
    # (inherited from parent MCP server) and returns _RemoteFirefox
    # sentinels instead of using direct AT-SPI on our bus.
    os.environ.pop('PLATFORM_DISPLAYS', None)

    bus_file = f'/tmp/a11y_bus_{display}'
    try:
        with open(bus_file) as f:
            bus = f.read().strip()
        if bus:
            os.environ['AT_SPI_BUS_ADDRESS'] = bus
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = bus
    except FileNotFoundError:
        pass  # Bus file may not exist yet — AT-SPI will fall back


# Parse args and setup BEFORE any project imports
if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <display> <platform>", file=sys.stderr)
    sys.exit(1)

DISPLAY = sys.argv[1]   # e.g. ":2"
PLATFORM = sys.argv[2]  # e.g. "chatgpt"
_setup_display_env(DISPLAY)

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Load .env (same as server.py)
_env_path = os.path.join(_ROOT, '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# NOW import AT-SPI and project modules
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi  # noqa: E402

# CRITICAL: core/platforms.py populates _PLATFORM_DISPLAYS at import time
# from both env var AND .env file. We popped the env var above, but the
# .env file fallback still fills the dict. Clear it after import so
# find_firefox_for_platform() uses the direct local AT-SPI path.
from core.platforms import _PLATFORM_DISPLAYS  # noqa: E402
_PLATFORM_DISPLAYS.clear()

from storage.redis_pool import get_client as get_redis, node_key  # noqa: E402

try:
    from storage import neo4j_client
except Exception:
    neo4j_client = None

from tools.inspect import handle_inspect  # noqa: E402
from tools.click import handle_click  # noqa: E402
from tools.attach import handle_attach  # noqa: E402
from tools.send import handle_send_message  # noqa: E402
from tools.extract import handle_quick_extract, handle_extract_history  # noqa: E402
from tools.dropdown import handle_select_dropdown, handle_prepare  # noqa: E402
from tools.plan import handle_plan  # noqa: E402
from tools.sessions import handle_list_sessions  # noqa: E402
from tools.monitors import handle_monitors  # noqa: E402
from tools.mode_select import handle_select_mode  # noqa: E402

# ─── Logging ─────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s [worker:{PLATFORM}:{DISPLAY}] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(f'worker.{PLATFORM}')

# ─── JSON encoder (handles datetime, AT-SPI objects) ────────────────

class _JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return str(obj)
        return super().default(obj)

# ─── Redis client (lazy init) ───────────────────────────────────────

_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = get_redis()
        except Exception as e:
            logger.error("Redis connection failed: %s", e)
    return _redis_client

# ─── Command handlers ───────────────────────────────────────────────

COMMAND_TIMEOUT = int(os.environ.get('WORKER_CMD_TIMEOUT', '120'))


class _CmdTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _CmdTimeout("Command timed out")


def handle_command(cmd_data: dict) -> dict:
    """Route a command to the appropriate tool handler.

    Each command maps 1:1 to an MCP tool. The handlers are the same
    functions the MCP server calls — they just run on the correct bus.
    """
    cmd = cmd_data.get('cmd', '')
    rc = _get_redis()

    if not rc and cmd not in ('ping',):
        return {'error': 'Redis not connected'}

    try:
        if cmd == 'ping':
            return {
                'status': 'alive',
                'platform': PLATFORM,
                'display': DISPLAY,
                'pid': os.getpid(),
                'redis': rc is not None,
            }

        elif cmd == 'inspect':
            return handle_inspect(
                PLATFORM, rc,
                scroll=cmd_data.get('scroll', 'bottom'),
                fresh_session=cmd_data.get('fresh_session', False),
            )

        elif cmd == 'click':
            return handle_click(
                PLATFORM,
                cmd_data.get('x', 0),
                cmd_data.get('y', 0),
            )

        elif cmd == 'attach':
            file_path = cmd_data.get('file_path', '')
            if not file_path:
                return {'error': 'file_path required'}
            return handle_attach(PLATFORM, file_path, rc)

        elif cmd == 'send':
            message = cmd_data.get('message', '')
            if not message:
                return {'error': 'message required'}
            return handle_send_message(
                PLATFORM, message, rc,
                display=DISPLAY,
                attachments=cmd_data.get('attachments'),
                session_type=cmd_data.get('session_type'),
                purpose=cmd_data.get('purpose'),
            )

        elif cmd == 'extract':
            return handle_quick_extract(
                PLATFORM, rc,
                neo4j_mod=neo4j_client,
                complete=cmd_data.get('complete', False),
            )

        elif cmd == 'extract_history':
            return handle_extract_history(
                PLATFORM, rc,
                max_messages=cmd_data.get('max_messages', 500),
            )

        elif cmd == 'plan':
            action = cmd_data.get('action', 'get')
            params = {k: v for k, v in cmd_data.items()
                      if k not in ('cmd', 'action')}
            return handle_plan(PLATFORM, action, params, rc)

        elif cmd == 'prepare':
            return handle_prepare(PLATFORM, rc)

        elif cmd == 'select_dropdown':
            dropdown = cmd_data.get('dropdown', '')
            target_value = cmd_data.get('target_value', '')
            if not dropdown or not target_value:
                return {'error': 'dropdown and target_value required'}
            return handle_select_dropdown(
                PLATFORM, dropdown, target_value, rc,
            )

        elif cmd == 'select_mode':
            mode = cmd_data.get('mode') or cmd_data.get('mode_name')
            model = cmd_data.get('model')
            if not mode and not model:
                return {'error': 'mode or model required'}
            return handle_select_mode(PLATFORM, mode=mode, model=model)

        elif cmd == 'list_sessions':
            return handle_list_sessions(
                cmd_data.get('platform_filter'), rc,
            )

        elif cmd == 'monitors':
            action = cmd_data.get('action', 'list')
            return handle_monitors(action, rc)

        elif cmd == 'check_stop':
            # Monitor support: check if stop button is visible
            return _check_stop_button()

        else:
            return {'error': f'Unknown command: {cmd}'}

    except _CmdTimeout:
        return {'error': f'Command {cmd} timed out after {COMMAND_TIMEOUT}s'}
    except Exception as e:
        logger.error("Command %s failed: %s\n%s", cmd, e, traceback.format_exc())
        return {'error': f'{cmd} failed: {e}'}


def _check_stop_button() -> dict:
    """Check if a stop button is visible for this platform.

    Used by the central monitor to detect response completion
    on multi-display without needing direct AT-SPI access.
    """
    from core import atspi
    from core.config import get_platform_config

    firefox = atspi.find_firefox_for_platform(PLATFORM)
    if not firefox:
        return {'stop_found': False, 'error': 'Firefox not found'}

    doc = atspi.get_platform_document(firefox, PLATFORM)
    if not doc:
        return {'stop_found': False, 'error': 'Document not found'}

    config = get_platform_config(PLATFORM)
    stop_patterns = config.get('stop_patterns', ['stop'])

    def _scan(obj, depth=0):
        if depth > 25:
            return False
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip().lower()
            if role in ('push button', 'button', 'toggle button'):
                if name and len(name) <= 50 and name in stop_patterns:
                    return True
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child and _scan(child, depth + 1):
                    return True
        except Exception:
            pass
        return False

    stop_found = _scan(doc)
    return {'stop_found': stop_found, 'platform': PLATFORM}


# ─── Unix socket server ─────────────────────────────────────────────

SOCKET_PATH = f'/tmp/taey_worker_{DISPLAY}.sock'
MAX_MSG_SIZE = 10 * 1024 * 1024  # 10MB — inspect results can be large


def _read_message(conn: socket.socket) -> bytes:
    """Read newline-terminated JSON from socket."""
    data = b''
    while True:
        try:
            chunk = conn.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
        if b'\n' in data:
            break
        if len(data) > MAX_MSG_SIZE:
            break
    return data


def run_worker():
    """Main loop: accept connections, handle commands, return results."""
    # Clean up stale socket
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(2)
    os.chmod(SOCKET_PATH, 0o600)

    # Ignore SIGPIPE (broken pipe from disconnected clients)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    logger.info("Worker ready — platform=%s display=%s socket=%s pid=%d",
                PLATFORM, DISPLAY, SOCKET_PATH, os.getpid())

    while True:
        try:
            conn, _ = server.accept()
            conn.settimeout(COMMAND_TIMEOUT + 10)  # Socket timeout > command timeout
        except Exception as e:
            logger.error("Accept failed: %s", e)
            continue

        try:
            raw = _read_message(conn)
            if not raw:
                continue

            cmd_data = json.loads(raw.decode().split('\n')[0])

            # Set per-command timeout via SIGALRM
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(COMMAND_TIMEOUT)
            try:
                result = handle_command(cmd_data)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            response = json.dumps(result, cls=_JSONEncoder) + '\n'
            conn.sendall(response.encode())

        except json.JSONDecodeError as e:
            try:
                conn.sendall(json.dumps({'error': f'Invalid JSON: {e}'}).encode() + b'\n')
            except Exception:
                pass
        except Exception as e:
            logger.error("Request handling error: %s", e)
            try:
                conn.sendall(json.dumps({'error': str(e)}).encode() + b'\n')
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ─── Entry point ─────────────────────────────────────────────────────

if __name__ == '__main__':
    run_worker()
