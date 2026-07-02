"""Post-consultation notification via Redis.

Pushes completion notifications to the requester's queue after extraction.
Uses the same key pattern as the V1 notification system.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
_REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
_DEFAULT_ACK_TIMEOUT_SECONDS = 5.0
_DEFAULT_ACK_POLL_SECONDS = 0.2
_DEFAULT_DELIVERY_ATTEMPTS = 2
_DEFAULT_ACK_TTL_SECONDS = 7200


@dataclass(slots=True)
class NotificationDelivery:
    """Result of a notification enqueue + receiver surfacing ACK."""
    surfaced: bool
    queued: bool
    acked: bool
    notification_id: str
    recipient: str
    queue_key: str
    ack_key: str
    attempts: int
    payload: dict[str, Any] = field(default_factory=dict)
    ack_payload: dict[str, Any] | None = None
    error: str = ''
    local_log_path: str = ''

    def __bool__(self) -> bool:
        return self.surfaced

    @property
    def delivered(self) -> bool:
        return self.surfaced

    def as_evidence(self) -> dict[str, Any]:
        return {
            'surface_ack': self.surfaced,
            'queued': self.queued,
            'acked': self.acked,
            'notification_id': self.notification_id,
            'recipient': self.recipient,
            'queue_key': self.queue_key,
            'ack_key': self.ack_key,
            'attempts': self.attempts,
            'ack_payload': self.ack_payload or {},
            'error': self.error,
            'local_log_path': self.local_log_path,
        }


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


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


def _decode_ack(raw: str | bytes | None) -> dict[str, Any] | None:
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='replace')
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = {'raw': str(raw)}
    return payload if isinstance(payload, dict) else {'raw': payload}


def _wait_for_ack(
    redis_client: Any,
    ack_key: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        ack_payload = _decode_ack(redis_client.get(ack_key))
        if ack_payload is not None:
            return ack_payload
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(max(0.01, poll_seconds), remaining))


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
    ack_timeout_seconds: Optional[float] = None,
    delivery_attempts: Optional[int] = None,
    local_log_dir: str | os.PathLike[str] | None = None,
) -> NotificationDelivery:
    """Push a consultation notification to a session's Redis queue.

    Key: taey:{recipient}:notifications  (defaults to `requester`).
    `requester` and `purpose` are always stamped INTO the payload (provenance —
    WHO the consultation was for), independent of WHO receives it (`recipient`).
    This separation lets the orchestrator route FAILURES to the operator
    (taeys-hands) while still recording the original requester in the payload,
    and route SUCCESSES to the requester — without ever losing provenance or
    silently orphaning a result (the GAIA->tutor orphan).
    Returns a NotificationDelivery. Truthiness means the receiver surfaced the
    payload and wrote the stamped ACK key; Redis enqueue alone is only queued.
    """
    target = recipient or requester
    notification_id = uuid.uuid4().hex
    key = f'taey:{target}:notifications'
    ack_key = f'taey:{target}:notifications:ack:{notification_id}'
    attempts_limit = max(
        1,
        int(
            delivery_attempts
            or _env_int('TAEY_NOTIFY_DELIVERY_ATTEMPTS', _DEFAULT_DELIVERY_ATTEMPTS)
        ),
    )
    ack_timeout = (
        _env_float('TAEY_NOTIFY_ACK_TIMEOUT_SECONDS', _DEFAULT_ACK_TIMEOUT_SECONDS)
        if ack_timeout_seconds is None else float(ack_timeout_seconds)
    )
    ack_poll = _env_float('TAEY_NOTIFY_ACK_POLL_SECONDS', _DEFAULT_ACK_POLL_SECONDS)
    full_response = response_text or ''
    source = source_file or output_path or ''
    output = output_path or source_file or ''
    base_payload = {
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
        'ack_required': True,
        'ack_key': ack_key,
    }
    last_payload = dict(base_payload)
    queued = False
    attempts_used = 0
    try:
        import redis
        r = redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, decode_responses=True)
        r.delete(ack_key)
        for attempt in range(1, attempts_limit + 1):
            attempts_used = attempt
            if not queued:
                last_payload = dict(base_payload)
                last_payload['delivery_attempt'] = attempt
                payload = json.dumps(last_payload)
                new_length = r.rpush(key, payload)
                queued = bool(new_length and int(new_length) > 0)
                if not queued:
                    logger.error("Notification enqueue to %s returned %r", key, new_length)
                    continue
                logger.info(
                    "Notification queued to %s (plan=%s, status=%s, attempt=%s/%s, ack=%s)",
                    key, plan_id, status, attempt, attempts_limit, ack_key,
                )
            else:
                logger.info(
                    "Notification awaiting ACK from %s (plan=%s, attempt=%s/%s, ack=%s)",
                    target, plan_id, attempt, attempts_limit, ack_key,
                )
            ack_payload = _wait_for_ack(
                r,
                ack_key,
                timeout_seconds=ack_timeout,
                poll_seconds=ack_poll,
            )
            if ack_payload is not None:
                logger.info(
                    "Notification surfaced by %s (plan=%s, ack=%s)",
                    target, plan_id, ack_key,
                )
                ttl = max(60, _env_int('TAEY_NOTIFY_ACK_TTL_SECONDS', _DEFAULT_ACK_TTL_SECONDS))
                try:
                    r.expire(ack_key, ttl)
                except Exception:
                    pass
                return NotificationDelivery(
                    surfaced=True,
                    queued=True,
                    acked=True,
                    notification_id=notification_id,
                    recipient=target,
                    queue_key=key,
                    ack_key=ack_key,
                    attempts=attempts_used,
                    payload=last_payload,
                    ack_payload=ack_payload,
                )
        error = 'notification_ack_missing' if queued else 'notification_enqueue_failed'
        delivery = NotificationDelivery(
            surfaced=False,
            queued=queued,
            acked=False,
            notification_id=notification_id,
            recipient=target,
            queue_key=key,
            ack_key=ack_key,
            attempts=attempts_used,
            payload=last_payload,
            error=error,
        )
        delivery.local_log_path = write_notification_local_log(
            {
                'kind': error,
                'notification_id': notification_id,
                'recipient': target,
                'requester': requester,
                'platform': platform,
                'status': status,
                'plan_id': plan_id,
                'purpose': purpose,
                'queue_key': key,
                'ack_key': ack_key,
                'attempts': attempts_used,
                'payload': last_payload,
                'delivery': delivery.as_evidence(),
            },
            local_log_dir=local_log_dir,
        )
        logger.error(
            "Notification not surfaced by %s (plan=%s, queued=%s, attempts=%s, ack=%s, local_log=%s)",
            target, plan_id, queued, attempts_used, ack_key, delivery.local_log_path,
        )
        return delivery
    except Exception as exc:
        delivery = NotificationDelivery(
            surfaced=False,
            queued=queued,
            acked=False,
            notification_id=notification_id,
            recipient=target,
            queue_key=key,
            ack_key=ack_key,
            attempts=attempts_used,
            payload=last_payload,
            error=str(exc),
        )
        try:
            delivery.local_log_path = write_notification_local_log(
                {
                    'kind': 'notification_delivery_exception',
                    'notification_id': notification_id,
                    'recipient': target,
                    'requester': requester,
                    'platform': platform,
                    'status': status,
                    'plan_id': plan_id,
                    'purpose': purpose,
                    'queue_key': key,
                    'ack_key': ack_key,
                    'attempts': attempts_used,
                    'payload': last_payload,
                    'error': str(exc),
                    'delivery': delivery.as_evidence(),
                },
                local_log_dir=local_log_dir,
            )
        except Exception as log_exc:
            delivery.error = f'{exc}; local_log_failed={log_exc}'
        logger.error("Notification push failed: %s", exc)
        return delivery
