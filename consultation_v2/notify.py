"""Post-consultation notification via Redis.

Delivery contract
-----------------
The consultation engine owns enqueueing completion notifications into the
fleet-notify queue. A successful ``RPUSH`` to ``taey:{recipient}:notifications``
is delivery to the notification substrate. Receiver hooks drain that queue
asynchronously; consumption/surfacing verification belongs to the async
stuck-inbox watchdog, not a synchronous sender-side ACK wait.

This module parks locally only when enqueue itself fails.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
_REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))


@dataclass(slots=True)
class NotificationDelivery:
    """Result of enqueueing a notification into fleet-notify."""
    delivered: bool
    queued: bool
    notification_id: str
    recipient: str
    queue_key: str
    attempts: int
    payload: dict[str, Any] = field(default_factory=dict)
    queue_length: int = 0
    acked: bool = False
    ack_payload: dict[str, Any] | None = None
    error: str = ''
    local_log_path: str = ''

    def __bool__(self) -> bool:
        return self.delivered

    def as_evidence(self) -> dict[str, Any]:
        return {
            'delivered': self.delivered,
            'queued': self.queued,
            'acked': self.acked,
            'notification_id': self.notification_id,
            'recipient': self.recipient,
            'queue_key': self.queue_key,
            'attempts': self.attempts,
            'queue_length': self.queue_length,
            'ack_payload': self.ack_payload or {},
            'error': self.error,
            'local_log_path': self.local_log_path,
        }


def _local_log_dir(local_log_dir: str | os.PathLike[str] | None = None) -> Path:
    configured = local_log_dir or os.environ.get('TAEY_NOTIFY_LOCAL_LOG_DIR')
    if configured:
        return Path(configured).expanduser()
    return (
        Path.home()
        / '.local'
        / 'state'
        / 'taeys-hands'
        / 'consultation_v2'
        / 'notifications'
    )


def write_notification_local_log(
    record: dict[str, Any],
    *,
    local_log_dir: str | os.PathLike[str] | None = None,
) -> str:
    """Persist a queryable local notification record outside Redis."""
    directory = _local_log_dir(local_log_dir)
    pending_dir = directory / 'pending'
    pending_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    notification_id = str(record.get('notification_id') or uuid.uuid4().hex)
    body = dict(record)
    body.setdefault('schema_version', 1)
    body.setdefault('written_at', now)
    body.setdefault('needs_attention', True)
    body['notification_id'] = notification_id
    path = pending_dir / f'{notification_id}.json'
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    index_path = directory / 'needs_attention.jsonl'
    with index_path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(body, sort_keys=True, separators=(',', ':')) + '\n')
    return str(path)


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
    local_log_dir: str | os.PathLike[str] | None = None,
) -> NotificationDelivery:
    """Push a consultation notification to a session's Redis queue.

    Key: taey:{recipient}:notifications  (defaults to `requester`).
    `requester` and `purpose` are always stamped INTO the payload (provenance —
    WHO the consultation was for), independent of WHO receives it (`recipient`).
    This separation lets the orchestrator route FAILURES to the operator
    (taeys-hands) while still recording the original requester in the payload,
    and route SUCCESSES to the requester — without ever losing provenance or
    silently orphaning a result.

    Returns a NotificationDelivery. Truthiness means Redis accepted the payload
    into the fleet-notify queue. Hook consumption is asynchronous and monitored
    by the stuck-inbox watchdog.
    """
    target = recipient or requester
    notification_id = uuid.uuid4().hex
    key = f'taey:{target}:notifications'
    full_response = response_text or ''
    source = source_file or output_path or ''
    output = output_path or source_file or ''
    payload = {
        'event': 'consultation_complete',
        'type': 'notification',
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
        'notification_id': notification_id,
    }
    queue_length = 0
    error = ''
    try:
        import redis
        r = redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, decode_responses=True)
        new_length = r.rpush(key, json.dumps(payload))
        try:
            queue_length = int(new_length or 0)
        except (TypeError, ValueError):
            error = f'enqueue returned non-integer length {new_length!r}'
        if queue_length > 0:
            logger.info(
                "Notification queued to %s (plan=%s, status=%s, notification_id=%s)",
                key, plan_id, status, notification_id,
            )
            return NotificationDelivery(
                delivered=True,
                queued=True,
                notification_id=notification_id,
                recipient=target,
                queue_key=key,
                attempts=1,
                payload=payload,
                queue_length=queue_length,
            )
        if not error:
            error = f'enqueue returned {new_length!r}'
    except Exception as exc:
        error = str(exc)

    delivery = NotificationDelivery(
        delivered=False,
        queued=False,
        notification_id=notification_id,
        recipient=target,
        queue_key=key,
        attempts=1,
        payload=payload,
        queue_length=queue_length,
        error=error,
    )
    try:
        delivery.local_log_path = write_notification_local_log(
            {
                'kind': 'notification_enqueue_failed',
                'notification_id': notification_id,
                'recipient': target,
                'requester': requester,
                'platform': platform,
                'status': status,
                'plan_id': plan_id,
                'purpose': purpose,
                'queue_key': key,
                'payload': payload,
                'error': error,
                'delivery': delivery.as_evidence(),
            },
            local_log_dir=local_log_dir,
        )
    except Exception as log_exc:
        delivery.error = f'{error}; local_log_failed={log_exc}'
    logger.error(
        "Notification enqueue failed for %s (plan=%s, error=%s, local_log=%s)",
        target, plan_id, delivery.error, delivery.local_log_path,
    )
    return delivery
