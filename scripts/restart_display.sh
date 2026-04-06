#!/usr/bin/env bash

set -Eeuo pipefail

DISPLAY_NUM="${1:-}"

if [[ -z "${DISPLAY_NUM}" || ! "${DISPLAY_NUM}" =~ ^[0-9]+$ ]]; then
    echo "Usage: $0 <display_number>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DISPLAY_STR=":${DISPLAY_NUM}"
BOT_TYPE="${2:-sft}"  # hmm, sft, dpo, or "none" to skip bot launch

# --- Load machine.env (single source of truth) ---
MACHINE_ENV=""
for candidate in "${HOME}/.taey/machine.env" "${REPO_ROOT}/machine.env"; do
    if [[ -f "${candidate}" ]]; then
        MACHINE_ENV="${candidate}"
        break
    fi
done

if [[ -z "${MACHINE_ENV}" ]]; then
    echo "ERROR: No machine.env found. Checked ~/.taey/machine.env and ${REPO_ROOT}/machine.env" >&2
    echo "Copy machine.env.example to ~/.taey/machine.env and customize." >&2
    exit 1
fi

# shellcheck source=/dev/null
source "${MACHINE_ENV}"

# Parse TAEY_DISPLAY_{N} → platform:profile:url
DISPLAY_VAR="TAEY_DISPLAY_${DISPLAY_NUM}"
DISPLAY_CONFIG="${!DISPLAY_VAR:-}"

if [[ -z "${DISPLAY_CONFIG}" ]]; then
    echo "ERROR: No mapping for display ${DISPLAY_STR} in ${MACHINE_ENV}" >&2
    echo "Expected: ${DISPLAY_VAR}=\"platform:profile:url\"" >&2
    exit 1
fi

# Split on first two colons only (URL contains colons)
PLATFORM="${DISPLAY_CONFIG%%:*}"
_remainder="${DISPLAY_CONFIG#*:}"
PROFILE="${_remainder%%:*}"
URL="${_remainder#*:}"

if [[ -z "${PLATFORM}" || -z "${URL}" || -z "${PROFILE}" ]]; then
    echo "ERROR: Malformed ${DISPLAY_VAR}='${DISPLAY_CONFIG}'" >&2
    echo "Expected format: platform:profile:url" >&2
    exit 1
fi

# Use machine-env Redis host, fall back to localhost
REDIS_HOST="${TAEY_REDIS_HOST:-127.0.0.1}"
export REDIS_HOST

SESSION_NAME="${BOT_TYPE}-${PLATFORM}"
BOT_PID_FILE="/tmp/${SESSION_NAME}.pid"
BOT_LOG_FILE="/tmp/${SESSION_NAME}.log"
FIREFOX_PID_FILE="/tmp/firefox_pid_${DISPLAY_STR}"
A11Y_BUS_FILE="/tmp/a11y_bus_${DISPLAY_STR}"
REGISTRY_LOG_FILE="/tmp/atspi2-registryd_${DISPLAY_NUM}.log"
FIREFOX_LOG_FILE="/tmp/firefox_${DISPLAY_NUM}.log"
ATSPI_REGISTRYD_PID=""
FIREFOX_PID=""
RESTART_PHASE="idle"

log() {
    printf '[restart:%s] %s\n' "${DISPLAY_STR}" "$*"
}

fail() {
    printf '[restart:%s] ERROR: %s\n' "${DISPLAY_STR}" "$*" >&2
    exit 1
}

rollback_partial_restart() {
    [[ "${RESTART_PHASE}" == "idle" || "${RESTART_PHASE}" == "complete" ]] && return 0

    log "Rolling back partial restart state"
    [[ -n "${FIREFOX_PID}" ]] && kill -TERM "${FIREFOX_PID}" 2>/dev/null || true
    [[ -n "${ATSPI_REGISTRYD_PID}" ]] && kill -TERM "${ATSPI_REGISTRYD_PID}" 2>/dev/null || true
    [[ -n "${DBUS_SESSION_BUS_PID:-}" ]] && kill -TERM "${DBUS_SESSION_BUS_PID}" 2>/dev/null || true
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

ATSPI_REGISTRYD_CMD=""
resolve_atspi_registryd() {
    if command -v at-spi2-registryd >/dev/null 2>&1; then
        ATSPI_REGISTRYD_CMD="$(command -v at-spi2-registryd)"
        return 0
    fi
    if [[ -x /usr/libexec/at-spi2-registryd ]]; then
        ATSPI_REGISTRYD_CMD="/usr/libexec/at-spi2-registryd"
        return 0
    fi
    fail "Could not locate at-spi2-registryd"
}

declare -a TARGET_PIDS=()
declare -a DBUS_PATHS=()

append_unique() {
    local value="$1"
    shift
    local existing
    for existing in "$@"; do
        [[ "${existing}" == "${value}" ]] && return 0
    done
    return 1
}

collect_display_processes() {
    TARGET_PIDS=()
    DBUS_PATHS=()

    local proc_entry pid env_file cmdline env_text dbus_addr dbus_path
    for proc_entry in /proc/[0-9]*; do
        pid="${proc_entry##*/}"
        env_file="${proc_entry}/environ"
        [[ -r "${env_file}" ]] || continue

        env_text="$(tr '\0' '\n' < "${env_file}" 2>/dev/null || true)"
        [[ "${env_text}" == *"DISPLAY=${DISPLAY_STR}"* ]] || continue

        cmdline="$(tr '\0' ' ' < "${proc_entry}/cmdline" 2>/dev/null || true)"
        [[ -n "${cmdline}" ]] || continue

        if [[ "${cmdline}" =~ (python|firefox|at-spi2-registryd|at-spi-bus-launcher|dbus-daemon|dbus-launch) ]]; then
            TARGET_PIDS+=("${pid}")
        fi

        dbus_addr="$(printf '%s\n' "${env_text}" | awk -F= '$1 == "DBUS_SESSION_BUS_ADDRESS" {print $2; exit}')"
        if [[ "${dbus_addr}" =~ ^unix:path=(/tmp/dbus-[^,]+) ]]; then
            dbus_path="${BASH_REMATCH[1]}"
            if ! append_unique "${dbus_path}" "${DBUS_PATHS[@]:-}"; then
                DBUS_PATHS+=("${dbus_path}")
            fi
        fi
    done
}

terminate_collected_processes() {
    if [[ ${#TARGET_PIDS[@]} -eq 0 ]]; then
        log "No display-bound bot/firefox/AT-SPI/D-Bus processes found"
        return 0
    fi

    log "Sending SIGTERM to PIDs: ${TARGET_PIDS[*]}"
    kill -TERM "${TARGET_PIDS[@]}" 2>/dev/null || true

    sleep 5

    local -a survivors=()
    local pid
    for pid in "${TARGET_PIDS[@]}"; do
        if kill -0 "${pid}" 2>/dev/null; then
            survivors+=("${pid}")
        fi
    done

    if [[ ${#survivors[@]} -gt 0 ]]; then
        log "Sending SIGKILL to stubborn PIDs: ${survivors[*]}"
        kill -KILL "${survivors[@]}" 2>/dev/null || true
        sleep 1
    fi
}

cleanup_pid_files() {
    log "Cleaning lock files and display-scoped temp state"
    rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}" "${FIREFOX_PID_FILE}" "${A11Y_BUS_FILE}" "${BOT_PID_FILE}"

    local dbus_path
    for dbus_path in "${DBUS_PATHS[@]:-}"; do
        [[ "${dbus_path}" == /tmp/dbus-* ]] || continue
        rm -f -- "${dbus_path}"
        compgen -G "${dbus_path},*" >/dev/null && rm -f -- "${dbus_path}",*
    done

    rm -f "/tmp/bot_pid_${DISPLAY_STR}" "/tmp/hmm_bot_${DISPLAY_NUM}.pid" "/tmp/sft_gen_bot_${DISPLAY_NUM}.pid"
}

kill_old_tmux_session() {
    if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
        log "Removing existing tmux session ${SESSION_NAME}"
        tmux kill-session -t "${SESSION_NAME}" 2>/dev/null || true
    fi
}

start_dbus_session() {
    log "Starting D-Bus session"
    local dbus_output
    dbus_output="$(dbus-launch --sh-syntax --exit-with-session)" || fail "dbus-launch failed"
    eval "${dbus_output}"
    export DBUS_SESSION_BUS_ADDRESS DBUS_SESSION_BUS_PID

    [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]] || fail "dbus-launch did not export DBUS_SESSION_BUS_ADDRESS"
    log "D-Bus session ready: ${DBUS_SESSION_BUS_ADDRESS}"
}

start_registryd() {
    log "Waiting 3s before starting at-spi2-registryd"
    sleep 3

    log "Starting at-spi2-registryd"
    "${ATSPI_REGISTRYD_CMD}" >"${REGISTRY_LOG_FILE}" 2>&1 &
    ATSPI_REGISTRYD_PID=$!
    export ATSPI_REGISTRYD_PID

    log "Waiting 3s for registryd to stabilize"
    sleep 3

    if ! kill -0 "${ATSPI_REGISTRYD_PID}" 2>/dev/null; then
        fail "at-spi2-registryd failed to stay running"
    fi
    log "Verified at-spi2-registryd is running (PID ${ATSPI_REGISTRYD_PID})"
}

start_firefox() {
    mkdir -p "/tmp/${PROFILE}"

    log "Starting Firefox on ${DISPLAY_STR}"
    GTK_USE_PORTAL=0 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    MOZ_DISABLE_RDD_SANDBOX=1 \
    MOZ_DISABLE_GPU_SANDBOXING=1 \
    GDK_BACKEND=x11 \
    firefox --display="${DISPLAY_STR}" --no-remote --profile "/tmp/${PROFILE}" "${URL}" >"${FIREFOX_LOG_FILE}" 2>&1 &
    FIREFOX_PID=$!
    export FIREFOX_PID
    printf '%s\n' "${FIREFOX_PID}" > "${FIREFOX_PID_FILE}"

    log "Waiting 10s for Firefox initialization"
    sleep 10

    if ! kill -0 "${FIREFOX_PID}" 2>/dev/null; then
        fail "Firefox exited during initialization"
    fi

    local a11y_addr=""
    a11y_addr="$(xprop -display "${DISPLAY_STR}" -root AT_SPI_BUS 2>/dev/null | sed 's/.*= "//;s/"$//' || true)"
    if [[ -n "${a11y_addr}" ]]; then
        printf '%s\n' "${a11y_addr}" > "${A11Y_BUS_FILE}"
        export AT_SPI_BUS_ADDRESS="${a11y_addr}"
        log "Recorded AT-SPI bus: ${a11y_addr}"
    fi
}

verify_firefox_atspi() {
    log "Verifying AT-SPI can see Firefox"
    DISPLAY="${DISPLAY_STR}" \
    DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS}" \
    AT_SPI_BUS_ADDRESS="${AT_SPI_BUS_ADDRESS:-}" \
    python3 - <<'PY'
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

Atspi.init()
desktop = Atspi.get_desktop(0)
apps = [
    desktop.get_child_at_index(i).get_name()
    for i in range(desktop.get_child_count())
]
assert any('Firefox' in (app or '') for app in apps), apps
PY
}

start_bot() {
    if [[ "${BOT_TYPE}" == "none" ]]; then
        log "Bot launch skipped (bot_type=none). Display ready for manual use."
        return 0
    fi

    log "Starting ${BOT_TYPE} bot for ${PLATFORM} in tmux session ${SESSION_NAME}"

    local bot_script="agents/sft_gen_bot.py"
    local bot_args="--round all --platforms '${PLATFORM}'"
    if [[ "${BOT_TYPE}" == "hmm" ]]; then
        bot_script="agents/hmm_bot.py"
        bot_args="--platforms '${PLATFORM}' --cycles 0"
    fi

    local bot_cmd
    bot_cmd="cd '${REPO_ROOT}' && env DISPLAY='${DISPLAY_STR}' DBUS_SESSION_BUS_ADDRESS='${DBUS_SESSION_BUS_ADDRESS}' TAEY_NOTIFY_NODE='taeys-hands' REDIS_HOST='${REDIS_HOST}' WEAVIATE_URL='http://10.0.0.163:8088' PYTHONPATH='${HOME}/embedding-server' python3 ${bot_script} ${bot_args} 2>&1 | tee '${BOT_LOG_FILE}'"

    tmux new-session -d -s "${SESSION_NAME}" "${bot_cmd}" || fail "Failed to start tmux session ${SESSION_NAME}"

    sleep 2
    tmux has-session -t "${SESSION_NAME}" 2>/dev/null || fail "tmux session ${SESSION_NAME} did not stay up"

    local bot_pid=""
    bot_pid="$(pgrep -n -f "DISPLAY=${DISPLAY_STR} .*${bot_script}.*${PLATFORM}" || true)"
    if [[ -n "${bot_pid}" ]]; then
        printf '%s\n' "${bot_pid}" > "${BOT_PID_FILE}"
        log "Bot running with PID ${bot_pid}"
    else
        log "Bot session started; PID discovery skipped"
    fi
}

main() {
    trap rollback_partial_restart ERR

    require_cmd dbus-launch
    require_cmd firefox
    require_cmd python3
    require_cmd tmux
    require_cmd xprop
    resolve_atspi_registryd

    log "Restarting display environment for ${PLATFORM} on ${DISPLAY_STR}"
    collect_display_processes
    kill_old_tmux_session
    terminate_collected_processes
    cleanup_pid_files

    export DISPLAY="${DISPLAY_STR}"
    RESTART_PHASE="dbus"
    start_dbus_session
    RESTART_PHASE="registryd"
    start_registryd
    RESTART_PHASE="firefox"
    start_firefox
    RESTART_PHASE="verify"
    verify_firefox_atspi || fail "AT-SPI verification failed for Firefox"
    log "AT-SPI verification passed"
    RESTART_PHASE="bot"
    start_bot
    RESTART_PHASE="complete"
    trap - ERR
    log "Restart complete"
}

main "$@"
