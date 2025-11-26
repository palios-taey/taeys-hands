#!/bin/bash
# Cross-platform browser launcher with Chrome DevTools Protocol (CDP)
# Supports macOS (Chrome/Chromium) and Linux (Chrome/Chromium/Firefox)

set -e

# Configuration
REMOTE_DEBUGGING_PORT=9222
USER_DATA_DIR="/tmp/taeys-hands-browser-profile"

# Detect OS
OS="$(uname -s)"
echo "Detected OS: $OS"

# Function to find Chrome/Chromium on macOS
find_chrome_macos() {
  if [ -d "/Applications/Google Chrome.app" ]; then
    echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  elif [ -d "/Applications/Chromium.app" ]; then
    echo "/Applications/Chromium.app/Contents/MacOS/Chromium"
  else
    echo ""
  fi
}

# Function to find Chrome/Chromium/Firefox on Linux
find_browser_linux() {
  # Try Chrome first
  if command -v google-chrome &> /dev/null; then
    echo "google-chrome"
    return
  elif command -v chromium-browser &> /dev/null; then
    echo "chromium-browser"
    return
  elif command -v chromium &> /dev/null; then
    echo "chromium"
    return
  # Fall back to Firefox
  elif command -v firefox &> /dev/null; then
    echo "firefox"
    return
  else
    echo ""
  fi
}

# Find browser based on OS
if [ "$OS" = "Darwin" ]; then
  # macOS
  BROWSER_PATH=$(find_chrome_macos)
  if [ -z "$BROWSER_PATH" ]; then
    echo "ERROR: Chrome or Chromium not found on macOS"
    echo "Please install Google Chrome or Chromium"
    exit 1
  fi

  echo "Starting browser: $BROWSER_PATH"
  echo "Remote debugging port: $REMOTE_DEBUGGING_PORT"
  echo "User data directory: $USER_DATA_DIR"

  # Launch Chrome with CDP enabled
  "$BROWSER_PATH" \
    --remote-debugging-port=$REMOTE_DEBUGGING_PORT \
    --user-data-dir="$USER_DATA_DIR" \
    --no-first-run \
    --no-default-browser-check \
    > /dev/null 2>&1 &

  echo "✓ Browser started (PID: $!)"

elif [ "$OS" = "Linux" ]; then
  # Linux
  BROWSER_CMD=$(find_browser_linux)
  if [ -z "$BROWSER_CMD" ]; then
    echo "ERROR: No supported browser found on Linux"
    echo "Please install one of: google-chrome, chromium-browser, chromium, or firefox"
    exit 1
  fi

  echo "Starting browser: $BROWSER_CMD"
  echo "Remote debugging port: $REMOTE_DEBUGGING_PORT"

  # Check if it's Firefox or Chrome/Chromium
  if [[ "$BROWSER_CMD" == *"firefox"* ]]; then
    echo "Using Firefox with remote debugging"

    # Firefox requires different flags
    # Remote debugging address format: --remote-debugging-port=<port>
    $BROWSER_CMD \
      --remote-debugging-port=$REMOTE_DEBUGGING_PORT \
      --profile "$USER_DATA_DIR" \
      > /dev/null 2>&1 &

    echo "✓ Firefox started (PID: $!)"
  else
    echo "Using Chrome/Chromium with CDP"

    # Chrome/Chromium flags
    $BROWSER_CMD \
      --remote-debugging-port=$REMOTE_DEBUGGING_PORT \
      --user-data-dir="$USER_DATA_DIR" \
      --no-first-run \
      --no-default-browser-check \
      > /dev/null 2>&1 &

    echo "✓ Chrome/Chromium started (PID: $!)"
  fi

else
  echo "ERROR: Unsupported operating system: $OS"
  echo "Only macOS (Darwin) and Linux are supported"
  exit 1
fi

echo ""
echo "Browser should now be accessible at:"
echo "  http://localhost:$REMOTE_DEBUGGING_PORT"
echo ""
echo "To stop the browser, run: pkill -f remote-debugging-port=$REMOTE_DEBUGGING_PORT"
