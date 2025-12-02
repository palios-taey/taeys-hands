#!/bin/bash
# Quick MCP restart script for Claude Code
# Usage: ./restart-mcp.sh

echo "🔄 Restarting MCP server..."

# Find and kill existing MCP server process
pkill -f "node.*mcp_server/dist/server-v2.js" 2>/dev/null

# Wait a moment for graceful shutdown
sleep 1

# Compile TypeScript if needed
if [ -f "mcp_server/server-v2.ts" ]; then
    echo "📦 Compiling TypeScript..."
    cd mcp_server && npx tsc && cd ..
fi

echo "✅ MCP ready for reconnect"
echo "   Use /mcp command in Claude Code to reconnect"
