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
import subprocess
import sys
import time
import traceback
from fnmatch import fnmatch
import hashlib

# ─── MUST set display env before any AT-SPI/GTK imports ─────────────
def _warn_display_env(message: str):
    print(f"display_worker env warning: {message}", file=sys.stderr)


def _read_isolated_bus_file(bus_file: str):
    try:
        with open(bus_file) as f:
            bus = f.read().strip()
        return bus or None
    except FileNotFoundError:
        return None


def _read_isolated_bus_xprop(display: str):
    try:
        result = subprocess.run(
            ['xprop', '-display', display, '-root', 'AT_SPI_BUS'],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _warn_display_env(f"xprop AT_SPI_BUS read failed on {display}: {exc}")
        return None

    if result.returncode != 0:
        stderr = result.stderr.strip()
        _warn_display_env(f"xprop AT_SPI_BUS read failed on {display}: {stderr or result.returncode}")
        return None

    if '"' not in result.stdout:
        return None
    bus = result.stdout.split('"', 2)[1].strip()
    return bus if bus.startswith('unix:') else None


def _write_isolated_bus_file(bus_file: str, bus: str):
    tmp_file = f'{bus_file}.tmp'
    with open(tmp_file, 'w') as f:
        f.write(f'{bus}\n')
    os.replace(tmp_file, bus_file)


def _a11y_bus_responds(bus: str):
    try:
        result = subprocess.run(
            [
                '/usr/bin/gdbus',
                'call',
                '--address',
                bus,
                '--dest',
                'org.freedesktop.DBus',
                '--object-path',
                '/org/freedesktop/DBus',
                '--method',
                'org.freedesktop.DBus.ListNames',
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except FileNotFoundError:
        _warn_display_env("gdbus missing; cannot connection-test cached AT-SPI bus before import")
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        _warn_display_env(f"cached AT-SPI bus connection test errored: {exc}")
        return False
    if result.returncode == 0:
        return True

    stderr = result.stderr.strip()
    _warn_display_env(f"cached AT-SPI bus connection rejected: {stderr or result.returncode}")
    return False


def _read_isolated_bus(display: str, bus_file: str):
    bus = _read_isolated_bus_file(bus_file)
    if bus and 'guid=' in bus and _a11y_bus_responds(bus):
        return bus

    if bus:
        reason = "missing guid" if 'guid=' not in bus else "connection rejected"
        _warn_display_env(f"cached AT-SPI bus for {display} needs refresh: {reason}")

    fresh_bus = _read_isolated_bus_xprop(display)
    if not fresh_bus:
        return bus

    try:
        _write_isolated_bus_file(bus_file, fresh_bus)
    except OSError as exc:
        _warn_display_env(f"could not rewrite {bus_file}: {exc}")
    return fresh_bus


def _setup_display_env(display: str):
    """Configure process environment for this display's AT-SPI bus."""
    os.environ['DISPLAY'] = display
    os.environ['GTK_USE_PORTAL'] = '0'

    # Worker IS the display — don't route through subprocess scanning.
    # Without this, find_firefox_for_platform() sees PLATFORM_DISPLAYS
    # (inherited from parent MCP server) and returns _RemoteFirefox
    # sentinels instead of using direct AT-SPI on our bus.
    os.environ.pop('PLATFORM_DISPLAYS', None)
    os.environ.pop('AT_SPI_BUS_ADDRESS', None)
    os.environ.pop('DBUS_SESSION_BUS_ADDRESS', None)

    bus_file = f'/tmp/a11y_bus_{display}'
    bus = _read_isolated_bus(display, bus_file)
    if bus:
        os.environ['AT_SPI_BUS_ADDRESS'] = bus
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = bus


def _reassert_worker_env():
    """Reapply isolated display env after .env loads or other mutations."""
    os.environ.pop('PLATFORM_DISPLAYS', None)
    _PLATFORM_DISPLAYS.clear()
    _setup_display_env(DISPLAY)


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
                _key = _key.strip()
                if _key in {
                    'DISPLAY', 'PLATFORM_DISPLAYS',
                    'AT_SPI_BUS_ADDRESS', 'DBUS_SESSION_BUS_ADDRESS',
                    'GTK_USE_PORTAL',
                }:
                    continue
                os.environ.setdefault(_key, _val.strip())

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
_reassert_worker_env()

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
                display=DISPLAY,
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

        elif cmd == 'get_send_button_state':
            return _get_send_button_state()

        elif cmd == 'get_content_hash':
            return _get_content_hash()

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

    _reassert_worker_env()

    firefox = atspi.find_firefox_for_platform(PLATFORM)
    if not firefox:
        firefox = atspi.find_firefox(PLATFORM)
    if not firefox:
        return {
            'stop_found': False,
            'error': 'Firefox not found',
            'display': os.environ.get('DISPLAY', ''),
        }

    doc = atspi.get_platform_document(firefox, PLATFORM)
    if not doc:
        return {'stop_found': False, 'error': 'Document not found'}

    config = get_platform_config(PLATFORM)
    stop_spec = config.get('element_map', {}).get('stop_button') or {}
    stop_role = stop_spec.get('role')
    stop_name = stop_spec.get('name')
    stop_names_any_of = stop_spec.get('names_any_of')

    if not isinstance(stop_role, str) or (
        not isinstance(stop_name, str)
        and not (
            isinstance(stop_names_any_of, list)
            and all(isinstance(item, str) for item in stop_names_any_of)
        )
    ):
        return {
            'stop_found': False,
            'error': f'Missing stop_button config for {PLATFORM}',
        }

    elements = []
    _scan_named_elements(doc, elements)
    stop_found = any(_spec_matches(element, stop_spec) for element in elements)
    return {'stop_found': stop_found, 'platform': PLATFORM}


def _get_monitor_document():
    """Get the active Firefox document for this worker platform."""
    from core import atspi

    _reassert_worker_env()

    firefox = atspi.find_firefox_for_platform(PLATFORM)
    if not firefox:
        firefox = atspi.find_firefox(PLATFORM)
    if not firefox:
        return None, None, {'error': 'Firefox not found'}

    doc = atspi.get_platform_document(firefox, PLATFORM)
    if not doc:
        return firefox, None, {'error': 'Document not found'}

    return firefox, doc, None


def _get_state_names(obj) -> set:
    try:
        state_set = obj.get_state_set()
    except Exception:
        return set()

    names = set()
    for state_name in ('showing', 'visible', 'enabled', 'editable',
                       'focusable', 'focused', 'selected', 'checked', 'pressed'):
        state = getattr(Atspi.StateType, state_name.upper(), None)
        if state and state_set.contains(state):
            names.add(state_name)
    return names


def _scan_named_elements(obj, elements, depth=0):
    if depth > 25:
        return
    try:
        name = (obj.get_name() or '').strip()
        role = obj.get_role_name() or ''
        if name:
            elements.append({
                'name': name,
                'role': role,
                'states': _get_state_names(obj),
            })
        for i in range(obj.get_child_count()):
            child = obj.get_child_at_index(i)
            if child:
                _scan_named_elements(child, elements, depth + 1)
    except Exception:
        return


def _value_matches(value: str, expected) -> bool:
    if expected is None:
        return True
    if isinstance(expected, list):
        return any(_value_matches(value, item) for item in expected)
    if isinstance(expected, str):
        return value == expected
    return False


def _spec_matches(element: dict, spec: dict) -> bool:
    name = (element.get('name') or '').strip()
    role = element.get('role') or ''
    states = set(element.get('states') or set())

    if 'name' in spec and not _value_matches(name, spec.get('name')):
        return False
    if 'names_any_of' in spec:
        names_any_of = spec.get('names_any_of')
        if isinstance(names_any_of, str):
            names_any_of = [names_any_of]
        if not any(_value_matches(name, candidate) for candidate in (names_any_of or [])):
            return False
    if 'name_contains' in spec:
        return False
    if 'name_pattern' in spec:
        patterns = spec.get('name_pattern')
        if isinstance(patterns, str):
            patterns = [patterns]
        if not any(fnmatch(name.lower(), pattern.lower()) for pattern in patterns):
            return False
    if 'role' in spec and role != spec.get('role'):
        return False
    if 'role_contains' in spec:
        return False
    required_states = set(spec.get('states_include') or [])
    if required_states and not required_states.issubset(states):
        return False
    return True


def _find_send_button(elements) -> dict:
    from core.config import get_platform_config

    config = get_platform_config(PLATFORM)
    element_map = config.get('element_map', {})
    send_keys = ('send_button', 'submit_button')
    candidates = [element_map[key] for key in send_keys if key in element_map]
    if not candidates:
        return {}

    for element in elements:
        for spec in candidates:
            if _spec_matches(element, spec):
                return element
    return {}


def _get_send_button_state() -> dict:
    """Report whether the send/submit button is visible and enabled."""
    _, doc, error = _get_monitor_document()
    if error:
        return {'send_visible': False, **error}

    elements = []
    _scan_named_elements(doc, elements)
    send_button = _find_send_button(elements)
    send_visible = bool(send_button) and 'enabled' in send_button.get('states', set())
    return {'send_visible': send_visible, 'platform': PLATFORM}


def _get_content_hash() -> dict:
    """Hash the visible document text snapshot for stability detection."""
    _, doc, error = _get_monitor_document()
    if error:
        return {'content_hash': '', **error}

    elements = []
    _scan_named_elements(doc, elements)

    chunks = []
    for element in elements:
        role = (element.get('role') or '').strip()
        name = (element.get('name') or '').strip()
        if not name:
            continue
        chunks.append(f"{role}:{name}")

    content_blob = "\n".join(chunks)
    content_hash = hashlib.sha256(content_blob.encode('utf-8')).hexdigest() if content_blob else ''
    return {'content_hash': content_hash, 'platform': PLATFORM}


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
