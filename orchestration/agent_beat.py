#!/usr/bin/env python3
"""
Agent Heartbeat Script

Lightweight heartbeat for any agent on any machine.
No orchestration package required — just HTTP POST to the dashboard.

Usage:
  # As a long-running process (beats every 12s):
  python3 agent_beat.py claude-weaver

  # With activity description:
  python3 agent_beat.py claude-weaver "reviewing consent middleware"

  # Single beat (for cron/hooks):
  python3 agent_beat.py claude-weaver --once

  # Send a message to The Stream:
  python3 agent_beat.py claude-weaver --message "Found a pattern that resonates"

  # Report task completion:
  python3 agent_beat.py claude-weaver --report task-abc123 --summary "Done"
"""

import json
import sys
import time
import urllib.request
import urllib.error

import os
DASHBOARD_URL = os.environ.get("ORCH_DASHBOARD_URL", "http://localhost:5001")


def post(endpoint: str, data: dict) -> dict:
    """POST JSON to dashboard API."""
    url = f"{DASHBOARD_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": str(e)}


def heartbeat_loop(agent_id: str, activity: str = ""):
    """Beat every 12 seconds until killed."""
    print(f"[heartbeat] {agent_id} beating at {DASHBOARD_URL} (Ctrl+C to stop)")
    while True:
        result = post("/api/heartbeat", {"agent_id": agent_id, "activity": activity})
        if "error" in result:
            print(f"[heartbeat] error: {result['error']}")
        time.sleep(12)


def main():
    if len(sys.argv) < 2:
        print("Usage: agent_beat.py <agent_id> [activity] [--once|--message|--report]")
        sys.exit(1)

    agent_id = sys.argv[1]
    args = sys.argv[2:]

    # --message "text"
    if "--message" in args:
        idx = args.index("--message")
        text = args[idx + 1] if idx + 1 < len(args) else ""
        msg_type = "insight"
        if "--type" in args:
            tidx = args.index("--type")
            msg_type = args[tidx + 1] if tidx + 1 < len(args) else "insight"
        result = post("/api/message", {"agent_id": agent_id, "text": text, "type": msg_type})
        print(json.dumps(result))
        return

    # --report task-id --summary "text"
    if "--report" in args:
        idx = args.index("--report")
        task_id = args[idx + 1] if idx + 1 < len(args) else ""
        summary = ""
        status = "completed"
        if "--summary" in args:
            sidx = args.index("--summary")
            summary = args[sidx + 1] if sidx + 1 < len(args) else ""
        if "--failed" in args:
            status = "failed"
        result = post("/api/report", {"task_id": task_id, "agent_id": agent_id, "status": status, "summary": summary})
        print(json.dumps(result))
        return

    # --once: single heartbeat
    activity = ""
    if args and args[0] not in ("--once",):
        activity = args[0]
        args = args[1:]

    if "--once" in args:
        result = post("/api/heartbeat", {"agent_id": agent_id, "activity": activity})
        print(json.dumps(result))
        return

    # Default: continuous heartbeat
    try:
        heartbeat_loop(agent_id, activity)
    except KeyboardInterrupt:
        print(f"\n[heartbeat] {agent_id} stopped")


if __name__ == "__main__":
    main()
