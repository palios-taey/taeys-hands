"""
Redis Streams Task Queue

Uses Redis Streams with consumer groups for fair task distribution.
Ported from v4 event_sourcing.py (EventProducer/EventConsumer patterns)
and dcm/agent_mesh.py (SETNX claiming).

Redis keys:
  orch:streams:tasks     -> Stream (task broadcasts)
  orch:task:<id>:claimed -> String (agent_id, TTL=1800s)
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import OrchConfig, get_redis_sync, key


@dataclass
class TaskMessage:
    """A task message for the stream queue."""
    task_id: str
    phase_id: str = ""
    description: str = ""
    priority: int = 50
    capability_tags: List[str] = field(default_factory=list)
    file_blast_radius: List[str] = field(default_factory=list)
    estimated_tokens: int = 50_000
    created_at: float = field(default_factory=time.time)

    def to_stream_fields(self) -> Dict[str, str]:
        return {
            "task_id": self.task_id,
            "phase_id": self.phase_id,
            "description": self.description,
            "priority": str(self.priority),
            "capability_tags": json.dumps(self.capability_tags),
            "file_blast_radius": json.dumps(self.file_blast_radius),
            "estimated_tokens": str(self.estimated_tokens),
            "created_at": str(self.created_at),
        }

    @classmethod
    def from_stream_fields(cls, fields: Dict[str, str]) -> "TaskMessage":
        return cls(
            task_id=fields.get("task_id", ""),
            phase_id=fields.get("phase_id", ""),
            description=fields.get("description", ""),
            priority=int(fields.get("priority", "50")),
            capability_tags=json.loads(fields.get("capability_tags", "[]")),
            file_blast_radius=json.loads(fields.get("file_blast_radius", "[]")),
            estimated_tokens=int(fields.get("estimated_tokens", "50000")),
            created_at=float(fields.get("created_at", str(time.time()))),
        )


# Lua script for atomic task claiming (single winner, no race condition)
CLAIM_TASK_LUA = """
local claim_key = KEYS[1]
local load_key = KEYS[2]
local agent_id = ARGV[1]
local ttl = tonumber(ARGV[2])

if redis.call('EXISTS', claim_key) == 0 then
    redis.call('SET', claim_key, agent_id, 'EX', ttl)
    redis.call('HINCRBY', load_key, 'current_load', 1)
    return 1
end
return 0
"""

# Lua script for atomic task release (only owner can release)
RELEASE_TASK_LUA = """
local claim_key = KEYS[1]
local load_key = KEYS[2]
local agent_id = ARGV[1]

local current_owner = redis.call('GET', claim_key)
if current_owner == agent_id then
    redis.call('DEL', claim_key)
    redis.call('HINCRBY', load_key, 'current_load', -1)
    return 1
end
return 0
"""


class TaskQueue:
    """Redis Streams task queue with consumer groups."""

    def __init__(self, config: Optional[OrchConfig] = None):
        self.config = config or OrchConfig()
        self._redis = get_redis_sync(self.config)
        self._claim_script = self._redis.register_script(CLAIM_TASK_LUA)
        self._release_script = self._redis.register_script(RELEASE_TASK_LUA)
        self._ensure_consumer_group()

    def _ensure_consumer_group(self):
        """Create consumer group if it doesn't exist."""
        try:
            self._redis.xgroup_create(
                name=self.config.task_stream,
                groupname=self.config.consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

    def publish_task(self, task: TaskMessage) -> str:
        """Push a task to the stream. Returns stream message ID."""
        stream_id = self._redis.xadd(
            name=self.config.task_stream,
            fields=task.to_stream_fields(),
            maxlen=self.config.stream_maxlen,
            approximate=True,
        )
        return stream_id

    def read_tasks(self, agent_id: str, count: int = 5,
                   block_ms: int = 0) -> List[Tuple[str, TaskMessage]]:
        """Read unclaimed tasks from the stream via consumer group."""
        messages = self._redis.xreadgroup(
            groupname=self.config.consumer_group,
            consumername=agent_id,
            streams={self.config.task_stream: ">"},
            count=count,
            block=block_ms,
        )

        results = []
        if messages:
            for stream_name, stream_messages in messages:
                for msg_id, fields in stream_messages:
                    task = TaskMessage.from_stream_fields(fields)
                    results.append((msg_id, task))

        return results

    def try_claim(self, task_id: str, agent_id: str) -> bool:
        """Atomically claim a task. Returns True if this agent won."""
        claim_key = key(f"task:{task_id}:claimed")
        load_key = f"{self.config.agent_prefix}{agent_id}"
        return bool(self._claim_script(
            keys=[claim_key, load_key],
            args=[agent_id, self.config.file_lock_ttl_s],
        ))

    def release_claim(self, task_id: str, agent_id: str) -> bool:
        """Release a task claim (only if owner). Returns True if released."""
        claim_key = key(f"task:{task_id}:claimed")
        load_key = f"{self.config.agent_prefix}{agent_id}"
        return bool(self._release_script(
            keys=[claim_key, load_key],
            args=[agent_id],
        ))

    def ack_task(self, message_id: str) -> bool:
        """Acknowledge a processed task message."""
        return self._redis.xack(
            self.config.task_stream,
            self.config.consumer_group,
            message_id,
        ) > 0

    def get_pending(self, count: int = 100) -> List[Dict[str, Any]]:
        """Get pending (unacknowledged) task messages."""
        pending = self._redis.xpending_range(
            name=self.config.task_stream,
            groupname=self.config.consumer_group,
            min="-",
            max="+",
            count=count,
        )
        return [
            {
                "message_id": p["message_id"],
                "consumer": p["consumer"],
                "idle_ms": p.get("time_since_delivered", 0),
                "delivery_count": p.get("times_delivered", 0),
            }
            for p in pending
        ]

    def reclaim_stale(self, agent_id: str, min_idle_ms: int = 60_000,
                      count: int = 10) -> List[Tuple[str, TaskMessage]]:
        """Reclaim tasks stuck in pending for too long (dead agent recovery)."""
        try:
            result = self._redis.xautoclaim(
                name=self.config.task_stream,
                groupname=self.config.consumer_group,
                consumername=agent_id,
                min_idle_time=min_idle_ms,
                start_id="0-0",
                count=count,
            )

            claimed = []
            if result and len(result) > 1:
                for msg_id, fields in result[1]:
                    task = TaskMessage.from_stream_fields(fields)
                    claimed.append((msg_id, task))
            return claimed
        except Exception:
            return []

    def stream_length(self) -> int:
        """Get current stream length."""
        try:
            return self._redis.xlen(self.config.task_stream)
        except Exception:
            return 0

    def get_claim_owner(self, task_id: str) -> Optional[str]:
        """Check who owns a task claim."""
        claim_key = key(f"task:{task_id}:claimed")
        return self._redis.get(claim_key)
