#!/bin/bash
# Replaces launch_team, launch_sft, setup_parallel_hmm
# Usage: ./launch_fleet.sh [bot_type] (default: hmm)

BOT_TYPE=${1:-"hmm"}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source .env if it exists
if [ -f "$REPO_ROOT/.env" ]; then
    source "$REPO_ROOT/.env"
fi

MACHINE=$(hostname)

# Defaults if not in .env
DISPLAYS_MIRA=${DISPLAYS_MIRA:-"chatgpt:2,claude:3,gemini:4,grok:5,perplexity:6"}
DISPLAYS_THOR=${DISPLAYS_THOR:-"perplexity:4,gemini:6,grok:7,claude:8,perplexity:9,claude:10,chatgpt:11,grok:12,chatgpt:13"}

if [[ "$MACHINE" == *"mira"* ]]; then 
    MAPPINGS=$DISPLAYS_MIRA
elif [[ "$MACHINE" == *"thor"* ]]; then
    MAPPINGS=$DISPLAYS_THOR
else
    MAPPINGS=$DISPLAYS_MIRA
fi

echo "🚀 Launching fleet of type: $BOT_TYPE on $MACHINE"

IFS=',' read -ra PAIRS <<< "$MAPPINGS"
for pair in "${PAIRS[@]}"; do
    IFS=':' read -r platform disp <<< "$pair"
    "$SCRIPT_DIR/restart_display.sh" "$disp" "$BOT_TYPE"
    sleep 3
done

echo "✅ Fleet launch complete. Use 'tmux ls' to view active bots."
