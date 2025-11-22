#!/bin/bash
# Start Chrome with remote debugging enabled
#
# This script launches Chrome with CDP (Chrome DevTools Protocol)
# so Taey's Hands can connect to existing browser sessions.
#
# IMPORTANT: Close Chrome first, then run this script.
# This preserves all your login sessions and cookies.

DEBUGGING_PORT=9222
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR="$HOME/.chrome-debug-profile"

# Check if Chrome is already running with debugging
if curl -s "http://localhost:$DEBUGGING_PORT/json/version" > /dev/null 2>&1; then
    echo "✓ Chrome debugging already available on port $DEBUGGING_PORT"
    curl -s "http://localhost:$DEBUGGING_PORT/json/version" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  Browser: {d.get(\"Browser\", \"Unknown\")}')"
    exit 0
fi

# Check if Chrome is running without debugging
if pgrep -x "Google Chrome" > /dev/null; then
    echo "⚠️  Chrome is running but debugging is NOT enabled."
    echo ""
    echo "To enable debugging, please:"
    echo "  1. Quit Chrome completely (Cmd+Q)"
    echo "  2. Run this script again"
    echo ""
    echo "Or run Chrome manually with:"
    echo "  $CHROME_PATH --remote-debugging-port=$DEBUGGING_PORT"
    exit 1
fi

# Launch Chrome with debugging (requires separate user-data-dir)
echo "Starting Chrome with remote debugging on port $DEBUGGING_PORT..."
mkdir -p "$USER_DATA_DIR"
"$CHROME_PATH" --remote-debugging-port=$DEBUGGING_PORT --user-data-dir="$USER_DATA_DIR" &

# Wait for Chrome to start
sleep 2

# Verify debugging is available
for i in {1..10}; do
    if curl -s "http://localhost:$DEBUGGING_PORT/json/version" > /dev/null 2>&1; then
        echo "✓ Chrome started with debugging enabled"
        echo ""
        echo "You can now:"
        echo "  1. Log into Claude, ChatGPT, Gemini, Grok in Chrome"
        echo "  2. Run: npm start (in taey-hands directory)"
        exit 0
    fi
    sleep 0.5
done

echo "❌ Failed to start Chrome with debugging"
exit 1
