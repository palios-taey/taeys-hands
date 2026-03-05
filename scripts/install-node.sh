#!/bin/bash
# install-node.sh: Install taeys-hands node dependencies on a new machine.
#
# Installs system tools and the tmux-send script to /usr/local/bin.
# Run as a user with sudo access on the target machine.
#
# Usage:
#   bash scripts/install-node.sh
#
# What it installs:
#   - tmux-send -> /usr/local/bin/tmux-send  (Claude-to-Claude messaging)
#   - System packages: xdotool, xsel, xdpyinfo (required for AT-SPI tools)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== taeys-hands node install ==="
echo "Repo: $REPO_ROOT"
echo "Host: $(hostname -s)"
echo ""

# --- tmux-send ---
echo "[1/2] Installing tmux-send..."
sudo install -m 755 "$REPO_ROOT/scripts/tmux-send" /usr/local/bin/tmux-send
echo "  -> /usr/local/bin/tmux-send"

# --- System packages ---
echo "[2/2] Installing system packages..."
if command -v apt-get &>/dev/null; then
    sudo apt-get install -y xdotool xsel x11-utils 2>&1 | grep -E "^(Setting|Unpacking|already|E:)" || true
else
    echo "  WARN: apt-get not found — install xdotool, xsel, xdpyinfo manually"
fi

echo ""
echo "=== Done ==="
echo "Verify: tmux-send --help 2>&1 | head -2"
echo "        tmux-send <session> 'hello'"
