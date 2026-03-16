#!/bin/bash
# deploy.sh — Pull latest code, reconnect MCP servers on all machines.
#
# Two phases:
#   1. DEPLOY: Pull code, install scripts, restart daemons (all machines)
#   2. RECONNECT: After ALL deploys finish, reconnect MCP in Claude sessions
#
# The reconnect phase runs as a detached process with a delay so the
# calling Claude session's Bash tool returns cleanly before Escape hits.
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

    echo "[local] Killing monitor + notification daemon..."
    pkill -f 'monitor.central' 2>/dev/null || true
    pkill -f 'notifications/daemon' 2>/dev/null || true
    sleep 1
    local daemon_path="/home/spark/orchestrator/notifications/daemon.py"
    nohup python3 "$daemon_path" \
        --redis-host "${REDIS_HOST:-192.168.100.10}" \
        > "/tmp/notify-daemon.log" 2>&1 &
    echo "[local] Notify daemon started (PID $!)"

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
        cd "$REPO" 2>/dev/null || { echo "REPO NOT FOUND: $REPO"; exit 1; }
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        git fetch origin main 2>&1 | tail -1
        git reset --hard origin/main 2>&1 | tail -1
        sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify 2>/dev/null || true
        pkill -f 'notifications/daemon' 2>/dev/null || true
        sleep 1
        DAEMON="${HOME_DIR}/orchestrator/notifications/daemon.py"
        if [ ! -f "$DAEMON" ]; then
            echo "WARNING: daemon not found at $DAEMON — skipping"
        else
            nohup python3 "$DAEMON" --redis-host "$REDIS" \
                > "/tmp/notify-daemon.log" 2>&1 &
            echo "Notify daemon started (PID $!)"
        fi
        echo "Done — commit: $(git log --oneline -1)"
DEPLOY_EOF
    local rc=$?
    [ $rc -ne 0 ] && echo "  [${host}] SSH FAILED (exit $rc)" || true
}

# Parse args
TARGET="${1:-all}"

if [ "$TARGET" = "--local" ]; then
    deploy_local
    echo ""
    echo "=== Deploy complete — MCP reconnect in 10 seconds ==="
    pkill -f 'deploy-reconnect.sh' 2>/dev/null || true
    # Reuse the same reconnect script (local only for --local)
    cat > /tmp/deploy-reconnect.sh <<'LEOF'
#!/bin/bash
sleep 10
for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null); do
    cmd=$(tmux display-message -t "$s" -p '#{pane_current_command}' 2>/dev/null || echo "")
    if [ "$cmd" = "claude" ]; then
        echo "[$s] reconnecting..."
        tmux send-keys -t "$s" Escape; sleep 5
        tmux send-keys -t "$s" -l "/mcp"; sleep 0.3; tmux send-keys -t "$s" Enter; sleep 2
        # Enter selects server, Enter selects first option (Reconnect or Enable).
        # NO Down — Reconnect is first option, Down would select Disable.
        tmux send-keys -t "$s" Enter; sleep 0.5; tmux send-keys -t "$s" Enter; sleep 5
        tmux send-keys -t "$s" -l "MCP servers reconnected with latest deployed code. Continue."
        sleep 0.3; tmux send-keys -t "$s" Enter
        echo "[$s] done"
    fi
done &
wait
LEOF
    chmod +x /tmp/deploy-reconnect.sh
    nohup /tmp/deploy-reconnect.sh > /tmp/mcp-reconnect.log 2>&1 &
    disown
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
echo "=== Phase 1: Deploy to all machines ==="
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
echo "=== Phase 2: MCP reconnect (all machines, in 10 seconds) ==="
# Kill any previous reconnect processes before spawning new one
pkill -f 'deploy-reconnect.sh' 2>/dev/null || true

# Write reconnect script to file, run detached.
# Survives after deploy.sh exits. 10s delay lets Bash tool return first.
cat > /tmp/deploy-reconnect.sh <<'REOF'
#!/bin/bash
sleep 10

# Reconnect function — sends key sequence to one tmux session
reconnect() {
    local session="$1"
    echo "[$session] Escape..."
    tmux send-keys -t "$session" Escape
    sleep 5
    echo "[$session] /mcp + Enter..."
    tmux send-keys -t "$session" -l "/mcp"
    sleep 0.3
    tmux send-keys -t "$session" Enter
    sleep 2
    echo "[$session] Enter → Enter (first option)..."
    tmux send-keys -t "$session" Enter
    sleep 0.5
    tmux send-keys -t "$session" Enter
    sleep 5
    echo "[$session] Continue prompt..."
    tmux send-keys -t "$session" -l "MCP servers reconnected with latest deployed code. Continue."
    sleep 0.3
    tmux send-keys -t "$session" Enter
    echo "[$session] done"
}

# Find all local Claude sessions
SESSIONS=()
for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null); do
    cmd=$(tmux display-message -t "$s" -p '#{pane_current_command}' 2>/dev/null || echo "")
    [ "$cmd" = "claude" ] && SESSIONS+=("$s")
done

echo "Local Claude sessions: ${SESSIONS[*]:-none}"

# Reconnect all local sessions sequentially
for s in "${SESSIONS[@]}"; do
    reconnect "$s"
done

# Remote machines — find and reconnect Claude sessions via SSH
for host in spark3 mira; do
    ssh -o ConnectTimeout=5 "$host" bash -s <<'REMOTE_EOF'
for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null); do
    cmd=$(tmux display-message -t "$s" -p '#{pane_current_command}' 2>/dev/null || echo "")
    if [ "$cmd" = "claude" ]; then
        echo "[$s@$(hostname)] reconnecting..."
        tmux send-keys -t "$s" Escape; sleep 5
        tmux send-keys -t "$s" -l "/mcp"; sleep 0.3
        tmux send-keys -t "$s" Enter; sleep 2
        tmux send-keys -t "$s" Enter; sleep 0.5
        tmux send-keys -t "$s" Enter; sleep 5
        tmux send-keys -t "$s" -l "MCP servers reconnected with latest deployed code. Continue."
        sleep 0.3; tmux send-keys -t "$s" Enter
        echo "[$s@$(hostname)] done"
    fi
done
REMOTE_EOF
done

wait
echo "All machines reconnected"
REOF
chmod +x /tmp/deploy-reconnect.sh
nohup /tmp/deploy-reconnect.sh > /tmp/mcp-reconnect.log 2>&1 &
disown
echo "Detached reconnect PID $! — will fire in 10s"
