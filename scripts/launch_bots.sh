#!/usr/bin/env bash
# launch_bots.sh — Launch one hmm_bot per platform and report bot deaths.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

REDIS_HOST="${REDIS_HOST:-192.168.100.10}"
REDIS_PORT="${REDIS_PORT:-6379}"
NOTIFY_INBOX="${NOTIFY_INBOX:-taey:taeys-hands:inbox}"
BOT_NOTIFY_FROM="${BOT_NOTIFY_FROM:-bot-launcher}"
AUTO_RESTART="${AUTO_RESTART:-0}"
RESTART_BASE_DELAY="${RESTART_BASE_DELAY:-1}"
RESTART_MAX_DELAY="${RESTART_MAX_DELAY:-60}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BOT_SCRIPT="${BOT_SCRIPT:-agents/sft_gen_bot.py}"
BOT_ROUND="${BOT_ROUND:-all}"

declare -a PLATFORMS=()
declare -A DISPLAY_BY_PLATFORM=()
declare -A BOT_PID=()
declare -A RESTART_DELAY=()
declare -A RESTART_PENDING=()
declare -A RESTART_AT=()

HANDLING_SIGCHLD=0
NEEDS_REAP=0

log() {
    printf '[%(%Y-%m-%d %H:%M:%S)T] %s\n' -1 "$*" >&2
}

read_platform_displays_raw() {
    if [[ -n "${PLATFORM_DISPLAYS:-}" ]]; then
        printf '%s\n' "${PLATFORM_DISPLAYS}"
        return 0
    fi

    if [[ -f "${ENV_FILE}" ]]; then
        local line
        while IFS= read -r line; do
            line="${line#"${line%%[![:space:]]*}"}"
            [[ -z "${line}" || "${line}" == \#* ]] && continue
            if [[ "${line}" == PLATFORM_DISPLAYS=* ]]; then
                printf '%s\n' "${line#PLATFORM_DISPLAYS=}"
                return 0
            fi
        done < "${ENV_FILE}"
    fi

    return 1
}

parse_platform_displays() {
    local raw
    raw="$(read_platform_displays_raw)" || {
        log "PLATFORM_DISPLAYS is not set and ${ENV_FILE} has no PLATFORM_DISPLAYS entry"
        return 1
    }

    local pair platform display
    IFS=',' read -r -a pairs <<< "${raw}"
    for pair in "${pairs[@]}"; do
        pair="${pair//[[:space:]]/}"
        [[ -z "${pair}" ]] && continue
        if [[ "${pair}" != *:* ]]; then
            log "Skipping malformed PLATFORM_DISPLAYS entry: ${pair}"
            continue
        fi

        platform="${pair%%:*}"
        display="${pair#*:}"
        [[ -z "${platform}" || -z "${display}" ]] && {
            log "Skipping malformed PLATFORM_DISPLAYS entry: ${pair}"
            continue
        }
        [[ "${display}" != :* ]] && display=":${display}"

        PLATFORMS+=("${platform}")
        DISPLAY_BY_PLATFORM["${platform}"]="${display}"
        RESTART_DELAY["${platform}"]="${RESTART_BASE_DELAY}"
        RESTART_PENDING["${platform}"]=0
        RESTART_AT["${platform}"]=0
    done

    if [[ "${#PLATFORMS[@]}" -eq 0 ]]; then
        log "No valid platform/display mappings found"
        return 1
    fi
}

bus_file_for_display() {
    local display="$1"
    printf '/tmp/a11y_bus_%s\n' "${display}"
}

notify_bot_death() {
    local platform="$1"
    local exit_code="$2"
    local payload

    payload="$(
        "${PYTHON_BIN}" - "${platform}" "${exit_code}" "${BOT_NOTIFY_FROM}" <<'PY'
import json
import sys

platform, exit_code, from_node = sys.argv[1:4]
print(json.dumps({
    "from": from_node,
    "type": "bot_death",
    "body": f"Bot {platform} died with exit code {exit_code}",
}))
PY
    )"

    if redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" \
        LPUSH "${NOTIFY_INBOX}" "${payload}" >/dev/null; then
        log "Notified conductor about ${platform} death (exit ${exit_code})"
    else
        log "Failed to notify conductor about ${platform} death (exit ${exit_code})"
    fi
}

launch_bot() {
    local platform="$1"
    local display="${DISPLAY_BY_PLATFORM[${platform}]}"
    local bus_file bus

    bus_file="$(bus_file_for_display "${display}")"
    if [[ ! -r "${bus_file}" ]]; then
        log "Cannot launch ${platform}: missing bus file ${bus_file}"
        return 1
    fi

    bus="$(<"${bus_file}")"
    if [[ -z "${bus}" ]]; then
        log "Cannot launch ${platform}: empty bus file ${bus_file}"
        return 1
    fi

    (
        cd "${REPO_ROOT}"
        exec env \
            DISPLAY="${display}" \
            DBUS_SESSION_BUS_ADDRESS="${bus}" \
            AT_SPI_BUS_ADDRESS="${bus}" \
            TAEY_NOTIFY_NODE="taeys-hands" \
            "${PYTHON_BIN}" "${BOT_SCRIPT}" --round "${BOT_ROUND}" --platforms "${platform}"
    ) &

    BOT_PID["${platform}"]=$!
    RESTART_PENDING["${platform}"]=0
    RESTART_AT["${platform}"]=0
    log "Launched ${platform} on ${display} (pid ${BOT_PID[${platform}]})"
}

schedule_restart() {
    local platform="$1"
    local delay="${RESTART_DELAY[${platform}]}"
    local now

    if [[ "${RESTART_PENDING[${platform}]}" == "1" ]]; then
        return 0
    fi

    now="$(date +%s)"
    RESTART_PENDING["${platform}"]=1
    RESTART_AT["${platform}"]=$((now + delay))

    log "Scheduling restart for ${platform} in ${delay}s"

    if (( delay < RESTART_MAX_DELAY )); then
        delay=$((delay * 2))
        if (( delay > RESTART_MAX_DELAY )); then
            delay="${RESTART_MAX_DELAY}"
        fi
    fi
    RESTART_DELAY["${platform}"]="${delay}"
}

process_restarts() {
    local platform now
    now="$(date +%s)"

    for platform in "${PLATFORMS[@]}"; do
        [[ "${RESTART_PENDING[${platform}]}" == "1" ]] || continue
        (( now >= RESTART_AT["${platform}"] )) || continue

        if launch_bot "${platform}"; then
            continue
        fi

        RESTART_PENDING["${platform}"]=0
        schedule_restart "${platform}"
    done
}

mark_sigchld() {
    NEEDS_REAP=1
}

reap_dead_bots() {
    local platform pid exit_code

    [[ "${NEEDS_REAP}" == "1" ]] || return 0

    if [[ "${HANDLING_SIGCHLD}" == "1" ]]; then
        return 0
    fi
    HANDLING_SIGCHLD=1
    NEEDS_REAP=0

    for platform in "${PLATFORMS[@]}"; do
        pid="${BOT_PID[${platform}]:-}"
        [[ -z "${pid}" ]] && continue

        if kill -0 "${pid}" 2>/dev/null; then
            continue
        fi

        set +e
        wait "${pid}"
        exit_code=$?
        set -e

        if [[ "${exit_code}" == "127" ]]; then
            continue
        fi

        BOT_PID["${platform}"]=""
        notify_bot_death "${platform}" "${exit_code}"

        if [[ "${AUTO_RESTART}" == "1" ]]; then
            schedule_restart "${platform}"
        else
            log "${platform} exited and auto-restart is disabled"
        fi
    done

    HANDLING_SIGCHLD=0
}

cleanup() {
    trap - EXIT INT TERM CHLD

    local platform pid
    for platform in "${PLATFORMS[@]}"; do
        pid="${BOT_PID[${platform}]:-}"
        [[ -z "${pid}" ]] && continue
        kill "${pid}" 2>/dev/null || true
    done

    for pid in $(jobs -pr); do
        kill "${pid}" 2>/dev/null || true
    done

    wait || true
}

main() {
    parse_platform_displays

    trap 'mark_sigchld' CHLD
    trap 'cleanup' EXIT INT TERM

    local platform
    for platform in "${PLATFORMS[@]}"; do
        launch_bot "${platform}"
    done

    log "Launcher active for platforms: ${PLATFORMS[*]}"
    log "AUTO_RESTART=${AUTO_RESTART} REDIS=${REDIS_HOST}:${REDIS_PORT} inbox=${NOTIFY_INBOX} round=${BOT_ROUND}"

    while true; do
        reap_dead_bots
        process_restarts
        sleep 1 &
        wait $! || true
    done
}

main "$@"
