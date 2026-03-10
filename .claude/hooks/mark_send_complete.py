#!/usr/bin/env python3
"""
PostToolUse hook for taey_send_message: Mark workflow as "sent".

When taey_send_message completes successfully:
1. Sets taey:workflow:active_status to "sent"
2. This allows taey_prepare for a DIFFERENT platform

The daemon is now monitoring in background, so we're free to start
another platform's workflow while waiting for the response.

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, node_key


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_result = data.get("tool_result", {})

    if isinstance(tool_result, str):
        try:
            result_data = json.loads(tool_result)
        except Exception:
            result_data = {"success": False}
    else:
        result_data = tool_result

    # Only mark complete if send was successful (no error key in result)
    if "error" in result_data:
        sys.exit(0)

    r = get_redis()
    if r:
        try:
            r.set(node_key("workflow:active_status"), "sent")
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
