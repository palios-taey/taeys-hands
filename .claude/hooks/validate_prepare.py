#!/usr/bin/env python3
"""
PreToolUse hook for taey_prepare
Requires: taey_list_sessions called recently (within 30 min).

WHY: You must know the current session state before preparing a new one.
     This prevents preparing without context (which caused mode selection bugs).

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os
import time

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, node_key

CHECKPOINT_TTL = 1800  # 30 minutes


def deny(reason: str):
    response = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(response))
    sys.exit(0)


def allow(reason: str):
    response = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(response))
    sys.exit(0)


WORKER_HOSTNAMES = {'jetson', 'thor'}


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        deny(f"Invalid JSON input: {e}")

    # Workers NEVER call prepare — they use default models only
    import socket
    hostname = socket.gethostname().lower()
    if hostname in WORKER_HOSTNAMES:
        deny(
            f"BLOCKED: Worker nodes ({hostname}) must NOT call taey_prepare.\n"
            "Workers use DEFAULT models only. Do NOT call taey_prepare or taey_select_dropdown.\n"
            "Workflow: taey_inspect → taey_attach → taey_inspect → taey_click → taey_send_message"
        )

    r = get_redis()
    if not r:
        deny("Cannot connect to Redis")
    try:
        r.ping()
    except Exception as e:
        deny(f"Redis connection failed: {e}")

    # Check for list_sessions checkpoint
    checkpoint = r.get(node_key("list_sessions_checkpoint"))
    if not checkpoint:
        deny(
            "Must call taey_list_sessions first.\n\n"
            "REQUIRED: taey_list_sessions() → then taey_prepare(platform)\n\n"
            "Why: You need to know current session state before preparing."
        )

    # Check if checkpoint is fresh enough
    try:
        checkpoint_time = float(checkpoint)
        age = time.time() - checkpoint_time
        if age > CHECKPOINT_TTL:
            r.delete(node_key("list_sessions_checkpoint"))
            deny(
                f"taey_list_sessions checkpoint expired ({int(age/60)} min old, limit 30 min).\n"
                "Call taey_list_sessions() again."
            )
    except (ValueError, TypeError):
        pass  # Non-timestamp checkpoint - allow through

    allow("list_sessions checkpoint valid")


if __name__ == "__main__":
    main()
