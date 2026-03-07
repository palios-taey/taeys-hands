#!/usr/bin/env bash
set -euo pipefail

DASHBOARD_URL="http://10.0.0.68:5001"
REDIS_HOST="192.168.100.10"
REDIS_PORT="6379"
NEO4J_HOST="192.168.100.10"
NEO4J_PORT="7687"

AGENTS=(
  claude-taeys-hands
  claude-weaver
  claude-claw
  gemini-cli
  codex-cli
  perplexity-computer
  qwen-local
)

log() {
  printf '[family_health] %s\n' "$*"
}

json_escape() {
  local value="$1"
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  printf '%s' "$value"
}

check_port() {
  local host="$1"
  local port="$2"
  local label="$3"

  if timeout 2 bash -lc "</dev/tcp/${host}/${port}" 2>/dev/null; then
    log "${label} reachable at ${host}:${port}"
    return 0
  fi

  log "${label} UNREACHABLE at ${host}:${port}"
  return 1
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

check_heartbeats() {
  local pulse_json
  pulse_json=$(curl -sS "${DASHBOARD_URL}/api/pulse")

  PULSE_JSON="${pulse_json}" python3 - "$@" <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["PULSE_JSON"])
expected = sys.argv[1:]

agents = {a.get("agent_id"): bool(a.get("alive")) for a in payload.get("agents", [])}
missing = []
alive = 0
for agent in expected:
    if agents.get(agent):
        alive += 1
    else:
        missing.append(agent)

print(f"{alive}/{len(expected)}")
print(",".join(missing))
PY
}

main() {
  local redis_ok=0
  local neo4j_ok=0

  if check_port "${REDIS_HOST}" "${REDIS_PORT}" "Redis"; then
    redis_ok=1
  fi

  if check_port "${NEO4J_HOST}" "${NEO4J_PORT}" "Neo4j"; then
    neo4j_ok=1
  fi

  mapfile -t hb_lines < <(check_heartbeats "${AGENTS[@]}")
  local hb_ratio="${hb_lines[0]}"
  local hb_missing="${hb_lines[1]}"

  local summary="health: heartbeats=${hb_ratio} redis=${redis_ok} neo4j=${neo4j_ok}"
  if [[ -n "${hb_missing}" ]]; then
    summary+=" missing=[${hb_missing}]"
  fi

  local kind="insight"
  if [[ "${hb_ratio}" != "7/7" || "${redis_ok}" -ne 1 || "${neo4j_ok}" -ne 1 ]]; then
    kind="alert"
  fi

  post_stream_message "${summary}" "${kind}"
  log "${summary}"
}

main "$@"
