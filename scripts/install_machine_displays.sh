#!/usr/bin/env bash
# install_machine_displays.sh — Install systemd user units for taey displays
# from machine.env. Idempotent. Run once per machine (or after machine.env
# changes) to provision Xvfb + Firefox + AT-SPI + x11vnc per platform.
#
# Reads ~/.taey/machine.env (or repo-root/machine.env) for TAEY_DISPLAY_N
# entries in the form: TAEY_DISPLAY_N="platform:profile:url"
#
# For each entry, generates:
#   ~/.config/systemd/user/taey-xvfb@.service       (template, generic)
#   ~/.config/systemd/user/taey-display-N.service   (one per display)
#
# After install, units are daemon-reloaded, enabled, and started.
# VNC port for display :N is 5900+N. Default VNC password is "<TAEY_VNC_PASSWORD>" (the
# canonical Family password) — override via TAEY_VNC_PASSWORD in machine.env.
#
# Usage: ./scripts/install_machine_displays.sh [--no-start] [--no-vnc]
#   --no-start    Generate + enable units but do not start (for staged rollouts)
#   --no-vnc      Generate units without x11vnc (Xvfb + Firefox + AT-SPI only)

set -Eeuo pipefail

NO_START=false
NO_VNC=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-start) NO_START=true; shift ;;
        --no-vnc) NO_VNC=true; shift ;;
        -h|--help) sed -n '1,/^set -Eeuo/p' "$0" | sed -n '/^#/p'; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
FIREFOX_USER_JS_SRC="${REPO_ROOT}/systemd/user/firefox-user.js"

# --- Load machine.env ---
MACHINE_ENV=""
for candidate in "${HOME}/.taey/machine.env" "${REPO_ROOT}/machine.env"; do
    if [[ -f "${candidate}" ]]; then
        MACHINE_ENV="${candidate}"
        break
    fi
done
if [[ -z "${MACHINE_ENV}" ]]; then
    echo "ERROR: No machine.env found (~/.taey/machine.env or ${REPO_ROOT}/machine.env)" >&2
    echo "Copy machine.env.example to ~/.taey/machine.env first." >&2
    exit 1
fi
# shellcheck source=/dev/null
source "${MACHINE_ENV}"

VNC_PASSWORD="${TAEY_VNC_PASSWORD:?set TAEY_VNC_PASSWORD}"

# --- Required tooling ---
require_cmd() {
    command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing command: $1" >&2; exit 1; }
}
require_cmd Xvfb
require_cmd dbus-run-session
require_cmd xprop
require_cmd openbox
$NO_VNC || require_cmd x11vnc

# Firefox binary path — Mira ships it as deb at /usr/lib/firefox/firefox,
# Thor 2 (Tegra aarch64) ships only the snap at
# /snap/firefox/current/usr/lib/firefox/firefox. Detect the actual binary
# rather than the wrapper at /usr/bin/firefox (which on snap systems just
# exec's `snap run firefox` and breaks --profile semantics).
FIREFOX_BIN=""
for cand in /usr/lib/firefox/firefox /snap/firefox/current/usr/lib/firefox/firefox; do
    if [[ -x "${cand}" ]]; then
        FIREFOX_BIN="${cand}"
        break
    fi
done
if [[ -z "${FIREFOX_BIN}" ]]; then
    echo "ERROR: Firefox binary not found at /usr/lib/firefox/firefox or /snap/firefox/current/usr/lib/firefox/firefox" >&2
    echo "Install via 'apt install firefox' (deb) or 'snap install firefox' (snap)." >&2
    exit 1
fi
echo "[install] firefox binary: ${FIREFOX_BIN}"

[[ -e /usr/libexec/at-spi-bus-launcher ]] || { echo "ERROR: at-spi-bus-launcher missing" >&2; exit 1; }
[[ -f "${FIREFOX_USER_JS_SRC}" ]] || { echo "ERROR: ${FIREFOX_USER_JS_SRC} missing" >&2; exit 1; }

mkdir -p "${SYSTEMD_USER_DIR}" "${HOME}/.taey/profiles"

# --- VNC password ---
if ! $NO_VNC; then
    if [[ ! -f "${HOME}/.taey/vnc_passwd" ]]; then
        echo "[install] storing VNC password ('${VNC_PASSWORD}') to ~/.taey/vnc_passwd"
        x11vnc -storepasswd "${VNC_PASSWORD}" "${HOME}/.taey/vnc_passwd" >/dev/null
        chmod 600 "${HOME}/.taey/vnc_passwd"
    fi
fi

# --- Generic Xvfb template unit ---
cat > "${SYSTEMD_USER_DIR}/taey-xvfb@.service" <<'EOF'
[Unit]
Description=Xvfb for display :%i
After=basic.target

[Service]
Type=simple
ExecStartPre=/usr/bin/bash -c 'rm -f /tmp/.X%i-lock /tmp/.X11-unix/X%i /tmp/a11y_bus_:%i /tmp/dbus_session_bus_:%i /tmp/firefox_pid_:%i'
ExecStart=/usr/bin/Xvfb :%i -screen 0 1920x1080x24 -ac -noreset
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
echo "[install] wrote ${SYSTEMD_USER_DIR}/taey-xvfb@.service"

# --- Per-display units from machine.env ---
INSTALLED=()
for var in $(compgen -v | grep -E '^TAEY_DISPLAY_[0-9]+$' | sort -V); do
    display_num="${var#TAEY_DISPLAY_}"
    cfg="${!var}"
    [[ -z "${cfg}" ]] && continue

    # Parse "platform:profile:url" — URL contains colons, so split on first two.
    platform="${cfg%%:*}"
    rest="${cfg#*:}"
    profile="${rest%%:*}"
    url="${rest#*:}"
    if [[ -z "${platform}" || -z "${profile}" || -z "${url}" ]]; then
        echo "ERROR: malformed ${var}='${cfg}' (expected platform:profile:url)" >&2
        exit 1
    fi

    label="${platform^}"
    vnc_port=$((5900 + display_num))
    unit_path="${SYSTEMD_USER_DIR}/taey-display-${display_num}.service"

    if $NO_VNC; then
        vnc_block=""
        stop_kill=""
    else
        vnc_block="/usr/bin/x11vnc -display :${display_num} -rfbport ${vnc_port} -rfbauth \$HOME/.taey/vnc_passwd -forever -shared -bg -o /tmp/x11vnc-${display_num}.log; "
        stop_kill="pkill -f \"x11vnc.*rfbport ${vnc_port}\" 2>/dev/null || true; "
    fi

    cat > "${unit_path}" <<EOF
[Unit]
Description=Taey Display :${display_num} (${label})
After=taey-xvfb@${display_num}.service
Requires=taey-xvfb@${display_num}.service

[Service]
Type=simple
Environment=DISPLAY=:${display_num}
ExecStart=/usr/bin/dbus-run-session -- /usr/bin/bash -lc 'echo "\$DBUS_SESSION_BUS_ADDRESS" > /tmp/dbus_session_bus_:${display_num}; /usr/libexec/at-spi-bus-launcher --launch-immediately & A11Y_ADDR=""; for i in \$(seq 1 20); do TMP_ADDR=\$(xprop -display :${display_num} -root AT_SPI_BUS 2>/dev/null | sed "s/.*= \\"//;s/\\"\$//"); case "\$TMP_ADDR" in unix:path=*|unix:abstract=*) A11Y_ADDR="\$TMP_ADDR"; echo "\$A11Y_ADDR" > /tmp/a11y_bus_:${display_num} && break ;; esac; sleep 1; done; AT_SPI_BUS_ADDRESS="\${A11Y_ADDR}" /usr/libexec/at-spi2-registryd & sleep 1; openbox & sleep 1; ${vnc_block}mkdir -p \$HOME/.taey/profiles/${profile}; cp ${FIREFOX_USER_JS_SRC} \$HOME/.taey/profiles/${profile}/user.js; echo "user_pref(\\"accessibility.force_disabled\\", -1);" >> \$HOME/.taey/profiles/${profile}/user.js; GTK_USE_PORTAL=0 LIBGL_ALWAYS_SOFTWARE=1 GNOME_ACCESSIBILITY=1 GTK_MODULES=gail:atk-bridge AT_SPI_BUS_ADDRESS="\${A11Y_ADDR}" ${FIREFOX_BIN} --no-remote --profile \$HOME/.taey/profiles/${profile} "${url}" & FIREFOX_PID=\$!; ( L_ADDR="\$A11Y_ADDR"; S_CNT=0; for i in \$(seq 1 30); do C_ADDR=\$(xprop -display :${display_num} -root AT_SPI_BUS 2>/dev/null | sed "s/.*= \\"//;s/\\"\$//"); if [[ "\$C_ADDR" == unix:* ]]; then if [[ "\$C_ADDR" != "\$L_ADDR" ]]; then printf "%s\n" "\$C_ADDR" > /tmp/a11y_bus_:${display_num}.tmp && mv /tmp/a11y_bus_:${display_num}.tmp /tmp/a11y_bus_:${display_num}; L_ADDR="\$C_ADDR"; S_CNT=0; else S_CNT=\$((S_CNT + 1)); fi; fi; [[ \$S_CNT -ge 3 ]] && break; sleep 2; done ) & [ -s /tmp/a11y_bus_:${display_num} ] || echo "WARNING: AT-SPI bus capture failed for :${display_num}" >&2; echo "\${FIREFOX_PID}" > /tmp/firefox_pid_:${display_num}; wait \${FIREFOX_PID}'
ExecStopPost=/usr/bin/bash -lc '${stop_kill}rm -f /tmp/a11y_bus_:${display_num} /tmp/dbus_session_bus_:${display_num} /tmp/firefox_pid_:${display_num}'
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
    echo "[install] wrote ${unit_path}  (platform=${platform} profile=${profile} vnc=${vnc_port})"
    INSTALLED+=("taey-display-${display_num}.service")
done

if [[ ${#INSTALLED[@]} -eq 0 ]]; then
    echo "ERROR: no TAEY_DISPLAY_N=... entries in ${MACHINE_ENV}" >&2
    exit 1
fi

# --- Reload + enable + start ---
systemctl --user daemon-reload
echo "[install] daemon-reload done"

for unit in "${INSTALLED[@]}"; do
    systemctl --user enable "${unit}" >/dev/null
done
echo "[install] enabled: ${INSTALLED[*]}"

if $NO_START; then
    echo "[install] --no-start: skipping start (run 'systemctl --user start ${INSTALLED[*]}' when ready)"
    exit 0
fi

systemctl --user restart "${INSTALLED[@]}"
echo "[install] started/restarted ${#INSTALLED[@]} display unit(s)"

# --- Verify ---
sleep 6
echo
echo "=== verification ==="
for unit in "${INSTALLED[@]}"; do
    state=$(systemctl --user is-active "${unit}" 2>/dev/null || echo unknown)
    echo "  ${unit}: ${state}"
done
if ! $NO_VNC; then
    echo
    echo "=== VNC ports ==="
    ss -lntp 2>/dev/null | awk '$4 ~ /:59[0-9][0-9]$/ {print "  "$4"  "$NF}' | sort
fi
echo
echo "Done. To restart one display later: systemctl --user restart taey-display-<N>.service"
echo "VNC password (from TAEY_VNC_PASSWORD): <TAEY_VNC_PASSWORD>"
