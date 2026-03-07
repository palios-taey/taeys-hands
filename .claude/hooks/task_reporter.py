#!/usr/bin/env python3
"""
PostToolUse hook: Auto-report task completions to Conductor's Console dashboard.

Pattern: Agent pushes task reports to Redis queue `orch:report:pending`.
This hook drains that queue on each tool call and POSTs to the dashboard API.

Also handles agent status updates (idle/working transitions).

Redis queue format (JSON):
    {"task_id": "task-xxx", "status": "completed", "summary": "What was done"}

Dashboard API:
    POST /api/report  - task completion report
    POST /api/status  - agent status update
    POST /api/message - insights/discoveries

Usage from agent code or bash:
    # Push a report to Redis (hook picks it up on next tool call)
    redis-cli RPUSH orch:report:pending '{"task_id":"task-xxx","status":"completed","summary":"Done"}'

    # Or directly via curl (bypass hook):
    curl -X POST http://10.0.0.68:5001/api/report -H 'Content-Type: application/json' \
         -d '{"task_id":"task-xxx","agent_id":"claude-weaver","status":"completed","summary":"Done"}'
"""
import json
import sys
import os
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, detect_node_id

DASHBOARD_URL = os.environ.get("CONDUCTOR_DASHBOARD_URL", "http://10.0.0.68:5001")
AGENT_ID_MAP = {
    "taeys-hands": "claude-weaver",
    "weaver": "claude-weaver",
    "claw": "claude-claw",
    "jetson-claude": "claude-jetson",
    "thor-claude": "claude-thor",
}


def get_agent_id():
    node_id = detect_node_id()
    return AGENT_ID_MAP.get(node_id, f"claude-{node_id}")


def post_json(path, data, timeout=3):
    """POST JSON to dashboard API. Fire-and-forget, never blocks."""
    try:
        url = f"{DASHBOARD_URL}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def drain_report_queue():
    """Pop pending task reports from Redis and POST each to dashboard."""
    r = get_redis()
    if not r:
        return 0

    agent_id = get_agent_id()
    count = 0

    try:
        for _ in range(20):  # max 20 reports per tool call
            raw = r.lpop("orch:report:pending")
            if not raw:
                break

            try:
                report = json.loads(raw)
            except json.JSONDecodeError:
                continue

            report.setdefault("agent_id", agent_id)
            post_json("/api/report", report)
            count += 1

            # If task completed, also post an idle status
            if report.get("status") == "completed":
                post_json("/api/status", {
                    "agent_id": agent_id,
                    "status": "idle",
                    "task": None,
                })
    except Exception:
        pass

    return count


def drain_message_queue():
    """Pop pending insight/discovery messages and POST to dashboard."""
    r = get_redis()
    if not r:
        return 0

    agent_id = get_agent_id()
    count = 0

    try:
        for _ in range(10):
            raw = r.lpop("orch:message:pending")
            if not raw:
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg.setdefault("agent_id", agent_id)
            msg.setdefault("type", "insight")
            post_json("/api/message", msg)
            count += 1
    except Exception:
        pass

    return count


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    reports = drain_report_queue()
    messages = drain_message_queue()

    response = {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}

    if reports > 0 or messages > 0:
        ctx = f"[Conductor] Reported {reports} task(s) and {messages} message(s) to dashboard."
        response["hookSpecificOutput"]["additionalContext"] = ctx

    print(json.dumps(response))
    sys.exit(0)


if __name__ == "__main__":
    main()
