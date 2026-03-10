#!/usr/bin/env python3
"""
Notification tmux fallback daemon.

Watches Redis inbox AND monitor notifications for a target node.
When the node is idle (no tool_running, no activity for 30s+), delivers
pending messages via tmux send-keys injection.

This is the SAFETY NET — the PostToolUse hook is the primary delivery path.
This daemon only fires when Claude is truly idle (no tool calls running,
no tool activity for 30+ seconds).

The >15s tool call problem is solved by:
1. PreToolUse hook sets tool_running flag (TTL 300s)
2. This daemon checks tool_running before injecting
3. Even a 5-minute tool call is safe — flag persists until PostToolUse clears it

Usage:
    python3 notifications/daemon.py --node weaver --tmux-session taeys-hands
    python3 notifications/daemon.py --node jetson-claude --tmux-session jetson-claude

Typically started alongside the MCP server and runs in the background.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notifications.inbox import (
    receive, receive_notifications, peek_count, peek_notifications_count,
    is_node_idle,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [notify-daemon] %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 5     # seconds between checks
DEFAULT_IDLE_THRESHOLD = 30   # seconds of no tool activity before tmux injection


def inject_via_tmux(session: str, message: str) -> bool:
    """Inject a message into a tmux session's input.

    Uses the tmux-send script (base64-safe) if available,
    falls back to raw tmux send-keys.
    """
    tmux_send = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'scripts', 'tmux-send',
    )

    try:
        if os.path.isfile(tmux_send) and os.access(tmux_send, os.X_OK):
            result = subprocess.run(
                [tmux_send, session, message],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0

        # Fallback: raw tmux send-keys
        result = subprocess.run(
            ['tmux', 'send-keys', '-t', session, message, 'Enter'],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error(f"tmux injection failed: {e}")
        return False


def format_inbox_message(msg: dict) -> str:
    """Format an inbox message for tmux display."""
    sender = msg.get('from', 'unknown')
    mtype = msg.get('type', 'message').upper()
    body = msg.get('body', str(msg))
    return f"[{mtype} from {sender}]: {body}"


def format_notification(notif: dict) -> str:
    """Format a monitor notification for tmux display."""
    status = notif.get('status', 'unknown')
    platform = notif.get('platform', 'unknown')
    msg = notif.get('message', '')
    elapsed = notif.get('elapsed_seconds', '')

    if status in ('response_complete', 'complete'):
        return f"[RESPONSE READY on {platform.upper()}] ({elapsed}s) — extract with taey_quick_extract('{platform}')"
    elif status == 'timeout':
        return f"[TIMEOUT on {platform}] after {elapsed}s"
    elif status == 'error':
        return f"[ERROR on {platform}] {msg}"
    else:
        return f"[{status.upper()} on {platform}] {msg}"


def requeue_messages(redis_client, node_id: str, messages: list[dict], key_type: str = "inbox"):
    """Put messages back if tmux injection fails."""
    key = f"taey:{node_id}:{'inbox' if key_type == 'inbox' else 'notifications'}"
    for msg in reversed(messages):
        redis_client.rpush(key, json.dumps(msg))


def run_daemon(node_id: str, tmux_session: str,
               redis_host: str = '127.0.0.1', redis_port: int = 6379,
               idle_threshold: int = 30, poll_interval: int = 5):
    """Main daemon loop."""
    import redis as redis_lib

    r = redis_lib.Redis(
        host=redis_host, port=redis_port,
        decode_responses=True, socket_timeout=2,
    )

    # Verify Redis connection
    try:
        r.ping()
    except Exception as e:
        logger.error(f"Cannot connect to Redis at {redis_host}:{redis_port}: {e}")
        sys.exit(1)

    # Verify tmux session exists
    check = subprocess.run(
        ['tmux', 'has-session', '-t', tmux_session],
        capture_output=True, timeout=5,
    )
    if check.returncode != 0:
        logger.error(f"tmux session '{tmux_session}' not found")
        sys.exit(1)

    logger.info(f"Started: node={node_id}, session={tmux_session}, "
                f"idle_threshold={idle_threshold}s, poll={poll_interval}s")

    while True:
        try:
            # Check both queues
            inbox_count = peek_count(r, node_id)
            notif_count = peek_notifications_count(r, node_id)

            if (inbox_count + notif_count) == 0:
                time.sleep(poll_interval)
                continue

            # Messages exist — check if node is idle
            if not is_node_idle(r, node_id, idle_threshold):
                # Node is active — PostToolUse hook will deliver
                time.sleep(poll_interval)
                continue

            # Node is idle — drain and inject via tmux
            parts = []

            # Drain inbox messages
            inbox_msgs = receive(r, node_id, max_count=10)
            for msg in inbox_msgs:
                parts.append(format_inbox_message(msg))

            # Drain monitor notifications
            notif_msgs = receive_notifications(r, node_id, max_count=10)
            for notif in notif_msgs:
                parts.append(format_notification(notif))

            if not parts:
                time.sleep(poll_interval)
                continue

            text = " | ".join(parts)
            logger.info(f"Injecting {len(parts)} message(s) via tmux: {text[:200]}...")

            if not inject_via_tmux(tmux_session, text):
                logger.error(f"tmux injection failed — re-queuing {len(parts)} messages")
                if inbox_msgs:
                    requeue_messages(r, node_id, inbox_msgs, "inbox")
                if notif_msgs:
                    requeue_messages(r, node_id, notif_msgs, "notifications")

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("Daemon stopped (keyboard interrupt)")
            break
        except Exception as e:
            logger.error(f"Daemon error: {e}")
            time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(
        description="Notification tmux fallback daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --node weaver --tmux-session taeys-hands\n"
            "  %(prog)s --node jetson-claude --tmux-session jetson-claude\n"
            "  %(prog)s --node weaver --tmux-session taeys-hands --idle-threshold 60\n"
        ),
    )
    parser.add_argument('--node', required=True, help='Target node ID to watch')
    parser.add_argument('--tmux-session', required=True, help='tmux session for injection')
    parser.add_argument('--redis-host',
                        default=os.environ.get('REDIS_HOST', '127.0.0.1'))
    parser.add_argument('--redis-port', type=int,
                        default=int(os.environ.get('REDIS_PORT', '6379')))
    parser.add_argument('--idle-threshold', type=int, default=DEFAULT_IDLE_THRESHOLD,
                        help='Seconds of inactivity before tmux injection (default: 30)')
    parser.add_argument('--poll-interval', type=int, default=DEFAULT_POLL_INTERVAL,
                        help='Seconds between polling checks (default: 5)')
    args = parser.parse_args()

    run_daemon(args.node, args.tmux_session, args.redis_host, args.redis_port,
               args.idle_threshold, args.poll_interval)


if __name__ == '__main__':
    main()
