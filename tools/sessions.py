"""
taey_list_sessions - Show active sessions and pending responses.

Provides situational awareness: what sessions are active,
what responses are pending, and recommendations for next action.
"""

import json
import logging
from typing import Any, Dict, Optional

from storage import neo4j_client
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def handle_list_sessions(platform: Optional[str],
                         redis_client) -> Dict[str, Any]:
    """List active sessions with pending response awareness.

    Shows:
    - Active sessions (from Neo4j)
    - Pending responses (from Redis)
    - Recommendation for next action

    Args:
        platform: Optional filter by platform.
        redis_client: Redis client.

    Returns:
        Sessions, waiting_on, and recommendation.
    """
    result = {
        "success": True,
        "sessions": [],
        "waiting_on": [],
        "recommendation": None,
    }

    # Get active sessions from Neo4j
    try:
        sessions = neo4j_client.get_active_sessions(platform)
    except Exception as e:
        logger.warning("Neo4j unavailable: %s", e)
        sessions = []
    result["sessions"] = [
        {
            "session_id": s.get("session_id"),
            "platform": s.get("platform"),
            "url": s.get("url"),
            "session_type": s.get("session_type"),
            "purpose": s.get("purpose"),
            "message_count": s.get("message_count"),
        }
        for s in sessions
    ]

    # Check for pending responses
    if redis_client:
        platforms_to_check = [platform] if platform else [
            'chatgpt', 'claude', 'gemini', 'grok', 'perplexity',
        ]
        for plat in platforms_to_check:
            pending = redis_client.get(node_key(f"pending_prompt:{plat}"))
            if pending:
                try:
                    data = json.loads(pending)
                    result["waiting_on"].append({
                        "platform": plat,
                        "sent_at": data.get("sent_at"),
                        "message_preview": data.get("content", "")[:100],
                    })
                except json.JSONDecodeError:
                    pass

    # Generate recommendation
    if result["waiting_on"]:
        plat = result["waiting_on"][0]["platform"]
        result["recommendation"] = f"Check pending response on {plat} with taey_quick_extract"
    elif result["sessions"]:
        result["recommendation"] = "Continue existing session or start new one with taey_plan"
    else:
        result["recommendation"] = "No active sessions. Start one with taey_plan"

    return result
