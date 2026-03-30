#!/usr/bin/env python3
"""
PreToolUse hook: Set tool_running flag for activity tracking.

Runs on ALL tool calls (*). Sets Redis key with 300s TTL so the
tmux fallback daemon knows not to inject during active tool execution.
PostToolUse hook (check_notifications.py) clears this flag.

Must be fast — adds ~50ms to every tool call (Python startup + Redis SET).
"""
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, detect_node_id


def main():
    # Drain stdin (required by hook protocol)
    try:
        sys.stdin.read()
    except Exception:
        pass

    # Set activity flag — never block on failure
    try:
        r = get_redis()
        if r:
            node_id = detect_node_id()
            r.set(f"taey:{node_id}:tool_running", "1", ex=300)
            r.set(f"taey:{node_id}:last_tool_activity", str(time.time()))
    except Exception:
        pass

    # Always allow
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Activity tracked",
        }
    }))


if __name__ == "__main__":
    main()
