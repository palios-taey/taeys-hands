"""
Event Sourcing

Append-only event log for orchestration state transitions.
Ported from v4 isma/event_sourcing.py (660 lines) - simplified for orch layer.

Redis key:
  orch:streams:events  -> Stream (100K entry retention)

Event types: agent.started, agent.stopped, task.created, task.claimed,
  task.completed, task.failed, file.locked, file.released, phase.gate_check
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .config import OrchConfig, get_redis_sync


class EventType(Enum):
    # Agent lifecycle
    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"
    AGENT_HEARTBEAT_LOST = "agent.heartbeat_lost"
    AGENT_RECOVERED = "agent.recovered"

    # Task events
    TASK_CREATED = "task.created"
    TASK_CLAIMED = "task.claimed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RELEASED = "task.released"

    # File lock events
    FILE_LOCKED = "file.locked"
    FILE_RELEASED = "file.released"
    FILE_LOCK_CONFLICT = "file.lock_conflict"

    # Phase gates
    PHASE_GATE_CHECK = "phase.gate_check"
    PHASE_COMPLETED = "phase.completed"

    # Git events
    GIT_BRANCH_CREATED = "git.branch_created"
    GIT_PR_OPENED = "git.pr_opened"
    GIT_MERGED = "git.merged"
    GIT_CONFLICT = "git.conflict"


@dataclass
class Event:
    """Immutable event with content-addressable hash."""
    event_type: str
    payload: Dict[str, Any]
    actor: str  # Agent ID or "system" or "coordinator"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    caused_by: Optional[str] = None  # Hash of parent event

    @property
    def event_hash(self) -> str:
        """16-char SHA256 prefix for content-addressable identity."""
        content = json.dumps({
            "event_type": self.event_type,
            "payload": self.payload,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "caused_by": self.caused_by,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_stream_fields(self) -> Dict[str, str]:
        return {
            "event_type": self.event_type,
            "payload": json.dumps(self.payload),
            "actor": self.actor,
            "timestamp": self.timestamp,
            "caused_by": self.caused_by or "",
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_stream_fields(cls, fields: Dict[str, str]) -> "Event":
        return cls(
            event_type=fields.get("event_type", ""),
            payload=json.loads(fields.get("payload", "{}")),
            actor=fields.get("actor", ""),
            timestamp=fields.get("timestamp", ""),
            caused_by=fields.get("caused_by") or None,
        )


class EventLog:
    """Append-only event log backed by Redis Streams."""

    def __init__(self, config: Optional[OrchConfig] = None):
        self.config = config or OrchConfig()
        self._redis = get_redis_sync(self.config)

    def publish(self, event: Event) -> str:
        """Publish event to the event stream. Returns stream message ID."""
        return self._redis.xadd(
            name=self.config.event_stream,
            fields=event.to_stream_fields(),
            maxlen=self.config.stream_maxlen,
            approximate=True,
        )

    def emit(self, event_type: str, payload: Dict[str, Any],
             actor: str, caused_by: Optional[str] = None) -> str:
        """Convenience: create and publish an event in one call."""
        event = Event(
            event_type=event_type,
            payload=payload,
            actor=actor,
            caused_by=caused_by,
        )
        return self.publish(event)

    def read_recent(self, count: int = 100) -> List[Event]:
        """Read the most recent events from the stream."""
        # XREVRANGE returns newest first
        messages = self._redis.xrevrange(
            name=self.config.event_stream,
            count=count,
        )
        events = []
        for msg_id, fields in messages:
            events.append(Event.from_stream_fields(fields))
        return events

    def read_by_type(self, event_type: str, count: int = 100) -> List[Event]:
        """Read recent events filtered by type."""
        all_events = self.read_recent(count=count * 3)  # Over-read then filter
        return [e for e in all_events if e.event_type == event_type][:count]

    def read_by_actor(self, actor: str, count: int = 100) -> List[Event]:
        """Read recent events filtered by actor."""
        all_events = self.read_recent(count=count * 3)
        return [e for e in all_events if e.actor == actor][:count]

    def stream_length(self) -> int:
        """Get current stream length."""
        try:
            return self._redis.xlen(self.config.event_stream)
        except Exception:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get stream statistics."""
        try:
            info = self._redis.xinfo_stream(self.config.event_stream)
            return {
                "length": info.get("length", 0),
                "first_entry": info.get("first-entry"),
                "last_entry": info.get("last-entry"),
            }
        except Exception as e:
            return {"error": str(e)}


# Module-level convenience instance
_log: Optional[EventLog] = None


def get_event_log() -> EventLog:
    """Get shared EventLog instance."""
    global _log
    if _log is None:
        _log = EventLog()
    return _log


def emit(event_type: str, payload: Dict[str, Any],
         actor: str = "system", caused_by: Optional[str] = None) -> str:
    """Convenience function to emit an event."""
    return get_event_log().emit(event_type, payload, actor, caused_by)
