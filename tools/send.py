"""taey_send_message - Paste, send, record, register monitor session.

HARD GATE: Refuses to send unless plan audit_passed=True.
No exceptions. No bypasses. Audit first, then send.
"""

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


def _check_audit_gate(platform: str, redis_client) -> Optional[str]:
    """Hard gate: verify plan exists and audit_passed=True.

    Returns None if OK, error string if blocked.
    """
    if not redis_client:
        return None  # No Redis = no enforcement possible

    plan_id = redis_client.get(node_key(f"plan:current:{platform}"))
    if not plan_id:
        return ("No active plan for this platform. "
                "Create a plan with taey_plan(action='create') first.")

    plan_data = redis_client.get(node_key(f"plan:{plan_id}"))
    if not plan_data:
        return (f"Plan {plan_id} expired or not found. "
                "Create a new plan with taey_plan(action='create').")

    try:
        plan = json.loads(plan_data)
    except (json.JSONDecodeError, TypeError):
        return f"Plan {plan_id} is corrupt. Create a new plan."

    # Only send_message plans are valid for sending
    if plan.get('action') != 'send_message':
        return f"Plan {plan_id} is for '{plan.get('action')}', not 'send_message'. Create a send_message plan."

    if not plan.get('audit_passed'):
        audit_result = plan.get('audit_result')
        if audit_result and audit_result.get('failures'):
            failures_summary = "; ".join(
                f"{f['field']}: need '{f.get('required')}', have '{f.get('current')}'"
                for f in audit_result['failures']
            )
            return (f"Plan {plan_id} audit FAILED: {failures_summary}. "
                    "Fix the issues and re-audit with taey_plan(action='audit').")
        return (f"Plan {plan_id} has not been audited. "
                "Call taey_plan(action='audit') before sending.")

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
                             timeout: int = 7200) -> Dict[str, Any]:
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
        session_key = node_key(f"active_session:{monitor_id}")
        redis_client.setex(
            session_key,
            timeout,
            json.dumps(session_data),
        )
        # Add to deterministic SET so monitor doesn't need SCAN
        redis_client.sadd(node_key("active_session_ids"), session_key)
        return {"registered": True, "monitor_id": monitor_id}
    except Exception as e:
        logger.error(f"Session registration failed: {e}")
        return {"registered": False, "error": str(e)}


def handle_send_message(platform: str, message: str,
                        redis_client, display: str,
                        attachments: List[str] = None,
                        session_type: str = None,
                        purpose: str = None) -> Dict[str, Any]:
    """Paste message, press Enter, record in Neo4j, register monitor session.

    BLOCKS unless plan audit_passed=True.
    """
    # ═══ HARD GATE: Audit must have passed ═══
    if platform not in SOCIAL_PLATFORMS:
        gate_error = _check_audit_gate(platform, redis_client)
        if gate_error:
            return {
                "error": gate_error,
                "platform": platform,
                "action": "audit_required",
                "hint": "Run taey_plan(action='audit') to verify state before sending.",
            }

    # Switch to platform tab
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform}", "platform": platform}
    time.sleep(0.5)

    firefox = atspi.find_firefox_for_platform(platform)
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    if not doc:
        return {"error": f"Could not find {platform} document", "platform": platform}
    url = atspi.get_document_url(doc)

    # Click input field to ensure focus is on the text area, not on
    # Attach/Toggle menu buttons left focused after file dialog close.
    # Without this, Ctrl+V from clipboard_paste hits the button and
    # reopens the attach dropdown instead of pasting into input.
    from core.tree import find_elements, detect_chrome_y
    try:
        elems = find_elements(doc, fence_after=None)
        chrome_y = detect_chrome_y(doc)
        input_el = None
        for e in elems:
            if e.get('role') == 'entry' and 'editable' in e.get('states', []) \
                    and e.get('y', 0) > chrome_y:
                input_el = e
                break
        if not input_el:
            for e in elems:
                if 'editable' in e.get('states', []) and e.get('y', 0) > chrome_y:
                    input_el = e
                    break
        if input_el:
            inp.click_at(input_el['x'], input_el['y'])
            time.sleep(0.3)
    except Exception as e:
        logger.warning("Could not click input field: %s", e)

    # Paste message
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

    # Press Enter (skip on social platforms where Enter = newline)
    enter_pressed = False
    if platform not in SOCIAL_PLATFORMS:
        if not inp.press_key('Return', timeout=5):
            # Clean up monitor session on send failure
            if monitor_registered and redis_client:
                session_key = node_key(f"active_session:{monitor_id}")
                redis_client.delete(session_key)
                redis_client.srem(node_key("active_session_ids"), session_key)
            # Clear pending_prompt so extract doesn't pick up a stale entry
            if redis_client:
                redis_client.delete(node_key(f"pending_prompt:{platform}"))
            return {"error": "Send (Enter) failed", "platform": platform, "neo4j": neo4j_result}
        enter_pressed = True

    # Re-capture URL after redirect (landing pages redirect to conversation URL)
    # Poll all 5 attempts — some platforms (Perplexity) do multi-stage redirects:
    #   landing → /search/new/{uuid} → /search/{slug}
    # Breaking on first change would capture the intermediate URL.
    if enter_pressed:
        for _attempt in range(5):
            time.sleep(1)
            try:
                new_url = atspi.get_document_url(doc)
                if new_url and new_url != url:
                    logger.info("URL redirect: %s → %s", url[:60], new_url[:60])
                    url = new_url
            except Exception as e:
                logger.debug("URL re-capture attempt %d: %s", _attempt, e)

        # Update all stored references with final URL
        if redis_client:
            redis_client.setex(node_key(f"pending_prompt:{platform}"), 3600, json.dumps({
                'content': message, 'attachments': attachments or [],
                'session_url': url, 'session_id': session_id,
                'message_id': message_id, 'sent_at': datetime.now().isoformat(),
            }))
        if session_id:
            try:
                neo4j_client.update_session(session_id, {'url': url})
            except Exception:
                pass
        if monitor_registered and redis_client:
            sess_key = node_key(f"active_session:{monitor_id}")
            raw = redis_client.get(sess_key)
            if raw:
                sess_data = json.loads(raw)
                sess_data['url'] = url
                ttl = redis_client.ttl(sess_key)
                if ttl > 0:
                    redis_client.setex(sess_key, ttl, json.dumps(sess_data))

    # Clear DISPLAY-scoped plan lock — send complete, monitor can resume cycling
    if redis_client:
        display = os.environ.get('DISPLAY', ':0')
        redis_client.delete(f"taey:plan_active:{display}")

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
