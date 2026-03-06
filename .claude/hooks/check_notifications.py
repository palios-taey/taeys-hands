#!/usr/bin/env python3
"""
Ambient Notification Hook (PostToolUse)

Reads pending notifications from Redis queue and injects them into Claude's
context via the additionalContext field. This implements the "piggybacking"
pattern for background process notifications.

Flow:
1. Monitor daemon pushes to Redis: rpush("taey:notifications", json)
2. This hook pops from Redis AFTER each tool call: lpop("taey:notifications")
3. Notifications delivered via additionalContext in hook output

IMPORTANT: additionalContext only works with PostToolUse, UserPromptSubmit,
and SessionStart hooks - NOT PreToolUse. This hook uses PostToolUse.

Works on: Spark, CCM, Windows (auto-detects environment)
"""
import json
import sys
import os

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_config, get_redis

CFG = get_config()


def log_debug(msg):
    """Write debug message to log file."""
    try:
        agent_id = CFG['agent_id']
        with open(f"/tmp/{agent_id}_notifications_debug.log", "a") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def get_pending_notifications():
    """
    Pop pending notifications from Redis queue.
    Returns list of notification dicts.
    """
    r = get_redis()
    if not r:
        return []

    try:
        notifications = []
        # Pop up to 10 notifications per tool call
        for _ in range(10):
            notification_json = r.lpop("taey:notifications")
            if not notification_json:
                break
            log_debug(f"Raw notification: {repr(notification_json)}")
            try:
                parsed = json.loads(notification_json)
                log_debug(f"Parsed: {parsed}")
                notifications.append(parsed)
            except json.JSONDecodeError as e:
                log_debug(f"JSON decode error: {e}")
                notifications.append({"raw": notification_json})

        return notifications
    except ImportError:
        return []
    except Exception as e:
        log_debug(f"Redis error: {e}")
        return []


def format_notifications(notifications):
    """Format notifications into human-readable context string."""
    if not notifications:
        return None

    lines = ["", "=== BACKGROUND NOTIFICATIONS ==="]
    requires_action = False

    for notif in notifications:
        if isinstance(notif, dict):
            status = notif.get('status', 'unknown')
            platform = notif.get('platform', 'unknown')
            msg = notif.get('message', '')
            elapsed = notif.get('elapsed_seconds', '')
            monitor_id = notif.get('monitor_id', '')[:8] if notif.get('monitor_id') else ''
            has_artifacts = notif.get('has_artifacts', False)
            exchange_hash = notif.get('exchange_hash', '')

            if status == 'response_complete':
                requires_action = True
                lines.append(f"")
                lines.append(f"  *** {platform.upper()} RESPONSE READY ***")
                lines.append(f"  Platform: {platform}")
                lines.append(f"  Response time: {elapsed}s")
                lines.append(f"  Artifacts: {'Yes - extract manually!' if has_artifacts else 'No'}")
                if exchange_hash:
                    lines.append(f"  Exchange stored in ISMA: {exchange_hash[:16]}")
                lines.append(f"  Monitor ID: {monitor_id}")
                if msg:
                    lines.append(f"  Message: {msg}")
                lines.append(f"")
                lines.append(f"  ACTION: Call taey_quick_extract(platform='{platform}', complete=True)")
            elif status == 'timeout':
                lines.append(f"  [TIMEOUT] [{platform}] Timed out after {elapsed}s - {monitor_id}")
            elif status == 'error':
                lines.append(f"  [ERROR] [{platform}] {msg} - {monitor_id}")
            elif status == 'started':
                lines.append(f"  [STARTED] [{platform}] Monitor started - {monitor_id}")
            elif status == 'complete':
                lines.append(f"  [COMPLETE] [{platform}] Response ready ({elapsed}s) - {monitor_id}")
                if msg:
                    lines.append(f"    Message: {msg}")
            else:
                lines.append(f"  [{status.upper()}] [{platform}] {msg}")
        else:
            lines.append(f"  {str(notif)}")

    lines.append("================================")

    if requires_action:
        lines.append("")
        lines.append("Extract the response with taey_quick_extract.")

    lines.append("")
    return "\n".join(lines)


def main():
    log_debug("PostToolUse hook started")

    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get('tool_name', 'unknown')
        log_debug(f"Tool completed: {tool_name}")
    except (json.JSONDecodeError, EOFError) as e:
        log_debug(f"Input error: {e}")
        sys.exit(0)

    notifications = get_pending_notifications()
    log_debug(f"Notifications found: {len(notifications)}")
    context = format_notifications(notifications)

    response = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse"
        }
    }

    if context:
        response["hookSpecificOutput"]["additionalContext"] = context
        log_debug(f"Injecting context: {len(context)} chars")
        print(context, file=sys.stderr)

    print(json.dumps(response))
    sys.exit(0)


if __name__ == "__main__":
    main()
