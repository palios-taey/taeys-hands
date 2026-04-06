#!/usr/bin/env bash
# Setup parallel HMM enrichment: 3 Xvfb displays × 1 platform each × 1 bot each.
#
# Usage: ./scripts/setup_parallel_hmm.sh [--vnc-password PASSWORD] [--skip-firefox] [--skip-bots]
#
# Creates:
#   :1 → Firefox → chatgpt.com → hmm_bot --platforms chatgpt
#   :2 → Firefox → gemini.google.com → hmm_bot --platforms gemini
#   :3 → Firefox → grok.com → hmm_bot --platforms grok
#
# AT-SPI isolation: find_firefox_for_platform() handles multiple Firefox
# instances by matching documents to platform URLs. No D-Bus isolation needed.
#
# Firefox profile is copied from the active profile (preserving cookies).
# VNC ports: 5901, 5902, 5903 (password protected)
# tmux sessions: hmm-chatgpt, hmm-gemini, hmm-grok

set -euo pipefail

VNC_PASSWORD="${VNC_PASSWORD:-thor}"
SKIP_FIREFOX=false
SKIP_BOTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --vnc-password) VNC_PASSWORD="$2"; shift 2 ;;
        --skip-firefox) SKIP_FIREFOX=true; shift ;;
        --skip-bots) SKIP_BOTS=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

RESOLUTION="1920x1080x24"
TAEY_PATH="${HOME}/taeys-hands"
EMBEDDING_PATH="${HOME}/embedding-server"

# --- Load machine.env if available ---
for candidate in "${HOME}/.taey/machine.env" "${TAEY_PATH}/machine.env"; do
    if [[ -f "${candidate}" ]]; then
        # shellcheck source=/dev/null
        source "${candidate}"
        break
    fi
done
REDIS_HOST="${TAEY_REDIS_HOST:-127.0.0.1}"

# Display numbers start at :2 to avoid :0 (physical) and :1 (GNOME session on some machines)
# Uses machine.env mappings if available, otherwise defaults
declare -A PLATFORMS
for display in 2 3 4; do
    DISPLAY_VAR="TAEY_DISPLAY_${display}"
    DISPLAY_CONFIG="${!DISPLAY_VAR:-}"
    if [[ -n "${DISPLAY_CONFIG}" ]]; then
        platform="${DISPLAY_CONFIG%%:*}"
        _remainder="${DISPLAY_CONFIG#*:}"
        url="${_remainder#*:}"
        PLATFORMS[$display]="${platform}|${url}"
    fi
done
# Fallback if no machine.env
if [[ ${#PLATFORMS[@]} -eq 0 ]]; then
    PLATFORMS=(
        [2]="chatgpt|https://chatgpt.com/?temporary-chat=true"
        [3]="gemini|https://gemini.google.com/app"
        [4]="grok|https://grok.com/"
    )
fi

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
    [ -z "$profile_base" ] && return
    local rel_path
    rel_path=$(grep -A3 '\[Install' "$profile_base/profiles.ini" | grep '^Default=' | head -1 | cut -d= -f2)
    if [ -n "$rel_path" ] && [ -d "$profile_base/$rel_path" ]; then
        echo "$profile_base/$rel_path"
        return
    fi
    for dir in "$profile_base"/*/; do
        [ -f "${dir}cookies.sqlite" ] && echo "${dir%/}" && return
    done
}

# VNC password file
VNC_PASSWD_FILE="/tmp/.vnc_passwd_hmm"
x11vnc -storepasswd "$VNC_PASSWORD" "$VNC_PASSWD_FILE" 2>/dev/null || true

# D-Bus: use system session bus (AT-SPI isolation via find_firefox_for_platform)
DBUS_ADDR=""
UID_NUM=$(id -u)
if [ -S "/run/user/${UID_NUM}/bus" ]; then
    DBUS_ADDR="unix:path=/run/user/${UID_NUM}/bus"
fi

echo "============================================================"
echo "  HMM Parallel Setup — $(hostname)"
echo "============================================================"
echo ""

SOURCE_PROFILE=""
if [ "$SKIP_FIREFOX" = false ]; then
    SOURCE_PROFILE=$(find_firefox_profile)
    if [ -z "$SOURCE_PROFILE" ]; then
        echo "WARNING: No Firefox profile with cookies found."
    else
        echo "Source profile: $SOURCE_PROFILE"
    fi
    echo ""
fi

for DNUM in 2 3 4; do
    IFS='|' read -r PLATFORM URL <<< "${PLATFORMS[$DNUM]}"
    DISPLAY_STR=":${DNUM}"
    VNC_PORT="590${DNUM}"
    TMUX_SESSION="hmm-${PLATFORM}"
    PROFILE_COPY="/tmp/ff-profile-${PLATFORM}"

    echo "--- Display :${DNUM} → ${PLATFORM} ---"

    # 1. Xvfb
    if [ -f "/tmp/.X${DNUM}-lock" ]; then
        echo "  Xvfb ${DISPLAY_STR} already running"
    else
        echo "  Starting Xvfb ${DISPLAY_STR}..."
        Xvfb "${DISPLAY_STR}" -screen 0 "${RESOLUTION}" &
        disown
        sleep 1
    fi

    # 2. x11vnc
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

    # 3. Firefox with profile copy
    if [ "$SKIP_FIREFOX" = false ]; then
        if DISPLAY="${DISPLAY_STR}" xdotool search --name 'Mozilla Firefox' &>/dev/null; then
            echo "  Firefox already running on ${DISPLAY_STR}"
        else
            # Copy profile
            PROFILE_ARG=""
            if [ -n "$SOURCE_PROFILE" ]; then
                echo "  Copying profile → ${PROFILE_COPY}..."
                rm -rf "${PROFILE_COPY}"
                cp -r "$SOURCE_PROFILE" "${PROFILE_COPY}"
                rm -f "${PROFILE_COPY}/lock" "${PROFILE_COPY}/.parentlock"
                # sessionstore preserved — contains session cookies for login
                PROFILE_ARG="--profile ${PROFILE_COPY}"
            fi

            echo "  Launching Firefox → ${URL}..."
            FF_ENV=(
                "DISPLAY=${DISPLAY_STR}"
                "MOZ_DISABLE_CONTENT_SANDBOX=1"
                "LIBGL_ALWAYS_SOFTWARE=1"
                "MOZ_ACCELERATED=0"
            )
            [ -n "$DBUS_ADDR" ] && FF_ENV+=("DBUS_SESSION_BUS_ADDRESS=$DBUS_ADDR")

            env "${FF_ENV[@]}" nohup firefox --no-remote ${PROFILE_ARG} "${URL}" \
                &>/tmp/firefox_${PLATFORM}.log &
            disown

            # Wait for Firefox window
            for i in $(seq 1 12); do
                sleep 2
                if DISPLAY="${DISPLAY_STR}" xdotool search --name 'Mozilla Firefox' &>/dev/null; then
                    echo "  Firefox ready (${i}×2s)"
                    break
                fi
            done
        fi
    fi

    # 4. Bot
    if [ "$SKIP_BOTS" = true ]; then
        echo "  Skipping bot (--skip-bots)"
    else
        if tmux has-session -t "${TMUX_SESSION}" 2>/dev/null; then
            echo "  tmux '${TMUX_SESSION}' — restarting bot..."
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
echo "    :2 chatgpt  → vnc://${FIRST_IP}:5902"
echo "    :3 gemini   → vnc://${FIRST_IP}:5903"
echo "    :4 grok     → vnc://${FIRST_IP}:5904"
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
