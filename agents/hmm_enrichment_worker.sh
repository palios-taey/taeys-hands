#!/bin/bash
# hmm_enrichment_worker.sh — HMM enrichment using local LLM with full autonomy.
#
# Architecture:
#   - Bash handles package builder commands (build, complete, fail, stats)
#   - local_llm_agent.py gives Qwen the GOAL and lets it use MCP tools freely
#   - No rigid step-by-step instructions — Qwen reasons about HOW to use tools
#
# Usage:
#   export LLM_API_URL=http://localhost:8080/v1
#   export TMUX_SUPERVISOR=weaver
#   export WEAVIATE_URL=http://10.0.0.163:8088
#   bash ~/taeys-hands/agents/hmm_enrichment_worker.sh
#
# Worker nodes: Thor (10.0.0.197), Jetson (10.0.0.8)

set -uo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
BUILDER="python3 ${HOME}/embedding-server/isma/scripts/hmm_package_builder.py"
AGENT_DIR="${HOME}/taeys-hands"
PLATFORMS=("chatgpt" "grok" "gemini")
LOG_DIR="/tmp/hmm_worker_logs"
SUPERVISOR="${TMUX_SUPERVISOR:-weaver}"
NODE_ID="${TAEY_NODE_ID:-$(hostname)}"

# DB settings — default to Mira (post-migration)
export WEAVIATE_URL="${WEAVIATE_URL:-http://10.0.0.163:8088}"
export REDIS_HOST="${REDIS_HOST:-192.168.100.10}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export NEO4J_URI="${NEO4J_URI:-bolt://10.0.0.163:7689}"

mkdir -p "$LOG_DIR" /tmp/hmm_packages /tmp/hmm_responses

log() { echo "[$(date '+%H:%M:%S')] [$NODE_ID] $*"; }
escalate() {
    log "ESCALATION: $*"
    if command -v tmux-send &>/dev/null && [[ -n "$SUPERVISOR" ]]; then
        tmux-send "$SUPERVISOR" "ESCALATION from $NODE_ID: $*" 2>/dev/null || true
    fi
}

check_llm() {
    curl -sf "${LLM_API_URL:-http://localhost:8080/v1}/models" >/dev/null 2>&1
}

run_agent() {
    local task_file="$1"
    local max_turns="${2:-50}"
    local log_file="$3"
    cd "$AGENT_DIR"
    timeout 600 python3 agents/local_llm_agent.py \
        --task-file "$task_file" \
        --max-turns "$max_turns" \
        2>"$log_file"
}

# ── Main loop ─────────────────────────────────────────────────────────────────
log "HMM Enrichment Worker starting on $NODE_ID"
log "LLM: ${LLM_API_URL:-http://localhost:8080/v1}"
log "Weaviate: $WEAVIATE_URL"
log "Platforms: ${PLATFORMS[*]}"

# Wait for LLM
for i in {1..30}; do
    check_llm && break
    log "Waiting for LLM server... ($i/30)"
    sleep 10
done
check_llm || { escalate "LLM not ready after 5min"; exit 1; }
log "LLM ready"

CYCLE=0
declare -A PKG_FILES=()
declare -A SENT=()
while true; do
    CYCLE=$((CYCLE + 1))
    log "=== CYCLE $CYCLE START ==="
    PKG_FILES=()
    SENT=()

    # Note: stats only counts theme index items. The sweep fallback finds 200K+
    # additional tiles from Weaviate that stats doesn't know about.
    # Always attempt to build — if nothing found, THEN sleep.
    STATS=$($BUILDER stats 2>/dev/null || echo "stats unavailable")
    log "Queue stats: $(echo "$STATS" | grep -E 'Remaining|Completed' | tr '\n' ' ' | tr -s ' ')"

    # ── Phase 1: BUILD & SEND ─────────────────────────────────────────────────

    for platform in "${PLATFORMS[@]}"; do
        log "--- Building package for $platform ---"

        BUILD_OUT=$($BUILDER next --platform "$platform" 2>&1) || {
            log "Build failed for $platform: $(echo "$BUILD_OUT" | tail -2)"
            continue
        }

        # Extract package path
        PKG_FILE=$(echo "$BUILD_OUT" | grep -oP 'Package ready: \K.*' | head -1)
        if [[ -z "$PKG_FILE" ]] || [[ ! -f "$PKG_FILE" ]]; then
            PKG_FILE=$(ls -t /tmp/hmm_packages/*.md 2>/dev/null | head -1)
        fi

        if [[ -z "$PKG_FILE" ]] || [[ ! -f "$PKG_FILE" ]]; then
            log "No package file for $platform — skipping"
            continue
        fi

        log "Package: $PKG_FILE"
        PKG_FILES[$platform]="$PKG_FILE"

        # Write send task — goal-level, not step-by-step
        TASK_FILE="/tmp/hmm_send_${platform}_c${CYCLE}.txt"
        cat > "$TASK_FILE" << TASKEOF
Your goal: Attach the file "${PKG_FILE}" to ${platform} and send this message:
"Analyze the attached HMM package. Respond with MINIFIED JSON on a single line per the format in the package."

Use the taeys-hands MCP tools to accomplish this. The file contains its own instructions, so the AI platform just needs to receive the file and that one-line prompt.

When you have successfully sent the message, output: SEND_COMPLETE
If you cannot complete the send after a reasonable number of attempts, output: SEND_FAILED: <reason>
TASKEOF

        AGENT_LOG="$LOG_DIR/send_${platform}_c${CYCLE}.log"
        log "Running agent (send) for $platform..."
        AGENT_OUT=$(run_agent "$TASK_FILE" 50 "$AGENT_LOG") || true
        log "Agent send output: $(echo "$AGENT_OUT" | tail -3)"

        if echo "$AGENT_OUT" | grep -q "SEND_COMPLETE\|SEND_FAILED"; then
            if echo "$AGENT_OUT" | grep -q "SEND_COMPLETE"; then
                log "Sent to $platform"
                SENT[$platform]=1
            else
                log "Send failed for $platform: $AGENT_OUT"
            fi
        else
            # If agent ran without error and we have a package, assume sent
            log "Agent finished without explicit confirmation for $platform — assuming sent"
            SENT[$platform]=1
        fi

        sleep 3
    done

    # ── Wait for responses ─────────────────────────────────────────────────────
    SENT_COUNT=${#SENT[@]}
    if [[ "$SENT_COUNT" -eq 0 ]]; then
        log "Nothing sent this cycle — queue may truly be empty. Sleeping 5min."
        escalate "No packages built on $NODE_ID — queue empty or Weaviate unreachable. Sleeping 5min."
        sleep 300
        continue
    fi

    log "Sent to $SENT_COUNT platforms. Waiting 90s for initial responses..."
    sleep 90

    # ── Phase 2: HARVEST ──────────────────────────────────────────────────────
    for platform in "${PLATFORMS[@]}"; do
        [[ -z "${SENT[$platform]+x}" ]] && continue

        log "--- Harvesting $platform ---"
        RESPONSE_FILE="/tmp/hmm_responses/response_${platform}_c${CYCLE}.txt"

        HARVEST_TASK="/tmp/hmm_harvest_${platform}_c${CYCLE}.txt"
        cat > "$HARVEST_TASK" << HARVESTEOF
Check ${platform} for a completed AI response.

Use taey_inspect to switch to ${platform} and examine the current state:
- If there is a stop/cancel/generating button visible, the AI is still working. Output: STILL_GENERATING
- If the AI has finished (copy buttons visible, no stop button), extract the response using taey_quick_extract and output:
  RESPONSE_START
  [the extracted text verbatim]
  RESPONSE_END
- If there is an error or the response is too short (under 50 chars), output: EXTRACT_FAILED
HARVESTEOF

        HARVEST_LOG="$LOG_DIR/harvest_${platform}_c${CYCLE}.log"
        log "Running agent (harvest) for $platform..."
        HARVEST_OUT=$(run_agent "$HARVEST_TASK" 25 "$HARVEST_LOG") || true

        if echo "$HARVEST_OUT" | grep -q "STILL_GENERATING"; then
            log "$platform still generating — will retry next cycle"

        elif echo "$HARVEST_OUT" | grep -q "RESPONSE_START"; then
            CONTENT=$(echo "$HARVEST_OUT" | awk '/RESPONSE_START/{found=1;next} /RESPONSE_END/{found=0} found{print}')
            if [[ -n "$CONTENT" ]]; then
                echo "$CONTENT" > "$RESPONSE_FILE"
                log "Response saved: $RESPONSE_FILE ($(wc -c < "$RESPONSE_FILE") bytes)"

                COMPLETE_OUT=$($BUILDER complete --platform "$platform" \
                    --response-file "$RESPONSE_FILE" 2>&1) || {
                    log "Builder complete failed for $platform: $COMPLETE_OUT"
                    escalate "Builder complete failed for $platform cycle $CYCLE: $(echo "$COMPLETE_OUT" | tail -3)"
                    continue
                }
                log "Builder complete: $(echo "$COMPLETE_OUT" | tail -3)"
            else
                log "Empty response content for $platform"
                escalate "Empty response from $platform on cycle $CYCLE"
            fi

        elif echo "$HARVEST_OUT" | grep -q "EXTRACT_FAILED"; then
            log "Extraction failed for $platform"
            $BUILDER fail --platform "$platform" "extract_failed" 2>&1 || true

        else
            log "Unexpected harvest result for $platform: $(echo "$HARVEST_OUT" | tail -5)"
        fi

        sleep 3
    done

    log "=== CYCLE $CYCLE DONE === Sleeping 30s"
    sleep 30
done
