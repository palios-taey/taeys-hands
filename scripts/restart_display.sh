#!/bin/bash
# Universal Display & Bot Manager (Thor, Mira, Jetson)
# Usage: ./restart_display.sh <display_number_or_platform> [bot_type]
# Example: ./restart_display.sh 11 sft
# Example: ./restart_display.sh chatgpt none  (Launches display only)

INPUT=$1
BOT_TYPE=${2:-"none"}

if [ -z "$INPUT" ]; then
    echo "Usage: $0 <display_number_or_platform> [bot_type (hmm|sft|consultation|none)]"
    exit 1
fi

# 1. Load Universal Config
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# Source .env if it exists
if [ -f "$REPO_ROOT/.env" ]; then
    source "$REPO_ROOT/.env"
fi

# Defaults if not in .env
REDIS_HOST=${REDIS_HOST:-"127.0.0.1"}
MACHINE=$(hostname)

# 2. Dynamic Display Mapping
# Use the ones from .env or these defaults for standard Mira/Thor deployments
DISPLAYS_MIRA=${DISPLAYS_MIRA:-"chatgpt:2,claude:3,gemini:4,grok:5,perplexity:6"}
DISPLAYS_THOR=${DISPLAYS_THOR:-"perplexity:4,gemini:6,grok:7,claude:8,perplexity:9,claude:10,chatgpt:11,grok:12,chatgpt:13"}

if [[ "$MACHINE" == *"mira"* ]]; then
    MAPPINGS=$DISPLAYS_MIRA
elif [[ "$MACHINE" == *"thor"* ]]; then
    MAPPINGS=$DISPLAYS_THOR
else
    # Fallback if unknown machine
    MAPPINGS=$DISPLAYS_MIRA
fi

# Resolve Platform & Display Num
if [[ "$INPUT" =~ ^[0-9]+$ ]]; then
    DISPLAY_NUM=$INPUT
    PLATFORM=$(echo "$MAPPINGS" | tr ',' '\n' | grep ":${DISPLAY_NUM}$" | cut -d':' -f1)
else
    PLATFORM=$INPUT
    DISPLAY_NUM=$(echo "$MAPPINGS" | tr ',' '\n' | grep "^${PLATFORM}:" | head -n1 | cut -d':' -f2)
fi

if [ -z "$PLATFORM" ] || [ -z "$DISPLAY_NUM" ]; then
    echo "Error: Display/Platform mapping not found for input '$INPUT' on $MACHINE"
    exit 1
fi

DISPLAY_STR=":${DISPLAY_NUM}"

# 3. Standardize Naming (Solves Issue #4)
PROFILE_DIR="/tmp/ff-profile-${MACHINE}-${PLATFORM}-${DISPLAY_NUM}"
TMUX_SESSION="${BOT_TYPE}-${PLATFORM}-${DISPLAY_NUM}"
BUS_FILE="/tmp/a11y_bus_${DISPLAY_STR}"

case $PLATFORM in
    chatgpt)    URL="https://chatgpt.com/?temporary-chat=true" ;;
    claude)     URL="https://claude.ai/new?incognito" ;;
    gemini)     URL="https://gemini.google.com/app" ;;
    grok)       URL="https://grok.com/" ;;
    perplexity) URL="https://www.perplexity.ai/" ;;
    *)          URL="https://google.com" ;;
esac

echo "====================================================="
echo "🚀 Launching $PLATFORM on $DISPLAY_STR ($MACHINE)"
echo "📁 Profile : $PROFILE_DIR"
echo "🖥️ Tmux    : $TMUX_SESSION"
echo "🔌 D-Bus   : $BUS_FILE"
echo "====================================================="

# 4. Total Teardown of Existing Stack for this Display
# Kill any tmux session with the standardized name or the old ones
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
tmux kill-session -t "sft-${PLATFORM}${DISPLAY_NUM}" 2>/dev/null || true
tmux kill-session -t "hmm-${PLATFORM}" 2>/dev/null || true

# Kill Xvfb and VNC for this display
pkill -f "Xvfb $DISPLAY_STR " 2>/dev/null || true
pkill -f "x11vnc.*$DISPLAY_STR" 2>/dev/null || true
# Kill Firefox on this profile
pkill -f "firefox.*$PROFILE_DIR" 2>/dev/null || true
# Kill any other Firefox on this display
pkill -f "firefox.*display=$DISPLAY_STR" 2>/dev/null || true

if [ -f "$BUS_FILE" ]; then
    # Kill the isolated dbus daemon for this display to prevent zombies
    # Attempt to read PID from file if it was stored by a previous run
    BUS_PID=$(grep -oP 'DBUS_SESSION_BUS_PID=\K[0-9]+' "$BUS_FILE" 2>/dev/null)
    [ -n "$BUS_PID" ] && kill -9 "$BUS_PID" 2>/dev/null || true
    rm -f "$BUS_FILE"
fi

# Clear X locks
rm -f /tmp/.X${DISPLAY_NUM}-lock /tmp/.X11-unix/X${DISPLAY_NUM}
fuser -k -9 "${DISPLAY_NUM}/tcp" 2>/dev/null || true
sleep 2

# 5. Initialize Profile
if [ ! -d "$PROFILE_DIR" ]; then
    mkdir -p "$PROFILE_DIR"
    echo 'user_pref("toolkit.accessibility.enabled", true);' > "$PROFILE_DIR/user.js"
    echo 'user_pref("dom.disable_open_during_load", false);' >> "$PROFILE_DIR/user.js"
    echo 'user_pref("gfx.webrender.all", false);' >> "$PROFILE_DIR/user.js"
    echo 'user_pref("layers.acceleration.disabled", true);' >> "$PROFILE_DIR/user.js"
fi

# 6. Start Xvfb & VNC
Xvfb "$DISPLAY_STR" -screen 0 1920x1080x24 > /dev/null 2>&1 &
sleep 2

VNC_PORT=$((5900 + DISPLAY_NUM))
x11vnc -display "$DISPLAY_STR" -bg -nopw -listen localhost -xkb -rfbport $VNC_PORT -forever > /dev/null 2>&1

# 7. True D-Bus Isolation (Solves Issue #3)
export DISPLAY="$DISPLAY_STR"
# We use dbus-launch but we want to capture its output to write to BUS_FILE
DBUS_OUTPUT=$(dbus-launch --sh-syntax)
eval "$DBUS_OUTPUT"

echo "$DBUS_OUTPUT" > "$BUS_FILE"
export AT_SPI_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS

# Start AT-SPI helpers on the isolated bus
if [ -x /usr/libexec/at-spi-bus-launcher ]; then
    /usr/libexec/at-spi-bus-launcher &
fi
if [ -x /usr/libexec/at-spi2-registryd ]; then
    /usr/libexec/at-spi2-registryd &
fi
sleep 2

# 8. Start Firefox
export MOZ_DISABLE_WAYLAND=1
export GTK_USE_PORTAL=0
export LIBGL_ALWAYS_SOFTWARE=1
export MOZ_DISABLE_RDD_SANDBOX=1
export MOZ_DISABLE_GPU_SANDBOXING=1
export GDK_BACKEND=x11

firefox --profile "$PROFILE_DIR" --new-instance "$URL" > /dev/null 2>&1 &
FIREFOX_PID=$!
echo "export FIREFOX_PID=$FIREFOX_PID" >> "$BUS_FILE"
sleep 5

# 9. Launch Bot (if requested)
if [ "$BOT_TYPE" != "none" ]; then
    echo "🤖 Spawning $BOT_TYPE bot in tmux..."
    tmux new-session -d -s "$TMUX_SESSION"
    
    # Send env vars to tmux
    tmux send-keys -t "$TMUX_SESSION" "export DISPLAY=$DISPLAY_STR" C-m
    tmux send-keys -t "$TMUX_SESSION" "export DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS" C-m
    tmux send-keys -t "$TMUX_SESSION" "export REDIS_HOST=$REDIS_HOST" C-m
    tmux send-keys -t "$TMUX_SESSION" "export TAEY_NOTIFY_NODE=taeys-hands" C-m
    tmux send-keys -t "$TMUX_SESSION" "export PYTHONPATH=$REPO_ROOT:$HOME/embedding-server" C-m
    
    if [ "$BOT_TYPE" == "hmm" ]; then
        tmux send-keys -t "$TMUX_SESSION" "python3 agents/hmm_bot.py --platforms $PLATFORM --cycles 0" C-m
    elif [ "$BOT_TYPE" == "sft" ]; then
        tmux send-keys -t "$TMUX_SESSION" "python3 agents/sft_gen_bot.py --round all --platforms $PLATFORM" C-m
    elif [ "$BOT_TYPE" == "consultation" ]; then
        tmux send-keys -t "$TMUX_SESSION" "python3 scripts/consultation.py --platform $PLATFORM" C-m
    fi
    echo "✅ Bot launched in tmux: $TMUX_SESSION"
else
    echo "✅ Display active and isolated (No background bot)."
fi
