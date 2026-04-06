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

# --- Load machine.env (single source of truth) ---
MACHINE_ENV=""
for candidate in "${HOME}/.taey/machine.env" "${TAEY_PATH}/machine.env"; do
    if [[ -f "${candidate}" ]]; then
        MACHINE_ENV="${candidate}"
        break
    fi
done
if [[ -n "${MACHINE_ENV}" ]]; then
    # shellcheck source=/dev/null
    source "${MACHINE_ENV}"
fi
REDIS_HOST="${TAEY_REDIS_HOST:-127.0.0.1}"

# Team layout — reads from machine.env if available, falls back to defaults
if [ "$TEAM" = "1" ]; then
    TEAM_DISPLAYS=(2 3 4)
    VNC_BASE=5902
elif [ "$TEAM" = "2" ]; then
    TEAM_DISPLAYS=(5 6 7)
    VNC_BASE=5905
else
    echo "Team must be 1 or 2"
    exit 1
fi

# Build PLATFORMS map from machine.env or defaults
declare -A PLATFORMS
for display in "${TEAM_DISPLAYS[@]}"; do
    DISPLAY_VAR="TAEY_DISPLAY_${display}"
    DISPLAY_CONFIG="${!DISPLAY_VAR:-}"
    if [[ -n "${DISPLAY_CONFIG}" ]]; then
        platform="${DISPLAY_CONFIG%%:*}"
        _remainder="${DISPLAY_CONFIG#*:}"
        profile="${_remainder%%:*}"
        url="${_remainder#*:}"
        tmux_session="hmm-${platform}"
    else
        # Fallback defaults if no machine.env
        case $display in
            2|5) platform="chatgpt"; url="https://chatgpt.com/?temporary-chat=true"; profile="ff-profile-chatgpt"; tmux_session="hmm-chatgpt" ;;
            3|6) platform="gemini"; url="https://gemini.google.com/app"; profile="ff-profile-gemini"; tmux_session="hmm-gemini" ;;
            4|7) platform="grok"; url="https://grok.com/"; profile="ff-profile-grok"; tmux_session="hmm-grok" ;;
        esac
        if [ "$TEAM" = "2" ]; then
            profile="${profile}2"
            tmux_session="${tmux_session}2"
        fi
    fi
    PLATFORMS[$display]="${platform}|${url}|${tmux_session}|${profile}"
done

echo "=== Launching Team $TEAM ==="

for display in "${!PLATFORMS[@]}"; do
    IFS='|' read -r platform url tmux_session profile <<< "${PLATFORMS[$display]}"
    vnc_port=$((display + 5900))

    echo ""
    echo "--- :$display → $platform ($tmux_session) ---"

    # Ensure Xvfb display exists
    if [ ! -e "/tmp/.X11-unix/X${display}" ]; then
        echo "  Cleaning stale state for :$display..."
        rm -f "/tmp/.X${display}-lock" "/tmp/.X11-unix/X${display}"

        echo "  Starting Xvfb :$display..."
        Xvfb ":$display" -screen 0 "$RESOLUTION" -noreset -ac &

        # Wait for display readiness (not just sleep)
        retries=20
        while ! DISPLAY=":$display" xdpyinfo >/dev/null 2>&1; do
            sleep 0.3
            retries=$((retries - 1))
            if [ $retries -le 0 ]; then
                echo "  ERROR: Xvfb :$display failed to start"
                continue 2
            fi
        done
        echo "  Xvfb :$display ready"

        # Start window manager (required for clipboard/keyboard focus)
        if command -v openbox >/dev/null 2>&1; then
            DISPLAY=":$display" openbox --sm-disable &
            sleep 0.5
            echo "  openbox started on :$display"
        fi
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

        # Write automation-friendly user.js if missing
        if [ ! -f "/tmp/$profile/user.js" ]; then
            cat > "/tmp/$profile/user.js" <<'USERJS'
user_pref("gfx.webrender.all", false);
user_pref("layers.acceleration.disabled", true);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("toolkit.cosmeticAnimations.enabled", false);
USERJS
        fi

        echo "  Starting isolated D-Bus for :$display..."
        eval "$(DISPLAY=:$display dbus-launch --sh-syntax --exit-with-session 2>/dev/null)" || true
        DISPLAY_DBUS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

        # Start AT-SPI registryd in isolated bus
        DISPLAY=":$display" DBUS_SESSION_BUS_ADDRESS="$DISPLAY_DBUS" /usr/libexec/at-spi2-registryd >/dev/null 2>&1 &
        sleep 2

        echo "  Launching Firefox on :$display with isolated D-Bus..."
        # GPU/RDD env vars prevent IPC crashes on Xvfb (especially aarch64)
        tmux send-keys -t "$tmux_session" \
            "DISPLAY=:$display DBUS_SESSION_BUS_ADDRESS='$DISPLAY_DBUS' LIBGL_ALWAYS_SOFTWARE=1 MOZ_DISABLE_RDD_SANDBOX=1 MOZ_DISABLE_GPU_SANDBOXING=1 GDK_BACKEND=x11 firefox --no-remote --profile /tmp/$profile '$url' &" Enter
        sleep 5

        # Record bus address for bot and MCP tools
        echo "$DISPLAY_DBUS" > "/tmp/a11y_bus_:${display}"
        echo "  Firefox launched (check VNC port $vnc_port for login)"
    fi

    # Start bot
    if [ "$SKIP_BOTS" = "false" ]; then
        DISPLAY_DBUS="$(cat /tmp/a11y_bus_:${display} 2>/dev/null || echo 'unix:path=/run/user/1000/bus')"
        echo "  Starting bot..."
        tmux send-keys -t "$tmux_session" \
            "cd $TAEY_PATH && DISPLAY=:$display DBUS_SESSION_BUS_ADDRESS='$DISPLAY_DBUS' TAEY_NOTIFY_NODE=taeys-hands REDIS_HOST=$REDIS_HOST WEAVIATE_URL=http://10.0.0.163:8088 PYTHONPATH=$EMBEDDING_PATH python3 agents/hmm_bot.py --platforms $platform --cycles 0" Enter
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
