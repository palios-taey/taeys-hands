#!/usr/bin/env bash
# Runtime entrypoint for generated taey-display-N.service units.

set -Eeuo pipefail

die() {
    echo "ERROR: $*" >&2
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

require_env() {
    local name="$1"
    [[ -n "${!name:-}" ]] || die "${name} must be set by the systemd unit or machine.env"
}

display_num="${1:-}"
[[ "${display_num}" =~ ^[1-9][0-9]*$ ]] || die "display number must be a positive integer"
display=":${display_num}"

for name in \
    DBUS_SESSION_BUS_ADDRESS \
    TAEY_REPO \
    TAEY_FIREFOX_BIN \
    TAEY_AT_SPI_BUS_LAUNCHER \
    TAEY_AT_SPI_REGISTRYD \
    TAEY_USE_SOFTWARE_GL \
    TAEY_PLATFORM \
    TAEY_PROFILE \
    TAEY_URL \
    TAEY_VNC_ENABLED \
    TAEY_VNC_PORT
do
    require_env "${name}"
done

case "${TAEY_USE_SOFTWARE_GL}" in
    0|1) ;;
    *) die "TAEY_USE_SOFTWARE_GL must be 0 or 1" ;;
esac
case "${TAEY_VNC_ENABLED}" in
    0|1) ;;
    *) die "TAEY_VNC_ENABLED must be 0 or 1" ;;
esac
[[ "${TAEY_VNC_PORT}" =~ ^[0-9]+$ ]] || die "TAEY_VNC_PORT must be numeric"
[[ "${TAEY_PROFILE}" != */* && "${TAEY_PROFILE}" != *..* ]] || die "TAEY_PROFILE must be a profile directory name, not a path"
case "${TAEY_URL}" in
    http://*|https://*) ;;
    *) die "TAEY_URL must start with http:// or https://" ;;
esac

require_cmd xprop
require_cmd sed
require_cmd openbox
if [[ "${TAEY_VNC_ENABLED}" == "1" ]]; then
    require_cmd x11vnc
    require_cmd pkill
    [[ -f "${HOME}/.taey/vnc_passwd" ]] || die "${HOME}/.taey/vnc_passwd is missing"
fi

[[ -d "${TAEY_REPO}" ]] || die "TAEY_REPO does not exist: ${TAEY_REPO}"
[[ -x "${TAEY_REPO}/scripts/install_firefox_user_js.sh" ]] || die "missing executable ${TAEY_REPO}/scripts/install_firefox_user_js.sh"
[[ -x "${TAEY_FIREFOX_BIN}" ]] || die "TAEY_FIREFOX_BIN missing or not executable: ${TAEY_FIREFOX_BIN}"
[[ -x "${TAEY_AT_SPI_BUS_LAUNCHER}" ]] || die "TAEY_AT_SPI_BUS_LAUNCHER missing or not executable: ${TAEY_AT_SPI_BUS_LAUNCHER}"
[[ -x "${TAEY_AT_SPI_REGISTRYD}" ]] || die "TAEY_AT_SPI_REGISTRYD missing or not executable: ${TAEY_AT_SPI_REGISTRYD}"

cleanup() {
    local rc=$?
    local pkill_rc=0
    if [[ "${TAEY_VNC_ENABLED}" == "1" ]]; then
        pkill -f "x11vnc.*rfbport ${TAEY_VNC_PORT}" 2>/dev/null || pkill_rc=$?
        if (( pkill_rc > 1 )); then
            echo "ERROR: x11vnc cleanup failed with status ${pkill_rc}" >&2
        fi
    fi
    rm -f "/tmp/dbus_session_bus_${display}" "/tmp/firefox_pid_${display}"
    exit "${rc}"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

echo "${DBUS_SESSION_BUS_ADDRESS}" > "/tmp/dbus_session_bus_${display}"

"${TAEY_AT_SPI_BUS_LAUNCHER}" --launch-immediately &

A11Y_ADDR=""
for _ in {1..20}; do
    tmp_addr="$(xprop -display "${display}" -root AT_SPI_BUS 2>/dev/null | sed 's/.*= "//;s/"$//' || true)"
    case "${tmp_addr}" in
        unix:path=*|unix:abstract=*)
            A11Y_ADDR="${tmp_addr}"
            echo "${A11Y_ADDR}" > "/tmp/a11y_bus_${display}"
            break
            ;;
    esac
    sleep 1
done
[[ -n "${A11Y_ADDR}" ]] || die "AT-SPI bus capture failed for ${display}"

AT_SPI_BUS_ADDRESS="${A11Y_ADDR}" "${TAEY_AT_SPI_REGISTRYD}" &
openbox &
sleep 1

if [[ "${TAEY_VNC_ENABLED}" == "1" ]]; then
    x11vnc \
        -display "${display}" \
        -rfbport "${TAEY_VNC_PORT}" \
        -rfbauth "${HOME}/.taey/vnc_passwd" \
        -forever \
        -shared \
        -bg \
        -o "/tmp/x11vnc-${display_num}.log"
fi

profile_dir="${HOME}/.taey/profiles/${TAEY_PROFILE}"
"${TAEY_REPO}/scripts/install_firefox_user_js.sh" "${profile_dir}"

GTK_USE_PORTAL=0 \
LIBGL_ALWAYS_SOFTWARE="${TAEY_USE_SOFTWARE_GL}" \
GNOME_ACCESSIBILITY=1 \
GTK_MODULES=gail:atk-bridge \
AT_SPI_BUS_ADDRESS="${A11Y_ADDR}" \
"${TAEY_FIREFOX_BIN}" --no-remote --profile "${profile_dir}" "${TAEY_URL}" &

firefox_pid=$!
echo "${firefox_pid}" > "/tmp/firefox_pid_${display}"
wait "${firefox_pid}"
