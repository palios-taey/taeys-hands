"""taey_list_sessions - Active sessions and pending responses."""

import json
import logging
from typing import Any, Dict, Optional

from storage import neo4j_client
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def handle_list_sessions(platform: Optional[str],
                         redis_client) -> Dict[str, Any]:
    """List active sessions with pending response awareness."""
    result = {"success": True, "sessions": [], "waiting_on": [],
              "recommendation": None}

    try:
        sessions = neo4j_client.get_active_sessions(platform)
    except Exception as e:
        logger.warning("Neo4j unavailable: %s", e)
        sessions = []
    result["sessions"] = [
        {"session_id": s.get("session_id"), "platform": s.get("platform"),
         "url": s.get("url"), "session_type": s.get("session_type"),
         "purpose": s.get("purpose"), "message_count": s.get("message_count")}
        for s in sessions
    ]

    if redis_client:
        platforms_to_check = [platform] if platform else [
            'chatgpt', 'claude', 'gemini', 'grok', 'perplexity']
        for plat in platforms_to_check:
            pending = redis_client.get(node_key(f"pending_prompt:{plat}"))
            if pending:
                try:
                    data = json.loads(pending)
                    result["waiting_on"].append({
                        "platform": plat, "sent_at": data.get("sent_at"),
                        "message_preview": data.get("content", "")[:100],
                    })
                except json.JSONDecodeError:
                    pass

    if result["waiting_on"]:
        plat = result["waiting_on"][0]["platform"]
        result["recommendation"] = f"Check pending response on {plat} with taey_quick_extract"
    elif result["sessions"]:
        result["recommendation"] = "Continue existing session or start new one with taey_plan"
    else:
        result["recommendation"] = "No active sessions. Start one with taey_plan"

    return result
