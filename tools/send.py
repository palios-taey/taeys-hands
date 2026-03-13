"""taey_send_message - Paste, send, record, register monitor session."""

import json
import os
import time
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List

from core import atspi, input as inp
from core.platforms import SOCIAL_PLATFORMS
from core.tree import find_elements, find_copy_buttons
from storage import neo4j_client
from storage.redis_pool import node_key, NODE_ID

logger = logging.getLogger(__name__)


def register_monitor_session(platform: str, monitor_id: str, url: str,
                             redis_client, session_id: str = None,
                             user_message_id: str = None,
                             tmux_session: str = None,
                             baseline_copies: int = 0,
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
        "baseline_copies": baseline_copies,
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
        # Count existing copy buttons as baseline — prevents false-positive
        # response_ready from copy_button_fallback on non-empty conversations.
        baseline_copies = 0
        try:
            all_elements = find_elements(doc)
            baseline_copies = len(find_copy_buttons(all_elements))
        except Exception:
            pass

        reg = register_monitor_session(
            platform=platform, monitor_id=monitor_id, url=url,
            redis_client=redis_client, session_id=session_id,
            user_message_id=message_id,
            baseline_copies=baseline_copies,
        )
        monitor_registered = reg.get("registered", False)

    # Press Enter (skip on social platforms where Enter = newline)
    enter_pressed = False
    if platform not in SOCIAL_PLATFORMS:
        if not inp.press_key('Return', timeout=5):
            # Clean up monitor session on send failure
            if monitor_registered and redis_client:
                redis_client.delete(node_key(f"active_session:{monitor_id}"))
            return {"error": "Send (Enter) failed", "platform": platform, "neo4j": neo4j_result}
        enter_pressed = True

    # Clear plan lock — send complete, monitor can resume cycling
    if redis_client:
        redis_client.delete(node_key("plan_active"))

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
