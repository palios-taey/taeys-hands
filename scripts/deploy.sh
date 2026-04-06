#!/bin/bash
# deploy.sh — Pull latest code, restart daemons, reconnect MCP via mcp-reconnect.
#
# Usage:
#   bash scripts/deploy.sh          # Deploy to all machines
#   bash scripts/deploy.sh spark2   # Deploy to one machine
#   bash scripts/deploy.sh --local  # Local only (no SSH)

set -euo pipefail

REPO_DIR="taeys-hands"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -f "$REPO_ROOT/.env" ]; then
    source "$REPO_ROOT/.env"
fi

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
    echo "[local] Cleaning __pycache__..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

    echo "[local] Pulling latest main..."
    git fetch origin main 2>&1 | tail -1
    git reset --hard origin/main 2>&1 | tail -1

    echo "[local] Installing taey-notify..."
    sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify 2>/dev/null || true

    echo "[local] Killing monitor + notification daemon..."
    pkill -f 'monitor.central' 2>/dev/null || true
    pkill -f 'notifications/daemon' 2>/dev/null || true
    sleep 1

    local daemon_path="/home/spark/orchestrator/notifications/daemon.py"
    if [ -f "$daemon_path" ]; then
        nohup python3 "$daemon_path" \
            --redis-host "${REDIS_HOST:-192.168.100.10}" \
            > "/tmp/notify-daemon.log" 2>&1 &
        echo "[local] Notify daemon started (PID $!)"
    fi

    echo "[local] Restarting central monitor..."
    nohup python3 -m monitor.central --cycle-interval 10 \
        > "/tmp/central_monitor.log" 2>&1 &
    echo "[local] Central monitor started (PID $!)"

    echo "[local] Done — commit: $(git log --oneline -1)"
}

deploy_remote() {
    local host="$1"
    local home="${MACHINES[$host]}"
    local repo_path="${home}/${REPO_DIR}"
    local redis_host="192.168.100.10"
    case "$host" in
        mira|thor|jetson) redis_host="10.0.0.68" ;;
    esac

    echo "[${host}] Deploying..."
    ssh -o ConnectTimeout=5 "$host" bash -s -- "${repo_path}" "${redis_host}" "${home}" <<'DEPLOY_EOF'
        REPO="$1"; REDIS="$2"; HOME_DIR="$3"
        cd "$REPO" || { echo "REPO NOT FOUND: $REPO"; exit 1; }
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        git fetch origin main 2>&1 | tail -1
        git reset --hard origin/main 2>&1 | tail -1
        sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify 2>/dev/null || true
        pkill -f 'notifications/daemon' 2>/dev/null || true
        sleep 1
        DAEMON="${HOME_DIR}/orchestrator/notifications/daemon.py"
        if [ -f "$DAEMON" ]; then
            nohup python3 "$DAEMON" --redis-host "$REDIS" \
                > "/tmp/notify-daemon.log" 2>&1 &
            echo "Notify daemon started (PID $!)"
        fi
        echo "Done — commit: $(git log --oneline -1)"
DEPLOY_EOF
    local rc=$?
    [ $rc -ne 0 ] && echo "  [${host}] SSH FAILED (exit $rc)" || true
}

# ─── Main ─────────────────────────────────────────────────────────────
TARGET="${1:-all}"

if [ "$TARGET" = "--local" ]; then
    deploy_local
    echo ""
    echo "=== Deploy complete ==="
    # MCP reconnect via mcp-reconnect (if installed)
    if command -v mcp-reconnect &>/dev/null; then
        CALLER=$(tmux display-message -p '#S' 2>/dev/null || echo "")
        echo "MCP reconnect in 10s (excluding caller '$CALLER')..."
        nohup mcp-reconnect --server taeys-hands --exclude "$CALLER" --delay 10 \
            > /tmp/mcp-reconnect.log 2>&1 &
        disown
    else
        echo "mcp-reconnect not installed — run /mcp manually in each session"
    fi
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
echo "=== Phase 1: Deploy ==="
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
echo "=== Phase 2: MCP reconnect ==="
if command -v mcp-reconnect &>/dev/null; then
    CALLER=$(tmux display-message -p '#S' 2>/dev/null || echo "")
    echo "MCP reconnect in 10s (excluding caller '$CALLER')..."
    nohup mcp-reconnect --server taeys-hands --exclude "$CALLER" --delay 10 \
        > /tmp/mcp-reconnect.log 2>&1 &
    disown
    echo "PID $! — run /mcp manually in caller session"
else
    echo "mcp-reconnect not installed — run /mcp manually"
fi
