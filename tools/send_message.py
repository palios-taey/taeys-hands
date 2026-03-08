"""
taey_send_message - Paste text, send, record, spawn monitor.

A primitive: pastes message into whatever is focused, records in Neo4j,
spawns a monitor daemon. Claude must click the input field first via
taey_click before calling this.

On CHAT platforms (ChatGPT, Claude, Gemini, Grok, Perplexity):
  Presses Enter to send after pasting.

On SOCIAL platforms (X/Twitter, LinkedIn):
  Does NOT press Enter (Enter = newline in DraftJS compose).
  Returns action_required flag — caller must click Post/Reply button.
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
from core.platforms import SOCIAL_PLATFORMS
from storage import neo4j_client
from storage.redis_pool import node_key, NODE_ID

logger = logging.getLogger(__name__)

# Track spawned daemon processes for zombie reaping
_daemon_processes = []


def _reap_daemons():
    """Clean up finished daemon processes to prevent zombies."""
    global _daemon_processes
    _daemon_processes = [p for p in _daemon_processes if p.poll() is None]


def spawn_monitor_daemon(platform: str, monitor_id: str, display: str,
                         session_id: str = None, user_message_id: str = None,
                         timeout: int = 3600, settle_seconds: int = 0) -> Dict[str, Any]:
    """Spawn a monitor daemon as a detached subprocess.

    Reusable by monitors.py for respawn scenarios (Gemini Deep Research,
    Claude Continue, ChatGPT Show More).

    Returns:
        Dict with spawned, pid, log path, or error.
    """
    daemon_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'monitor', 'daemon.py',
    )
    import sys as _sys
    python_bin = _sys.executable or '/usr/bin/python3'
    daemon_cmd = [
        python_bin, daemon_path,
        '--platform', platform,
        '--monitor-id', monitor_id,
        '--baseline-copy-count', '0',
        '--timeout', str(timeout),
        '--tmux-session', NODE_ID,
    ]
    if session_id:
        daemon_cmd.extend(['--session-id', session_id])
    if user_message_id:
        daemon_cmd.extend(['--user-message-id', user_message_id])
    if settle_seconds > 0:
        daemon_cmd.extend(['--settle-seconds', str(settle_seconds)])

    _reap_daemons()

    daemon_env = os.environ.copy()
    daemon_env['DISPLAY'] = display

    try:
        log_file = f"/tmp/taey_daemon_{monitor_id}.log"
        # Open with os.open so subprocess inherits the fd.
        # Do NOT close in parent — Popen(..., close_fds=False) keeps it open
        # for the child. On macOS, closing before the child writes = 0-byte log.
        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        proc = subprocess.Popen(
            daemon_cmd, env=daemon_env,
            stdout=log_fd, stderr=log_fd,
            close_fds=False,
            start_new_session=True,
        )
        os.close(log_fd)  # Safe to close AFTER Popen has dup'd the fd
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
            logger.warning("Neo4j unavailable for session tracking: %s", e)

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
    spawn_result = spawn_monitor_daemon(
        platform=platform,
        monitor_id=monitor_id,
        display=display,
        session_id=session_id,
        user_message_id=message_id,
    )
    daemon_spawned = spawn_result.get("spawned", False)
    daemon_pid = spawn_result.get("pid")
    daemon_log_path = spawn_result.get("log")

    # Step 6: Press Enter to send (SKIP on social platforms where Enter = newline)
    enter_pressed = False
    if platform not in SOCIAL_PLATFORMS:
        if not inp.press_key('Return', timeout=5):
            if daemon_spawned and daemon_pid:
                try:
                    os.kill(daemon_pid, 15)  # SIGTERM
                except (ProcessLookupError, OSError):
                    pass
            return {"error": "Send (Enter key) failed", "platform": platform, "neo4j": neo4j_result}
        enter_pressed = True

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

    if not enter_pressed:
        result["action_required"] = (
            "Text pasted but NOT sent. On social platforms (X, LinkedIn), "
            "Enter creates a newline. You MUST click the Post/Reply button "
            "to submit. Use taey_inspect to find the button, then taey_click."
        )

    if not daemon_spawned:
        result["warning"] = "Monitor daemon FAILED to spawn. Use taey_quick_extract manually."

    return result
