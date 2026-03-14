#!/usr/bin/env python3
"""
PostToolUse hook: Mark response as reviewed after extraction.

Sets/clears Redis flags to track extraction state:
- complete=False: sets taey:response_reviewed:{platform} (enables complete=True)
- complete=True: clears response flags + workflow lock (workflow fully done)

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
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    # Only process taey_quick_extract
    if tool_name not in ["taey_quick_extract", "mcp__taeys-hands__taey_quick_extract"]:
        return

    if not isinstance(tool_result, dict):
        return
    if not tool_result.get("success", False):
        return

    platform = tool_input.get("platform", "")
    complete = tool_input.get("complete", False)

    if not platform:
        return

    r = get_redis()
    if not r:
        return

    try:
        if complete:
            # complete=True - clear all flags (workflow complete)
            r.delete(node_key(f"response_reviewed:{platform}"))
            r.delete(node_key("workflow:active_platform"))
            r.delete(node_key("workflow:active_status"))
            r.delete(node_key("workflow:active_timestamp"))
        else:
            # complete=False - set reviewed flag (enables complete=True)
            r.set(node_key(f"response_reviewed:{platform}"), "true", ex=3600)

            has_artifacts = tool_result.get("has_artifacts", False)
            content_length = tool_result.get("length", 0)
            r.hset(node_key(f"extraction_summary:{platform}"), mapping={
                "has_artifacts": str(has_artifacts).lower(),
                "content_length": str(content_length),
                "platform": platform
            })
            r.expire(node_key(f"extraction_summary:{platform}"), 3600)

    except Exception as e:
        import logging
        logging.getLogger(__name__).error("mark_response_reviewed: Redis operation failed: %s", e)


if __name__ == "__main__":
    main()
