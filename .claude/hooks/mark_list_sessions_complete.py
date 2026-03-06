#!/usr/bin/env python3
"""
PostToolUse hook for taey_list_sessions: Store checkpoint in Redis.

This checkpoint is required before taey_prepare can be called (enforced by
validate_prepare.py). Ensures you have situational awareness before starting
a new platform workflow.

Redis key: taey:list_sessions_checkpoint (30 min TTL)

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os
import time

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_result = data.get("tool_result", {})

    # Only store checkpoint if list_sessions succeeded (no error key)
    if isinstance(tool_result, str):
        try:
            result_data = json.loads(tool_result)
        except Exception:
            result_data = {"error": "parse_failed"}
    else:
        result_data = tool_result if isinstance(tool_result, dict) else {}

    if "error" in result_data:
        sys.exit(0)

    r = get_redis()
    if r:
        try:
            r.set("taey:list_sessions_checkpoint", str(time.time()), ex=1800)  # 30 min TTL
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
