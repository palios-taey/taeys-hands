#!/bin/bash
# PostToolUse hook for worker nodes (Jetson/Thor).
# After MCP tool calls complete, injects a reminder to continue cycling.
# Prevents workers from stopping to "wait for daemon notifications".
#
# Only activates on worker nodes (not Spark).

HOSTNAME=$(hostname)

# Only run on worker nodes
case "$HOSTNAME" in
    jetson*|thor*) ;;
    *) exit 0 ;;
esac

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only trigger after MCP tool calls that indicate end of a platform cycle
case "$TOOL_NAME" in
    mcp__taeys-hands__taey_quick_extract|mcp__taeys-hands__taey_send_message)
        # Check if there's a pending escalation (worker waiting for Spark response)
        ESCALATION_PENDING=""
        if command -v redis-cli &>/dev/null; then
            ESCALATION_PENDING=$(redis-cli -h 192.168.x.10 -p 6379 GET "taey:${HOSTNAME}:escalation_pending" 2>/dev/null)
        fi

        if [ -n "$ESCALATION_PENDING" ] && [ "$ESCALATION_PENDING" != "(nil)" ]; then
            # Worker is waiting for escalation response from Spark - don't nudge
            exit 0
        fi

        # Inject continue reminder
        jq -n '{
            hookSpecificOutput: {
                hookEventName: "PostToolUse",
                message: "CONTINUE CYCLING. Do NOT wait for daemon notifications. Send to next platform immediately, or if all platforms have been sent to, re-inspect each to check for responses. Start a new enrichment cycle if current cycle is complete."
            }
        }'
        exit 0
        ;;
    *)
        exit 0
        ;;
esac
