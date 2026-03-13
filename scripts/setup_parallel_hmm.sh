#!/usr/bin/env bash
# Setup parallel HMM enrichment: 3 Xvfb displays × 1 platform each × 1 bot each.
#
# Usage: ./scripts/setup_parallel_hmm.sh [--vnc-password PASSWORD] [--skip-firefox]
#
# Creates:
#   :1 → Firefox → chatgpt.com → hmm_bot --platforms chatgpt
#   :2 → Firefox → gemini.google.com → hmm_bot --platforms gemini
#   :3 → Firefox → grok.com → hmm_bot --platforms grok
#
# Firefox instances each get a COPY of the active profile (preserving cookies).
# VNC ports: 5901, 5902, 5903 (password protected)
# tmux sessions: hmm-chatgpt, hmm-gemini, hmm-grok
#
# After first run, user must VNC in and verify logins on each display.
# Subsequent runs with --skip-firefox reuse existing Firefox instances.

set -euo pipefail

VNC_PASSWORD="${VNC_PASSWORD:-thor}"
SKIP_FIREFOX=false
SKIP_BOTS=false

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --vnc-password) VNC_PASSWORD="$2"; shift 2 ;;
        --skip-firefox) SKIP_FIREFOX=true; shift ;;
        --skip-bots) SKIP_BOTS=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

RESOLUTION="1920x1080x24"

# Platform config: display_num → platform|url
declare -A PLATFORMS=(
    [1]="chatgpt|https://chatgpt.com"
    [2]="gemini|https://gemini.google.com/app"
    [3]="grok|https://grok.com/"
)

# Check dependencies
for cmd in Xvfb x11vnc firefox tmux; do
    command -v "$cmd" >/dev/null || { echo "ERROR: $cmd not found"; exit 1; }
done

# Find the active Firefox profile (the one with cookies)
find_firefox_profile() {
    local profile_base=""
    for base in "$HOME/.config/mozilla/firefox" "$HOME/.mozilla/firefox"; do
        if [ -f "$base/profiles.ini" ]; then
            profile_base="$base"
            break
        fi
    done
    if [ -z "$profile_base" ]; then
        echo ""
        return
    fi
    # Get the default-release profile path
    local rel_path
    rel_path=$(grep -A3 '\[Install' "$profile_base/profiles.ini" | grep '^Default=' | head -1 | cut -d= -f2)
    if [ -n "$rel_path" ] && [ -d "$profile_base/$rel_path" ]; then
        echo "$profile_base/$rel_path"
        return
    fi
    # Fallback: find profile with cookies.sqlite
    for dir in "$profile_base"/*/; do
        if [ -f "${dir}cookies.sqlite" ]; then
            echo "${dir%/}"
            return
        fi
    done
    echo ""
}

# D-Bus session address
DBUS_ADDR=""
UID_NUM=$(id -u)
if [ -S "/run/user/${UID_NUM}/bus" ]; then
    DBUS_ADDR="unix:path=/run/user/${UID_NUM}/bus"
fi

# VNC password file
VNC_PASSWD_FILE="/tmp/.vnc_passwd_hmm"
x11vnc -storepasswd "$VNC_PASSWORD" "$VNC_PASSWD_FILE" 2>/dev/null || true

echo "============================================================"
echo "  HMM Parallel Setup — $(hostname)"
echo "============================================================"
echo ""

# Find and copy Firefox profile for each instance
SOURCE_PROFILE=""
if [ "$SKIP_FIREFOX" = false ]; then
    SOURCE_PROFILE=$(find_firefox_profile)
    if [ -z "$SOURCE_PROFILE" ]; then
        echo "WARNING: No Firefox profile found with cookies."
        echo "         Firefox will launch without logins — VNC in to log in manually."
    else
        echo "Source profile: $SOURCE_PROFILE"
        echo ""
    fi
fi

for DNUM in 1 2 3; do
    IFS='|' read -r PLATFORM URL <<< "${PLATFORMS[$DNUM]}"
    DISPLAY_STR=":${DNUM}"
    VNC_PORT="590${DNUM}"
    TMUX_SESSION="hmm-${PLATFORM}"
    PROFILE_COPY="/tmp/ff-profile-${PLATFORM}"

    echo "--- Display :${DNUM} → ${PLATFORM} ---"

    # 1. Start Xvfb if not running
    if [ -f "/tmp/.X${DNUM}-lock" ]; then
        echo "  Xvfb ${DISPLAY_STR} already running"
    else
        echo "  Starting Xvfb ${DISPLAY_STR}..."
        Xvfb "${DISPLAY_STR}" -screen 0 "${RESOLUTION}" &
        disown
        sleep 1
    fi

    # 2. Start x11vnc with password if not running
    if ss -tlnp 2>/dev/null | grep -q ":${VNC_PORT} "; then
        echo "  x11vnc already on port ${VNC_PORT}"
    else
        echo "  Starting x11vnc on port ${VNC_PORT} (password: ${VNC_PASSWORD})..."
        if [ -f "$VNC_PASSWD_FILE" ]; then
            x11vnc -display "${DISPLAY_STR}" -rfbport "${VNC_PORT}" -rfbauth "$VNC_PASSWD_FILE" -bg -quiet -forever 2>/dev/null || true
        else
            x11vnc -display "${DISPLAY_STR}" -rfbport "${VNC_PORT}" -passwd "$VNC_PASSWORD" -bg -quiet -forever 2>/dev/null || true
        fi
    fi

    # 3. Start Firefox with profile copy (if not skipped and not already running)
    if [ "$SKIP_FIREFOX" = false ]; then
        FF_COUNT=$(DISPLAY="${DISPLAY_STR}" xdotool search --name 'Mozilla Firefox' 2>/dev/null | wc -l || echo 0)
        if [ "$FF_COUNT" -gt 0 ]; then
            echo "  Firefox already running on ${DISPLAY_STR}"
        else
            # Copy profile if source exists
            if [ -n "$SOURCE_PROFILE" ]; then
                echo "  Copying profile to ${PROFILE_COPY}..."
                # Kill any Firefox on this display first
                DISPLAY="${DISPLAY_STR}" pkill -f firefox 2>/dev/null || true
                sleep 1
                rm -rf "${PROFILE_COPY}"
                cp -r "$SOURCE_PROFILE" "${PROFILE_COPY}"
                # Remove locks from copy
                rm -f "${PROFILE_COPY}/lock" "${PROFILE_COPY}/.parentlock"
                rm -rf "${PROFILE_COPY}/sessionstore"* "${PROFILE_COPY}/sessionstore-backups"
                PROFILE_ARG="--profile ${PROFILE_COPY}"
            else
                PROFILE_ARG=""
            fi

            echo "  Launching Firefox → ${URL}..."
            FF_ENV=(
                env
                "DISPLAY=${DISPLAY_STR}"
                "MOZ_DISABLE_CONTENT_SANDBOX=1"
                "LIBGL_ALWAYS_SOFTWARE=1"
                "MOZ_ACCELERATED=0"
            )
            if [ -n "$DBUS_ADDR" ]; then
                FF_ENV+=("DBUS_SESSION_BUS_ADDRESS=$DBUS_ADDR")
            fi
            "${FF_ENV[@]}" firefox --no-remote ${PROFILE_ARG} "${URL}" &>/tmp/firefox_${PLATFORM}.log &
            disown
            sleep 4
        fi
    fi

    # 4. Start bot (unless --skip-bots)
    if [ "$SKIP_BOTS" = true ]; then
        echo "  Skipping bot (--skip-bots)"
    else
        if tmux has-session -t "${TMUX_SESSION}" 2>/dev/null; then
            echo "  tmux '${TMUX_SESSION}' exists — restarting bot..."
            tmux send-keys -t "${TMUX_SESSION}" C-c "" 2>/dev/null || true
            sleep 2
        else
            echo "  Creating tmux '${TMUX_SESSION}'..."
            tmux new-session -d -s "${TMUX_SESSION}" -x 200 -y 50
        fi

        BOT_CMD="cd ~/taeys-hands && DISPLAY=${DISPLAY_STR} PYTHONPATH=~/embedding-server python3 agents/hmm_bot.py --platforms ${PLATFORM} 2>&1 | tee /tmp/hmm_bot_${PLATFORM}.log"
        tmux send-keys -t "${TMUX_SESSION}" "${BOT_CMD}" Enter
        echo "  Bot started in tmux '${TMUX_SESSION}'"
    fi

    echo ""
done

echo "============================================================"
echo "  All 3 platforms running in parallel!"
echo "============================================================"
echo ""
echo "  VNC (password: ${VNC_PASSWORD}):"
FIRST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "    :1 chatgpt  → vnc://${FIRST_IP}:5901"
echo "    :2 gemini   → vnc://${FIRST_IP}:5902"
echo "    :3 grok     → vnc://${FIRST_IP}:5903"
echo ""
echo "  tmux sessions:"
echo "    tmux attach -t hmm-chatgpt"
echo "    tmux attach -t hmm-gemini"
echo "    tmux attach -t hmm-grok"
echo ""
echo "  Logs:"
echo "    tail -f /tmp/hmm_bot_chatgpt.log"
echo "    tail -f /tmp/hmm_bot_gemini.log"
echo "    tail -f /tmp/hmm_bot_grok.log"
echo ""
echo "  Stop all: pkill -f hmm_bot"
