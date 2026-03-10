#!/usr/bin/env python3
"""
PreToolUse hook for taey_attach
Validates: platform is specified and file_path exists.

Plan check is advisory only — attaching without a plan is allowed
(HMM enrichment, ad-hoc testing, standalone workflows).

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
    file_path = tool_input.get("file_path", "")

    if not platform:
        deny("No platform specified in taey_attach")

    if not file_path:
        deny("No file_path specified in taey_attach")

    if not os.path.isfile(file_path):
        deny(f"File not found: {file_path}")

    allow(f"Attach allowed for {platform} — file exists: {os.path.basename(file_path)}")


if __name__ == "__main__":
    main()
