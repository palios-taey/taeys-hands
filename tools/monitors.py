"""taey_monitors, taey_respawn_monitor - Monitor session management."""

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
    """List or kill active monitor sessions."""
    if action == "list":
        sessions = []
        if redis_client:
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor, match=node_key("active_session:*"), count=100)
                for key in keys:
                    try:
                        data = redis_client.get(key)
                        if data:
                            sessions.append(json.loads(data))
                    except Exception:
                        pass
                if cursor == 0:
                    break
        # Also check plan lock
        plan_active = None
        if redis_client:
            plan_data = redis_client.get(node_key("plan_active"))
            if plan_data:
                try:
                    plan_active = json.loads(plan_data)
                except Exception:
                    plan_active = {"raw": plan_data}
        return {"success": True, "sessions": sessions, "count": len(sessions),
                "plan_active": plan_active}

    elif action == "kill":
        cleared = 0
        # Clear all active sessions from Redis
        if redis_client:
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor, match=node_key("active_session:*"), count=100)
                for key in keys:
                    redis_client.delete(key)
                    cleared += 1
                if cursor == 0:
                    break
            # Also clear legacy monitor keys and notifications
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor, match=node_key("monitor:*"), count=100)
                for key in keys:
                    redis_client.delete(key)
                    cleared += 1
                if cursor == 0:
                    break
            redis_client.delete(node_key("notifications"))
            redis_client.delete(node_key("plan_active"))

        # Kill any legacy daemon processes still running
        killed = 0
        try:
            r = subprocess.run(['pgrep', '-f', 'monitor.*daemon'],
                              capture_output=True, text=True)
            for pid in (r.stdout.strip().split('\n') if r.stdout.strip() else []):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    killed += 1
                except (ProcessLookupError, ValueError):
                    pass
        except Exception:
            pass

        return {"success": True, "sessions_cleared": cleared,
                "legacy_processes_killed": killed}

    return {"error": f"Unknown action '{action}'. Use 'list' or 'kill'."}


def handle_respawn_monitor(platform: str, redis_client,
                           display: str) -> Dict[str, Any]:
    """Register fresh monitor session for multi-step response flows."""
    from tools.send import register_monitor_session

    session_id = user_message_id = url = None
    if redis_client:
        pending_json = redis_client.get(node_key(f"pending_prompt:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
                session_id = pending.get('session_id')
                user_message_id = pending.get('message_id')
                url = pending.get('session_url')
            except (json.JSONDecodeError, TypeError):
                pass

    monitor_id = str(uuid.uuid4())[:8]
    result = register_monitor_session(
        platform=platform, monitor_id=monitor_id, url=url,
        redis_client=redis_client, session_id=session_id,
        user_message_id=user_message_id,
    )

    if result.get("registered"):
        return {
            "success": True, "platform": platform,
            "monitor": {"id": monitor_id, "registered": True},
            "session_id": session_id,
            "note": f"Monitor session registered for {platform}.",
        }
    return {
        "success": False, "platform": platform,
        "error": f"Failed to register session: {result.get('error')}",
        "hint": "Use taey_quick_extract manually when response is ready.",
    }
