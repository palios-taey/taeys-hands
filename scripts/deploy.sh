#!/bin/bash
# deploy.sh — Pull latest code, kill MCP servers, reconnect Claude sessions.
#
# Two phases:
#   1. DEPLOY: Pull code, clean pycache, kill MCP + daemons (all machines)
#   2. RECONNECT: After ALL deploys finish, reconnect MCP in Claude sessions
#
# MCP servers are stdio children of Claude Code. Killing them breaks the pipe.
# The /mcp reconnect spawns fresh servers with the new code.
#
# Reconnect uses tmux capture-pane to read screen text and find the correct
# menu option (Reconnect/Enable) — no blind keystroke sequences.
#
# Usage:
#   bash scripts/deploy.sh          # Deploy to all machines
#   bash scripts/deploy.sh spark2   # Deploy to one machine
#   bash scripts/deploy.sh --local  # Local only (no SSH)

set -euo pipefail

REPO_DIR="taeys-hands"

# Machine registry: SSH host alias → home dir prefix
# SSH aliases defined in ~/.ssh/config
declare -A MACHINES=(
    [spark1]="/home/spark"
    [spark2]="/home/spark"
    [thor]="/home/thor"
    [jetson]="/home/jetson"
)

deploy_local() {
    echo "[local] Cleaning __pycache__ (prevents stale .pyc shadowing)..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

    echo "[local] Pulling latest main..."
    git fetch origin main 2>&1 | tail -1
    git reset --hard origin/main 2>&1 | tail -1

    echo "[local] Installing taey-notify..."
    sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify 2>/dev/null || true

    echo "[local] Killing MCP servers + monitor + notification daemon..."
    pkill -f 'taeys-hands/server.py' 2>/dev/null || true
    pkill -f 'isma/src/mcp_server.py' 2>/dev/null || true
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
# Smart MCP reconnect: reads screen text to find menu options.
#
# /mcp menu has two levels:
#   Level 1: Server list + "Reconnect all" (if multiple servers)
#   Level 2 (per-server): View tools, Reconnect, Enable, Disable
#
# Strategy:
#   1. Open /mcp, capture screen
#   2. If "Reconnect" found at level 1 → select it (handles single + multi server)
#   3. If server name found but no Reconnect → select server, then find
#      Reconnect/Enable in submenu
#
# Uses tmux capture-pane -p which strips ANSI codes for clean text matching.

write_reconnect_script() {
    cat > /tmp/deploy-reconnect.sh <<'REOF'
#!/bin/bash
sleep 10

# Wait for /mcp menu to render by checking for navigation hint.
# Returns 0 if menu detected, 1 if timeout.
wait_for_menu() {
    local session="$1"
    for attempt in 1 2 3 4 5; do
        local screen
        screen=$(tmux capture-pane -t "$session" -p 2>/dev/null)
        if echo "$screen" | grep -q "to navigate"; then
            echo "[$session] Menu detected (attempt $attempt)"
            return 0
        fi
        sleep 1
    done
    echo "[$session] WARNING: menu not detected after 5s"
    return 1
}

# Find a server entry in the /mcp server list.
# Server entries have format: "name · status" (with middle dot ·)
# Returns position (0-indexed) among server entries, or -1.
find_server_position() {
    local session="$1"
    local target="$2"

    local screen
    screen=$(tmux capture-pane -t "$session" -p 2>/dev/null)

    local pos=0 target_pos=-1
    while IFS= read -r line; do
        # Server entries contain " · " (middle dot with spaces)
        if echo "$line" | grep -q ' · '; then
            # Strip whitespace and leading cursor markers
            local name
            name=$(echo "$line" | sed 's/^[[:space:]❯]*//' | sed 's/ ·.*//')
            if echo "$name" | grep -qi "$target"; then
                target_pos=$pos
                echo "[$session] Found server '$name' at position $pos"
                break
            fi
            pos=$((pos + 1))
        fi
    done <<< "$screen"

    echo "$target_pos"
}

# Select numbered option in submenu (inside box-drawn border).
# Submenu items look like: "│ ❯ 1. Reconnect │" or "│   2. Disable │"
select_submenu_option() {
    local session="$1"
    local target="$2"

    local screen
    screen=$(tmux capture-pane -t "$session" -p 2>/dev/null)

    local pos=0 target_pos=-1
    while IFS= read -r line; do
        # Strip box-drawing chars and whitespace
        local clean
        clean=$(echo "$line" | sed 's/[│╭╮╰╯─]//g' | sed 's/^[[:space:]❯]*//' | sed 's/[[:space:]]*$//')
        [ -z "$clean" ] && continue
        # Match numbered menu items: "1. Reconnect", "2. Disable", etc.
        if echo "$clean" | grep -qE '^[0-9]+\.'; then
            if echo "$clean" | grep -qi "$target"; then
                target_pos=$pos
                echo "[$session] Found submenu '$clean' at position $pos"
                break
            fi
            pos=$((pos + 1))
        fi
    done <<< "$screen"

    if [ $target_pos -ge 0 ]; then
        for ((i=0; i<target_pos; i++)); do
            tmux send-keys -t "$session" Down; sleep 0.3
        done
        tmux send-keys -t "$session" Enter
        return 0
    fi
    # Fallback: just press Enter (first option is usually Reconnect)
    echo "[$session] Submenu '$target' not found, pressing Enter"
    tmux send-keys -t "$session" Enter
    return 1
}

# Reconnect one Claude Code session
reconnect() {
    local session="$1"
    echo "[$session] Escape (cancel pending)..."
    tmux send-keys -t "$session" Escape
    sleep 5

    echo "[$session] /mcp Enter..."
    tmux send-keys -t "$session" -l "/mcp"
    sleep 0.3
    tmux send-keys -t "$session" Enter

    # Wait for menu to actually render
    if ! wait_for_menu "$session"; then
        echo "[$session] FAILED — /mcp menu didn't appear. Skipping."
        tmux send-keys -t "$session" Escape
        return 1
    fi

    # Find taeys-hands in server list
    local pos
    pos=$(find_server_position "$session" "taeys-hands")

    if [ "$pos" -ge 0 ]; then
        echo "[$session] Navigating to taeys-hands (position $pos)..."
        for ((i=0; i<pos; i++)); do
            tmux send-keys -t "$session" Down; sleep 0.3
        done
        tmux send-keys -t "$session" Enter
        sleep 2

        # Now in submenu — select Reconnect
        select_submenu_option "$session" "Reconnect"
        sleep 8
    else
        echo "[$session] taeys-hands not found in server list"
        tmux send-keys -t "$session" Escape
        sleep 1
    fi

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
        tmux send-keys -t "$s" Enter

        # Wait for menu (look for navigation hint)
        menu_ok=0
        for attempt in 1 2 3 4 5; do
            screen=$(tmux capture-pane -t "$s" -p 2>/dev/null)
            if echo "$screen" | grep -q "to navigate"; then
                menu_ok=1; break
            fi
            sleep 1
        done

        if [ $menu_ok -eq 1 ]; then
            # Find taeys-hands among server entries (lines with " · ")
            pos=0; target_pos=-1
            while IFS= read -r line; do
                if echo "$line" | grep -q ' · '; then
                    name=$(echo "$line" | sed 's/^[[:space:]❯]*//' | sed 's/ ·.*//')
                    if echo "$name" | grep -qi "taeys-hands"; then
                        target_pos=$pos
                        echo "[$s@$(hostname)] Found taeys-hands at position $pos"
                        break
                    fi
                    pos=$((pos + 1))
                fi
            done <<< "$screen"

            if [ $target_pos -ge 0 ]; then
                for ((i=0; i<target_pos; i++)); do
                    tmux send-keys -t "$s" Down; sleep 0.3
                done
                tmux send-keys -t "$s" Enter; sleep 2
                # Select Reconnect (first option in submenu)
                tmux send-keys -t "$s" Enter; sleep 8
            else
                echo "[$s@$(hostname)] taeys-hands not found"
                tmux send-keys -t "$s" Escape; sleep 1
            fi
        else
            echo "[$s@$(hostname)] menu didn't appear"
            tmux send-keys -t "$s" Escape; sleep 1
        fi

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
