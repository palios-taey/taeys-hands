#!/bin/bash
# deploy.sh — Pull latest code and restart MCP servers on all machines.
#
# Kills MCP server processes, then sends /mcp to Claude Code tmux sessions
# to trigger reconnect. Without /mcp, tools stay dead (can't make a tool
# call to trigger auto-restart when the tool provider is down).
#
# Usage:
#   bash scripts/deploy.sh          # Deploy to all machines
#   bash scripts/deploy.sh spark2   # Deploy to one machine
#   bash scripts/deploy.sh --local  # Local only (no SSH)

set -euo pipefail

REPO_DIR="taeys-hands"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Machine registry: SSH host alias → home dir prefix
# Uses hostnames from ~/.ssh/config
declare -A MACHINES=(
    [spark1]="/home/spark"
    [spark2]="/home/spark"
    [spark3]="/home/spark"
    [spark4]="/home/spark"
    [thor]="/home/thor"
    [jetson]="/home/jetson"
    [mira]="/home/mira"
)

# Claude Code tmux sessions per machine — send /mcp after kill to reconnect.
# Without this, killing the MCP server leaves tools dead (Claude Code can't
# make a tool call to trigger auto-restart).
declare -A TMUX_SESSIONS=(
    [thor]="thor-claude"
    [jetson]="jetson-claude"
    [mira]="treasurer"
    [spark3]="claw"
)

deploy_local() {
    echo "[local] Cleaning __pycache__ (prevents stale .pyc shadowing)..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

    echo "[local] Ensuring main branch..."
    git fetch origin main 2>&1 | tail -1
    git reset --hard origin/main 2>&1 | tail -1

    echo "[local] Killing MCP server processes..."
    pkill -f 'python3.*server\.py' 2>/dev/null && echo "[local] MCP servers killed" \
        || echo "[local] No MCP servers running"

    echo "[local] Done — commit: $(git log --oneline -1)"
}

deploy_remote() {
    local host="$1"
    local home="${MACHINES[$host]}"
    local repo_path="${home}/${REPO_DIR}"

    echo "[${host}] Deploying..."
    ssh -o ConnectTimeout=5 "$host" "
        cd ${repo_path} 2>/dev/null || { echo 'REPO NOT FOUND: ${repo_path}'; exit 1; }
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        git fetch origin main 2>&1 | tail -1
        git reset --hard origin/main 2>&1 | tail -1
        pkill -f 'python3.*server\\.py' 2>/dev/null && echo 'MCP servers killed' || echo 'No MCP servers running'
        echo \"Done — commit: \$(git log --oneline -1)\"
    " 2>&1 | sed "s/^/  /" || echo "  [${host}] SSH FAILED"

    # Send /mcp to Claude Code tmux session to trigger MCP reconnect
    local session="${TMUX_SESSIONS[$host]:-}"
    if [ -n "$session" ]; then
        echo "  [${host}] Sending /mcp to session '$session'..."
        tmux-send "$host" "$session" "/mcp" 2>&1 | sed "s/^/  /" || echo "  [${host}] tmux-send failed"
    fi
}

# Parse args
TARGET="${1:-all}"

if [ "$TARGET" = "--local" ]; then
    deploy_local
    exit 0
fi

if [ "$TARGET" != "all" ]; then
    # Deploy to single machine
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

# Remote machines in parallel
pids=()
for host in "${!MACHINES[@]}"; do
    [ "$host" = "spark1" ] && continue  # Already did local
    deploy_remote "$host" &
    pids+=($!)
done

# Wait for all remotes
for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
done

echo ""
echo "=== Deploy complete ==="
