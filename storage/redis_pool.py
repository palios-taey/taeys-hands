"""
Redis connection pool with host auto-detection and node-scoped keys.

Provides a singleton connection pool to prevent TCP TIME_WAIT
accumulation that crashed the Mac network stack (Jan 17, 2026).

Node-scoped keys prevent collision when multiple machines
(Spark, Jetson, Thor) share the same Redis instance.
"""

import os
import socket
import subprocess
import platform as _platform
import logging
from typing import Optional

import redis

logger = logging.getLogger(__name__)

# Auto-detect host based on OS
# Mac uses management network (10.0.0.x)
# Linux (Spark) uses NCCL fabric (192.168.100.x)
if _platform.system() == 'Darwin':
    DEFAULT_HOST = os.environ.get('REDIS_HOST', '10.x.x.68')
else:
    DEFAULT_HOST = os.environ.get('REDIS_HOST', '192.168.x.10')

DEFAULT_PORT = int(os.environ.get('REDIS_PORT', 6379))


def _detect_node_id() -> str:
    """Auto-detect a unique instance ID for Redis key scoping.

    Priority:
    1. TAEY_NODE_ID env var (explicit override)
    2. tmux session name (auto-isolates per tmux session)
    3. hostname (fallback — one instance per machine only)
    """
    explicit = os.environ.get('TAEY_NODE_ID')
    if explicit:
        return explicit

    # tmux session name: each Claude session runs in its own tmux,
    # so this naturally isolates taeys-hands vs taey-ed on same machine.
    try:
        result = subprocess.run(
            ['tmux', 'display-message', '-p', '#S'],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    return socket.gethostname()


NODE_ID = _detect_node_id()

_pool: Optional[redis.ConnectionPool] = None
_client: Optional[redis.Redis] = None


def node_key(suffix: str) -> str:
    """Return an instance-scoped Redis key.

    Prevents key collision between MCP server instances sharing Redis.
    Works across machines (Spark/Jetson/Thor) and across sessions on
    the same machine (taeys-hands/taey-ed).

    Args:
        suffix: Key suffix (e.g., 'current_map', 'pending_prompt:claude').

    Returns:
        Full key like 'taey:taeys-hands:current_map'.
    """
    return f"taey:{NODE_ID}:{suffix}"


def get_pool() -> redis.ConnectionPool:
    """Get or create the shared connection pool."""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool(
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            decode_responses=True,
            max_connections=20,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
        )
    return _pool


def get_client() -> redis.Redis:
    """Get the shared Redis client using the connection pool.

    Returns:
        Redis client.

    Raises:
        ConnectionError: If Redis is not available.
    """
    global _client
    if _client is None:
        try:
            _client = redis.Redis(connection_pool=get_pool())
            _client.ping()
        except Exception as e:
            _client = None
            raise ConnectionError(f"Redis connection failed: {e}") from e
    return _client
