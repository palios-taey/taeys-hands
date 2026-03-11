#!/bin/bash
# mcp-watch.sh — watches MCP source files, kills stale server on changes.
# Claude Code stdio transport auto-relaunches the server on next tool call.
#
# Usage:
#   bash scripts/mcp-watch.sh              # Run in foreground
#   bash scripts/mcp-watch.sh &            # Run in background
#   nohup bash scripts/mcp-watch.sh &      # Persist across logout
#
# Requires: inotifywait (inotify-tools package)

set -euo pipefail

MCP_SRC_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DEBOUNCE=3
LAST_TRIGGER=0

# Ensure inotifywait is available
if ! command -v inotifywait &>/dev/null; then
    echo "ERROR: inotifywait not found. Install: sudo apt install inotify-tools"
    exit 1
fi

echo "Watching MCP source: $MCP_SRC_DIR"
echo "Debounce: ${DEBOUNCE}s"
echo "Watched dirs: core/ tools/ storage/ monitor/ server.py"

inotifywait -m -r -e close_write,moved_to \
    --exclude '\.git|__pycache__|\.pyc|\.log|/tmp/' \
    "$MCP_SRC_DIR/core" \
    "$MCP_SRC_DIR/tools" \
    "$MCP_SRC_DIR/storage" \
    "$MCP_SRC_DIR/monitor" \
    "$MCP_SRC_DIR/server.py" \
    2>/dev/null | while read -r dir events file; do

    now=$(date +%s)
    elapsed=$((now - LAST_TRIGGER))
    [ "$elapsed" -lt "$DEBOUNCE" ] && continue
    LAST_TRIGGER=$now

    echo "$(date): Source changed: ${file} — killing MCP servers..."
    pkill -f 'python3.*server\.py' 2>/dev/null \
        && echo "$(date): MCP servers killed (Claude Code will auto-relaunch)" \
        || echo "$(date): No MCP servers running"
done
