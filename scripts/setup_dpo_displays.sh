#!/usr/bin/env bash
# Setup virtual displays for DPO bot: 4 platforms on separate Xvfb displays.
#
# Usage: ./scripts/setup_dpo_displays.sh [--vnc-password PASSWORD] [--skip-firefox]
#
# Creates:
#   :2 → Firefox → chatgpt.com (jesselarose@gmail.com)
#   :3 → Firefox → gemini.google.com (jesselarose@gmail.com)
#   :4 → Firefox → grok.com (jesselarose@gmail.com)
#   :5 → Firefox → claude.ai (kendra.s.larose@gmail.com)
#
# VNC ports: 5902-5905 (password protected)
# Login: cookies copied from active Firefox profile. Use login_bot.py for
#        accounts that need different credentials (Claude = kendra.s.larose@gmail).

set -euo pipefail

VNC_PASSWORD="${VNC_PASSWORD:-thor}"
SKIP_FIREFOX=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --vnc-password) VNC_PASSWORD="$2"; shift 2 ;;
        --skip-firefox) SKIP_FIREFOX=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

RESOLUTION="1920x1080x24"

# 1. Load Universal Config
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [ -f "$REPO_ROOT/.env" ]; then
    source "$REPO_ROOT/.env"
fi

MACHINE=$(hostname)
DISPLAYS_MIRA=${DISPLAYS_MIRA:-"chatgpt:2,claude:3,gemini:4,grok:5,perplexity:6"}
DISPLAYS_THOR=${DISPLAYS_THOR:-"perplexity:4,gemini:6,grok:7,claude:8,perplexity:9,claude:10,chatgpt:11,grok:12,chatgpt:13"}

if [[ "$MACHINE" == *"mira"* ]]; then 
    MAPPINGS=$DISPLAYS_MIRA
elif [[ "$MACHINE" == *"thor"* ]]; then
    MAPPINGS=$DISPLAYS_THOR
else
    MAPPINGS=$DISPLAYS_MIRA
fi

# Resolve mappings into associative array for loop compatibility
declare -A PLATFORMS
IFS=',' read -ra PAIRS <<< "$MAPPINGS"
for pair in "${PAIRS[@]}"; do
    IFS=':' read -r platform disp <<< "$pair"
    case $platform in
        chatgpt)    url="https://chatgpt.com/?temporary-chat=true" ;;
        claude)     url="https://claude.ai/new?incognito" ;;
        gemini)     url="https://gemini.google.com/app" ;;
        grok)       url="https://grok.com/" ;;
        perplexity) url="https://www.perplexity.ai/" ;;
        *)          url="https://google.com" ;;
    esac
    PLATFORMS[$disp]="$platform|$url"
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Find active Firefox profile (for cookie copy)
find_active_profile() {
    local profiles_dir
    for d in ~/.mozilla/firefox ~/.config/mozilla/firefox; do
        if [ -d "$d" ]; then
            profiles_dir="$d"
            break
        fi
    done
    [ -z "$profiles_dir" ] && return 1

    # Parse profiles.ini for Default= or find the one with cookies.sqlite
    local default_profile
    if [ -f "$profiles_dir/profiles.ini" ]; then
        default_profile=$(grep -A5 '^\[Install' "$profiles_dir/profiles.ini" | grep 'Default=' | head -1 | cut -d= -f2)
    fi

    if [ -n "$default_profile" ] && [ -d "$profiles_dir/$default_profile" ]; then
        echo "$profiles_dir/$default_profile"
        return 0
    fi

    # Fallback: find profile dir with newest cookies.sqlite
    find "$profiles_dir" -name cookies.sqlite -printf '%T@ %h\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2
}

ACTIVE_PROFILE=$(find_active_profile)
if [ -z "$ACTIVE_PROFILE" ]; then
    echo "ERROR: No active Firefox profile found"
    exit 1
fi
echo "Active profile: $ACTIVE_PROFILE"

for DISPLAY_NUM in "${!PLATFORMS[@]}"; do
    IFS='|' read -r PLATFORM URL <<< "${PLATFORMS[$DISPLAY_NUM]}"
    echo ""
    echo "=== Setting up :$DISPLAY_NUM for $PLATFORM ==="

    # Kill existing Xvfb on this display
    if [ -f "/tmp/.X${DISPLAY_NUM}-lock" ]; then
        kill "$(cat /tmp/.X${DISPLAY_NUM}-lock 2>/dev/null)" 2>/dev/null || true
        rm -f "/tmp/.X${DISPLAY_NUM}-lock"
        sleep 1
    fi

    # Start Xvfb
    Xvfb ":${DISPLAY_NUM}" -screen 0 "$RESOLUTION" -ac -nolisten tcp &
    sleep 1
    echo "  Xvfb :${DISPLAY_NUM} started (PID $!)"

    # Start VNC
    VNC_PORT=$((5900 + DISPLAY_NUM))
    x11vnc -display ":${DISPLAY_NUM}" -forever -shared -rfbport "$VNC_PORT" \
        -passwd "$VNC_PASSWORD" -bg -o "/tmp/vnc-${PLATFORM}.log" 2>/dev/null
    echo "  VNC on port $VNC_PORT"

    if [ "$SKIP_FIREFOX" = true ]; then
        echo "  Skipping Firefox (--skip-firefox)"
        continue
    fi

    # Copy profile
    PROFILE_DIR="/tmp/ff-profile-${PLATFORM}"
    rm -rf "$PROFILE_DIR"
    mkdir -p "$PROFILE_DIR"

    # Copy essential files for login
    for f in cookies.sqlite cookies.sqlite-wal cookies.sqlite-shm \
             key4.db cert9.db logins.json signedInUser.json \
             storage.sqlite storage-sync-v2.sqlite webappsstore.sqlite \
             permissions.sqlite prefs.js; do
        [ -f "$ACTIVE_PROFILE/$f" ] && cp "$ACTIVE_PROFILE/$f" "$PROFILE_DIR/" 2>/dev/null || true
    done

    # Clean locks from copy
    rm -f "$PROFILE_DIR/lock" "$PROFILE_DIR/.parentlock" 2>/dev/null

    # Start Firefox
    DISPLAY=":${DISPLAY_NUM}" firefox --profile "$PROFILE_DIR" --no-remote "$URL" &
    sleep 3
    echo "  Firefox started for $PLATFORM"
done

echo ""
echo "=== DPO displays ready ==="
echo "VNC access: vncviewer localhost:5902-5905 (password: $VNC_PASSWORD)"
echo ""
echo "To start DPO bot on a single platform:"
echo "  DISPLAY=:2 python3 agents/dpo_bot.py --platforms chatgpt --cycles 1"
echo ""
echo "To start all platforms in parallel tmux sessions:"
for DISPLAY_NUM in "${!PLATFORMS[@]}"; do
    IFS='|' read -r PLATFORM URL <<< "${PLATFORMS[$DISPLAY_NUM]}"
    echo "  tmux new-session -d -s dpo-${PLATFORM} \"DISPLAY=:${DISPLAY_NUM} python3 ${ROOT_DIR}/agents/dpo_bot.py --platforms ${PLATFORM}\""
done
