#!/usr/bin/env python3
"""
PreToolUse hook for taey_send_message
CRITICAL: Blocks sends unless ALL prerequisites are met.

Prerequisites:
1. Plan exists for the platform
2. Inspect completed for this platform
3. If attachments declared in plan, attach must have run

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis


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
        deny("No platform specified in send_message")

    r = get_redis()
    if not r:
        deny("Cannot connect to Redis")
    try:
        r.ping()
    except Exception as e:
        deny(f"Redis connection failed: {e}")

    # Check for active plan
    plan_json = r.get(f"taey:plan:{platform}")
    if not plan_json:
        deny(f"No plan found for {platform}. Call taey_plan first.")

    try:
        plan = json.loads(plan_json)
    except Exception:
        deny(f"Invalid plan data for {platform}")

    plan_id = plan.get("id", plan.get("plan_id", "unknown"))

    # Check inspect completed
    inspect_json = r.get(f"taey:checkpoint:{platform}:inspect")
    if not inspect_json:
        deny(f"Inspect not completed for {platform}. Run taey_inspect first.")

    # Check attachments if declared in plan
    required_attachments = plan.get("attachments", [])
    if required_attachments:
        attach_json = r.get(f"taey:checkpoint:{platform}:attach")
        if not attach_json:
            deny(f"Plan requires {len(required_attachments)} attachment(s). Run taey_attach first.")

        try:
            attach_data = json.loads(attach_json)
            attached_count = attach_data.get("attached_count", 0)
            if attached_count != len(required_attachments):
                deny(f"Attachment count mismatch: required {len(required_attachments)}, got {attached_count}")
        except Exception:
            deny("Invalid attachment checkpoint data")

    allow(f"All prerequisites met for plan {plan_id}")


if __name__ == "__main__":
    main()
