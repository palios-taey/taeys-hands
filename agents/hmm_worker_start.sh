#!/bin/bash
# hmm_worker_start.sh — Launch autonomous HMM enrichment agent
#
# Starts Qwen3.5 as a continuous autonomous agent with full MCP tool access.
# NOT a script — the LLM manages the entire enrichment workflow.
#
# Usage:
#   bash ~/taeys-hands/agents/hmm_worker_start.sh
#
# Prerequisites:
#   - Qwen3.5-35B-A3B running on localhost:8080
#   - Firefox with chat platform tabs on DISPLAY
#   - taeys-hands MCP server (started automatically by the agent)

set -uo pipefail

NODE_ID="${TAEY_NODE_ID:-$(hostname)}"
DISPLAY="${DISPLAY:-:1}"
export DISPLAY

echo "[$(date '+%H:%M:%S')] HMM Worker starting on $NODE_ID (DISPLAY=$DISPLAY)"

# ── Environment ──────────────────────────────────────────────────────────────
export LLM_API_URL="${LLM_API_URL:-http://localhost:8080/v1}"
export LLM_MODEL="${LLM_MODEL:-}"  # auto-detect from server
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-8192}"
export LLM_TEMPERATURE="${LLM_TEMPERATURE:-0.3}"  # low temp for reliable tool use

export WEAVIATE_URL="${WEAVIATE_URL:-http://10.0.0.163:8088}"
export REDIS_HOST="${REDIS_HOST:-192.168.100.10}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export NEO4J_URI="${NEO4J_URI:-bolt://10.0.0.163:7689}"
export TAEY_NODE_ID="$NODE_ID"
export TMUX_SUPERVISOR="${TMUX_SUPERVISOR:-weaver}"

# ── Wait for LLM server ─────────────────────────────────────────────────────
echo "Checking LLM server at $LLM_API_URL..."
for i in $(seq 1 30); do
    if curl -sf "${LLM_API_URL}/models" >/dev/null 2>&1; then
        MODEL=$(curl -sf "${LLM_API_URL}/models" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo "unknown")
        echo "LLM ready: $MODEL"
        break
    fi
    echo "  Waiting for LLM... ($i/30)"
    sleep 10
done

if ! curl -sf "${LLM_API_URL}/models" >/dev/null 2>&1; then
    echo "ERROR: LLM not ready after 5 minutes. Exiting."
    exit 1
fi

# ── Ensure directories ──────────────────────────────────────────────────────
mkdir -p /tmp/hmm_packages /tmp/hmm_responses /tmp/hmm_worker_logs

# ── Navigate all platforms to fresh pages ─────────────────────────────────
# Stale page state (existing conversations, preference dialogs) breaks
# the attach workflow. Start every cycle from a clean slate.
echo "Navigating platforms to fresh pages..."
navigate_to() {
    local shortcut="$1" url="$2" name="$3"
    xdotool key "$shortcut"
    sleep 1
    xdotool key ctrl+l
    sleep 0.3
    echo -n "$url" | xsel --clipboard --input
    xdotool key ctrl+v
    sleep 0.2
    xdotool key Return
    sleep 2
    echo "  $name → $url"
}
navigate_to "alt+1" "https://chatgpt.com/?temporary-chat=true" "ChatGPT"
navigate_to "alt+4" "https://grok.com" "Grok"
navigate_to "alt+3" "https://gemini.google.com/app" "Gemini"
echo "All platforms on fresh pages."
sleep 2

# ── Launch continuous agent ──────────────────────────────────────────────────
AGENT_DIR="${HOME}/taeys-hands"
SYSTEM_PROMPT="${AGENT_DIR}/agents/hmm_system_prompt.md"

echo "Launching continuous HMM enrichment agent..."
echo "  System prompt: $SYSTEM_PROMPT"
echo "  Supervisor: $TMUX_SUPERVISOR"
echo "  Platforms: chatgpt, grok, gemini"

cd "$AGENT_DIR"
exec python3 agents/local_llm_agent.py \
    --continuous \
    --system-prompt "$SYSTEM_PROMPT" \
    --max-turns 100 \
    --cycle-pause 30 \
    --verbose \
    "Run one complete HMM enrichment cycle. Build packages for chatgpt, grok, and gemini using: python3 ~/embedding-server/isma/scripts/hmm_package_builder.py next --platform <name>. Get the prompt with: python3 ~/embedding-server/isma/scripts/hmm_package_builder.py prompt. Send each package to its platform using MCP tools (inspect, attach, re-inspect, click input, send_message). Then harvest responses (inspect each platform, extract if complete). Validate JSON responses. Complete packages with: python3 ~/embedding-server/isma/scripts/hmm_package_builder.py complete --platform <name> --response-file <path>. Output CYCLE_COMPLETE when done, QUEUE_EMPTY if no packages available, or ESCALATE: <reason> if stuck."
