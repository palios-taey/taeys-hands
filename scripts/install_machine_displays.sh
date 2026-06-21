#!/usr/bin/env bash
# Install systemd user units for taey displays from machine.env.
#
# Usage:
#   ./scripts/install_machine_displays.sh [--machine-env PATH] [--no-start] [--no-vnc]
#   ./scripts/install_machine_displays.sh --append-instance NAME --start-display N
#   ./scripts/install_machine_displays.sh --print-instance-env NAME --start-display N
#
# machine.env must contain TAEY_DISPLAY_N rows:
#   TAEY_DISPLAY_2="chatgpt:ff-profile-chatgpt:https://chatgpt.com/"

set -Eeuo pipefail

NO_START=false
NO_VNC=false
MACHINE_ENV_ARG=""
APPEND_INSTANCE=""
PRINT_INSTANCE=""
START_DISPLAY=""

die() {
    echo "ERROR: $*" >&2
    exit 1
}

log() {
    echo "[install] $*"
}

usage() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

require_env() {
    local name="$1"
    [[ -n "${!name:-}" ]] || die "${name} must be set in ${MACHINE_ENV}"
}

expand_home_path() {
    local value="$1"
    case "${value}" in
        "~") printf '%s\n' "${HOME}" ;;
        "~/"*) printf '%s\n' "${HOME}/${value#~/}" ;;
        *) printf '%s\n' "${value}" ;;
    esac
}

trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "${value}"
}

strip_quotes() {
    local value="$1"
    local first last
    if (( ${#value} >= 2 )); then
        first="${value:0:1}"
        last="${value: -1}"
        if [[ "${first}" == "${last}" && ( "${first}" == '"' || "${first}" == "'" ) ]]; then
            value="${value:1:${#value}-2}"
        fi
    fi
    printf '%s' "${value}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --machine-env)
            [[ $# -ge 2 ]] || die "--machine-env requires a path"
            MACHINE_ENV_ARG="$2"
            shift 2
            ;;
        --append-instance)
            [[ $# -ge 2 ]] || die "--append-instance requires a name"
            APPEND_INSTANCE="$2"
            shift 2
            ;;
        --print-instance-env)
            [[ $# -ge 2 ]] || die "--print-instance-env requires a name"
            PRINT_INSTANCE="$2"
            shift 2
            ;;
        --start-display)
            [[ $# -ge 2 ]] || die "--start-display requires a display number"
            START_DISPLAY="$2"
            shift 2
            ;;
        --no-start)
            NO_START=true
            shift
            ;;
        --no-vnc)
            NO_VNC=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown arg: $1"
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

DISPLAY_REGISTRY_PLATFORMS=(chatgpt claude gemini grok perplexity)
DISPLAY_REGISTRY_URLS=(
    "https://chatgpt.com/"
    "https://claude.ai/new"
    "https://gemini.google.com/app"
    "https://grok.com/"
    "https://perplexity.ai/"
)

validate_instance_args() {
    local name="$1"
    local start="$2"
    [[ "${name}" =~ ^[a-z][a-z0-9_]*$ ]] || die "instance name must match [a-z][a-z0-9_]*"
    [[ "${start}" =~ ^[1-9][0-9]*$ ]] || die "--start-display must be a positive integer"
}

instance_platform_name() {
    local name="$1"
    local platform="$2"
    if [[ "${name}" == "default" ]]; then
        printf '%s\n' "${platform}"
    else
        printf '%s_%s\n' "${name}" "${platform}"
    fi
}

emit_instance_rows() {
    local name="$1"
    local start="$2"
    local idx display_num base_platform platform url profile
    validate_instance_args "${name}" "${start}"
    for idx in "${!DISPLAY_REGISTRY_PLATFORMS[@]}"; do
        display_num=$((start + idx))
        base_platform="${DISPLAY_REGISTRY_PLATFORMS[$idx]}"
        platform="$(instance_platform_name "${name}" "${base_platform}")"
        url="${DISPLAY_REGISTRY_URLS[$idx]}"
        if [[ "${name}" == "default" ]]; then
            profile="ff-profile-${base_platform}"
        else
            profile="ff-profile-${name}-${base_platform}"
        fi
        printf 'TAEY_DISPLAY_%s="%s:%s:%s"\n' "${display_num}" "${platform}" "${profile}" "${url}"
    done
}

resolve_machine_env() {
    local env_path="${MACHINE_ENV_ARG:-${TAEY_MACHINE_ENV:-${HOME}/.taey/machine.env}}"
    env_path="$(expand_home_path "${env_path}")"
    case "${env_path}" in
        /*) printf '%s\n' "${env_path}" ;;
        *) printf '%s\n' "${PWD}/${env_path}" ;;
    esac
}

MACHINE_ENV="$(resolve_machine_env)"
[[ "${MACHINE_ENV}" != *[[:space:]]* ]] || die "machine env path cannot contain whitespace: ${MACHINE_ENV}"

if [[ -n "${PRINT_INSTANCE}" ]]; then
    [[ -n "${START_DISPLAY}" ]] || die "--print-instance-env requires --start-display"
    emit_instance_rows "${PRINT_INSTANCE}" "${START_DISPLAY}"
    exit 0
fi

append_instance_rows() {
    local env_path="$1"
    local name="$2"
    local start="$3"
    local line var existing
    local rows=()
    local pending=()

    [[ -n "${start}" ]] || die "--append-instance requires --start-display"
    validate_instance_args "${name}" "${start}"

    mkdir -p "$(dirname "${env_path}")"
    if [[ ! -f "${env_path}" ]]; then
        [[ -f "${REPO_ROOT}/systemd/machine.env.template" ]] || die "missing ${REPO_ROOT}/systemd/machine.env.template"
        cp "${REPO_ROOT}/systemd/machine.env.template" "${env_path}"
        chmod 600 "${env_path}"
        log "created ${env_path} from systemd/machine.env.template"
    fi

    mapfile -t rows < <(emit_instance_rows "${name}" "${start}")
    for line in "${rows[@]}"; do
        var="${line%%=*}"
        existing="$(grep -E "^${var}=" "${env_path}" || true)"
        if [[ -n "${existing}" && "${existing}" != "${line}" ]]; then
            die "${var} already exists in ${env_path} with a different value"
        fi
        if [[ -z "${existing}" ]]; then
            pending+=("${line}")
        fi
    done

    if [[ ${#pending[@]} -eq 0 ]]; then
        log "display rows for instance ${name} already exist in ${env_path}"
        return 0
    fi

    {
        printf '\n# Display set generated by install_machine_displays.sh --append-instance %s --start-display %s\n' "${name}" "${start}"
        for line in "${pending[@]}"; do
            printf '%s\n' "${line}"
        done
    } >> "${env_path}"
    log "added ${#pending[@]} display row(s) for instance ${name} in ${env_path}"
}

if [[ -n "${APPEND_INSTANCE}" ]]; then
    append_instance_rows "${MACHINE_ENV}" "${APPEND_INSTANCE}" "${START_DISPLAY}"
fi

ensure_machine_env_secure() {
    local env_path="$1"
    local owner mode
    [[ -f "${env_path}" ]] || die "No machine.env found at ${env_path}; copy systemd/machine.env.template to that path first"
    owner="$(stat -c '%u' "${env_path}")"
    [[ "${owner}" == "$(id -u)" ]] || die "${env_path} must be owned by $(id -un)"
    mode="$(stat -c '%a' "${env_path}")"
    if (( 8#${mode} & 077 )); then
        chmod 600 "${env_path}" || die "failed to chmod 600 ${env_path}"
        log "tightened permissions on ${env_path}"
    fi
}

declare -A ENV_VALUES=()
load_machine_env() {
    local line key value
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="$(trim "${line}")"
        [[ -z "${line}" || "${line}" == \#* ]] && continue
        [[ "${line}" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || die "unsupported line in ${MACHINE_ENV}: ${line}"
        key="${BASH_REMATCH[1]}"
        value="$(strip_quotes "$(trim "${BASH_REMATCH[2]}")")"
        ENV_VALUES["${key}"]="${value}"
        export "${key}=${value}"
    done < "${MACHINE_ENV}"
}

ensure_machine_env_secure "${MACHINE_ENV}"
load_machine_env

for name in TAEY_REPO TAEY_FIREFOX_BIN TAEY_AT_SPI_BUS_LAUNCHER TAEY_AT_SPI_REGISTRYD TAEY_USE_SOFTWARE_GL; do
    require_env "${name}"
done
if ! ${NO_VNC}; then
    require_env TAEY_VNC_PASSWORD
fi

TAEY_REPO="$(expand_home_path "${TAEY_REPO}")"
TAEY_FIREFOX_BIN="$(expand_home_path "${TAEY_FIREFOX_BIN}")"
TAEY_AT_SPI_BUS_LAUNCHER="$(expand_home_path "${TAEY_AT_SPI_BUS_LAUNCHER}")"
TAEY_AT_SPI_REGISTRYD="$(expand_home_path "${TAEY_AT_SPI_REGISTRYD}")"
export TAEY_REPO TAEY_FIREFOX_BIN TAEY_AT_SPI_BUS_LAUNCHER TAEY_AT_SPI_REGISTRYD

case "${TAEY_USE_SOFTWARE_GL}" in
    0|1) ;;
    *) die "TAEY_USE_SOFTWARE_GL must be 0 or 1 in ${MACHINE_ENV}" ;;
esac

require_cmd systemctl
require_cmd Xvfb
require_cmd dbus-run-session
require_cmd xprop
require_cmd openbox
require_cmd sort
if ! ${NO_VNC}; then
    require_cmd x11vnc
    require_cmd pkill
fi

[[ -d "${TAEY_REPO}" ]] || die "TAEY_REPO does not exist: ${TAEY_REPO}"
[[ -f "${TAEY_REPO}/systemd/user/firefox-user.js" ]] || die "missing ${TAEY_REPO}/systemd/user/firefox-user.js"
[[ -x "${TAEY_REPO}/scripts/install_firefox_user_js.sh" ]] || die "missing executable ${TAEY_REPO}/scripts/install_firefox_user_js.sh"
[[ -x "${TAEY_REPO}/scripts/display_unit_runner.sh" ]] || die "missing executable ${TAEY_REPO}/scripts/display_unit_runner.sh"
[[ -x "${TAEY_FIREFOX_BIN}" ]] || die "TAEY_FIREFOX_BIN missing or not executable: ${TAEY_FIREFOX_BIN}"
[[ -x "${TAEY_AT_SPI_BUS_LAUNCHER}" ]] || die "TAEY_AT_SPI_BUS_LAUNCHER missing or not executable: ${TAEY_AT_SPI_BUS_LAUNCHER}"
[[ -x "${TAEY_AT_SPI_REGISTRYD}" ]] || die "TAEY_AT_SPI_REGISTRYD missing or not executable: ${TAEY_AT_SPI_REGISTRYD}"

mkdir -p "${SYSTEMD_USER_DIR}" "${HOME}/.taey/profiles"

declare -a DISPLAY_NUMS=()
declare -A DISPLAY_PLATFORM=()
declare -A DISPLAY_PROFILE=()
declare -A DISPLAY_URL=()
declare -A SEEN_PLATFORM=()
declare -A SEEN_PROFILE=()

read_display_config() {
    local key display_num cfg platform rest profile url
    for key in "${!ENV_VALUES[@]}"; do
        [[ "${key}" =~ ^TAEY_DISPLAY_([0-9]+)$ ]] || continue
        display_num="${BASH_REMATCH[1]}"
        cfg="${ENV_VALUES[$key]}"
        [[ "${display_num}" =~ ^[1-9][0-9]*$ ]] || die "${key} must use a positive display number"
        [[ "${cfg}" == *:*:* ]] || die "malformed ${key}; expected platform:profile:url"
        platform="${cfg%%:*}"
        rest="${cfg#*:}"
        profile="${rest%%:*}"
        url="${rest#*:}"

        [[ "${platform}" =~ ^[a-z][a-z0-9_]*$ ]] || die "${key} platform must match [a-z][a-z0-9_]*"
        [[ "${profile}" =~ ^[A-Za-z0-9._-]+$ ]] || die "${key} profile must be a directory name"
        case "${url}" in
            http://*|https://*) ;;
            *) die "${key} url must start with http:// or https://" ;;
        esac
        [[ "${url}" != *" "* && "${url}" != *$'\t'* && "${url}" != *"\""* && "${url}" != *"'"* ]] || die "${key} url contains unsupported whitespace or quotes"
        [[ -z "${SEEN_PLATFORM[$platform]:-}" ]] || die "duplicate platform ${platform} in ${key} and ${SEEN_PLATFORM[$platform]}"
        [[ -z "${SEEN_PROFILE[$profile]:-}" ]] || die "duplicate profile ${profile} in ${key} and ${SEEN_PROFILE[$profile]}"

        SEEN_PLATFORM["${platform}"]="${key}"
        SEEN_PROFILE["${profile}"]="${key}"
        DISPLAY_NUMS+=("${display_num}")
        DISPLAY_PLATFORM["${display_num}"]="${platform}"
        DISPLAY_PROFILE["${display_num}"]="${profile}"
        DISPLAY_URL["${display_num}"]="${url}"
    done
}

read_display_config
if [[ ${#DISPLAY_NUMS[@]} -eq 0 ]]; then
    die "no TAEY_DISPLAY_N=platform:profile:url entries in ${MACHINE_ENV}"
fi
mapfile -t DISPLAY_NUMS < <(printf '%s\n' "${DISPLAY_NUMS[@]}" | sort -n)

SYSTEMD_ENV_FILE="${MACHINE_ENV}"
if [[ "${MACHINE_ENV}" == "${HOME}/"* ]]; then
    SYSTEMD_ENV_FILE="%h/${MACHINE_ENV#"${HOME}/"}"
fi

if ! ${NO_VNC}; then
    log "storing VNC password in ${HOME}/.taey/vnc_passwd"
    x11vnc -storepasswd "${TAEY_VNC_PASSWORD}" "${HOME}/.taey/vnc_passwd" >/dev/null
    chmod 600 "${HOME}/.taey/vnc_passwd"
fi

write_xvfb_unit() {
    cat > "${SYSTEMD_USER_DIR}/taey-xvfb@.service" <<'EOF'
[Unit]
Description=Xvfb for display :%i
After=basic.target

[Service]
Type=simple
ExecStartPre=/usr/bin/bash -lc 'set -Eeuo pipefail; rm -f /tmp/.X%i-lock /tmp/.X11-unix/X%i /tmp/a11y_bus_:%i /tmp/dbus_session_bus_:%i /tmp/firefox_pid_:%i'
ExecStart=/usr/bin/Xvfb :%i -screen 0 1920x1080x24 -ac -noreset
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
    log "wrote ${SYSTEMD_USER_DIR}/taey-xvfb@.service"
}

write_bus_watcher_unit() {
    cat > "${SYSTEMD_USER_DIR}/taey-bus-watcher@.service" <<EOF
[Unit]
Description=Taey AT-SPI bus pointer watcher for display :%i
Requires=taey-display-%i.service
After=taey-display-%i.service
PartOf=taey-display-%i.service

[Service]
Type=simple
EnvironmentFile=${SYSTEMD_ENV_FILE}
Environment=DISPLAY=:%i
ExecStart=/usr/bin/bash -lc 'set -Eeuo pipefail; : "\$\${TAEY_REPO:?TAEY_REPO}"; exec "\$\${TAEY_REPO}/scripts/bus_watcher.sh" %i'
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF
    log "wrote ${SYSTEMD_USER_DIR}/taey-bus-watcher@.service"
}

write_display_unit() {
    local display_num="$1"
    local platform="${DISPLAY_PLATFORM[$display_num]}"
    local profile="${DISPLAY_PROFILE[$display_num]}"
    local url="${DISPLAY_URL[$display_num]}"
    local vnc_enabled=0
    local vnc_port=$((5900 + display_num))
    local unit_path="${SYSTEMD_USER_DIR}/taey-display-${display_num}.service"

    if ! ${NO_VNC}; then
        vnc_enabled=1
    fi

    cat > "${unit_path}" <<EOF
[Unit]
Description=Taey Display :${display_num} (${platform})
After=taey-xvfb@${display_num}.service
Requires=taey-xvfb@${display_num}.service

[Service]
Type=simple
EnvironmentFile=${SYSTEMD_ENV_FILE}
Environment=DISPLAY=:${display_num}
Environment=TAEY_PLATFORM=${platform}
Environment=TAEY_PROFILE=${profile}
Environment=TAEY_URL=${url}
Environment=TAEY_VNC_ENABLED=${vnc_enabled}
Environment=TAEY_VNC_PORT=${vnc_port}
ExecStartPre=/usr/bin/bash -lc 'set -Eeuo pipefail; : "\$\${TAEY_REPO:?TAEY_REPO}"; test -x "\$\${TAEY_REPO}/scripts/display_unit_runner.sh"'
ExecStart=/usr/bin/dbus-run-session -- /usr/bin/bash -lc 'set -Eeuo pipefail; : "\$\${TAEY_REPO:?TAEY_REPO}"; exec "\$\${TAEY_REPO}/scripts/display_unit_runner.sh" ${display_num}'
Restart=always
RestartSec=10
TimeoutStopSec=20

[Install]
WantedBy=default.target
EOF
    log "wrote ${unit_path} (platform=${platform} profile=${profile} vnc_port=${vnc_port} vnc_enabled=${vnc_enabled})"
}

check_display_collisions() {
    local display_num
    ${NO_START} && return 0
    for display_num in "${DISPLAY_NUMS[@]}"; do
        if [[ -e "/tmp/.X${display_num}-lock" || -S "/tmp/.X11-unix/X${display_num}" ]]; then
            if ! systemctl --user is-active --quiet "taey-xvfb@${display_num}.service"; then
                die "display :${display_num} appears in use outside taey-xvfb@${display_num}.service"
            fi
        fi
    done
}

write_xvfb_unit
write_bus_watcher_unit

INSTALLED=()
for display_num in "${DISPLAY_NUMS[@]}"; do
    write_display_unit "${display_num}"
    INSTALLED+=("taey-display-${display_num}.service")
done

check_display_collisions

systemctl --user daemon-reload
log "daemon-reload done"

for unit in "${INSTALLED[@]}"; do
    systemctl --user enable "${unit}" >/dev/null
    display_num="${unit#taey-display-}"
    display_num="${display_num%.service}"
    systemctl --user enable "taey-bus-watcher@${display_num}.service" >/dev/null
done
log "enabled: ${INSTALLED[*]}"

if ${NO_START}; then
    log "--no-start: generated and enabled units without starting them"
    exit 0
fi

systemctl --user restart "${INSTALLED[@]}"
for unit in "${INSTALLED[@]}"; do
    display_num="${unit#taey-display-}"
    display_num="${display_num%.service}"
    systemctl --user restart "taey-bus-watcher@${display_num}.service"
done
log "started/restarted ${#INSTALLED[@]} display unit(s)"

sleep 6
echo
echo "=== verification ==="
failed=0
for unit in "${INSTALLED[@]}"; do
    state="$(systemctl --user is-active "${unit}" 2>/dev/null || true)"
    display_num="${unit#taey-display-}"
    display_num="${display_num%.service}"
    watcher_state="$(systemctl --user is-active "taey-bus-watcher@${display_num}.service" 2>/dev/null || true)"
    echo "  ${unit}: ${state}"
    echo "  taey-bus-watcher@${display_num}.service: ${watcher_state}"
    [[ "${state}" == "active" ]] || failed=1
    [[ "${watcher_state}" == "active" ]] || failed=1
done

if ! ${NO_VNC}; then
    require_cmd ss
    echo
    echo "=== VNC ports ==="
    ss -lntp | awk '$4 ~ /:59[0-9][0-9]$/ {print "  "$4"  "$NF}' | sort
fi

if (( failed )); then
    die "one or more display services failed verification"
fi

echo
echo "Done. To restart one display later: systemctl --user restart taey-display-<N>.service"
