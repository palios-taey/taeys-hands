#!/usr/bin/env bash
# setup_worker.sh — Set up HMM enrichment worker on any machine.
#
# Usage: TAEY_NODE_ID=<id> bash setup_worker.sh [--skip-firefox] [--platforms chatgpt,grok,gemini]
#
# Requirements: Xvfb, x11vnc, firefox, xdotool, tmux
# Profile sync: /tmp/ff-profile-sync.tar.gz must exist (from Spark 1)
#
# Creates per-platform:
#   Xvfb display → Firefox with cookies → hmm_bot in tmux

set -euo pipefail

NODE_ID="${TAEY_NODE_ID:?TAEY_NODE_ID must be set}"
SKIP_FIREFOX=false
PLATFORMS="chatgpt,grok"
REDIS_HOST="${REDIS_HOST:-192.168.100.10}"
WEAVIATE_URL="${WEAVIATE_URL:-http://10.0.0.163:8088}"
NEO4J_URI="${NEO4J_URI:-bolt://10.0.0.163:7689}"
EMBEDDING_URL="${EMBEDDING_URL:-http://192.168.100.10:8091/v1/embeddings}"
RESOLUTION="1920x1080x24"
VNC_PASSWORD="${VNC_PASSWORD:-thor}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-firefox) SKIP_FIREFOX=true; shift ;;
        --platforms) PLATFORMS="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

IFS=',' read -ra PLATFORM_LIST <<< "$PLATFORMS"

# Map platform → display number (consistent across all machines)
declare -A PLATFORM_DISPLAY=(
    [chatgpt]=2
    [grok]=3
    [gemini]=4
)

declare -A PLATFORM_URL=(
    [chatgpt]="https://chatgpt.com"
    [grok]="https://grok.com/"
    [gemini]="https://gemini.google.com/app"
)

for cmd in Xvfb firefox xdotool tmux; do
    command -v "$cmd" >/dev/null || { echo "ERROR: $cmd not found"; exit 1; }
done

echo "============================================================"
echo "  HMM Worker Setup — $(hostname) (${NODE_ID})"
echo "  Platforms: ${PLATFORMS}"
echo "============================================================"
echo ""

# VNC password file
VNC_PASSWD_FILE="/tmp/.vnc_passwd_hmm"
if command -v x11vnc &>/dev/null; then
    x11vnc -storepasswd "$VNC_PASSWORD" "$VNC_PASSWD_FILE" 2>/dev/null || true
fi

# D-Bus
DBUS_ADDR=""
UID_NUM=$(id -u)
if [ -S "/run/user/${UID_NUM}/bus" ]; then
    DBUS_ADDR="unix:path=/run/user/${UID_NUM}/bus"
fi

# Kill existing bots first
for plat in "${PLATFORM_LIST[@]}"; do
    tmux_sess="hmm-${plat}"
    if tmux has-session -t "$tmux_sess" 2>/dev/null; then
        tmux send-keys -t "$tmux_sess" C-c "" 2>/dev/null || true
        sleep 1
    fi
done

for plat in "${PLATFORM_LIST[@]}"; do
    DNUM="${PLATFORM_DISPLAY[$plat]}"
    URL="${PLATFORM_URL[$plat]}"
    DISPLAY_STR=":${DNUM}"
    VNC_PORT="590${DNUM}"
    TMUX_SESSION="hmm-${plat}"
    PROFILE_COPY="/tmp/ff-profile-${plat}"

    echo "--- :${DNUM} → ${plat} ---"

    # 1. Xvfb
    if [ -f "/tmp/.X${DNUM}-lock" ]; then
        echo "  Xvfb ${DISPLAY_STR} already running"
    else
        echo "  Starting Xvfb ${DISPLAY_STR}..."
        Xvfb "${DISPLAY_STR}" -screen 0 "${RESOLUTION}" &
        disown
        sleep 1
    fi

    # 2. VNC (optional)
    if command -v x11vnc &>/dev/null; then
        if ss -tlnp 2>/dev/null | grep -q ":${VNC_PORT} "; then
            echo "  x11vnc already on port ${VNC_PORT}"
        else
            echo "  Starting x11vnc on port ${VNC_PORT}..."
            if [ -f "$VNC_PASSWD_FILE" ]; then
                x11vnc -display "${DISPLAY_STR}" -rfbport "${VNC_PORT}" -rfbauth "$VNC_PASSWD_FILE" -bg -quiet -forever 2>/dev/null || true
            else
                x11vnc -display "${DISPLAY_STR}" -rfbport "${VNC_PORT}" -passwd "$VNC_PASSWORD" -bg -quiet -forever 2>/dev/null || true
            fi
        fi
    fi

    # 3. Firefox with profile
    if [ "$SKIP_FIREFOX" = false ]; then
        # Kill existing Firefox on this display
        for pid in $(DISPLAY="${DISPLAY_STR}" xdotool search --class Firefox 2>/dev/null | while read wid; do
            xdotool getwindowpid "$wid" 2>/dev/null
        done | sort -u); do
            kill "$pid" 2>/dev/null || true
        done
        sleep 1

        # Extract profile from sync tarball
        echo "  Extracting profile → ${PROFILE_COPY}..."
        rm -rf "${PROFILE_COPY}"
        mkdir -p "${PROFILE_COPY}"
        tar xzf /tmp/ff-profile-sync.tar.gz -C "${PROFILE_COPY}" 2>/dev/null || true
        rm -f "${PROFILE_COPY}/lock" "${PROFILE_COPY}/.parentlock"

        echo "  Launching Firefox → ${URL}..."
        FF_ENV=(
            "DISPLAY=${DISPLAY_STR}"
            "MOZ_DISABLE_CONTENT_SANDBOX=1"
            "LIBGL_ALWAYS_SOFTWARE=1"
            "MOZ_ACCELERATED=0"
        )
        [ -n "$DBUS_ADDR" ] && FF_ENV+=("DBUS_SESSION_BUS_ADDRESS=$DBUS_ADDR")

        env "${FF_ENV[@]}" nohup firefox --no-remote --profile "${PROFILE_COPY}" "${URL}" \
            &>/tmp/firefox_${plat}.log &
        disown

        # Wait for Firefox window
        for i in $(seq 1 15); do
            sleep 2
            if DISPLAY="${DISPLAY_STR}" xdotool search --name 'Firefox' &>/dev/null; then
                echo "  Firefox ready (${i}×2s)"
                break
            fi
            [ "$i" = "15" ] && echo "  WARNING: Firefox may not have started"
        done

        # Position window to fill screen
        sleep 1
        WID=$(DISPLAY="${DISPLAY_STR}" xdotool search --name 'Firefox' 2>/dev/null | tail -1)
        if [ -n "$WID" ]; then
            DISPLAY="${DISPLAY_STR}" xdotool windowmove "$WID" 0 0 2>/dev/null || true
            DISPLAY="${DISPLAY_STR}" xdotool windowsize "$WID" 1920 1080 2>/dev/null || true
        fi
    fi

    # 4. Bot in tmux
    if ! tmux has-session -t "${TMUX_SESSION}" 2>/dev/null; then
        echo "  Creating tmux '${TMUX_SESSION}'..."
        tmux new-session -d -s "${TMUX_SESSION}" -x 200 -y 50
    fi

    REPO_DIR="$(cd ~/taeys-hands 2>/dev/null && pwd)"
    BOT_CMD="cd ${REPO_DIR} && DISPLAY=${DISPLAY_STR} TAEY_NODE_ID=${NODE_ID} NOTIFY_TARGET=weaver REDIS_HOST=${REDIS_HOST} WEAVIATE_URL=${WEAVIATE_URL} NEO4J_URI=${NEO4J_URI} EMBEDDING_URL=${EMBEDDING_URL} PYTHONPATH=~/embedding-server python3 agents/hmm_bot.py --platforms ${plat} 2>&1 | tee /tmp/hmm_bot_${plat}.log"
    tmux send-keys -t "${TMUX_SESSION}" "${BOT_CMD}" Enter
    echo "  Bot started in tmux '${TMUX_SESSION}'"
    echo ""
done

echo "============================================================"
echo "  Worker ${NODE_ID} — ${#PLATFORM_LIST[@]} platforms running"
echo "============================================================"
echo ""
echo "  tmux sessions:"
for plat in "${PLATFORM_LIST[@]}"; do
    echo "    tmux attach -t hmm-${plat}"
done
echo ""
echo "  Logs:"
for plat in "${PLATFORM_LIST[@]}"; do
    echo "    tail -f /tmp/hmm_bot_${plat}.log"
done
echo ""
