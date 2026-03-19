#!/usr/bin/env bash
# launch_team.sh — Launch one HMM enrichment team (3 platforms) on virtual displays.
#
# CRITICAL: Firefox MUST be launched with DBUS_SESSION_BUS_ADDRESS set,
# otherwise AT-SPI cannot see it and all automation fails silently.
#
# Usage:
#   ./scripts/launch_team.sh 1              # Team 1: displays :2,:3,:4
#   ./scripts/launch_team.sh 2              # Team 2: displays :5,:6,:7
#   ./scripts/launch_team.sh 1 --skip-firefox  # Restart bots only (Firefox already running)
#   ./scripts/launch_team.sh 1 --skip-bots     # Launch Firefox only (login via VNC first)
#
# Each team gets 3 displays, 3 Firefox instances, 3 tmux sessions, 3 VNC ports.
# Team 1: chatgpt(:2/5902), gemini(:3/5903), grok(:4/5904)
# Team 2: chatgpt2(:5/5905), gemini2(:6/5906), grok2(:7/5907)

set -euo pipefail

TEAM="${1:?Usage: launch_team.sh <team_number> [--skip-firefox] [--skip-bots]}"
SKIP_FIREFOX=false
SKIP_BOTS=false
VNC_PASSWORD="${VNC_PASSWORD:-thor}"
RESOLUTION="1920x1080x24"
DBUS="unix:path=/run/user/1000/bus"
EMBEDDING_PATH="${HOME}/embedding-server"
TAEY_PATH="${HOME}/taeys-hands"

shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-firefox) SKIP_FIREFOX=true; shift ;;
        --skip-bots) SKIP_BOTS=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Team layout
if [ "$TEAM" = "1" ]; then
    declare -A PLATFORMS=(
        [2]="chatgpt|https://chatgpt.com/?temporary-chat=true|hmm-chatgpt|ff-profile-chatgpt"
        [3]="gemini|https://gemini.google.com/app|hmm-gemini|ff-profile-gemini"
        [4]="grok|https://grok.com/|hmm-grok|ff-profile-grok"
    )
    VNC_BASE=5902
elif [ "$TEAM" = "2" ]; then
    declare -A PLATFORMS=(
        [5]="chatgpt|https://chatgpt.com/?temporary-chat=true|hmm-chatgpt2|ff-profile-chatgpt2"
        [6]="gemini|https://gemini.google.com/app|hmm-gemini2|ff-profile-gemini2"
        [7]="grok|https://grok.com/|hmm-grok2|ff-profile-grok2"
    )
    VNC_BASE=5905
else
    echo "Team must be 1 or 2"
    exit 1
fi

echo "=== Launching Team $TEAM ==="

for display in "${!PLATFORMS[@]}"; do
    IFS='|' read -r platform url tmux_session profile <<< "${PLATFORMS[$display]}"
    vnc_port=$((display + 5900))

    echo ""
    echo "--- :$display → $platform ($tmux_session) ---"

    # Ensure Xvfb display exists
    if [ ! -e "/tmp/.X11-unix/X${display}" ]; then
        echo "  Starting Xvfb :$display..."
        Xvfb ":$display" -screen 0 "$RESOLUTION" -ac &
        sleep 1
    else
        echo "  Xvfb :$display already running"
    fi

    # Ensure tmux session exists
    tmux new-session -d -s "$tmux_session" 2>/dev/null || true

    # Ensure VNC
    if ! ss -tlnp | grep -q ":${vnc_port} " 2>/dev/null; then
        echo "  Starting VNC on port $vnc_port..."
        x11vnc -storepasswd "$VNC_PASSWORD" /tmp/.vnc_passwd_hmm 2>/dev/null || true
        x11vnc -display ":$display" -rfbport "$vnc_port" -rfbauth /tmp/.vnc_passwd_hmm -bg -quiet -forever 2>/dev/null
    else
        echo "  VNC already on port $vnc_port"
    fi

    # Ensure Firefox profile exists
    if [ ! -d "/tmp/$profile" ]; then
        echo "  Creating profile /tmp/$profile..."
        mkdir -p "/tmp/$profile"
        echo "  ⚠ Empty profile — login required via VNC port $vnc_port"
    fi

    # Launch Firefox (MUST have DBUS_SESSION_BUS_ADDRESS!)
    if [ "$SKIP_FIREFOX" = "false" ]; then
        # Kill existing Firefox on this profile
        pkill -f "$profile" 2>/dev/null || true
        sleep 2

        echo "  Launching Firefox on :$display with D-Bus..."
        # Launch via tmux to ensure D-Bus inheritance
        tmux send-keys -t "$tmux_session" \
            "DISPLAY=:$display DBUS_SESSION_BUS_ADDRESS=$DBUS firefox --no-remote --profile /tmp/$profile '$url' &" Enter
        sleep 5
        echo "  Firefox launched (check VNC port $vnc_port for login)"
    fi

    # Start bot
    if [ "$SKIP_BOTS" = "false" ]; then
        echo "  Starting bot..."
        tmux send-keys -t "$tmux_session" \
            "cd $TAEY_PATH && DISPLAY=:$display DBUS_SESSION_BUS_ADDRESS=$DBUS PYTHONPATH=$EMBEDDING_PATH python3 agents/hmm_bot.py --platforms $platform --cycles 0" Enter
        echo "  Bot started in tmux session: $tmux_session"
    fi
done

echo ""
echo "=== Team $TEAM launched ==="
echo ""
echo "VNC access (password: $VNC_PASSWORD):"
for display in "${!PLATFORMS[@]}"; do
    IFS='|' read -r platform url tmux_session profile <<< "${PLATFORMS[$display]}"
    vnc_port=$((display + 5900))
    echo "  :$display $platform → vnc://$(hostname -I | awk '{print $1}'):$vnc_port"
done
echo ""
echo "Monitor: tmux attach -t hmm-<platform>"
