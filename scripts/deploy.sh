#!/bin/bash
# deploy.sh — Pull latest code and restart MCP servers on all machines.
#
# Kills MCP server processes on each machine. Claude Code's stdio transport
# auto-relaunches the server command from .mcp.json on the next tool call.
# This IS the hot-reload mechanism — no /mcp or manual reconnect needed.
#
# For file-watch auto-reload during development, see mcp-watch.sh.
#
# Usage:
#   bash scripts/deploy.sh          # Deploy to all machines
#   bash scripts/deploy.sh spark2   # Deploy to one machine
#   bash scripts/deploy.sh --local  # Local only (no SSH)

set -euo pipefail

REPO_DIR="taeys-hands"

# Machine registry: SSH host alias → home dir prefix
declare -A MACHINES=(
    [spark1]="/home/spark"
    [spark2]="/home/spark"
    [spark3]="/home/spark"
    [spark4]="/home/spark"
    [thor]="/home/thor"
    [jetson]="/home/jetson"
    [mira]="/home/mira"
)

deploy_local() {
    echo "[local] Cleaning __pycache__ (prevents stale .pyc shadowing)..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

    echo "[local] Pulling latest main..."
    git fetch origin main 2>&1 | tail -1
    git reset --hard origin/main 2>&1 | tail -1

    echo "[local] Installing taey-notify..."
    sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify 2>/dev/null || true

    echo "[local] Killing MCP server processes..."
    pkill -f 'python3.*server\.py' 2>/dev/null && echo "[local] MCP servers killed (auto-relaunch on next tool call)" \
        || echo "[local] No MCP servers running"

    echo "[local] Restarting notification daemons..."
    pkill -f 'notifications/daemon' 2>/dev/null || true
    sleep 1
    # Start daemons for all local tmux sessions
    for session in $(tmux ls -F '#{session_name}' 2>/dev/null); do
        nohup python3 notifications/daemon.py \
            --node "$session" --tmux-session "$session" \
            --redis-host "${REDIS_HOST:-192.168.100.10}" \
            > "/tmp/notify-daemon-${session}.log" 2>&1 &
        echo "[local] Notify daemon started for $session (PID $!)"
    done

    echo "[local] Done — commit: $(git log --oneline -1)"
}

deploy_remote() {
    local host="$1"
    local home="${MACHINES[$host]}"
    local repo_path="${home}/${REPO_DIR}"
    # Mira can't reach NCCL network — use management IP for Redis
    local redis_host="192.168.100.10"
    [ "$host" = "mira" ] && redis_host="10.0.0.68"

    echo "[${host}] Deploying..."
    ssh -o ConnectTimeout=5 "$host" bash -s -- "${repo_path}" "${redis_host}" <<'DEPLOY_EOF'
        REPO="$1"; REDIS="$2"
        cd "$REPO" 2>/dev/null || { echo "REPO NOT FOUND: $REPO"; exit 1; }
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        git fetch origin main 2>&1 | tail -1
        git reset --hard origin/main 2>&1 | tail -1
        sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify 2>/dev/null || true
        pkill -f 'python3.*server\.py' 2>/dev/null && echo 'MCP killed (auto-relaunch on next tool call)' || echo 'No MCP running'
        pkill -f 'notifications/daemon' 2>/dev/null || true
        sleep 1
        for session in $(tmux ls -F '#{session_name}' 2>/dev/null || true); do
            nohup python3 notifications/daemon.py \
                --node "$session" --tmux-session "$session" \
                --redis-host "$REDIS" \
                > "/tmp/notify-daemon-${session}.log" 2>&1 &
            echo "Notify daemon started for $session (PID $!)"
        done
        echo "Done — commit: $(git log --oneline -1)"
DEPLOY_EOF
    local rc=$?
    [ $rc -ne 0 ] && echo "  [${host}] SSH FAILED (exit $rc)" || true
}

# Parse args
TARGET="${1:-all}"

if [ "$TARGET" = "--local" ]; then
    deploy_local
    exit 0
fi

if [ "$TARGET" != "all" ]; then
    if [[ -v "MACHINES[$TARGET]" ]]; then
        deploy_remote "$TARGET"
    else
        echo "Unknown machine: $TARGET"
        echo "Available: ${!MACHINES[*]} --local"
        exit 1
    fi
    exit 0
fi

# Deploy to all machines: local first, then remote in parallel
echo "=== Deploying to all machines ==="
echo ""

deploy_local
echo ""

pids=()
for host in "${!MACHINES[@]}"; do
    [ "$host" = "spark1" ] && continue
    deploy_remote "$host" &
    pids+=($!)
done

for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
done

echo ""
echo "=== Deploy complete ==="
