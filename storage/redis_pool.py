"""Redis connection pool with instance-scoped keys."""

import os
import logging
import socket
import subprocess
from typing import Optional

import redis

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.environ.get('REDIS_PORT', 6379))

_pool: Optional[redis.ConnectionPool] = None
_client: Optional[redis.Redis] = None


def get_pool() -> redis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool(
            host=DEFAULT_HOST, port=DEFAULT_PORT,
            decode_responses=True, max_connections=20,
            socket_timeout=5.0, socket_connect_timeout=5.0,
            retry_on_timeout=False,
        )
    return _pool


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        try:
            _client = redis.Redis(connection_pool=get_pool())
            _client.ping()
        except Exception as e:
            _client = None
            raise ConnectionError(f"Redis connection failed: {e}") from e
    return _client


def _load_env_file() -> dict:
    """Try loading .env from project root. Returns dict of key=value pairs."""
    # Walk up from this file (storage/redis_pool.py) to find project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, '.env')
    result = {}
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        result[k.strip()] = v.strip()
        except Exception:
            pass
    return result


def _detect_node_id() -> str:
    """TAEY_NODE_ID env > .env file > display-scoped auto-id > tmux session > hostname.

    Priority order:
      1. TAEY_NODE_ID environment variable (set by caller or .mcp.json)
      2. TAEY_NODE_ID from .env file (standalone scripts may not have loaded it yet)
      3. Display-scoped auto-id (taeys-hands-d{N}) for multi-instance collision prevention
      4. tmux session name
      5. hostname

    The .env fallback (step 2) is critical for standalone scripts like
    consultation.py and monitor/central.py that run outside the MCP server
    process. Without it, they generate different node IDs than the MCP
    server and PostToolUse hooks, breaking Redis key lookups.
    """
    explicit = os.environ.get('TAEY_NODE_ID')
    if explicit:
        return explicit

    # Try loading from .env — standalone scripts may not have loaded it yet.
    # This is the most common case for node ID mismatch: MCP server gets
    # TAEY_NODE_ID from .mcp.json, but consultation.py/monitor don't.
    env_vars = _load_env_file()
    env_node_id = env_vars.get('TAEY_NODE_ID')
    if env_node_id:
        # Also set it in the environment so downstream code sees it
        os.environ['TAEY_NODE_ID'] = env_node_id
        return env_node_id

    # Auto-scope by DISPLAY if available — prevents multi-instance collision
    display = os.environ.get('DISPLAY', '')
    if display:
        display_num = display.lstrip(':')
        if display_num.isdigit():
            return f"taeys-hands-d{display_num}"
    try:
        tty = _find_ancestor_tty()
        if tty:
            r = subprocess.run(
                ['tmux', 'list-panes', '-a', '-F', '#{pane_tty} #{session_name}'],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    parts = line.split(' ', 1)
                    if len(parts) == 2 and parts[0] == tty:
                        return parts[1]
    except Exception:
        pass
    try:
        r = subprocess.run(['tmux', 'display-message', '-p', '#S'],
                           capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return socket.gethostname()


def _find_ancestor_tty() -> str:
    """Walk process tree to find nearest ancestor with a real TTY."""
    pid = os.getpid()
    for _ in range(10):
        try:
            with open(f'/proc/{pid}/stat') as f:
                stat = f.read()
            after_comm = stat[stat.rfind(')') + 2:]
            pid = int(after_comm.split()[1])
            if pid <= 1:
                break
            fd0 = os.readlink(f'/proc/{pid}/fd/0')
            if fd0.startswith('/dev/pts/') or fd0.startswith('/dev/tty'):
                return fd0
        except Exception:
            break
    return ''


_NODE_ID = _detect_node_id()
NODE_ID = _NODE_ID
logger.info("Redis node ID: %s", _NODE_ID)


def node_key(suffix: str) -> str:
    """Instance-scoped Redis key: taey:{node_id}:{suffix}."""
    return f"taey:{_NODE_ID}:{suffix}"
