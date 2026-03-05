#!/bin/bash
# hmm_worker.sh — HMM enrichment worker using local LLM for UI interaction.
#
# Architecture:
#   - This script handles package builder commands and the enrichment loop
#   - local_llm_agent.py handles only UI interactions (attach, click, send, extract)
#
# Usage:
#   export LLM_API_URL=http://localhost:8080/v1
#   export TMUX_SUPERVISOR=weaver
#   bash ~/taeys-hands/agents/hmm_worker.sh
#
# Worker nodes: Jetson (10.0.0.8), Thor (10.0.0.197)

set -uo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
BUILDER="python3 ${HOME}/embedding-server/isma/scripts/hmm_package_builder.py"
AGENT_DIR="${HOME}/taeys-hands"
AGENT="python3 ${AGENT_DIR}/agents/local_llm_agent.py"
PLATFORMS=("chatgpt" "grok" "gemini")
LOG_DIR="/tmp/hmm_worker_logs"
SUPERVISOR="${TMUX_SUPERVISOR:-weaver}"
NODE_ID="${TAEY_NODE_ID:-$(hostname)}"

# DB settings
export NEO4J_URI="${NEO4J_URI:-bolt://10.0.0.163:7689}"
export REDIS_HOST="${REDIS_HOST:-192.168.100.10}"
export REDIS_PORT="${REDIS_PORT:-6379}"

mkdir -p "$LOG_DIR" /tmp/hmm_packages

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
    local max_turns="${2:-40}"
    local log_file="$3"
    cd "$AGENT_DIR"
    timeout 300 python3 agents/local_llm_agent.py \
        --task-file "$task_file" \
        --max-turns "$max_turns" \
        2>"$log_file"
}

# ── Main loop ─────────────────────────────────────────────────────────────────
log "HMM Worker starting on $NODE_ID"
log "LLM: ${LLM_API_URL:-http://localhost:8080/v1}"
log "Platforms: ${PLATFORMS[*]}"

# Wait for LLM to be ready
for i in {1..30}; do
    check_llm && break
    log "Waiting for LLM server... ($i/30)"
    sleep 10
done
check_llm || { escalate "LLM server not available after 5min — aborting"; exit 1; }
log "LLM server ready"

CYCLE=0
while true; do
    CYCLE=$((CYCLE + 1))
    log "=== CYCLE $CYCLE START ==="

    # Check queue stats
    STATS=$($BUILDER stats 2>/dev/null || echo "stats unavailable")
    log "Queue: $STATS"

    # Detect if queue is empty
    if echo "$STATS" | grep -q "remaining.*0\|0.*remaining\|queue_size.*0"; then
        log "Queue appears empty. Checking..."
        # Try building a package — if nothing available, sleep and retry
        TEST_OUT=$($BUILDER next --platform chatgpt 2>&1 || true)
        if echo "$TEST_OUT" | grep -qiE "empty|no items|nothing"; then
            log "Queue empty. Sleeping 5min then checking again."
            escalate "Queue empty — all items processed. Sleeping 5min."
            sleep 300
            continue
        fi
    fi

    # ── Phase 1: SEND ─────────────────────────────────────────────────────────
    declare -A SENT_PLATFORMS
    for platform in "${PLATFORMS[@]}"; do
        log "--- Building package for $platform ---"

        # Build next package
        BUILD_OUT=$($BUILDER next --platform "$platform" 2>&1) || {
            log "No package for $platform: $BUILD_OUT"
            continue
        }
        log "Builder: $BUILD_OUT"

        # Find package file (most recent .md in /tmp/hmm_packages/)
        PKG_FILE=$(ls -t /tmp/hmm_packages/*.md 2>/dev/null | head -1)
        if [[ -z "$PKG_FILE" ]]; then
            log "No package file found for $platform — skipping"
            continue
        fi
        log "Package: $PKG_FILE"

        # Get analysis prompt (first 500 chars for task file, full prompt separate)
        PROMPT_PREVIEW=$($BUILDER prompt 2>/dev/null | head -c 500 || echo "Analyze the attached HMM package")

        # Write task for agent — send phase
        TASK_FILE="/tmp/hmm_task_send_${platform}.txt"
        cat > "$TASK_FILE" << TASKEOF
HMM Enrichment — SEND PHASE for platform: $platform

Your job: Attach the package file and send the analysis prompt to $platform.

Steps (follow exactly):
1. Press Escape on $platform to dismiss any dialogs (call taey_inspect first)
2. Call taey_inspect('$platform')
3. Call taey_attach('$platform', '$PKG_FILE')
4. Call taey_inspect('$platform') AGAIN — attachment shifts element positions
5. Find the input/entry field from step 4 results and click it with taey_click
6. Call taey_send_message('$platform', 'Analyze the attached HMM package. Respond with MINIFIED JSON on a single line per the format in the package.')
7. Output exactly: SEND_COMPLETE

Do NOT wait for a response. Just send and report SEND_COMPLETE.
TASKEOF

        AGENT_LOG="$LOG_DIR/send_${platform}_cycle${CYCLE}.log"
        log "Running agent (send) for $platform..."
        AGENT_OUT=$(run_agent "$TASK_FILE" 40 "$AGENT_LOG") || true

        if echo "$AGENT_OUT" | grep -q "SEND_COMPLETE"; then
            log "✓ Sent to $platform"
            SENT_PLATFORMS[$platform]=1
        else
            log "Agent did not confirm send for $platform. Last output:"
            echo "$AGENT_OUT" | tail -5
            # Mark as sent anyway if agent ran without error (it may have sent but not confirmed)
            SENT_PLATFORMS[$platform]=1
        fi

        # Brief pause between platforms
        sleep 5
    done

    # ── Wait for responses ────────────────────────────────────────────────────
    log "All sends done. Waiting 90s for initial responses..."
    sleep 90

    # ── Phase 2: HARVEST ──────────────────────────────────────────────────────
    for platform in "${PLATFORMS[@]}"; do
        [[ -z "${SENT_PLATFORMS[$platform]+x}" ]] && { log "Skipping $platform (not sent)"; continue; }

        log "--- Harvesting $platform ---"

        RESPONSE_FILE="/tmp/hmm_response_${platform}_cycle${CYCLE}.txt"

        # Write harvest task
        HARVEST_FILE="/tmp/hmm_task_harvest_${platform}.txt"
        cat > "$HARVEST_FILE" << HARVESTEOF
HMM Enrichment — HARVEST PHASE for platform: $platform

Your job: Extract the completed response from $platform.

Steps:
1. Call taey_inspect('$platform')
2. Check the controls:
   - If STOP/CANCEL button is visible → platform is still generating
     Output exactly: STILL_GENERATING
   - If no stop button AND copy buttons visible → response is complete
     Call taey_quick_extract('$platform') to get the content
     Then output exactly:
     RESPONSE_START
     [paste the full extracted content here verbatim]
     RESPONSE_END
3. If page shows an error or the response is very short (<50 chars), output: EXTRACT_FAILED

Output ONLY one of: STILL_GENERATING, EXTRACT_FAILED, or RESPONSE_START...RESPONSE_END
HARVESTEOF

        HARVEST_LOG="$LOG_DIR/harvest_${platform}_cycle${CYCLE}.log"
        log "Running agent (harvest) for $platform..."
        HARVEST_OUT=$(run_agent "$HARVEST_FILE" 20 "$HARVEST_LOG") || true

        if echo "$HARVEST_OUT" | grep -q "STILL_GENERATING"; then
            log "$platform still generating — will retry next cycle"
            # Re-send to builder queue (don't mark complete)

        elif echo "$HARVEST_OUT" | grep -q "RESPONSE_START"; then
            # Extract content between markers
            RESPONSE_CONTENT=$(echo "$HARVEST_OUT" | \
                awk '/RESPONSE_START/{found=1; next} /RESPONSE_END/{found=0} found{print}')

            if [[ -n "$RESPONSE_CONTENT" ]]; then
                echo "$RESPONSE_CONTENT" > "$RESPONSE_FILE"
                log "Response saved: $RESPONSE_FILE ($(wc -c < "$RESPONSE_FILE") bytes)"

                # Process with builder
                log "Processing response with builder..."
                COMPLETE_OUT=$($BUILDER complete --platform "$platform" \
                    --response-file "$RESPONSE_FILE" 2>&1) || {
                    log "Builder complete failed for $platform: $COMPLETE_OUT"
                    escalate "Builder complete failed for $platform on cycle $CYCLE: $COMPLETE_OUT"
                    continue
                }
                log "Builder complete: $COMPLETE_OUT"
            else
                log "Response content empty for $platform"
                escalate "Empty response content from $platform on cycle $CYCLE"
            fi

        elif echo "$HARVEST_OUT" | grep -q "EXTRACT_FAILED"; then
            log "Extraction failed for $platform"
            $BUILDER fail --platform "$platform" "extract_failed" 2>&1 || true

        else
            log "Unexpected harvest output for $platform:"
            echo "$HARVEST_OUT" | tail -10
        fi

        sleep 5
    done

    unset SENT_PLATFORMS
    declare -A SENT_PLATFORMS

    log "=== CYCLE $CYCLE COMPLETE === Sleeping 30s"
    sleep 30
done
