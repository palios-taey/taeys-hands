#!/bin/bash
# chat_hmm_enrichment_worker.sh — HMM enrichment via Family Chat platforms.
#
# Architecture:
#   - hmm_package_builder.py builds packages (same as local-LLM and codex variants)
#   - consultation_v2/consult.py dispatches the prompt to Firefox on a Thor 2
#     X display (per-platform: chatgpt :7, claude :8, gemini :9, grok :10)
#   - consult.py spawns a monitor process; we tail its log for response_complete
#   - consultation_v2/act.py extract pulls the response text via AT-SPI
#   - hmm_store_results.py triple-writes to Weaviate + Neo4j + Redis
#
# Environment (set by caller or defaults):
#   PLATFORM        chatgpt | claude | gemini | grok
#                   (perplexity excluded — Jesse 2026-04-30: can't do HMM)
#   TAEY_NODE_ID    Logger ID (default: "${HOSTNAME}-${PLATFORM}")
#   WEAVIATE_URL    Default: http://REDACTED_LAN_IP:8088 (Mira)
#   REDIS_HOST      Default: REDACTED_LAN_IP
#   REDIS_PORT      Default: 6379
#   NEO4J_URI       Default: bolt://REDACTED_LAN_IP:7689
#   PYTHONPATH      Must include the embedding-server checkout
#   CONSULT_MODE    Optional override mode for consult.py (e.g. "instant" for chatgpt)
#
# Usage (one tmux session per platform on Thor 2):
#   tmux new-session -s hmm-claude -d \
#     "PLATFORM=claude bash ~/taeys-hands/agents/chat_hmm_enrichment_worker.sh"

set -uo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PLATFORM="${PLATFORM:-claude}"
TAEYS_HANDS_REPO="${TAEYS_HANDS_REPO:-${HOME}/taeys-hands}"
EMBEDDING_REPO="${EMBEDDING_REPO:-${HOME}/embedding-server-fresh}"
[[ ! -d "${EMBEDDING_REPO}" ]] && EMBEDDING_REPO="${HOME}/embedding-server"

BUILDER_PY="${EMBEDDING_REPO}/isma/scripts/hmm_package_builder.py"
PYBIN="${PYBIN:-${HOME}/.venvs/hmm_drive/bin/python3}"
[[ ! -x "${PYBIN}" ]] && PYBIN="$(command -v python3)"

NODE_ID="${TAEY_NODE_ID:-$(hostname)-${PLATFORM}}"
LOG_DIR="/tmp/hmm_worker_logs"
SUPERVISOR="${TMUX_SUPERVISOR:-weaver}"
MAX_RETRIES=2
COOLDOWN_SHORT=5
COOLDOWN_LONG=300
MONITOR_TIMEOUT=900   # 15 min hard cap per consultation

# DB endpoints — Thor 2 reaches Mira's stores
export WEAVIATE_URL="${WEAVIATE_URL:-http://REDACTED_LAN_IP:8088}"
export REDIS_HOST="${REDIS_HOST:-REDACTED_LAN_IP}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export NEO4J_URI="${NEO4J_URI:-bolt://REDACTED_LAN_IP:7689}"
export EMBEDDING_URL="${EMBEDDING_URL:-http://REDACTED_LAN_IP:8089/v1/embeddings}"
export PYTHONPATH="${EMBEDDING_REPO}:${PYTHONPATH:-}"

mkdir -p "${LOG_DIR}" /tmp/hmm_packages /tmp/hmm_responses /tmp/hmm_prompts

log() { echo "[$(date '+%H:%M:%S')] [${NODE_ID}] $*"; }

escalate() {
    log "ESCALATION: $*"
    if command -v taey-notify >/dev/null && [[ -n "${SUPERVISOR}" ]]; then
        taey-notify "${SUPERVISOR}" "WORKER ${NODE_ID}: $*" --type escalation 2>/dev/null || true
    fi
}

# ── Validate platform — Perplexity excluded per Jesse 2026-04-30 ──────────────
case "${PLATFORM}" in
    chatgpt|claude|gemini|grok) ;;
    perplexity)
        escalate "Perplexity is NOT eligible for HMM enrichment — refuse to start"
        exit 2 ;;
    *)
        escalate "Unknown platform: ${PLATFORM}"
        exit 2 ;;
esac

# ── Optional consult mode override (e.g. chatgpt → instant) ──────────────────
CONSULT_MODE_FLAG=()
if [[ -n "${CONSULT_MODE:-}" ]]; then
    CONSULT_MODE_FLAG=(--mode "${CONSULT_MODE}")
fi

# ── Get analysis prompt template from builder ────────────────────────────────
ANALYSIS_PROMPT=$("${PYBIN}" "${BUILDER_PY}" prompt 2>/dev/null)
if [[ -z "${ANALYSIS_PROMPT}" ]]; then
    escalate "Failed to get ANALYSIS_PROMPT from builder"
    exit 1
fi

# ── Dispatch + harvest one package via Chat platform ─────────────────────────
analyze_package() {
    local pkg_file="$1"
    local response_file="$2"
    local pkg_basename
    pkg_basename=$(basename "${pkg_file}")

    # Compose full prompt: ANALYSIS_PROMPT + package body, JSON-only constraint
    local prompt_file="/tmp/hmm_prompts/${NODE_ID}_${pkg_basename%.md}.md"
    {
        echo "You are an HMM (Harmonic Motif Memory) enrichment analyst. Analyze every item in the package below."
        echo
        echo "${ANALYSIS_PROMPT}"
        echo
        echo "------ PACKAGE BEGIN ------"
        cat "${pkg_file}"
        echo "------ PACKAGE END ------"
        echo
        echo "OUTPUT REQUIREMENT: Reply with ONLY the minified JSON object. No markdown fencing, no explanation, no preamble. Start with { and end with }."
    } > "${prompt_file}"

    # Send a short message + attach the full prompt as a file. Long prompts
    # (50KB+) blow the OS arg-list cap if passed positionally.
    local short_msg="Analyze the attached HMM enrichment package and respond with ONLY the minified JSON object per the instructions in the attached file. No markdown fencing, no explanation, no preamble."

    # Dispatch via consult.py — captures dispatched event + monitor log path
    local dispatch_log="${LOG_DIR}/${NODE_ID}_dispatch_$(date +%s).jsonl"
    log "dispatching to ${PLATFORM} via consult.py (file=${prompt_file})"
    if ! (cd "${TAEYS_HANDS_REPO}" && \
          "${PYBIN}" -m consultation_v2.consult "${PLATFORM}" "${short_msg}" \
            --file "${prompt_file}" \
            "${CONSULT_MODE_FLAG[@]}" \
            > "${dispatch_log}" 2>&1); then
        log "consult.py dispatch failed — see ${dispatch_log}"
        return 1
    fi

    # Extract monitor log path from the dispatched event stream
    local monitor_log
    monitor_log=$(grep -oP '"log":\s*"\K/tmp/monitor_[^"]+' "${dispatch_log}" | tail -1)
    if [[ -z "${monitor_log}" ]]; then
        log "no monitor log path in dispatch output"
        return 1
    fi
    log "monitor log: ${monitor_log}"

    # Wait for monitor to emit response complete (or unverified, or fatal)
    local elapsed=0
    local poll=5
    local outcome=""
    while [[ ${elapsed} -lt ${MONITOR_TIMEOUT} ]]; do
        if [[ -f "${monitor_log}" ]]; then
            if grep -q '"event":\s*"complete"' "${monitor_log}" 2>/dev/null; then
                outcome="complete"; break
            elif grep -qE '"event":\s*"(completion_unverified|fatal)"' "${monitor_log}" 2>/dev/null; then
                outcome="unverified"; break
            fi
        fi
        sleep ${poll}
        elapsed=$((elapsed + poll))
    done

    if [[ -z "${outcome}" ]]; then
        log "monitor timeout after ${MONITOR_TIMEOUT}s"
        return 1
    fi
    if [[ "${outcome}" != "complete" ]]; then
        log "monitor reported ${outcome} — abandoning this package"
        return 1
    fi

    # Extract response text via AT-SPI
    log "extracting response via act.py"
    local extract_out="${LOG_DIR}/${NODE_ID}_extract_$(date +%s).json"
    if ! (cd "${TAEYS_HANDS_REPO}" && \
          "${PYBIN}" -m consultation_v2.act extract "${PLATFORM}" \
            > "${extract_out}" 2>&1); then
        log "act.py extract failed — see ${extract_out}"
        return 1
    fi

    # Pull the JSON object out of the extracted text and write to response_file.
    # The extract stdout shape is JSON with a 'response' / 'text' field
    # depending on the platform; tolerate both, then unwrap to the inner JSON.
    if ! "${PYBIN}" - "${extract_out}" "${response_file}" <<'PY'
import json, re, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    raw = f.read()

# act.py output is one JSON document per line (event stream). The terminal
# event carries the response text under one of several keys.
text = ""
for line in raw.splitlines():
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    for key in ("response", "text", "extracted", "value", "result"):
        v = obj.get(key)
        if isinstance(v, str) and v:
            text = v
if not text:
    # Fallback: regex the whole blob for a JSON object payload
    m = re.search(r"\{[^{}]*\"items\".*\}", raw, re.DOTALL)
    if not m:
        sys.exit("no response text or JSON in extract output")
    text = m.group(0)

# Strip thinking tags and code fences
text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
text = re.sub(r"^```(?:json)?\s*", "", text)
text = re.sub(r"\s*```$", "", text)

# Direct parse
try:
    data = json.loads(text)
except json.JSONDecodeError:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        sys.exit("could not locate JSON in response")
    data = json.loads(m.group(0))

with open(dst, "w") as f:
    json.dump(data, f)
PY
    then
        log "response JSON parse failed"
        return 1
    fi

    return 0
}

# ── Verify reachability before starting the loop ─────────────────────────────
log "=== Chat HMM enrichment worker starting on ${NODE_ID} ==="
log "  platform=${PLATFORM}  weaviate=${WEAVIATE_URL}  redis=${REDIS_HOST}:${REDIS_PORT}"

if ! curl -sf "${WEAVIATE_URL}/v1/.well-known/ready" >/dev/null 2>&1; then
    escalate "Weaviate not reachable at ${WEAVIATE_URL}"
    exit 1
fi
if ! redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" PING >/dev/null 2>&1; then
    escalate "Redis not reachable at ${REDIS_HOST}:${REDIS_PORT}"
    exit 1
fi

# ── Main loop ────────────────────────────────────────────────────────────────
CYCLE=0
EMPTY_STREAK=0
ERROR_STREAK=0

while true; do
    CYCLE=$((CYCLE + 1))
    log "── cycle ${CYCLE} ──"

    PKG_OUTPUT=$("${PYBIN}" "${BUILDER_PY}" next --platform "${PLATFORM}" 2>&1)
    if ! echo "${PKG_OUTPUT}" | grep -q "Package ready:"; then
        EMPTY_STREAK=$((EMPTY_STREAK + 1))
        if [[ ${EMPTY_STREAK} -ge 5 ]]; then
            log "empty 5×; long sleep"
            "${PYBIN}" "${BUILDER_PY}" stats 2>/dev/null | tail -10
            escalate "queue empty for 5 cycles or builder unreachable"
            sleep ${COOLDOWN_LONG}
            EMPTY_STREAK=0
        else
            log "empty (${EMPTY_STREAK}/5); short sleep"
            sleep 30
        fi
        continue
    fi
    EMPTY_STREAK=0

    PKG_FILE=$(echo "${PKG_OUTPUT}" | grep -oP '/tmp/hmm_packages/\S+\.md' | head -1)
    PKG_ID=$(echo "${PKG_OUTPUT}" | grep -oP 'pkg_\w+' | head -1)
    if [[ -z "${PKG_FILE}" || ! -f "${PKG_FILE}" ]]; then
        log "no package file in builder output"
        "${PYBIN}" "${BUILDER_PY}" fail --platform "${PLATFORM}" "no_package_file" 2>/dev/null || true
        ERROR_STREAK=$((ERROR_STREAK + 1))
        sleep ${COOLDOWN_SHORT}
        continue
    fi
    log "package: ${PKG_FILE}  id=${PKG_ID:-unknown}"

    RESPONSE_FILE="/tmp/hmm_responses/${PLATFORM}_${NODE_ID}_$(date +%s).json"
    SUCCESS=false
    for ATTEMPT in $(seq 1 ${MAX_RETRIES}); do
        if analyze_package "${PKG_FILE}" "${RESPONSE_FILE}"; then
            SUCCESS=true; break
        fi
        log "analyze attempt ${ATTEMPT}/${MAX_RETRIES} failed"
        sleep ${COOLDOWN_SHORT}
    done

    if ! ${SUCCESS}; then
        "${PYBIN}" "${BUILDER_PY}" fail --platform "${PLATFORM}" "chat_dispatch_failed" 2>/dev/null || true
        ERROR_STREAK=$((ERROR_STREAK + 1))
        if [[ ${ERROR_STREAK} -ge 5 ]]; then
            escalate "5 consecutive failures — pausing 5min"
            sleep ${COOLDOWN_LONG}
            ERROR_STREAK=0
        fi
        continue
    fi

    log "completing via builder"
    if COMPLETE_OUT=$("${PYBIN}" "${BUILDER_PY}" complete --platform "${PLATFORM}" --response-file "${RESPONSE_FILE}" 2>&1); then
        ERROR_STREAK=0
        STORED=$(echo "${COMPLETE_OUT}" | grep -oE 'stored.*[0-9]+' | head -1)
        log "SUCCESS pkg=${PKG_ID:-unknown} ${STORED}"
    else
        log "complete failed: ${COMPLETE_OUT}"
        ERROR_STREAK=$((ERROR_STREAK + 1))
        if [[ ${ERROR_STREAK} -ge 5 ]]; then
            escalate "5 consecutive complete failures — pausing 5min"
            sleep ${COOLDOWN_LONG}
            ERROR_STREAK=0
        fi
    fi

    sleep ${COOLDOWN_SHORT}
done
