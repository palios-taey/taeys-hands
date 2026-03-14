#!/usr/bin/env python3
"""
PreToolUse hook for taey_attach
CRITICAL: Blocks attach unless a plan exists for the platform.
Also validates: platform is specified and file_path exists.
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
    file_path = tool_input.get("file_path", "")

    if not platform:
        deny("No platform specified in taey_attach")

    if not file_path:
        deny("No file_path specified in taey_attach")

    if not os.path.isfile(file_path):
        deny(f"File not found: {file_path}")

    # Require active plan — Redis is required infrastructure
    r = get_redis()
    if not r:
        deny("Redis unavailable — required infrastructure is down")
    try:
        r.ping()
    except Exception:
        deny("Redis unavailable — required infrastructure is down")

    plan_json = r.get(node_key(f"plan:{platform}"))
    if not plan_json:
        deny(f"No plan for {platform}. Create a plan with taey_plan first. "
             "Plans auto-include identity files and consolidate attachments.")

    allow(f"Attach allowed for {platform} — plan exists, file: {os.path.basename(file_path)}")


if __name__ == "__main__":
    main()
