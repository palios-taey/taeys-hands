#!/bin/bash
# Prevent worker nodes (Jetson, Thor) from modifying code files.
# Spark is the only node that should edit code in this repo.
# When blocked, Claude is directed to escalate to Spark via tmux.

HOSTNAME=$(hostname)

# Only enforce on worker nodes — Spark can edit freely
case "$HOSTNAME" in
    spark*) exit 0 ;;
esac

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

deny() {
    jq -n --arg reason "$1" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: $reason
        }
    }'
    exit 0
}

# Block Edit/Write on any .py, .json, .yaml, .yml, .md file in this repo
if [ "$TOOL_NAME" = "Edit" ] || [ "$TOOL_NAME" = "Write" ]; then
    if echo "$FILE_PATH" | grep -qE '\.(py|json|yaml|yml|md|sh)$'; then
        deny "BLOCKED: Worker nodes cannot modify code. Escalate to Spark Claude.

HOW TO ESCALATE:
1. Run: tmux-send spark1 taeys-hands \"ESCALATION from $HOSTNAME: <describe problem and what you tried>\"
2. STOP and wait for Spark's response (check tmux output)
3. Spark will fix the code and deploy via git push
4. Run: cd ~/taeys-hands && git pull
5. Then restart: /exit and relaunch claude

DO NOT attempt workarounds. DO NOT modify files via Bash."
    fi
fi

# Block Bash commands that modify repo Python files
if [ "$TOOL_NAME" = "Bash" ] && [ -n "$COMMAND" ]; then
    # Catch sed -i, tee, >, >> targeting .py files in taeys-hands
    if echo "$COMMAND" | grep -qE '(sed\s+-i|>\s*\S+\.py|>>\s*\S+\.py|tee\s+\S+\.py)' && \
       echo "$COMMAND" | grep -q 'taeys-hands'; then
        deny "BLOCKED: Cannot modify repo files via Bash on worker nodes. Escalate to Spark Claude.

Run: tmux-send spark1 taeys-hands \"ESCALATION from $HOSTNAME: <describe the issue>\""
    fi
    # Block git commit/add on worker nodes
    if echo "$COMMAND" | grep -qE 'git\s+(commit|add|stash|checkout|reset)'; then
        deny "BLOCKED: Worker nodes cannot make git changes. Only Spark commits code.

Run: tmux-send spark1 taeys-hands \"ESCALATION from $HOSTNAME: <describe the issue>\""
    fi
fi

exit 0
