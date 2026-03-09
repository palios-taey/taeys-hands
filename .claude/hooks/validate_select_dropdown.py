#!/usr/bin/env python3
"""
PreToolUse hook for taey_select_dropdown
Requires: taey_prepare called for this platform (workflow lock must be active).

WHY: taey_select_dropdown changes model/mode. You MUST call taey_prepare first
     to understand what the options actually mean. Selecting without prepare
     caused mode selection bugs (e.g. selecting "Thinking" instead of "Deep Think").

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os

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
    platform = tool_input.get("platform", "")

    if not platform:
        deny("No platform specified in taey_select_dropdown")

    r = get_redis()
    if not r:
        deny("Cannot connect to Redis")
    try:
        r.ping()
    except Exception as e:
        deny(f"Redis connection failed: {e}")

    # Check that taey_prepare was called for this platform
    active_platform = r.get(node_key("workflow:active_platform"))
    if not active_platform:
        deny(
            f"taey_prepare not called for {platform}.\n\n"
            f"REQUIRED WORKFLOW:\n"
            f"1. taey_list_sessions()\n"
            f"2. taey_prepare(platform='{platform}')  ← tells you what options are available\n"
            f"3. taey_select_dropdown(...)  ← only AFTER you know the options\n\n"
            f"Without prepare, you don't know what the dropdown options mean."
        )

    if active_platform != platform:
        deny(
            f"Workflow locked to '{active_platform}', but trying to select dropdown on '{platform}'.\n\n"
            f"Complete the workflow for '{active_platform}' first, or call:\n"
            f"  taey_prepare(platform='{platform}')"
        )

    allow(f"Prepare completed for {platform}, dropdown selection allowed")


if __name__ == "__main__":
    main()
