#!/bin/bash
# deploy.sh — Pull latest code and restart MCP servers on all machines.
#
# For stdio MCP servers, killing the process forces Claude Code to
# relaunch it on the next tool call. This IS the hot-reload mechanism.
#
# Usage:
#   bash scripts/deploy.sh          # Deploy to all machines
#   bash scripts/deploy.sh spark2   # Deploy to one machine
#   bash scripts/deploy.sh --local  # Local only (no SSH)

set -euo pipefail

REPO_DIR="taeys-hands"

# Machine registry: SSH host alias → home dir prefix
# Uses hostnames from ~/.ssh/config
declare -A MACHINES=(
    [spark1]="/home/spark"
    [spark2]="/home/spark"
    [spark4]="/home/spark"
    [thor]="/home/thor"
    [jetson]="/home/jetson"
    [mira]="/home/mira"
)

deploy_local() {
    echo "[local] Cleaning __pycache__ (prevents stale .pyc shadowing)..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

    echo "[local] Ensuring main branch..."
    git checkout main 2>&1 | tail -1
    git pull origin main 2>&1 | tail -3

    echo "[local] Killing MCP server processes..."
    # Match the MCP server pattern but not this script or editors
    pkill -f 'python3.*server\.py' 2>/dev/null && echo "[local] MCP servers killed (will auto-restart)" \
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
        git checkout main 2>&1 | tail -1
        git pull origin main 2>&1 | tail -3
        pkill -f 'python3.*server\\.py' 2>/dev/null && echo 'MCP servers killed' || echo 'No MCP servers running'
        echo \"Done — commit: \$(git log --oneline -1)\"
    " 2>&1 | sed "s/^/  /" || echo "  [${host}] SSH FAILED"
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
