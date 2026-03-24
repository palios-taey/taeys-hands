#!/usr/bin/env bash
# launch_isolated_display.sh — Launch Firefox on an isolated AT-SPI bus
#
# Each display gets its own dbus-run-session + at-spi-bus-launcher.
# No shared bus = no contention = 100% AT-SPI reliability.
#
# Usage:
#   ./scripts/launch_isolated_display.sh <display> <platform> <profile> <url>
#   ./scripts/launch_isolated_display.sh 5 chatgpt ff-profile-chatgpt2 "https://chatgpt.com/?temporary-chat=true"

set -euo pipefail

DISPLAY_NUM="${1:?Usage: launch_isolated_display.sh <display> <platform> <profile> <url>}"
PLATFORM="${2}"
PROFILE="${3}"
URL="${4}"
RESOLUTION="1920x1080x24"

echo "=== Display :${DISPLAY_NUM} — ${PLATFORM} ==="

# Clean stale Xvfb state
rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}"
pkill -f "Xvfb :${DISPLAY_NUM} " 2>/dev/null || true
sleep 0.3

# Start Xvfb
Xvfb ":${DISPLAY_NUM}" -screen 0 "${RESOLUTION}" -noreset -ac &
retries=20
while ! DISPLAY=":${DISPLAY_NUM}" xdpyinfo >/dev/null 2>&1; do
    sleep 0.3
    retries=$((retries - 1))
    [ $retries -le 0 ] && { echo "ERROR: Xvfb :${DISPLAY_NUM} failed"; exit 1; }
done
echo "  Xvfb :${DISPLAY_NUM} ready"

# Start openbox
DISPLAY=":${DISPLAY_NUM}" openbox --sm-disable &
sleep 0.5

# Launch isolated D-Bus session with its own AT-SPI bus
# This is the key: dbus-run-session creates a fresh session bus
# at-spi-bus-launcher registers on THAT bus, not the shared one
# Firefox registers on THAT bus
# The Python bot reads AT_SPI_BUS from the X11 root window
dbus-run-session -- bash -c "
    export DISPLAY=:${DISPLAY_NUM}

    # Start AT-SPI bus launcher for this display
    /usr/libexec/at-spi-bus-launcher --launch-immediately &
    sleep 1

    # Write the bus address to a file so the Python bot can read it
    A11Y_ADDR=\$(xprop -display :${DISPLAY_NUM} -root AT_SPI_BUS 2>/dev/null \
        | sed 's/.*= \"//' | sed 's/\"\$//')
    echo \"\${A11Y_ADDR}\" > /tmp/a11y_bus_:${DISPLAY_NUM}
    echo \"  AT-SPI bus: \${A11Y_ADDR}\"

    # Firefox profile setup
    mkdir -p /tmp/${PROFILE}
    cat > /tmp/${PROFILE}/user.js <<'USERJS'
user_pref(\"gfx.webrender.all\", false);
user_pref(\"layers.acceleration.disabled\", true);
user_pref(\"browser.sessionstore.resume_from_crash\", false);
user_pref(\"browser.shell.checkDefaultBrowser\", false);
user_pref(\"toolkit.cosmeticAnimations.enabled\", false);
USERJS

    # Launch Firefox on the isolated bus
    # GTK_USE_PORTAL=0 forces GTK embedded file dialog (not portal)
    # Portal dialogs fail on isolated D-Bus sessions
    GTK_USE_PORTAL=0 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    MOZ_DISABLE_RDD_SANDBOX=1 \
    MOZ_DISABLE_GPU_SANDBOXING=1 \
    GDK_BACKEND=x11 \
    firefox --no-remote --profile /tmp/${PROFILE} '${URL}' &
    FIREFOX_PID=\$!
    echo \"  Firefox PID: \${FIREFOX_PID}\"
    echo \"\${FIREFOX_PID}\" > /tmp/firefox_pid_:${DISPLAY_NUM}

    # Keep the session alive as long as Firefox runs
    wait \${FIREFOX_PID}
" &

echo "  Isolated session launched (background)"
echo "  Bus address will be at: /tmp/a11y_bus_:${DISPLAY_NUM}"
echo "  Firefox PID will be at: /tmp/firefox_pid_:${DISPLAY_NUM}"
