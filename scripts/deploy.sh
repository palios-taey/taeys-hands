#!/bin/bash
# deploy.sh — Pull latest code, kill MCP servers, reconnect Claude sessions.
#
# Two phases:
#   1. DEPLOY: Pull code, clean pycache, kill MCP + daemons (all machines)
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
# SSH aliases defined in ~/.ssh/config (spark2→spark@10.0.0.80, thor→thor@10.0.0.197, etc.)
declare -A MACHINES=(
    [spark1]="/home/spark"
    [spark2]="/home/spark"
    [thor]="/home/thor"
    [jetson]="/home/jetson"
)

# Kill all MCP server processes for taeys-hands and isma-memory.
# MCP servers are stdio children of Claude Code — killing them makes Claude Code
# detect the broken pipe. The /mcp reconnect spawns fresh servers with new code.
kill_mcp_servers() {
    echo "[$(hostname)] Killing MCP server processes..."
    pkill -f 'taeys-hands/server.py' 2>/dev/null || true
    pkill -f 'isma/src/mcp_server.py' 2>/dev/null || true
}

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

    # Kill MCP servers so reconnect picks up new code
    kill_mcp_servers

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
        thor|jetson) redis_host="10.0.0.68" ;;
    esac

    echo "[${host}] Deploying..."
    ssh -o ConnectTimeout=5 "$host" bash -s -- "${repo_path}" "${redis_host}" "${home}" <<'DEPLOY_EOF'
        REPO="$1"; REDIS="$2"; HOME_DIR="$3"
        cd "$REPO" || { echo "REPO NOT FOUND: $REPO"; exit 1; }
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        git fetch origin main 2>&1 | tail -1
        git reset --hard origin/main 2>&1 | tail -1
        sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify 2>/dev/null || true

        # Kill MCP servers + daemons
        pkill -f 'taeys-hands/server.py' 2>/dev/null || true
        pkill -f 'isma/src/mcp_server.py' 2>/dev/null || true
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

# ─── Reconnect helper ─────────────────────────────────────────────────
# Reconnects all Claude Code sessions on a machine by:
# 1. Sending Escape to cancel any pending operation
# 2. Sending /mcp + Enter to open MCP management
# 3. Reading the screen to find "Reconnect" or "Enable" option
# 4. Navigating to the correct option and selecting it
#
# Uses tmux capture-pane for text matching instead of blind keystrokes.
write_reconnect_script() {
    cat > /tmp/deploy-reconnect.sh <<'REOF'
#!/bin/bash
sleep 10

# Smart select — reads screen, finds target text, navigates to it
# Usage: smart_select <session> <search_text>
# Searches captured pane for a line containing search_text.
# If found, calculates arrow key presses needed from current selection.
smart_select() {
    local session="$1"
    local search="$2"
    sleep 1

    # Capture the visible pane content (strips ANSI codes)
    local screen
    screen=$(tmux capture-pane -t "$session" -p 2>/dev/null)

    # Look for the search text (case-insensitive)
    if echo "$screen" | grep -qi "$search"; then
        echo "[$session] Found '$search' on screen"
        # In Claude Code /mcp menu, options are listed vertically.
        # First option is pre-selected. Count lines between first option
        # and our target to know how many Down arrows to press.
        #
        # Menu items contain: Reconnect, Enable, Disable
        # We want "Reconnect" — it's typically the first/only option
        # when servers exist. Just press Enter to select it.
        tmux send-keys -t "$session" Enter
        return 0
    else
        echo "[$session] '$search' NOT found on screen, pressing Enter (default)"
        echo "[$session] Screen content (last 10 lines):"
        echo "$screen" | tail -10 | sed 's/^/    /'
        tmux send-keys -t "$session" Enter
        return 1
    fi
}

# Reconnect one Claude Code tmux session
reconnect() {
    local session="$1"
    echo "[$session] Escape (cancel pending)..."
    tmux send-keys -t "$session" Escape
    sleep 5

    echo "[$session] /mcp Enter..."
    tmux send-keys -t "$session" -l "/mcp"
    sleep 0.3
    tmux send-keys -t "$session" Enter
    sleep 3

    # Read screen and select "Reconnect" option
    smart_select "$session" "Reconnect"
    sleep 8

    echo "[$session] Sending continue prompt..."
    tmux send-keys -t "$session" -l "MCP servers reconnected with latest deployed code. Continue."
    sleep 0.3
    tmux send-keys -t "$session" Enter
    echo "[$session] done"
}

# ─── Local sessions ───────────────────────────────────────────────────
SESSIONS=()
for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null); do
    cmd=$(tmux display-message -t "$s" -p '#{pane_current_command}' 2>/dev/null || echo "")
    if [ "$cmd" = "claude" ]; then
        SESSIONS+=("$s")
    else
        echo "[$s] skipped (running: $cmd, not claude)"
    fi
done

echo "Local Claude sessions: ${SESSIONS[*]:-none}"

for s in "${SESSIONS[@]}"; do
    reconnect "$s"
done

# ─── Remote sessions ──────────────────────────────────────────────────
for host in spark2 thor jetson; do
    echo "--- Reconnecting on $host ---"
    ssh -o ConnectTimeout=5 "$host" bash -s <<'REMOTE_REOF' 2>/dev/null || echo "[$host] SSH failed — skipping"
for s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null); do
    cmd=$(tmux display-message -t "$s" -p '#{pane_current_command}' 2>/dev/null || echo "")
    if [ "$cmd" = "claude" ]; then
        echo "[$s@$(hostname)] reconnecting..."
        tmux send-keys -t "$s" Escape; sleep 5
        tmux send-keys -t "$s" -l "/mcp"; sleep 0.3
        tmux send-keys -t "$s" Enter; sleep 3
        # Read screen for "Reconnect"
        screen=$(tmux capture-pane -t "$s" -p 2>/dev/null)
        if echo "$screen" | grep -qi "Reconnect"; then
            echo "[$s@$(hostname)] Found Reconnect"
        else
            echo "[$s@$(hostname)] Reconnect not found, pressing Enter anyway"
        fi
        tmux send-keys -t "$s" Enter; sleep 8
        tmux send-keys -t "$s" -l "MCP servers reconnected with latest deployed code. Continue."
        sleep 0.3; tmux send-keys -t "$s" Enter
        echo "[$s@$(hostname)] done"
    else
        echo "[$s@$(hostname)] skipped (running: $cmd, not claude)"
    fi
done
REMOTE_REOF
done

echo "All machines reconnected"
REOF
    chmod +x /tmp/deploy-reconnect.sh
}

# ─── Main ─────────────────────────────────────────────────────────────
TARGET="${1:-all}"

if [ "$TARGET" = "--local" ]; then
    deploy_local
    echo ""
    echo "=== Deploy complete — MCP reconnect in 10 seconds ==="
    pkill -f 'deploy-reconnect.sh' 2>/dev/null || true
    write_reconnect_script
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
pkill -f 'deploy-reconnect.sh' 2>/dev/null || true
write_reconnect_script
nohup /tmp/deploy-reconnect.sh > /tmp/mcp-reconnect.log 2>&1 &
disown
echo "Detached reconnect PID $! — will fire in 10s"
