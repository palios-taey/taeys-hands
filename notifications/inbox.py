"""
Redis-backed inbox for inter-Claude messaging and notification delivery.

Architecture:
- Each instance has an inbox: taey:{node_id}:inbox (LIST) for inter-Claude messages
- Monitor daemons push to: taey:{node_id}:notifications (LIST) for response detection
- Activity tracking: taey:{node_id}:tool_running (key with 300s TTL)
- Last activity: taey:{node_id}:last_tool_activity (epoch string)

Delivery paths (priority order):
1. PostToolUse hook (primary) — drains both inbox + notifications after each tool call
2. tmux fallback daemon — injects when instance is idle (no tool_running, no activity >30s)

The >15s tool call problem:
- PreToolUse sets tool_running flag (TTL 300s safety net)
- PostToolUse clears it when tool finishes
- tmux daemon checks flag before injecting — won't inject during long tool calls
- Even a 5-minute tool call is safe: flag stays set until PostToolUse clears it
"""
from __future__ import annotations

import json
import time


def send(redis_client, target_node: str, body: str, msg_type: str = "message",
         from_node: str = "unknown", priority: str = "normal") -> bool:
    """Send a message to a node's inbox.

    Args:
        redis_client: Redis connection.
        target_node: Recipient node ID (e.g. 'weaver', 'jetson-claude').
        body: Message text.
        msg_type: escalation, heartbeat, notification, response_ready, message.
        from_node: Sender node ID.
        priority: high, normal, low.
    """
    msg = json.dumps({
        "from": from_node,
        "type": msg_type,
        "body": body,
        "timestamp": time.time(),
        "priority": priority,
    })
    redis_client.lpush(f"taey:{target_node}:inbox", msg)
    return True


def receive(redis_client, node_id: str, max_count: int = 10) -> list[dict]:
    """Pop messages from own inbox (atomic, no duplicates)."""
    messages = []
    for _ in range(max_count):
        raw = redis_client.rpop(f"taey:{node_id}:inbox")
        if not raw:
            break
        try:
            messages.append(json.loads(raw))
        except json.JSONDecodeError:
            messages.append({"raw": raw, "type": "unparseable"})
    return messages


def receive_notifications(redis_client, node_id: str, max_count: int = 10) -> list[dict]:
    """Pop monitor daemon notifications (taey:{node_id}:notifications)."""
    messages = []
    key = f"taey:{node_id}:notifications"
    for _ in range(max_count):
        raw = redis_client.lpop(key)
        if not raw:
            break
        try:
            messages.append(json.loads(raw))
        except json.JSONDecodeError:
            messages.append({"raw": raw, "type": "unparseable"})
    return messages


def peek_count(redis_client, node_id: str) -> int:
    """Check inbox size without consuming."""
    return redis_client.llen(f"taey:{node_id}:inbox")


def peek_notifications_count(redis_client, node_id: str) -> int:
    """Check monitor notifications count without consuming."""
    return redis_client.llen(f"taey:{node_id}:notifications")


def set_tool_running(redis_client, node_id: str, ttl: int = 300):
    """Mark node as mid-tool-call. TTL is safety net for crashes."""
    redis_client.set(f"taey:{node_id}:tool_running", "1", ex=ttl)
    redis_client.set(f"taey:{node_id}:last_tool_activity", str(time.time()))


def clear_tool_running(redis_client, node_id: str):
    """Clear tool-running flag and update last activity."""
    redis_client.delete(f"taey:{node_id}:tool_running")
    redis_client.set(f"taey:{node_id}:last_tool_activity", str(time.time()))


def is_node_idle(redis_client, node_id: str, idle_threshold: int = 30) -> bool:
    """Check if a node is idle (safe to inject via tmux).

    Idle means: no tool_running flag AND last_tool_activity > threshold seconds ago.
    """
    if redis_client.exists(f"taey:{node_id}:tool_running"):
        return False
    last_str = redis_client.get(f"taey:{node_id}:last_tool_activity")
    if not last_str:
        return True  # no activity recorded = idle
    try:
        elapsed = time.time() - float(last_str)
        return elapsed > idle_threshold
    except (ValueError, TypeError):
        return True
