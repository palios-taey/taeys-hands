#!/usr/bin/env python3
"""
PreToolUse hook for taey_prepare: Enforce ONE active platform at a time.

LEAN WORKFLOW ENFORCEMENT:
- Once taey_prepare(X) is called, you're LOCKED into completing X's send cycle
- Cannot call taey_prepare(Y) until X's send_message completes
- This prevents dangerous window-switching mid-workflow

Redis keys used:
- taey:workflow:active_platform       -> Current platform locked in workflow
- taey:workflow:active_status         -> "preparing" | "sent"
- taey:workflow:active_timestamp      -> When lock was acquired

Lock is cleared when:
- taey_send_message completes (PostToolUse sets status to "sent")
- Lock is stale (>30 minutes)
- Same platform calls prepare again (re-prepare allowed)

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os
import time

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, node_key


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


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        deny(f"Invalid JSON input: {e}")

    tool_input = data.get("tool_input", {})
    requested_platform = tool_input.get("platform", "")

    if not requested_platform:
        deny("No platform specified in taey_prepare")

    r = get_redis()
    if not r:
        deny("Cannot connect to Redis")
    try:
        r.ping()
    except Exception as e:
        deny(f"Redis connection failed: {e}")

    # Check for active platform lock
    active_platform = r.get(node_key("workflow:active_platform"))
    active_status = r.get(node_key("workflow:active_status"))
    active_timestamp = r.get(node_key("workflow:active_timestamp"))

    # No active platform - allow and set lock
    if not active_platform:
        r.set(node_key("workflow:active_platform"), requested_platform)
        r.set(node_key("workflow:active_status"), "preparing")
        r.set(node_key("workflow:active_timestamp"), str(time.time()))
        allow(f"Workflow lock acquired for {requested_platform}")

    # Check if lock is stale (>30 minutes)
    if active_timestamp:
        try:
            age = time.time() - float(active_timestamp)
            if age > 1800:  # 30 minutes
                # Clear stale lock
                r.delete(node_key("workflow:active_platform"))
                r.delete(node_key("workflow:active_status"))
                r.delete(node_key("workflow:active_timestamp"))
                # Set new lock
                r.set(node_key("workflow:active_platform"), requested_platform)
                r.set(node_key("workflow:active_status"), "preparing")
                r.set(node_key("workflow:active_timestamp"), str(time.time()))
                allow(f"Stale lock cleared ({int(age/60)} min old). New lock for {requested_platform}")
        except Exception:
            pass

    # Same platform - allow re-prepare (refresh the workflow)
    if active_platform == requested_platform:
        r.set(node_key("workflow:active_status"), "preparing")
        r.set(node_key("workflow:active_timestamp"), str(time.time()))
        allow(f"Re-preparing {requested_platform} (same platform)")

    # Different platform - check if previous is complete
    if active_status == "sent":
        # Previous platform sent its message - clear and allow new
        r.set(node_key("workflow:active_platform"), requested_platform)
        r.set(node_key("workflow:active_status"), "preparing")
        r.set(node_key("workflow:active_timestamp"), str(time.time()))
        allow(f"Previous platform ({active_platform}) complete. Now locked to {requested_platform}")

    # Check if a monitor daemon is running for the active platform
    # If so, send_message already completed - the PostToolUse hook may have failed
    if active_status == "preparing":
        try:
            monitor_keys = r.keys(node_key("monitor:*"))
            for key in monitor_keys:
                monitor_json = r.get(key)
                if monitor_json:
                    monitor_data = json.loads(monitor_json)
                    if monitor_data.get("platform") == active_platform:
                        # Monitor exists = send_message completed successfully
                        r.set(node_key("workflow:active_platform"), requested_platform)
                        r.set(node_key("workflow:active_status"), "preparing")
                        r.set(node_key("workflow:active_timestamp"), str(time.time()))
                        allow(f"Monitor running for {active_platform} (send complete). Now locked to {requested_platform}")
        except Exception:
            pass

    # Previous platform still in workflow - DENY
    deny(
        f"WORKFLOW LOCKED to {active_platform} (status: {active_status}).\n\n"
        f"Complete the send cycle for {active_platform} before preparing {requested_platform}.\n"
        f"Call taey_send_message(platform='{active_platform}') to complete,\n"
        f"or wait 30 min for lock timeout."
    )


if __name__ == "__main__":
    main()
