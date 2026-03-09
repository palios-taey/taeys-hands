#!/bin/bash
# Watch PALIOS tmux session and notify claw session when it stops.
# Usage: bash scripts/watch-palios.sh [check_interval_seconds]
#
# Checks if openclaw-tui process is alive. Sends notification when it dies.
# Simple process-based check avoids false positives from stale tmux buffer.

INTERVAL="${1:-30}"
NOTIFY_SESSION="claw"
WAS_RUNNING=false

while true; do
    if pgrep -f "openclaw-tui" > /dev/null 2>&1; then
        WAS_RUNNING=true
    else
        if $WAS_RUNNING; then
            # Was running, now it's not — it crashed/aborted
            tmux-send "$NOTIFY_SESSION" "PALIOS DOWN: openclaw-tui process died. Check claw:1 and restart."
            WAS_RUNNING=false
            # Wait longer to avoid spam
            sleep 120
        fi
    fi

    sleep "$INTERVAL"
done
