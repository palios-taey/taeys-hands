#!/usr/bin/env python3
"""
Unified Notification Hook (PostToolUse)

Drains THREE notification sources after each tool call:
1. taey:{node_id}:notifications — monitor daemon (response detection)
2. taey:{node_id}:inbox — inter-Claude messages (escalations, heartbeats)
3. orch:notify:{node_id} — orchestration notifications

Also clears the tool_running flag (set by PreToolUse pre_tool_activity.py)
so the tmux fallback daemon knows this instance is between tool calls.

Delivery is via additionalContext — Claude sees notifications inline after
each tool result, enabling it to react to background events without
explicit polling.

Works on: Spark, CCM, Jetson, Thor (auto-detects environment)
"""
import json
import sys
import os
import time

# Add hooks directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_config, get_redis, node_key, detect_node_id

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


def clear_tool_activity(r, node_id):
    """Clear tool_running flag and update last activity timestamp.

    This tells the tmux fallback daemon that the instance is between
    tool calls (safe to inject if idle long enough).
    """
    try:
        r.delete(f"taey:{node_id}:tool_running")
        r.set(f"taey:{node_id}:last_tool_activity", str(time.time()))
    except Exception as e:
        log_debug(f"Activity clear error: {e}")


def drain_queue(r, key, max_count=10, from_tail=False):
    """Pop up to max_count items from a Redis list. Returns parsed dicts.

    Args:
        from_tail: If True, use RPOP (for LPUSH writers = FIFO).
                   If False, use LPOP (for RPUSH writers = FIFO).
    """
    items = []
    pop_fn = r.rpop if from_tail else r.lpop
    for _ in range(max_count):
        raw = pop_fn(key)
        if not raw:
            break
        try:
            parsed = json.loads(raw)
            items.append(parsed)
        except json.JSONDecodeError:
            items.append({"raw": raw})
    return items


def get_all_pending(r, node_id):
    """Drain all notification sources. Returns (monitor_notifs, inbox_msgs, orch_notifs)."""
    # 1. Monitor daemon notifications (RPUSH writers → LPOP = FIFO)
    monitor = drain_queue(r, f"taey:{node_id}:notifications", 10)

    # 2. Inter-Claude inbox messages (LPUSH writers → RPOP = FIFO)
    inbox = drain_queue(r, f"taey:{node_id}:inbox", 10, from_tail=True)

    # 3. Orchestration notifications
    orch = drain_queue(r, f"orch:notify:{node_id}", 5)

    return monitor, inbox, orch


def format_monitor_notification(notif):
    """Format a monitor daemon notification."""
    status = notif.get('status', 'unknown')
    platform = notif.get('platform', 'unknown')
    msg = notif.get('message', '')
    elapsed = notif.get('elapsed_seconds', '')
    monitor_id = notif.get('monitor_id', '')[:8] if notif.get('monitor_id') else ''
    has_artifacts = notif.get('has_artifacts', False)
    exchange_hash = notif.get('exchange_hash', '')

    lines = []
    if status == 'response_complete':
        lines.append(f"  *** {platform.upper()} RESPONSE READY ***")
        lines.append(f"  Platform: {platform}")
        lines.append(f"  Response time: {elapsed}s")
        lines.append(f"  Artifacts: {'Yes - extract manually!' if has_artifacts else 'No'}")
        if exchange_hash:
            lines.append(f"  Exchange stored in ISMA: {exchange_hash[:16]}")
        lines.append(f"  Monitor ID: {monitor_id}")
        if msg:
            lines.append(f"  Message: {msg}")
        lines.append(f"  ACTION: Call taey_quick_extract(platform='{platform}', complete=True)")
        return '\n'.join(lines), True
    elif status == 'timeout':
        return f"  [TIMEOUT] [{platform}] Timed out after {elapsed}s - {monitor_id}", False
    elif status == 'error':
        return f"  [ERROR] [{platform}] {msg} - {monitor_id}", False
    elif status == 'started':
        return f"  [STARTED] [{platform}] Monitor started - {monitor_id}", False
    elif status == 'complete':
        line = f"  [COMPLETE] [{platform}] Response ready ({elapsed}s) - {monitor_id}"
        if msg:
            line += f"\n    Message: {msg}"
        return line, True
    else:
        return f"  [{status.upper()}] [{platform}] {msg}", False


def format_inbox_message(msg):
    """Format an inter-Claude inbox message."""
    sender = msg.get('from', 'unknown')
    mtype = msg.get('type', 'message').upper()
    body = msg.get('body', str(msg))
    priority = msg.get('priority', 'normal')
    prefix = "!!!" if priority == "high" else ""
    return f"  {prefix}[{mtype} from {sender}]: {body}"


def format_all(monitor_notifs, inbox_msgs, orch_notifs):
    """Format all notifications into a single context string."""
    total = len(monitor_notifs) + len(inbox_msgs) + len(orch_notifs)
    if total == 0:
        return None

    lines = ["", "=== NOTIFICATIONS ==="]
    requires_action = False

    # Monitor daemon notifications (response detection)
    if monitor_notifs:
        lines.append("--- Response Detection ---")
        for notif in monitor_notifs:
            text, action = format_monitor_notification(notif)
            lines.append(text)
            if action:
                requires_action = True

    # Inter-Claude inbox messages
    if inbox_msgs:
        lines.append("--- Messages ---")
        for msg in inbox_msgs:
            lines.append(format_inbox_message(msg))

    # Orchestration notifications
    if orch_notifs:
        lines.append("--- Orchestration ---")
        for notif in orch_notifs:
            notif_type = notif.get('type', 'info')
            notif_msg = notif.get('message', str(notif))
            lines.append(f"  [{notif_type.upper()}] {notif_msg}")

    lines.append("=====================")

    if requires_action:
        lines.append("Extract responses with taey_quick_extract.")

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

    r = get_redis()
    if not r:
        # No Redis — nothing to do
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse"}}))
        sys.exit(0)

    node_id = detect_node_id()

    # Clear tool_running flag (set by PreToolUse pre_tool_activity.py)
    clear_tool_activity(r, node_id)

    # Drain all notification sources
    try:
        monitor, inbox, orch = get_all_pending(r, node_id)
        total = len(monitor) + len(inbox) + len(orch)
        log_debug(f"Drained: {len(monitor)} monitor, {len(inbox)} inbox, {len(orch)} orch")
    except Exception as e:
        log_debug(f"Redis drain error: {e}")
        monitor, inbox, orch = [], [], []
        total = 0

    context = format_all(monitor, inbox, orch)

    response = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse"
        }
    }

    if context:
        response["hookSpecificOutput"]["additionalContext"] = context
        log_debug(f"Injecting context: {len(context)} chars, {total} items")
        print(context, file=sys.stderr)

    print(json.dumps(response))
    sys.exit(0)


if __name__ == "__main__":
    main()
