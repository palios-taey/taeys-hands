"""
taey_send_message - Paste text, send, record, spawn monitor.

A primitive: pastes message into whatever is focused, presses Enter,
records in Neo4j, spawns a monitor daemon. Claude must click the
input field first via taey_click before calling this.
"""

import json
import os
import subprocess
import time
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List

from core import atspi, input as inp
from storage import neo4j_client
from storage.redis_pool import node_key, NODE_ID

logger = logging.getLogger(__name__)

# Track spawned daemon processes for zombie reaping
_daemon_processes = []


def _reap_daemons():
    """Clean up finished daemon processes to prevent zombies."""
    global _daemon_processes
    _daemon_processes = [p for p in _daemon_processes if p.poll() is None]


def handle_send_message(platform: str, message: str,
                        redis_client, display: str,
                        attachments: List[str] = None,
                        session_type: str = None,
                        purpose: str = None) -> Dict[str, Any]:
    """Paste message, press Enter, record in Neo4j, spawn monitor.

    PRECONDITION: Claude has already clicked the input field via taey_click.
    This tool does NOT click the input - it pastes into whatever is focused.

    Flow:
    1. Switch to platform tab, get document/URL
    2. Clipboard paste message
    3. Neo4j: get_or_create_session, add_message
    4. Redis: store pending_prompt
    5. Spawn monitor daemon BEFORE Enter (avoids race condition)
    6. Press Enter to send
    7. Invalidate stored map (UI mutated)
    """
    # Step 1: Switch to platform, get document + URL
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform}", "platform": platform}
    time.sleep(0.5)

    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    if not doc:
        return {"error": f"Could not find {platform} document", "platform": platform}

    url = atspi.get_document_url(doc)

    # Step 2: Clipboard paste message into focused input
    if not inp.clipboard_paste(message):
        return {"error": f"Failed to paste message into {platform} input", "platform": platform}
    time.sleep(0.2)

    # Step 3: Store in Neo4j
    neo4j_result = None
    session_id = None
    message_id = None

    if url:
        session_id = neo4j_client.get_or_create_session(platform, url)
        if session_id:
            if session_type or purpose:
                neo4j_client.update_session(session_id, {
                    k: v for k, v in {'session_type': session_type, 'purpose': purpose}.items() if v
                })
            message_id = neo4j_client.add_message(session_id, 'user', message, attachments)
            neo4j_result = {"session_id": session_id, "message_id": message_id}

    # Step 4: Store pending_prompt in Redis for extract linkage
    if redis_client:
        redis_client.setex(node_key(f"pending_prompt:{platform}"), 3600, json.dumps({
            'content': message,
            'attachments': attachments or [],
            'session_url': url,
            'session_id': session_id,
            'message_id': message_id,
            'sent_at': datetime.now().isoformat(),
        }))

    # Step 5: Spawn monitor daemon BEFORE Enter
    monitor_id = str(uuid.uuid4())[:8]
    daemon_timeout = 3600  # 1 hour default

    daemon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'monitor', 'daemon.py')
    daemon_cmd = [
        '/usr/bin/python3', daemon_path,
        '--platform', platform,
        '--monitor-id', monitor_id,
        '--baseline-copy-count', '0',
        '--timeout', str(daemon_timeout),
        '--tmux-session', NODE_ID,
    ]
    if session_id:
        daemon_cmd.extend(['--session-id', session_id])
    if message_id:
        daemon_cmd.extend(['--user-message-id', message_id])

    _reap_daemons()

    daemon_env = os.environ.copy()
    daemon_env['DISPLAY'] = display
    daemon_spawned = False
    daemon_pid = None
    daemon_log_path = None

    try:
        log_file = f"/tmp/taey_daemon_{monitor_id}.log"
        daemon_log = open(log_file, 'w')
        proc = subprocess.Popen(
            daemon_cmd, env=daemon_env,
            stdout=daemon_log, stderr=daemon_log,
            start_new_session=True,
        )
        daemon_log.close()
        daemon_spawned = True
        daemon_pid = proc.pid
        daemon_log_path = log_file
        _daemon_processes.append(proc)
    except Exception as e:
        logger.error(f"Daemon spawn failed: {e}")

    # Step 6: Press Enter to send
    if not inp.press_key('Return', timeout=5):
        if daemon_spawned and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        return {"error": "Send (Enter key) failed", "platform": platform, "neo4j": neo4j_result}

    # Step 7: Invalidate stored map (UI mutated after send)
    if redis_client:
        redis_client.delete(node_key("current_map"))

    result = {
        "platform": platform,
        "url": url,
        "message_length": len(message),
        "neo4j": neo4j_result,
        "monitor": {
            "id": monitor_id,
            "spawned": daemon_spawned,
            "pid": daemon_pid,
            "log": daemon_log_path,
        },
    }

    if not daemon_spawned:
        result["warning"] = "Monitor daemon FAILED to spawn. Use taey_quick_extract manually."

    return result
