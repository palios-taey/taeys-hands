"""Canonical shared-primitive surface for consultation_v2 (FLOW §7).

This module is the SINGLE import site for the shared primitives a driver may
call. Per FLOW_CONSULTATION_ENGINE.md §7 ("Shared primitives own"):

    - snapshot and menu_snapshot
    - exact match and structural match
    - click element, pointer move (hover), paste, key press, scroll,
      clipboard read/write
    - URL read and display/window focus
    - lock, run-state, monitor registration, storage, and fleet-notify calls

The first three groups already exist:

    - interaction/observation primitives live on ``ConsultationRuntime``
      (consultation_v2.runtime): snapshot, menu_snapshot, click, hover, paste,
      type_text, press, scroll_to_bottom, scroll_element_into_view,
      focus_firefox, read_clipboard, write_clipboard, current_url, wait_until.
    - the exact + structural matcher lives in consultation_v2.snapshot
      (``matches_spec``) — strict, exact-only, structural-locator aware.
    - the fleet-notify transport primitive lives in consultation_v2.notify
      (``push_notification``).

This module re-exports those so a driver imports ONE surface, and ADDS the
state primitives that previously had no clean home (they were scattered across
``tools/send.py``, ``tools/plan.py``, ``monitor/central.py`` — legacy
platform-driving modules a clean-engine driver must not import). The state
primitives here wire the EXISTING Redis key shapes (via storage.redis_pool's
``node_key`` and the DISPLAY-scoped plan lock) so the central monitor and the
legacy MCP paths observe identical state. They are NOT a new key scheme.

HARD CONSTRAINT (FLOW §7, CONSULTATION_CONTRACT §20-22): shared primitives carry
ZERO platform knowledge. No primitive in this module branches on, defaults to,
or hardcodes a platform name, an element name, or a YAML element-map key. A
primitive takes a resolved element/locator (or opaque ids supplied by the
caller) and acts; it never knows which platform it is serving. Per-platform
labels/roles/URLs live in YAML; per-platform behavior lives in the platform
driver.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from redis.exceptions import WatchError

from storage.redis_pool import node_key, get_client, NODE_ID

# --- Re-exported existing primitive surfaces (single import site) -----------
from .runtime import ConsultationRuntime  # interaction + observation primitives
from .snapshot import matches_spec, build_snapshot, build_menu_snapshot  # match
from .notify import push_notification  # fleet-notify transport
from . import storage_policy
from .types import ElementRef, Snapshot

__all__ = [
    # interaction / observation (re-export)
    "ConsultationRuntime",
    "build_snapshot",
    "build_menu_snapshot",
    "matches_spec",
    "ElementRef",
    "Snapshot",
    # notify transport (re-export)
    "push_notification",
    # locks
    "acquire_display_lock",
    "release_display_lock",
    "display_lock_held",
    # run-state (idempotency checkpoints)
    "write_run_state",
    "read_run_state",
    "clear_run_state",
    # monitor registration
    "register_monitor_session",
    "deregister_monitor_session",
    # storage
    "store_consultation",
]


# ---------------------------------------------------------------------------
# Locks — DISPLAY-scoped plan lock (matches tools/send.py + monitor/central.py)
# ---------------------------------------------------------------------------
#
# Key: ``taey:plan_active:{DISPLAY}``. The central monitor checks this exact key
# to decide whether it may cycle tabs (monitor/central.py::_plan_active reads
# ``taey:plan_active:{DISPLAY}``). One display drives one Firefox window, so the
# lock is the per-window dispatch mutex required by FLOW §10 (setup is
# sequential per display). The lock is keyed by DISPLAY only — never by
# platform — because the display is the physical contention unit.

def _display(display: str | None = None) -> str:
    return display or os.environ.get("DISPLAY", ":0")


def _plan_lock_key(display: str | None = None) -> str:
    return f"taey:plan_active:{_display(display)}"


def _process_starttime(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
            stat = fh.read()
    except OSError:
        return None
    end = stat.rfind(")")
    if end < 0:
        return None
    fields = stat[end + 2:].split()
    if len(fields) < 20:
        return None
    return fields[19]


def _lock_record(owner_token: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    holder_pid = os.getpid()
    holder_starttime = _process_starttime(holder_pid)
    if not holder_starttime:
        raise RuntimeError(f"unable to read holder_starttime for pid {holder_pid}")
    record = dict(payload or {})
    record["owner_token"] = owner_token
    record["holder_pid"] = holder_pid
    record["holder_starttime"] = holder_starttime
    record.setdefault("locked_at", datetime.now(timezone.utc).isoformat())
    return record


def acquire_display_lock(
    payload: Optional[Dict[str, Any]] = None,
    ttl: int = 3600,
    display: str | None = None,
) -> str | None:
    """Take the DISPLAY-scoped dispatch lock so the monitor will not cycle the
    tab mid-setup. Returns this owner's token on success, None if another owner
    already holds the lock. Raises ConnectionError if Redis is unreachable — a
    lock that cannot be taken is a loud failure, never a silent "proceed without
    the lock".

    Acquisition is a single Redis SET NX claim. If any holder key already
    exists, this dispatcher refuses the display; acquire never deletes or
    replaces another holder's lock.
    """
    client = get_client()
    key = _plan_lock_key(display)
    owner_token = str((payload or {}).get("owner_token") or uuid.uuid4())
    record = _lock_record(owner_token, payload)
    body = json.dumps(record)
    return owner_token if client.set(key, body, ex=ttl, nx=True) else None


def release_display_lock(owner_token: str | None, display: str | None = None) -> bool:
    """Release the DISPLAY-scoped dispatch lock (send complete / step failed).
    Returns True only if the lock still belongs to ``owner_token`` and was
    removed. Never deletes a lock owned by another dispatch."""
    if not owner_token:
        return False
    client = get_client()
    key = _plan_lock_key(display)
    while True:
        with client.pipeline() as pipe:
            try:
                pipe.watch(key)
                raw = pipe.get(key)
                if not raw:
                    pipe.unwatch()
                    return False
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    record = {}
                if record.get("owner_token") != owner_token:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.delete(key)
                removed = pipe.execute()[0]
                return bool(removed)
            except WatchError:
                continue


def display_lock_held(display: str | None = None) -> bool:
    """True if the DISPLAY-scoped dispatch lock is currently held."""
    client = get_client()
    return bool(client.exists(_plan_lock_key(display)))


# ---------------------------------------------------------------------------
# Run-state — durable idempotency checkpoints (FLOW §8, CONTRACT §10)
# ---------------------------------------------------------------------------
#
# Key: ``taey:{node}:run_state:{request_id}``. Written as the flow progresses
# (submitted / url / completed) so a drift-triggered re-run RESUMES from the
# captured chat URL and NEVER replays a possibly-landed irreversible send. The
# request_id is supplied by the caller (the driver/dispatch boundary); this
# primitive is opaque to what it identifies and carries no platform knowledge.

def _run_state_key(request_id: str) -> str:
    return node_key(f"run_state:{request_id}")


def write_run_state(request_id: str, state: Dict[str, Any], ttl: int = 7200) -> bool:
    """Persist (merge) the durable run-state checkpoint for ``request_id``.

    The caller passes the fields it is checkpointing (e.g. ``status``,
    ``url``, ``session_id``, ``prompt_hash``, ``attachment_hashes``,
    ``monitor_id``); they are merged over any existing record and an
    ``updated_at`` timestamp is stamped. Merge (not overwrite) so an early
    ``submitted`` checkpoint is not lost when a later ``completed`` checkpoint
    is written. Raises if Redis is unreachable."""
    client = get_client()
    key = _run_state_key(request_id)
    existing_raw = client.get(key)
    record: Dict[str, Any] = {}
    if existing_raw:
        record = json.loads(existing_raw)
    record.update(state)
    record["request_id"] = request_id
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    return bool(client.setex(key, ttl, json.dumps(record)))


def read_run_state(request_id: str) -> Optional[Dict[str, Any]]:
    """Return the durable run-state record for ``request_id`` or None if absent.
    A re-run reads this FIRST to avoid a duplicate send (CONTRACT §10)."""
    client = get_client()
    raw = client.get(_run_state_key(request_id))
    if not raw:
        return None
    return json.loads(raw)


def clear_run_state(request_id: str) -> bool:
    """Remove the run-state record once the flow is fully done and delivered."""
    client = get_client()
    return bool(client.delete(_run_state_key(request_id)))


# ---------------------------------------------------------------------------
# Monitor registration (matches tools/send.py::register_monitor_session)
# ---------------------------------------------------------------------------
#
# Keys: per-session ``taey:{node}:active_session:{monitor_id}`` + the
# deterministic SET ``taey:{node}:active_session_ids`` that the central monitor
# reads without a SCAN (monitor/central.py::_get_sessions, SET-based path). The
# shape MUST match the legacy registrar exactly so a V2-registered session and a
# legacy-registered session are indistinguishable to the one central monitor.

def register_monitor_session(
    monitor_id: str,
    session: Dict[str, Any],
) -> bool:
    """Register an in-flight session for the central monitor (FLOW §9). The
    caller supplies the session payload (platform, url, mode, timeout, requester,
    started_ts, ...) as opaque data — this primitive does not interpret platform.

    A failed registration is a loud failure (raises on Redis error): per FLOW §8
    a dispatch that cannot be registered must NOT be treated as monitored."""
    client = get_client()
    session_key = node_key(f"active_session:{monitor_id}")
    record = dict(session)
    record.setdefault("monitor_id", monitor_id)
    record.setdefault("tmux_session", NODE_ID)
    record.setdefault("started_ts", time.time())
    record.setdefault("started", datetime.now(timezone.utc).isoformat())
    client.set(session_key, json.dumps(record, default=str))
    client.sadd(node_key("active_session_ids"), session_key)
    return True


def deregister_monitor_session(monitor_id: str) -> bool:
    """Remove an in-flight session registration (both the per-session key and
    its membership in the deterministic SET)."""
    client = get_client()
    session_key = node_key(f"active_session:{monitor_id}")
    removed = client.delete(session_key)
    client.srem(node_key("active_session_ids"), session_key)
    return bool(removed)


# ---------------------------------------------------------------------------
# Storage (thin wrapper over storage.neo4j_client — FLOW §12)
# ---------------------------------------------------------------------------
#
# Storage is OPTIONAL per FLOW §12: if it fails, a real preserved response may
# still be delivered, so a storage error here is returned as an outcome dict,
# not raised. The wrapper exists so a driver has one storage entry point instead
# of importing the Neo4j client directly and re-implementing the session/message
# write order.

def store_consultation(
    platform: str,
    url: str,
    user_prompt: str,
    response_text: str,
    *,
    attachments: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Persist a completed consultation turn (session + user message + assistant
    message). ``platform`` here is opaque DATA stored as a record field, not a
    control-flow branch — no behavior in this function changes based on its
    value. ``attachments`` is the only message metadata the storage layer
    accepts (storage.neo4j_client.add_message) and is recorded on the user
    message. Returns ``{"stored": bool, "session_id": str|None, "error":
    str|None}`` and never raises (storage is optional per FLOW §12)."""
    def _write() -> Dict[str, Any]:
        from storage import neo4j_client
        session_id = neo4j_client.get_or_create_session(platform=platform, url=url)
        if session_id is None:
            return {"stored": False, "session_id": None, "error": "session_create_failed"}
        neo4j_client.add_message(
            session_id=session_id, role="user", content=user_prompt,
            attachments=attachments or [],
        )
        neo4j_client.add_message(
            session_id=session_id, role="assistant", content=response_text,
        )
        return {"stored": True, "session_id": session_id, "error": None}

    try:
        return storage_policy.run_bounded_store_call(
            'Neo4j consultation store',
            _write,
        )
    except Exception as exc:  # storage is optional; surface as outcome, not raise
        return {"stored": False, "session_id": None, "error": str(exc)}
