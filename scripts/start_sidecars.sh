#!/usr/bin/env bash
# Start sidecar daemons for all local tmux-based agents.
# Each sidecar listens on orch:inbox:{agent_id} and injects tasks into tmux.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SIDECAR="$REPO_DIR/orchestration/sidecar.py"

export ORCH_REDIS_HOST="${ORCH_REDIS_HOST:-192.168.x.10}"
export ORCH_REDIS_PORT="${ORCH_REDIS_PORT:-6379}"

# Agent ID -> tmux session mapping (local agents only)
declare -A AGENTS=(
    ["claude-taeys-hands"]="taeys-hands"
    ["claude-weaver"]="weaver"
    ["conductor-gemini"]="conductor-gemini"
    ["conductor-codex"]="conductor-codex"
    ["weaver-gemini"]="weaver-gemini"
    ["weaver-codex"]="weaver-codex"
)

start_sidecar() {
    local agent_id="$1"
    local session="$2"
    local pidfile="/tmp/sidecar_${agent_id}.pid"

    # Check if already running
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "[sidecars] $agent_id already running (pid $(cat "$pidfile"))"
        return 0
    fi

    # Check if tmux session exists
    if ! tmux has-session -t "$session" 2>/dev/null; then
        echo "[sidecars] SKIP $agent_id - no tmux session '$session'"
        return 0
    fi

    python3 "$SIDECAR" --agent-id "$agent_id" --session "$session" &
    local pid=$!
    echo "$pid" > "$pidfile"
    echo "[sidecars] Started $agent_id -> $session (pid $pid)"
}

stop_all() {
    echo "[sidecars] Stopping all..."
    for agent_id in "${!AGENTS[@]}"; do
        local pidfile="/tmp/sidecar_${agent_id}.pid"
        if [[ -f "$pidfile" ]]; then
            local pid
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                echo "[sidecars] Stopped $agent_id (pid $pid)"
            fi
            rm -f "$pidfile"
        fi
    done
}

status() {
    for agent_id in "${!AGENTS[@]}"; do
        local pidfile="/tmp/sidecar_${agent_id}.pid"
        if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
            echo "[OK]   $agent_id (pid $(cat "$pidfile"))"
        else
            echo "[DOWN] $agent_id"
        fi
    done
}

case "${1:-start}" in
    start)
        echo "[sidecars] Starting sidecar daemons..."
        for agent_id in "${!AGENTS[@]}"; do
            start_sidecar "$agent_id" "${AGENTS[$agent_id]}"
        done
        echo "[sidecars] Done. $(ls /tmp/sidecar_*.pid 2>/dev/null | wc -l) sidecars active."
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 1
        for agent_id in "${!AGENTS[@]}"; do
            start_sidecar "$agent_id" "${AGENTS[$agent_id]}"
        done
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
