"""taey_monitors, taey_respawn_monitor - Monitor daemon management."""

import json
import os
import signal
import subprocess
import uuid
import logging
from typing import Any, Dict

from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def handle_monitors(action: str, redis_client) -> Dict[str, Any]:
    """List or kill background monitor daemons."""
    if action == "list":
        monitors = []
        if redis_client:
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor, match=node_key("monitor:") + "*", count=100)
                for key in keys:
                    try:
                        data = redis_client.get(key)
                        if data:
                            monitors.append(json.loads(data))
                    except Exception:
                        pass
                if cursor == 0:
                    break
        return {"success": True, "monitors": monitors, "count": len(monitors)}

    elif action == "kill":
        killed, cleared = 0, 0
        try:
            r = subprocess.run(['pgrep', '-f', 'monitor.*daemon'],
                              capture_output=True, text=True)
            for pid in (r.stdout.strip().split('\n') if r.stdout.strip() else []):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    killed += 1
                except (ProcessLookupError, ValueError):
                    pass
        except Exception as e:
            logger.warning(f"pgrep failed: {e}")

        if redis_client:
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor, match=node_key("monitor:") + "*", count=100)
                for key in keys:
                    redis_client.delete(key)
                    cleared += 1
                if cursor == 0:
                    break
            redis_client.delete(node_key("notifications"))

        return {"success": True, "processes_killed": killed,
                "redis_entries_cleared": cleared}

    return {"error": f"Unknown action '{action}'. Use 'list' or 'kill'."}


def handle_respawn_monitor(platform: str, redis_client,
                           display: str) -> Dict[str, Any]:
    """Spawn fresh monitor daemon for multi-step response flows."""
    from tools.send import spawn_monitor_daemon

    session_id = user_message_id = None
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
        platform=platform, monitor_id=monitor_id, display=display,
        session_id=session_id, user_message_id=user_message_id)

    if result.get("spawned"):
        return {
            "success": True, "platform": platform,
            "monitor": {"id": monitor_id, "spawned": True,
                        "pid": result["pid"], "log": result["log"]},
            "session_id": session_id,
            "note": f"Fresh monitor spawned for {platform}.",
        }
    return {
        "success": False, "platform": platform,
        "error": f"Failed to spawn monitor: {result.get('error')}",
        "hint": "Use taey_quick_extract manually when response is ready.",
    }
