#!/usr/bin/env python3
"""
PreToolUse hook: Block taey_ tools when a response is pending review.

LEAN WORKFLOW ENFORCEMENT:
- When a platform has an unread AI response, you MUST extract it before
  doing anything else (except on that platform's extract/inspect/click tools).
- Prevents accidentally starting new sends while responses are waiting.

Allows through:
- taey_quick_extract (always - to actually extract the response)
- taey_inspect (always - to check what's on screen)
- taey_click (always - to click elements)
- All other tools are blocked IF a different platform has a pending response

Redis keys checked:
- taey:pending_prompt:{platform} - set by send_message, cleared by quick_extract
- taey:response_ready:{platform} - set by monitor daemon

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis

# Tools that are always allowed (extraction + navigation)
ALWAYS_ALLOWED = {
    'taey_quick_extract',
    'taey_inspect',
    'taey_click',
    'taey_extract_history',
    'taey_list_sessions',
    'taey_monitors',
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

    # Check for pending responses on any platform
    try:
        pending_keys = r.keys("taey:pending_prompt:*")
        ready_keys = r.keys("taey:response_ready:*")

        all_pending = set()

        for key in pending_keys:
            platform = key.replace("taey:pending_prompt:", "")
            all_pending.add(platform)

        for key in ready_keys:
            platform = key.replace("taey:response_ready:", "")
            all_pending.add(platform)

        if not all_pending:
            allow("No pending responses")

        # Check if current tool is for the pending platform
        current_platform = tool_input.get("platform", "")

        # If only one pending platform and this tool is for it, allow
        if len(all_pending) == 1 and current_platform in all_pending:
            allow(f"Tool targets pending platform {current_platform}")

        # If current platform has a pending response, block other actions
        pending_list = ", ".join(sorted(all_pending))
        deny(
            f"PENDING RESPONSES on: {pending_list}\n\n"
            f"Extract pending responses before continuing:\n"
            f"  taey_quick_extract(platform='{list(all_pending)[0]}')\n\n"
            f"Or check status with: taey_list_sessions()"
        )

    except Exception:
        allow("Redis check failed - allowing")


if __name__ == "__main__":
    main()
