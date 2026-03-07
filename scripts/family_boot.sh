#!/usr/bin/env bash
set -euo pipefail

DASHBOARD_URL="http://10.0.0.68:5001"
REDIS_HOST="192.168.100.10"
REDIS_PORT="6379"
NEO4J_HOST="192.168.100.10"
NEO4J_PORT="7687"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

LOCAL_SESSIONS=(weaver codex-cli gemini-cli)

log() {
  printf '[family_boot] %s\n' "$*"
}

json_escape() {
  local value="$1"
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  printf '%s' "$value"
}

wait_for_port() {
  local host="$1"
  local port="$2"
  local label="$3"
  local attempts="${4:-30}"
  local sleep_s="${5:-2}"

  for ((i=1; i<=attempts; i++)); do
    if timeout 2 bash -lc "</dev/tcp/${host}/${port}" 2>/dev/null; then
      log "${label} is reachable at ${host}:${port}"
      return 0
    fi
    log "waiting for ${label} (${i}/${attempts})"
    sleep "${sleep_s}"
  done

  log "ERROR: ${label} not reachable at ${host}:${port}"
  return 1
}

ensure_service_running() {
  local service="$1"
  if systemctl is-active --quiet "${service}"; then
    log "${service} already running"
    return 0
  fi

  log "starting ${service}"
  systemctl start "${service}"
  sleep 2

  if systemctl is-active --quiet "${service}"; then
    log "${service} started"
    return 0
  fi

  log "ERROR: failed to start ${service}"
  return 1
}

check_tmux_session_local() {
  local session="$1"
  if tmux has-session -t "${session}" 2>/dev/null; then
    log "tmux session present: ${session}"
    return 0
  fi

  log "MISSING tmux session: ${session}"
  return 1
}

check_tmux_session_remote() {
  local target="$1"
  local session="$2"
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "${target}" "tmux has-session -t '${session}'" >/dev/null 2>&1; then
    log "remote tmux session present: ${target}:${session}"
    return 0
  fi

  log "MISSING remote tmux session: ${target}:${session}"
  return 1
}

start_remote_heartbeat() {
  local target="$1"
  local agent_id="$2"
  local activity="$3"
  local cmd="cd '${ROOT_DIR}' && nohup python3 orchestration/agent_beat.py '${agent_id}' '${activity}' >/tmp/${agent_id}_heartbeat.log 2>&1 &"

  if ssh -o BatchMode=yes -o ConnectTimeout=5 "${target}" "pgrep -f 'python3 orchestration/agent_beat.py ${agent_id}'" >/dev/null 2>&1; then
    log "remote heartbeat already running for ${agent_id} on ${target}"
    return 0
  fi

  if ssh -o BatchMode=yes -o ConnectTimeout=5 "${target}" "${cmd}" >/dev/null 2>&1; then
    log "started remote heartbeat for ${agent_id} on ${target}"
    return 0
  fi

  log "ERROR: failed to start remote heartbeat for ${agent_id} on ${target}"
  return 1
}

post_report() {
  local status="$1"
  local summary="$2"
  local payload
  payload=$(printf '{"task_id":"family-boot","agent_id":"codex-cli","status":"%s","summary":"%s"}' \
    "$(json_escape "${status}")" "$(json_escape "${summary}")")

  curl -sS -X POST "${DASHBOARD_URL}/api/report" \
    -H 'Content-Type: application/json' \
    -d "${payload}" >/dev/null
}

post_stream_message() {
  local text="$1"
  local kind="$2"
  local payload
  payload=$(printf '{"agent_id":"codex-cli","type":"%s","text":"%s"}' \
    "$(json_escape "${kind}")" "$(json_escape "${text}")")

  curl -sS -X POST "${DASHBOARD_URL}/api/message" \
    -H 'Content-Type: application/json' \
    -d "${payload}" >/dev/null
}

main() {
  local missing_sessions=0

  wait_for_port "${REDIS_HOST}" "${REDIS_PORT}" "Redis"
  wait_for_port "${NEO4J_HOST}" "${NEO4J_PORT}" "Neo4j"

  ensure_service_running conductor
  ensure_service_running heartbeats

  for session in "${LOCAL_SESSIONS[@]}"; do
    if ! check_tmux_session_local "${session}"; then
      missing_sessions=$((missing_sessions + 1))
    fi
  done

  if ! check_tmux_session_remote "spark@10.0.0.10" "claw"; then
    missing_sessions=$((missing_sessions + 1))
  fi

  if ! check_tmux_session_remote "thor@10.0.0.197" "thor-claude"; then
    missing_sessions=$((missing_sessions + 1))
  fi

  start_remote_heartbeat "spark@10.0.0.10" "claude-claw" "idle"
  start_remote_heartbeat "thor@10.0.0.197" "qwen-local" "idle"

  local summary="Boot checks passed; missing_tmux_sessions=${missing_sessions}"
  post_report "completed" "${summary}"

  if [[ "${missing_sessions}" -gt 0 ]]; then
    post_stream_message "${summary}" "alert"
  else
    post_stream_message "${summary}" "insight"
  fi

  log "${summary}"
}

main "$@"
