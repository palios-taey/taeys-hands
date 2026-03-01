"""
taey_list_monitors, taey_kill_monitors, taey_respawn_monitor - Monitor daemon management.

Lists running background monitor daemons, provides emergency
stop capability, and respawns monitors for multi-step response flows.
"""

import json
import os
import signal
import subprocess
import uuid
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


def handle_respawn_monitor(platform: str, redis_client, display: str) -> Dict[str, Any]:
    """Spawn a fresh monitor daemon for multi-step response flows.

    Used when the first daemon has exited after detecting the initial
    response cycle, but a second generation cycle is expected:
    - Gemini Deep Research: plan card -> click "Start research" -> actual research
    - Claude Continue: truncated response -> click Continue -> rest of response
    - ChatGPT Show More: collapsed -> expand -> full content

    Reads pending_prompt from Redis to maintain session/message linkage.

    Args:
        platform: Which platform to monitor.
        redis_client: Redis client.
        display: X display string.

    Returns:
        Dict with new monitor info.
    """
    from tools.send_message import spawn_monitor_daemon

    # Read existing pending_prompt for session linkage
    session_id = None
    user_message_id = None
    if redis_client:
        pending_json = redis_client.get(node_key(f"pending_prompt:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
                session_id = pending.get('session_id')
                user_message_id = pending.get('message_id')
            except (json.JSONDecodeError, TypeError):
                pass

    monitor_id = str(uuid.uuid4())[:8]

    result = spawn_monitor_daemon(
        platform=platform,
        monitor_id=monitor_id,
        display=display,
        session_id=session_id,
        user_message_id=user_message_id,
    )

    if result.get("spawned"):
        return {
            "success": True,
            "platform": platform,
            "monitor": {
                "id": monitor_id,
                "spawned": True,
                "pid": result["pid"],
                "log": result["log"],
            },
            "session_id": session_id,
            "note": f"Fresh monitor spawned for {platform}. Will notify when response completes.",
        }
    else:
        return {
            "success": False,
            "platform": platform,
            "error": f"Failed to spawn monitor: {result.get('error')}",
            "hint": "Use taey_quick_extract manually when response is ready.",
        }
