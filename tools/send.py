"""taey_send_message - Paste, send, record, register monitor session."""

import json
import os
import subprocess
import sys
import time
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from core import atspi, input as inp
from core.platforms import SOCIAL_PLATFORMS
from storage import neo4j_client
from storage.redis_pool import node_key, NODE_ID

logger = logging.getLogger(__name__)



def _validate_send_requirements(platform: str, redis_client) -> Optional[str]:
    """Check that plan-required attachments were actually attached.

    Returns None if OK, or an error string if send should be blocked.
    """
    if not redis_client:
        return None

    # Get active plan for this platform
    plan_id = redis_client.get(node_key(f"plan:current:{platform}"))
    if not plan_id:
        return None  # No active plan — nothing to validate

    plan_data = redis_client.get(node_key(f"plan:{plan_id}"))
    if not plan_data:
        return None

    try:
        plan = json.loads(plan_data)
    except (json.JSONDecodeError, TypeError):
        return None

    required_attachments = plan.get('attachments', [])
    if not required_attachments:
        return None  # No attachments required

    # Check attach checkpoint exists
    checkpoint_raw = redis_client.get(node_key(f"checkpoint:{platform}:attach"))
    if not checkpoint_raw:
        return (f"Plan {plan_id} requires {len(required_attachments)} attachment(s) "
                f"but no attach checkpoint found. Attach files before sending.")

    try:
        checkpoint = json.loads(checkpoint_raw)
    except (json.JSONDecodeError, TypeError):
        return (f"Plan {plan_id} requires attachments but checkpoint is corrupt. "
                f"Re-attach files before sending.")

    logger.info("Send validation passed: plan=%s, attachments=%d, checkpoint=%s",
                plan_id, len(required_attachments), checkpoint.get('file', 'unknown'))
    return None


def _ensure_central_monitor(display: str):
    """Ensure the central monitor process is running. Spawn if not."""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'monitor.central'],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            return  # already running
    except Exception:
        pass

    # Spawn central monitor as detached process
    monitor_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_file = '/tmp/central_monitor.log'
    try:
        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        env = os.environ.copy()
        env['DISPLAY'] = display
        subprocess.Popen(
            [sys.executable, '-m', 'monitor.central', '--cycle-interval', '10'],
            cwd=monitor_dir,
            env=env,
            stdout=log_fd, stderr=log_fd,
            close_fds=True, start_new_session=True,
        )
        os.close(log_fd)
        logger.info("Central monitor spawned (display=%s)", display)
    except Exception as e:
        logger.warning("Failed to spawn central monitor: %s", e)


def register_monitor_session(platform: str, monitor_id: str, url: str,
                             redis_client, session_id: str = None,
                             user_message_id: str = None,
                             tmux_session: str = None,
                             timeout: int = 3600) -> Dict[str, Any]:
    """Register active session for the central monitor to track."""
    if not redis_client:
        return {"registered": False, "error": "Redis not available"}

    session_data = {
        "platform": platform,
        "monitor_id": monitor_id,
        "url": url or "",
        "session_id": session_id,
        "user_message_id": user_message_id,
        "tmux_session": tmux_session or NODE_ID,
        "stop_seen": False,
        "generating_since": None,
        "started_ts": time.time(),
        "timeout": timeout,
        "started": datetime.now().isoformat(),
    }

    try:
        redis_client.setex(
            node_key(f"active_session:{monitor_id}"),
            timeout,
            json.dumps(session_data),
        )
        return {"registered": True, "monitor_id": monitor_id}
    except Exception as e:
        logger.error(f"Session registration failed: {e}")
        return {"registered": False, "error": str(e)}


def handle_send_message(platform: str, message: str,
                        redis_client, display: str,
                        attachments: List[str] = None,
                        session_type: str = None,
                        purpose: str = None) -> Dict[str, Any]:
    """Paste message, press Enter, record in Neo4j, register monitor session."""
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

    # Register monitor session BEFORE Enter (chat platforms only)
    monitor_id = str(uuid.uuid4())[:8]
    monitor_registered = False

    if platform not in SOCIAL_PLATFORMS:
        _ensure_central_monitor(display)
        reg = register_monitor_session(
            platform=platform, monitor_id=monitor_id, url=url,
            redis_client=redis_client, session_id=session_id,
            user_message_id=message_id,
        )
        monitor_registered = reg.get("registered", False)

    # Validate plan requirements before sending
    if platform not in SOCIAL_PLATFORMS:
        validation_error = _validate_send_requirements(platform, redis_client)
        if validation_error:
            return {"error": validation_error, "platform": platform,
                    "action": "attach_missing", "neo4j": neo4j_result}

    # Press Enter (skip on social platforms where Enter = newline)
    enter_pressed = False
    if platform not in SOCIAL_PLATFORMS:
        if not inp.press_key('Return', timeout=5):
            # Clean up monitor session on send failure
            if monitor_registered and redis_client:
                redis_client.delete(node_key(f"active_session:{monitor_id}"))
            return {"error": "Send (Enter) failed", "platform": platform, "neo4j": neo4j_result}
        enter_pressed = True

    # Re-capture URL after redirect (landing pages redirect to conversation URL)
    if enter_pressed:
        for _attempt in range(5):
            time.sleep(1)
            try:
                new_url = atspi.get_document_url(doc)
                if new_url and new_url != url:
                    logger.info("URL redirect: %s → %s", url[:60], new_url[:60])
                    url = new_url
                    # Update pending_prompt with conversation URL
                    if redis_client:
                        redis_client.setex(node_key(f"pending_prompt:{platform}"), 3600, json.dumps({
                            'content': message, 'attachments': attachments or [],
                            'session_url': url, 'session_id': session_id,
                            'message_id': message_id, 'sent_at': datetime.now().isoformat(),
                        }))
                    # Update monitor session with conversation URL
                    if monitor_registered and redis_client:
                        sess_key = node_key(f"active_session:{monitor_id}")
                        raw = redis_client.get(sess_key)
                        if raw:
                            sess_data = json.loads(raw)
                            sess_data['url'] = url
                            ttl = redis_client.ttl(sess_key)
                            if ttl > 0:
                                redis_client.setex(sess_key, ttl, json.dumps(sess_data))
                    break
            except Exception as e:
                logger.debug("URL re-capture attempt %d: %s", _attempt, e)

    # Clear global plan lock — send complete, monitor can resume cycling
    if redis_client:
        redis_client.delete("taey:plan_active")

    result = {
        "platform": platform, "url": url, "message_length": len(message),
        "neo4j": neo4j_result,
        "monitor": {"id": monitor_id, "registered": monitor_registered},
    }

    if not enter_pressed:
        result["action_required"] = (
            "Text pasted but NOT sent. On social platforms, Enter = newline. "
            "Click the Post/Reply button via taey_inspect + taey_click."
        )
    if not monitor_registered:
        result["warning"] = "Monitor session NOT registered. Use taey_quick_extract manually."

    return result
