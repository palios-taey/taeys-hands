#!/usr/bin/env python3
"""
PreToolUse hook for taey_inspect
Requires: Plan exists for the platform (call taey_plan first).

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
# Platforms unavailable on worker Firefox instances (no tab / needs login)
WORKER_BLOCKED_PLATFORMS = {'grok', 'claude', 'perplexity', 'x_twitter', 'linkedin'}


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        deny(f"Invalid JSON input: {e}")

    tool_input = data.get("tool_input", {})
    platform = tool_input.get("platform", "")

    # Block workers from platforms they don't have tabs for
    import socket
    hostname = socket.gethostname().lower()
    if hostname in WORKER_HOSTNAMES and platform in WORKER_BLOCKED_PLATFORMS:
        deny(
            f"BLOCKED: {platform} is not available on {hostname}.\n"
            "Workers have ONLY ChatGPT (Alt+1) and Gemini (Alt+2).\n"
            "Skip this platform and move to the next package."
        )

    if not platform:
        deny("No platform specified in taey_inspect")

    r = get_redis()
    if not r:
        allow("Redis unavailable - allowing inspect without plan check")
    try:
        r.ping()
    except Exception:
        allow("Redis unavailable - allowing inspect without plan check")

    # Check for plan (plans are consumption-based - deleted after successful send)
    plan_json = r.get(node_key(f"plan:{platform}"))
    if not plan_json:
        allow(f"No plan found for {platform} - allowing inspect (plan is advisory)")

    allow(f"Plan exists for {platform}, inspect allowed")


if __name__ == "__main__":
    main()
