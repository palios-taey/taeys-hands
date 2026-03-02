"""
Redis connection pool with host auto-detection.

Provides a singleton connection pool to prevent TCP TIME_WAIT
accumulation under high connection churn.

Configure via environment variables (see module-level constants below).
"""

import os
import logging
import socket
import subprocess
from typing import Optional

import redis

logger = logging.getLogger(__name__)

# Connection defaults — override via environment variables
DEFAULT_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
DEFAULT_PORT = int(os.environ.get('REDIS_PORT', 6379))

_pool: Optional[redis.ConnectionPool] = None
_client: Optional[redis.Redis] = None


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


# Instance-scoped key prefix


def _detect_node_id() -> str:
    """Auto-detect instance ID: TAEY_NODE_ID > tmux session > hostname."""
    explicit = os.environ.get('TAEY_NODE_ID')
    if explicit:
        return explicit
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

_NODE_ID = _detect_node_id()
NODE_ID = _NODE_ID


def node_key(suffix: str) -> str:
    """Instance-scoped Redis key: taey:{node_id}:{suffix}."""
    return f"taey:{_NODE_ID}:{suffix}"
