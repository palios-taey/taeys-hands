#!/usr/bin/env python3
"""
PreToolUse hook for taey_select_dropdown
Requires: Plan exists for the platform (same check as validate_attach).

Workers are blocked (they use default models only).

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


WORKER_HOSTNAMES = {'jetson', 'thor'}


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        deny(f"Invalid JSON input: {e}")

    # Workers NEVER select dropdowns — they use default models only
    import socket
    hostname = socket.gethostname().lower()
    if hostname in WORKER_HOSTNAMES:
        deny(
            f"BLOCKED: Worker nodes ({hostname}) must NOT call taey_select_dropdown.\n"
            "Workers use DEFAULT models only.\n"
            "Workflow: taey_inspect → taey_attach → taey_inspect → taey_click → taey_send_message"
        )

    tool_input = data.get("tool_input", {})
    platform = tool_input.get("platform", "")

    if not platform:
        deny("No platform specified in taey_select_dropdown")

    r = get_redis()
    if not r:
        deny("Redis unavailable — required infrastructure is down")
    try:
        r.ping()
    except Exception:
        deny("Redis unavailable — required infrastructure is down")

    # Check for plan (same gate as validate_attach)
    plan_json = r.get(node_key(f"plan:{platform}"))
    if not plan_json:
        deny(
            f"No plan for {platform}. Create a plan with taey_plan first.\n"
            "Plans define the required model/mode/tools for the platform."
        )

    allow(f"Plan exists for {platform}, dropdown selection allowed")


if __name__ == "__main__":
    main()
