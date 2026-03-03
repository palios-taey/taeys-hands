#!/usr/bin/env bash
# Setup a virtual X display with VNC and Firefox for a taeys-hands instance.
#
# Usage: ./scripts/setup_display.sh <display_number> <instance_name>
# Example: ./scripts/setup_display.sh 1 weaver
#
# Starts Xvfb, x11vnc, and Firefox with 5 platform tabs on :N.
# Connect via VNC: vncviewer localhost:590N

set -euo pipefail

DISPLAY_NUM="${1:?Usage: $0 <display_number> <instance_name>}"
INSTANCE="${2:?Usage: $0 <display_number> <instance_name>}"
DISPLAY_STR=":${DISPLAY_NUM}"
VNC_PORT="590${DISPLAY_NUM}"
RESOLUTION="1920x1080x24"

# Platform URLs (match tab_shortcut order: Alt+1 through Alt+5)
URLS=(
    "https://chatgpt.com/?temporary-chat=true"
    "https://claude.ai/new"
    "https://gemini.google.com/app"
    "https://grok.com/"
    "https://www.perplexity.ai/"
)

# Check dependencies
for cmd in Xvfb x11vnc firefox; do
    command -v "$cmd" >/dev/null || { echo "ERROR: $cmd not found"; exit 1; }
done

# Start Xvfb if not already running
if [ -f "/tmp/.X${DISPLAY_NUM}-lock" ]; then
    echo "Xvfb ${DISPLAY_STR} already running (lock file exists)"
else
    echo "Starting Xvfb ${DISPLAY_STR} at ${RESOLUTION}..."
    Xvfb "${DISPLAY_STR}" -screen 0 "${RESOLUTION}" &
    sleep 1
    echo "Xvfb started (PID $!)"
fi

# Start x11vnc if not already bound to this port
if ss -tlnp | grep -q ":${VNC_PORT} "; then
    echo "x11vnc already running on port ${VNC_PORT}"
else
    echo "Starting x11vnc on port ${VNC_PORT}..."
    x11vnc -display "${DISPLAY_STR}" -rfbport "${VNC_PORT}" -nopw -bg -quiet 2>/dev/null
    echo "x11vnc started — connect with: vncviewer localhost:${VNC_PORT}"
fi

# Launch Firefox with platform tabs
if DISPLAY="${DISPLAY_STR}" xdotool search --name 'Mozilla Firefox' >/dev/null 2>&1; then
    echo "Firefox already running on ${DISPLAY_STR}"
else
    echo "Launching Firefox on ${DISPLAY_STR} with ${#URLS[@]} platform tabs..."
    DISPLAY="${DISPLAY_STR}" firefox "${URLS[@]}" &
    sleep 3
    echo "Firefox launched"
fi

echo ""
echo "=== ${INSTANCE} instance ready ==="
echo "  DISPLAY=${DISPLAY_STR}"
echo "  TAEY_NODE_ID=${INSTANCE}"
echo "  VNC: vncviewer localhost:${VNC_PORT}"
echo ""
echo "In the ${INSTANCE} tmux session, set:"
echo "  export DISPLAY=${DISPLAY_STR} TAEY_NODE_ID=${INSTANCE}"
