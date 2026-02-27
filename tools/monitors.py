"""
taey_list_monitors, taey_kill_monitors - Monitor daemon management.

Lists running background monitor daemons and provides emergency
stop capability to kill all monitors.
"""

import json
import os
import signal
import subprocess
import logging
from typing import Any, Dict

from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def handle_list_monitors(redis_client) -> Dict[str, Any]:
    """List all active background monitor daemons.

    Checks Redis for monitor status entries.

    Args:
        redis_client: Redis client.

    Returns:
        List of monitor statuses.
    """
    monitors = []

    if redis_client:
        # Scan for monitor keys
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match="taey:monitor:*", count=100)
            for key in keys:
                try:
                    data = redis_client.get(key)
                    if data:
                        monitor = json.loads(data)
                        monitors.append(monitor)
                except (json.JSONDecodeError, Exception):
                    pass
            if cursor == 0:
                break

    return {
        "success": True,
        "monitors": monitors,
        "count": len(monitors),
    }


def handle_kill_monitors(redis_client) -> Dict[str, Any]:
    """Emergency stop: kill ALL background monitor daemons.

    1. Kill tracked daemon processes
    2. Kill orphaned monitor_daemon.py processes
    3. Clear all monitor entries from Redis

    Args:
        redis_client: Redis client.

    Returns:
        Count of processes killed and Redis entries cleared.
    """
    killed = 0
    cleared = 0

    # Kill orphaned monitor_daemon.py processes
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'monitor.*daemon'],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    killed += 1
                except (ProcessLookupError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"pgrep failed: {e}")

    # Clear Redis monitor entries
    if redis_client:
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match="taey:monitor:*", count=100)
            for key in keys:
                redis_client.delete(key)
                cleared += 1
            if cursor == 0:
                break

        # Clear notification queue
        redis_client.delete(node_key("notifications"))

    return {
        "success": True,
        "processes_killed": killed,
        "redis_entries_cleared": cleared,
    }
