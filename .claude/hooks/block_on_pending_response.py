#!/usr/bin/env python3
"""
PreToolUse hook: Block double-sends to a platform with a pending response.

LEAN WORKFLOW ENFORCEMENT:
- Prevents sending a NEW message to a platform that already has one generating.
- Does NOT block cross-platform work (Dream Cycle pattern: send to A, move to B).
- Only blocks taey_send_message to the SAME platform with a pending_prompt.

Redis keys checked:
- taey:pending_prompt:{platform} - set by send_message, cleared by quick_extract
- taey:response_ready:{platform} - set by monitor daemon (response complete, unextracted)

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, node_key

# Tools that are always allowed (extraction + navigation)
ALWAYS_ALLOWED = {
    'taey_quick_extract',
    'taey_inspect',
    'taey_click',
    'taey_extract_history',
    'taey_list_sessions',
    'taey_monitors',
    'taey_plan',
    'taey_prepare',
    'taey_respawn_monitor',
    'taey_select_dropdown',
    'taey_attach',
}


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


def allow(reason: str = ""):
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
    except json.JSONDecodeError:
        allow()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Strip MCP prefix if present
    short_name = tool_name.split("__")[-1] if "__" in tool_name else tool_name

    # Always allow extraction and navigation tools
    if short_name in ALWAYS_ALLOWED:
        allow(f"{short_name} always allowed")

    # Connect to Redis
    r = get_redis()
    if not r:
        allow("Redis unavailable - allowing")

    try:
        r.ping()
    except Exception:
        allow("Redis ping failed - allowing")

    # Only block taey_send_message to a platform that already has a pending response
    # Cross-platform work is always allowed (Dream Cycle pattern)
    try:
        current_platform = tool_input.get("platform", "")

        # Only send_message can be blocked (prevents double-send)
        if short_name != "taey_send_message":
            allow(f"{short_name} allowed - only send_message is gated")

        # Check if THIS platform has a pending prompt
        pending_key = node_key(f"pending_prompt:{current_platform}")
        if r.exists(pending_key):
            deny(
                f"PENDING RESPONSE on {current_platform} — cannot double-send.\n\n"
                f"Extract first: taey_quick_extract(platform='{current_platform}')\n"
                f"Or check status: taey_list_sessions()"
            )

        # No pending on this platform — allow the send
        allow(f"No pending response on {current_platform}")

    except Exception:
        allow("Redis check failed - allowing")


if __name__ == "__main__":
    main()
