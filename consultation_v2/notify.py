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
    response_text: str,
    purpose: Optional[str] = None,
    recipient: Optional[str] = None,
    source_file: Optional[str] = None,
    output_path: Optional[str] = None,
) -> bool:
    """Push a consultation notification to a session's Redis queue.

    Key: taey:{recipient}:notifications  (defaults to `requester`).
    `requester` and `purpose` are always stamped INTO the payload (provenance —
    WHO the consultation was for), independent of WHO receives it (`recipient`).
    This separation lets the orchestrator route FAILURES to the operator
    (taeys-hands) while still recording the original requester in the payload,
    and route SUCCESSES to the requester — without ever losing provenance or
    silently orphaning a result (the GAIA->tutor orphan).
    Returns True on success, False on failure (never raises).
    """
    target = recipient or requester
    try:
        import redis
        r = redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, decode_responses=True)
        full_response = response_text or ''
        source = source_file or output_path or ''
        output = output_path or source_file or ''
        payload = json.dumps({
            'event': 'consultation_complete',
            'platform': platform,
            'status': status,
            'plan_id': plan_id,
            'requester': requester,
            'purpose': purpose,
            'response_text': full_response,
            'response_chars': len(full_response),
            'source_file': source,
            'output_path': output,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        key = f'taey:{target}:notifications'
        new_length = r.rpush(key, payload)
        delivered = bool(new_length and int(new_length) > 0)
        if delivered:
            logger.info("Notification pushed to %s (plan=%s, status=%s)", key, plan_id, status)
        else:
            logger.error("Notification push to %s returned %r", key, new_length)
        return delivered
    except Exception as exc:
        logger.error("Notification push failed: %s", exc)
        return False
