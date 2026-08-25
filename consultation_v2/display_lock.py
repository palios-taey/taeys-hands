from __future__ import annotations

import json
import logging
import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

from storage.redis_pool import get_client

from consultation_v2 import primitives


CAREERS_POLICY = "careers"
DISCRETIONARY_POLICY = "discretionary"
LOCK_POLICIES = frozenset({CAREERS_POLICY, DISCRETIONARY_POLICY})
DEFAULT_WAIT_SECONDS = 300.0
MINIMUM_LOCK_TTL_SECONDS = 4000
COLLISION_RECEIPT_KEY = "taey:display_lock_collisions"
COLLISION_RECEIPT_LIMIT = 1000
logger = logging.getLogger(__name__)


class DisplayLockTimeout(RuntimeError):
    pass


class DisplayLockUnavailable(RuntimeError):
    pass


def resolve_lock_policy(value: str | None, *, default: str) -> str:
    policy = str(value or default).strip().lower()
    if policy not in LOCK_POLICIES:
        raise ValueError(
            f"display lock policy must be one of {sorted(LOCK_POLICIES)}"
        )
    return policy


def display_lock_ttl(runtime_seconds: float | int) -> int:
    runtime = max(0.0, float(runtime_seconds))
    return max(MINIMUM_LOCK_TTL_SECONDS, math.ceil(runtime) + 300)


def _local_collision_receipt(record: Dict[str, Any]) -> None:
    path = Path(
        os.environ.get(
            "TAEY_DISPLAY_LOCK_COLLISION_FALLBACK",
            "/tmp/taey_display_lock_collisions.jsonl",
        )
    ).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    with os.fdopen(descriptor, 'ab') as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _record_collision(record: Dict[str, Any]) -> None:
    encoded = json.dumps(record, ensure_ascii=True, sort_keys=True)
    try:
        client = get_client()
        with client.pipeline() as pipe:
            pipe.rpush(COLLISION_RECEIPT_KEY, encoded)
            pipe.ltrim(COLLISION_RECEIPT_KEY, -COLLISION_RECEIPT_LIMIT, -1)
            pipe.execute()
        return
    except Exception as exc:
        logger.error("display-lock collision Redis receipt failed: %s", exc)
    try:
        _local_collision_receipt(record)
    except Exception as exc:
        logger.error("display-lock collision fallback receipt failed: %s", exc)


def _collision_record(
    *,
    kind: str,
    display: str,
    policy: str,
    request_id: str,
    entrypoint: str,
    wait_ms: int,
    holder: Dict[str, Any] | None,
    error: str | None = None,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "schema": "taey_display_lock_collision.v1",
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "display": display,
        "policy": policy,
        "request_id": request_id,
        "entrypoint": entrypoint,
        "wait_ms": wait_ms,
        "holder": dict(holder or {}),
    }
    if error:
        record["error"] = error
    _record_collision(record)
    return record


def _safe_lock_record(display: str) -> Dict[str, Any] | None:
    try:
        return primitives.display_lock_record(display)
    except Exception as exc:
        return {"lookup_error": f"{type(exc).__name__}: {exc}"}


@contextmanager
def entrypoint_display_lock(
    *,
    display: str,
    policy: str,
    request_id: str,
    entrypoint: str,
    payload: Dict[str, Any] | None = None,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    ttl: int = MINIMUM_LOCK_TTL_SECONDS,
) -> Iterator[Dict[str, Any]]:
    policy = resolve_lock_policy(policy, default=CAREERS_POLICY)
    started = time.monotonic()
    deadline = started + max(0.0, float(wait_seconds))
    holder: Dict[str, Any] | None = None
    owner_token: str | None = None
    acquisition_error: Exception | None = None
    lock_payload = {
        **dict(payload or {}),
        "display": display,
        "request_id": request_id,
        "entrypoint": entrypoint,
        "policy": policy,
    }
    while True:
        try:
            owner_token = primitives.acquire_display_lock(
                payload=lock_payload,
                ttl=ttl,
                display=display,
            )
            if owner_token:
                break
            holder = primitives.display_lock_record(display)
        except Exception as exc:
            acquisition_error = exc
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    wait_ms = round((time.monotonic() - started) * 1000)
    if owner_token:
        lock_record = {
            "acquired": True,
            "owner_token": owner_token,
            "wait_ms": wait_ms,
            "holder": None,
            "policy": policy,
        }
        try:
            yield lock_record
        finally:
            try:
                released = primitives.release_display_lock(owner_token, display=display)
                lock_record["released"] = released is True
            except Exception as exc:
                lock_record["released"] = False
                _collision_record(
                    kind="release_error",
                    display=display,
                    policy=policy,
                    request_id=request_id,
                    entrypoint=entrypoint,
                    wait_ms=wait_ms,
                    holder=_safe_lock_record(display),
                    error=f"{type(exc).__name__}: {exc}",
                )
                if policy == DISCRETIONARY_POLICY:
                    raise
        return

    if acquisition_error is not None:
        error = f"{type(acquisition_error).__name__}: {acquisition_error}"
        if policy == DISCRETIONARY_POLICY:
            raise DisplayLockUnavailable(
                f"display {display} lock unavailable: {error}"
            ) from acquisition_error
        collision = _collision_record(
            kind="lock_unavailable",
            display=display,
            policy=policy,
            request_id=request_id,
            entrypoint=entrypoint,
            wait_ms=wait_ms,
            holder=None,
            error=error,
        )
    else:
        if policy == DISCRETIONARY_POLICY:
            raise DisplayLockTimeout(
                f"display {display} remained locked after {wait_ms}ms; "
                f"holder={json.dumps(holder or {}, sort_keys=True)}"
            )
        collision = _collision_record(
            kind="wait_timeout",
            display=display,
            policy=policy,
            request_id=request_id,
            entrypoint=entrypoint,
            wait_ms=wait_ms,
            holder=holder,
        )

    logger.warning(
        "careers display-lock fail-open: display=%s request_id=%s kind=%s wait_ms=%s",
        display,
        request_id,
        collision["kind"],
        wait_ms,
    )
    with primitives.allow_display_lock_bypass(display):
        lock_record = {
            "acquired": False,
            "owner_token": None,
            "wait_ms": wait_ms,
            "holder": holder,
            "policy": policy,
            "collision": collision,
        }
        try:
            yield lock_record
        finally:
            lock_record["released"] = False
