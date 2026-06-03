#!/usr/bin/env bash
# launch_isolated_display.sh — launch ONE display with Firefox on an isolated
# AT-SPI bus, using the full production recipe (the same recipe the
# taey-display-N.service systemd units run). Use this instead of hand-crafting
# units or one-off launch commands.
#
# Recipe (hardened, matches the systemd unit — #100 isolation + #164 bus capture):
#   - own Xvfb (started if the display isn't already up)
#   - own dbus-run-session  -> isolated session bus (no shared-bus contention)
#   - at-spi-bus-launcher + at-spi2-registryd on that bus
#   - DETERMINISTIC AT-SPI bus capture to /tmp/a11y_bus_:N (retry loop, NOT a
#     single sleep) + a background re-capture loop (the bus address can change
#     after Firefox attaches)
#   - Firefox profile gets accessibility.force_disabled=-1 (REQUIRED — without
#     it Firefox never builds the a11y tree) plus the repo firefox-user.js
#   - AT_SPI_BUS_ADDRESS exported to Firefox; real /usr/lib/firefox/firefox
#   - x11vnc on 59NN (best-effort, only if ~/.taey/vnc_passwd exists)
#
# Usage:
#   ./scripts/launch_isolated_display.sh <display> <platform> <profile> <url>
#   ./scripts/launch_isolated_display.sh 17 dashboard ff-profile-dashboard "http://localhost:5002/ui"
#
# Reads bus from:  /tmp/a11y_bus_:<display>   (consumers: core.atspi via gi/Atspi)
# Firefox pid at:  /tmp/firefox_pid_:<display>

set -uo pipefail

DISPLAY_NUM="${1:?Usage: launch_isolated_display.sh <display> <platform> <profile> <url>}"
PLATFORM="${2:?missing platform}"
PROFILE="${3:?missing profile}"
URL="${4:?missing url}"
RESOLUTION="1920x1080x24"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export TAEY_D="${DISPLAY_NUM}"
export TAEY_PROFILE_DIR="${HOME}/.taey/profiles/${PROFILE}"
export TAEY_URL="${URL}"
export TAEY_VNC="$((5900 + DISPLAY_NUM))"
export TAEY_USERJS="${TAEY_REPO:-$REPO}/systemd/user/firefox-user.js"
export FIREFOX_BIN="${FIREFOX_BIN:-/usr/lib/firefox/firefox}"

echo "=== launch_isolated_display :${DISPLAY_NUM} (${PLATFORM}) -> ${URL} ==="

# 1. Xvfb — start only if the display isn't already up (don't clobber a live one)
if ! DISPLAY=":${DISPLAY_NUM}" xdpyinfo >/dev/null 2>&1; then
    rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}"
    Xvfb ":${DISPLAY_NUM}" -screen 0 "${RESOLUTION}" -ac -noreset >/dev/null 2>&1 &
    for _ in $(seq 1 20); do DISPLAY=":${DISPLAY_NUM}" xdpyinfo >/dev/null 2>&1 && break; sleep 0.3; done
    DISPLAY=":${DISPLAY_NUM}" xdpyinfo >/dev/null 2>&1 || { echo "ERROR: Xvfb :${DISPLAY_NUM} failed"; exit 1; }
    echo "  Xvfb :${DISPLAY_NUM} started"
else
    echo "  Xvfb :${DISPLAY_NUM} already up — reusing"
fi

# 2. The isolated session (runs under its own dbus-run-session). Defined as an
#    exported function so we avoid fragile nested-quoting in a bash -c string.
_taey_session() {
    D=":${TAEY_D}"
    export DISPLAY="$D"
    echo "$DBUS_SESSION_BUS_ADDRESS" > "/tmp/dbus_session_bus_:${TAEY_D}"

    /usr/libexec/at-spi-bus-launcher --launch-immediately &

    # deterministic bus capture (retry loop — the launcher publishes AT_SPI_BUS
    # to the X root asynchronously; a single sleep races and loses)
    A=""
    for _ in $(seq 1 20); do
        T=$(xprop -display "$D" -root AT_SPI_BUS 2>/dev/null | sed 's/.*= "//; s/"$//')
        case "$T" in
            unix:path=*|unix:abstract=*) A="$T"; printf '%s\n' "$A" > "/tmp/a11y_bus_:${TAEY_D}"; break ;;
        esac
        sleep 1
    done

    AT_SPI_BUS_ADDRESS="$A" /usr/libexec/at-spi2-registryd &
    sleep 1
    openbox &
    sleep 1

    if [ -f "${HOME}/.taey/vnc_passwd" ]; then
        x11vnc -display "$D" -rfbport "${TAEY_VNC}" -rfbauth "${HOME}/.taey/vnc_passwd" \
            -forever -shared -bg -o "/tmp/x11vnc-${TAEY_D}.log" >/dev/null 2>&1 || true
    fi

    # profile + REQUIRED accessibility pref
    mkdir -p "${TAEY_PROFILE_DIR}"
    if [ -f "${TAEY_USERJS}" ]; then cp "${TAEY_USERJS}" "${TAEY_PROFILE_DIR}/user.js"; else : > "${TAEY_PROFILE_DIR}/user.js"; fi
    printf '%s\n' 'user_pref("accessibility.force_disabled", -1);' >> "${TAEY_PROFILE_DIR}/user.js"

    GTK_USE_PORTAL=0 LIBGL_ALWAYS_SOFTWARE=1 GNOME_ACCESSIBILITY=1 GTK_MODULES=gail:atk-bridge \
        AT_SPI_BUS_ADDRESS="$A" \
        "${FIREFOX_BIN}" --no-remote --profile "${TAEY_PROFILE_DIR}" "${TAEY_URL}" &
    FF=$!
    printf '%s\n' "$FF" > "/tmp/firefox_pid_:${TAEY_D}"

    # #164 background re-capture — AT_SPI_BUS can change once Firefox attaches
    (
        L="$A"; S=0
        for _ in $(seq 1 30); do
            C=$(xprop -display "$D" -root AT_SPI_BUS 2>/dev/null | sed 's/.*= "//; s/"$//')
            if [[ "$C" == unix:* ]]; then
                if [[ "$C" != "$L" ]]; then
                    printf '%s\n' "$C" > "/tmp/a11y_bus_:${TAEY_D}.tmp" && mv "/tmp/a11y_bus_:${TAEY_D}.tmp" "/tmp/a11y_bus_:${TAEY_D}"
                    L="$C"; S=0
                else
                    S=$((S + 1))
                fi
            fi
            [[ $S -ge 3 ]] && break
            sleep 2
        done
    ) &

    [ -s "/tmp/a11y_bus_:${TAEY_D}" ] || echo "WARNING: AT-SPI bus capture failed for $D" >&2
    wait "$FF"
}
export -f _taey_session

dbus-run-session -- bash -c '_taey_session' &

echo "  launched (background). bus -> /tmp/a11y_bus_:${DISPLAY_NUM} | ffpid -> /tmp/firefox_pid_:${DISPLAY_NUM} | vnc ${TAEY_VNC}"
echo "  drive with: DISPLAY=:${DISPLAY_NUM} AT_SPI_BUS_ADDRESS=\$(cat /tmp/a11y_bus_:${DISPLAY_NUM}) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus"
