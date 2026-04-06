#!/usr/bin/env bash
# launch_sft.sh — Launch SFT training generation on virtual displays.
#
# Uses hardened Xvfb launch (lock cleanup, openbox WM, Firefox GPU env vars).
# Reuses existing Firefox profiles with active logins.
#
# Usage:
#   ./scripts/launch_sft.sh                    # Full launch (Xvfb + Firefox + bots)
#   ./scripts/launch_sft.sh --skip-firefox     # Restart bots only
#   ./scripts/launch_sft.sh --skip-bots        # Launch Firefox only (check via VNC)
#   ./scripts/launch_sft.sh --round dpo        # DPO round instead of SFT
#
# Displays: :5 (chatgpt), :6 (gemini), :7 (grok)
# Profiles: ff-profile-chatgpt2, ff-profile-gemini2, ff-profile-grok2
# VNC: 5905, 5906, 5907

set -euo pipefail

SKIP_FIREFOX=false
SKIP_BOTS=false
ROUND="sft"
VNC_PASSWORD="${VNC_PASSWORD:-thor}"
RESOLUTION="1920x1080x24"
TAEY_PATH="${HOME}/taeys-hands"
EMBEDDING_PATH="${HOME}/embedding-server"

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-firefox) SKIP_FIREFOX=true; shift ;;
        --skip-bots) SKIP_BOTS=true; shift ;;
        --round) ROUND="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# --- Load machine.env (single source of truth) ---
for candidate in "${HOME}/.taey/machine.env" "${TAEY_PATH}/machine.env"; do
    if [[ -f "${candidate}" ]]; then
        # shellcheck source=/dev/null
        source "${candidate}"
        break
    fi
done
REDIS_HOST="${TAEY_REDIS_HOST:-127.0.0.1}"

# Platform layout from machine.env or defaults
declare -A PLATFORMS
for display in 5 6 7; do
    DISPLAY_VAR="TAEY_DISPLAY_${display}"
    DISPLAY_CONFIG="${!DISPLAY_VAR:-}"
    if [[ -n "${DISPLAY_CONFIG}" ]]; then
        platform="${DISPLAY_CONFIG%%:*}"
        _remainder="${DISPLAY_CONFIG#*:}"
        profile="${_remainder%%:*}"
        url="${_remainder#*:}"
        PLATFORMS[$display]="${platform}|${url}|sft-${platform}|${profile}"
    fi
done
# Fallback if no machine.env
if [[ ${#PLATFORMS[@]} -eq 0 ]]; then
    PLATFORMS=(
        [5]="chatgpt|https://chatgpt.com/?temporary-chat=true|sft-chatgpt|ff-profile-chatgpt2"
        [6]="gemini|https://gemini.google.com/app|sft-gemini|ff-profile-gemini2"
        [7]="grok|https://grok.com/|sft-grok|ff-profile-grok2"
    )
fi

echo "=== Launching SFT ($ROUND) ==="

for display in "${!PLATFORMS[@]}"; do
    IFS='|' read -r platform url tmux_session profile <<< "${PLATFORMS[$display]}"
    vnc_port=$((display + 5900))

    echo ""
    echo "--- :$display -> $platform ($tmux_session) ---"

    # Clean and start Xvfb
    if ! DISPLAY=":$display" xdpyinfo >/dev/null 2>&1; then
        echo "  Cleaning stale state for :$display..."
        rm -f "/tmp/.X${display}-lock" "/tmp/.X11-unix/X${display}"
        pkill -f "Xvfb :${display} " 2>/dev/null || true
        sleep 0.3

        echo "  Starting Xvfb :$display..."
        Xvfb ":$display" -screen 0 "$RESOLUTION" -noreset -ac &

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
    else
        echo "  Xvfb :$display already running"
    fi

    # Start window manager if not already running
    if ! pgrep -f "openbox.*DISPLAY=:${display}" >/dev/null 2>&1; then
        if command -v openbox >/dev/null 2>&1; then
            DISPLAY=":$display" openbox --sm-disable &
            sleep 0.5
            echo "  openbox started on :$display"
        fi
    fi

    # Ensure tmux session
    tmux new-session -d -s "$tmux_session" 2>/dev/null || true

    # VNC
    if ! ss -tlnp | grep -q ":${vnc_port} " 2>/dev/null; then
        echo "  Starting VNC on port $vnc_port..."
        x11vnc -storepasswd "$VNC_PASSWORD" /tmp/.vnc_passwd_sft 2>/dev/null || true
        x11vnc -display ":$display" -rfbport "$vnc_port" -rfbauth /tmp/.vnc_passwd_sft -bg -quiet -forever 2>/dev/null
    else
        echo "  VNC already on port $vnc_port"
    fi

    # Profile check
    if [ ! -d "/tmp/$profile" ]; then
        echo "  WARNING: Profile /tmp/$profile does not exist!"
        echo "  Create it or copy cookies from an existing profile."
        continue
    fi

    # Write automation user.js
    if [ ! -f "/tmp/$profile/user.js" ]; then
        cat > "/tmp/$profile/user.js" <<'USERJS'
user_pref("gfx.webrender.all", false);
user_pref("layers.acceleration.disabled", true);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("toolkit.cosmeticAnimations.enabled", false);
USERJS
        echo "  Wrote user.js to profile"
    fi

    # Launch Firefox with isolated D-Bus
    if [ "$SKIP_FIREFOX" = "false" ]; then
        pkill -f "firefox.*$profile" 2>/dev/null || true
        sleep 2

        echo "  Starting isolated D-Bus for :$display..."
        eval "$(DISPLAY=:$display dbus-launch --sh-syntax --exit-with-session 2>/dev/null)" || true
        DISPLAY_DBUS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

        DISPLAY=":$display" DBUS_SESSION_BUS_ADDRESS="$DISPLAY_DBUS" /usr/libexec/at-spi2-registryd >/dev/null 2>&1 &
        sleep 2

        echo "  Launching Firefox on :$display..."
        tmux send-keys -t "$tmux_session" \
            "DISPLAY=:$display DBUS_SESSION_BUS_ADDRESS='$DISPLAY_DBUS' LIBGL_ALWAYS_SOFTWARE=1 MOZ_DISABLE_RDD_SANDBOX=1 MOZ_DISABLE_GPU_SANDBOXING=1 GDK_BACKEND=x11 firefox --no-remote --profile /tmp/$profile '$url' &" Enter
        sleep 5

        echo "$DISPLAY_DBUS" > "/tmp/a11y_bus_:${display}"
        echo "  Firefox launched (VNC port $vnc_port)"
    fi

    # Start SFT bot
    if [ "$SKIP_BOTS" = "false" ]; then
        DISPLAY_DBUS="$(cat /tmp/a11y_bus_:${display} 2>/dev/null || echo 'unix:path=/run/user/1000/bus')"
        sleep 2
        echo "  Starting SFT bot ($ROUND)..."
        tmux send-keys -t "$tmux_session" \
            "cd $TAEY_PATH && DISPLAY=:$display DBUS_SESSION_BUS_ADDRESS='$DISPLAY_DBUS' REDIS_HOST=$REDIS_HOST WEAVIATE_URL=http://10.0.0.163:8088 PYTHONPATH=$EMBEDDING_PATH python3 agents/sft_gen_bot.py --round $ROUND --platforms $platform 2>&1 | tee /tmp/sft_${platform}.log" Enter
        echo "  Bot started in tmux: $tmux_session"
    fi
done

echo ""
echo "=== SFT launch complete ==="
echo ""
echo "VNC access (password: $VNC_PASSWORD):"
for display in "${!PLATFORMS[@]}"; do
    IFS='|' read -r platform url tmux_session profile <<< "${PLATFORMS[$display]}"
    vnc_port=$((display + 5900))
    echo "  :$display $platform -> vnc://$(hostname -I | awk '{print $1}'):$vnc_port"
done
echo ""
echo "Monitor: tmux attach -t sft-<platform>"
