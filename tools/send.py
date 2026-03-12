"""taey_send_message - Paste, send, record, spawn monitor."""

import json
import os
import subprocess
import time
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List

from core import atspi, input as inp
from core.platforms import SOCIAL_PLATFORMS
from storage import neo4j_client
from storage.redis_pool import node_key, NODE_ID

logger = logging.getLogger(__name__)

_daemon_processes = []
_reap_counter = 0


def _reap_daemons():
    global _daemon_processes
    _daemon_processes = [p for p in _daemon_processes if p.poll() is None]


def spawn_monitor_daemon(platform: str, monitor_id: str, display: str,
                         session_id: str = None, user_message_id: str = None,
                         timeout: int = 3600, settle_seconds: int = 0) -> Dict[str, Any]:
    """Spawn monitor daemon as detached subprocess."""
    daemon_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'monitor', 'daemon.py',
    )
    import sys as _sys
    cmd = [
        _sys.executable or '/usr/bin/python3', daemon_path,
        '--platform', platform, '--monitor-id', monitor_id,
        '--baseline-copy-count', '0', '--timeout', str(timeout),
        '--tmux-session', NODE_ID,
    ]
    if session_id:
        cmd.extend(['--session-id', session_id])
    if user_message_id:
        cmd.extend(['--user-message-id', user_message_id])
    if settle_seconds > 0:
        cmd.extend(['--settle-seconds', str(settle_seconds)])

    _reap_daemons()
    env = os.environ.copy()
    env['DISPLAY'] = display

    try:
        log_file = f"/tmp/taey_daemon_{monitor_id}.log"
        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        proc = subprocess.Popen(
            cmd, env=env, stdout=log_fd, stderr=log_fd,
            close_fds=True, pass_fds=(log_fd,), start_new_session=True,
        )
        os.close(log_fd)
        _daemon_processes.append(proc)
        return {"spawned": True, "pid": proc.pid, "log": log_file}
    except Exception as e:
        logger.error(f"Daemon spawn failed: {e}")
        return {"spawned": False, "error": str(e)}


def handle_send_message(platform: str, message: str,
                        redis_client, display: str,
                        attachments: List[str] = None,
                        session_type: str = None,
                        purpose: str = None) -> Dict[str, Any]:
    """Paste message, press Enter, record in Neo4j, spawn monitor."""
    global _reap_counter
    _reap_counter += 1
    if _reap_counter % 10 == 0:
        _reap_daemons()

    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform}", "platform": platform}
    time.sleep(0.5)

    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    if not doc:
        return {"error": f"Could not find {platform} document", "platform": platform}
    url = atspi.get_document_url(doc)

    if not inp.clipboard_paste(message):
        return {"error": f"Failed to paste message", "platform": platform}
    time.sleep(0.2)

    # Neo4j storage
    neo4j_result = session_id = message_id = None
    if url:
        try:
            session_id = neo4j_client.get_or_create_session(platform, url)
            if session_id:
                if session_type or purpose:
                    neo4j_client.update_session(session_id, {
                        k: v for k, v in {'session_type': session_type, 'purpose': purpose}.items() if v
                    })
                message_id = neo4j_client.add_message(session_id, 'user', message, attachments)
                neo4j_result = {"session_id": session_id, "message_id": message_id}
        except Exception as e:
            logger.warning("Neo4j unavailable: %s", e)

    # Redis pending_prompt
    if redis_client:
        redis_client.setex(node_key(f"pending_prompt:{platform}"), 3600, json.dumps({
            'content': message, 'attachments': attachments or [],
            'session_url': url, 'session_id': session_id,
            'message_id': message_id, 'sent_at': datetime.now().isoformat(),
        }))

    # Spawn monitor BEFORE Enter (chat platforms only)
    monitor_id = str(uuid.uuid4())[:8]
    daemon_spawned = daemon_pid = daemon_log_path = None

    if platform not in SOCIAL_PLATFORMS:
        spawn_result = spawn_monitor_daemon(
            platform=platform, monitor_id=monitor_id, display=display,
            session_id=session_id, user_message_id=message_id,
        )
        daemon_spawned = spawn_result.get("spawned", False)
        daemon_pid = spawn_result.get("pid")
        daemon_log_path = spawn_result.get("log")

    # Press Enter (skip on social platforms where Enter = newline)
    enter_pressed = False
    if platform not in SOCIAL_PLATFORMS:
        if not inp.press_key('Return', timeout=5):
            if daemon_spawned and daemon_pid:
                try:
                    os.kill(daemon_pid, 15)
                except (ProcessLookupError, OSError):
                    pass
            return {"error": "Send (Enter) failed", "platform": platform, "neo4j": neo4j_result}
        enter_pressed = True

    result = {
        "platform": platform, "url": url, "message_length": len(message),
        "neo4j": neo4j_result,
        "monitor": {"id": monitor_id, "spawned": daemon_spawned,
                     "pid": daemon_pid, "log": daemon_log_path},
    }

    if not enter_pressed:
        result["action_required"] = (
            "Text pasted but NOT sent. On social platforms, Enter = newline. "
            "Click the Post/Reply button via taey_inspect + taey_click."
        )
    if not daemon_spawned:
        result["warning"] = "Monitor daemon FAILED to spawn. Use taey_quick_extract manually."

    return result
