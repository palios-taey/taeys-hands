"""Post-consultation notification via Redis.

Pushes completion notifications to the requester's queue after extraction.
Uses the same key pattern as the V1 notification system.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
_REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))


def push_notification(
    requester: str,
    platform: str,
    status: str,
    plan_id: str,
    preview: str,
) -> bool:
    """Push consultation-complete notification to requester's Redis queue.

    Key: taey:{requester}:notifications
    Returns True on success, False on failure (never raises).
    """
    try:
        import redis
        r = redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, decode_responses=True)
        payload = json.dumps({
            'event': 'consultation_complete',
            'platform': platform,
            'status': status,
            'plan_id': plan_id,
            'preview': preview[:200],
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        key = f'taey:{requester}:notifications'
        r.rpush(key, payload)
        logger.info("Notification pushed to %s (plan=%s, status=%s)", key, plan_id, status)
        return True
    except Exception as exc:
        logger.error("Notification push failed: %s", exc)
        return False
