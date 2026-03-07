#!/usr/bin/env bash
set -euo pipefail

DASHBOARD_URL="http://10.0.0.68:5001"
ROOT_DIR="/home/spark/taeys-hands"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=5)
BEATS_PER_RUN="${BEATS_PER_RUN:-5}"
HEARTBEAT_INTERVAL_S="${HEARTBEAT_INTERVAL_S:-12}"

log() {
  printf '[remote_heartbeats] %s\n' "$*"
}

json_escape() {
  local value="$1"
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  printf '%s' "$value"
}

post_stream_alert() {
  local text="$1"
  local payload
  payload=$(printf '{"agent_id":"codex-cli","type":"alert","text":"%s"}' "$(json_escape "${text}")")

  curl -sS -X POST "${DASHBOARD_URL}/api/message" \
    -H 'Content-Type: application/json' \
    -d "${payload}" >/dev/null || true
}

remote_beat_once() {
  local ssh_target="$1"
  local agent_id="$2"
  local label="$3"
  local cmd="cd '${ROOT_DIR}' && python3 orchestration/agent_beat.py '${agent_id}' --once"

  if ssh "${SSH_OPTS[@]}" "${ssh_target}" "${cmd}" >/dev/null 2>&1; then
    log "heartbeat ok: ${label} (${agent_id})"
    return 0
  fi

  local msg="remote heartbeat failed for ${label} (${agent_id}) via ${ssh_target}"
  log "${msg}"
  post_stream_alert "${msg}"
  return 1
}

direct_beat_once() {
  local agent_id="$1"
  local activity="$2"
  local payload
  payload=$(printf '{"agent_id":"%s","activity":"%s"}' \
    "$(json_escape "${agent_id}")" "$(json_escape "${activity}")")

  if curl -sS -X POST "${DASHBOARD_URL}/api/heartbeat" \
    -H 'Content-Type: application/json' \
    -d "${payload}" >/dev/null; then
    log "heartbeat ok: ${agent_id}"
    return 0
  fi

  local msg="direct heartbeat failed for ${agent_id}"
  log "${msg}"
  post_stream_alert "${msg}"
  return 1
}

main() {
  local i
  local failed=0

  for ((i=1; i<=BEATS_PER_RUN; i++)); do
    remote_beat_once "spark@10.0.0.10" "claude-claw" "claw" || failed=1
    remote_beat_once "thor@10.0.0.197" "qwen-local" "qwen" || failed=1
    direct_beat_once "perplexity-computer" "remote heartbeat" || failed=1

    if [[ "${i}" -lt "${BEATS_PER_RUN}" ]]; then
      sleep "${HEARTBEAT_INTERVAL_S}"
    fi
  done

  exit "${failed}"
}

main "$@"
