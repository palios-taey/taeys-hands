#!/bin/bash
# Block raw tmux commands in Bash tool calls.
# Prevents accidental tmux send-keys to wrong sessions.
# All tmux communication should go through structured tools, not raw shell.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -n "$COMMAND" ] && echo "$COMMAND" | grep -qE 'tmux\s+send-keys'; then
    jq -n '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: "BLOCKED: Raw tmux send-keys commands are not allowed. Use structured MCP tools for inter-process communication."
        }
    }'
    exit 0
fi

exit 0
