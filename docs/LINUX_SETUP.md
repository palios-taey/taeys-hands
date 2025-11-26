# Linux/Ubuntu Setup Guide for Taey's Hands

This guide covers setting up taeys-hands browser automation on Linux (Ubuntu/Debian).

## Prerequisites

### 1. System Dependencies

Install required Linux automation tools:

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y xdotool xclip

# Fedora/RHEL
sudo dnf install -y xdotool xclip

# Arch Linux
sudo pacman -S xdotool xclip
```

**What these do:**
- `xdotool` - Mouse/keyboard automation (equivalent to macOS AppleScript)
- `xclip` - Clipboard operations

### 2. Browser Installation

Install a supported browser (Chrome, Chromium, or Firefox):

```bash
# Option 1: Google Chrome (recommended)
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt-get install -f  # Fix dependencies if needed

# Option 2: Chromium (open source)
sudo apt install chromium-browser

# Option 3: Firefox
sudo apt install firefox
```

### 3. Node.js and npm

Install Node.js 18+ (required for Playwright and MCP server):

```bash
# Using NodeSource repository (recommended)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Verify installation
node --version  # Should be v18+ or v20+
npm --version
```

### 4. Install Project Dependencies

```bash
cd /path/to/taeys-hands
npm install
```

## Display Setup (CRITICAL for headless servers)

If running on a headless server (like DGX Spark), you MUST have X11/Wayland display access.

### Option A: Remote Desktop Session (Recommended for Testing)

1. **Start a desktop session** on the server (GNOME, KDE, XFCE, etc.)
2. **Connect via VNC or RDP** from your local machine
3. **Verify DISPLAY environment variable** is set:
   ```bash
   echo $DISPLAY
   # Should output something like: :0 or :1
   ```

### Option B: Virtual Display (Xvfb) for Automation

For fully automated operation without desktop:

```bash
# Install Xvfb (X Virtual Framebuffer)
sudo apt install xvfb

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Now browser and xdotool will work
```

**Add to ~/.bashrc for persistence:**
```bash
export DISPLAY=:99
```

## Launch Browser with Remote Debugging

### Using the start-browser.sh script (cross-platform):

```bash
cd /path/to/taeys-hands
./scripts/start-browser.sh
```

This script automatically:
- Detects your OS (Linux/macOS)
- Finds available browser (Chrome > Chromium > Firefox)
- Launches with remote debugging enabled on port 9222

### Manual browser launch:

```bash
# Chrome
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/taeys-hands-browser-profile &

# Chromium
chromium-browser --remote-debugging-port=9222 --user-data-dir=/tmp/taeys-hands-browser-profile &

# Firefox
firefox --remote-debugging-port=9222 --profile /tmp/taeys-hands-browser-profile &
```

**Verify browser is running with debugging:**
```bash
curl http://localhost:9222/json/version
# Should return browser version info JSON
```

## Test the Setup

### 1. Test Linux Bridge (xdotool + xclip)

```bash
cd src/core
node linux-bridge.js
```

**Expected output:**
```
Testing Linux bridge...
Current mouse position: 1234, 567
Frontmost app: Google Chrome
✓ Linux bridge working
```

**If it fails:**
- Check DISPLAY is set: `echo $DISPLAY`
- Verify xdotool installed: `which xdotool`
- Try running with sudo (permissions issue): `sudo xdotool getmouselocation`

### 2. Test Browser Connection

```bash
node src/core/browser-connector.js
```

**Expected output:**
```
Detected OS: Linux
✓ Browser debugging already available on port 9222
✓ Connected to Chromium-based browser via CDP
  Active pages: 1

Open pages:
  [0] chrome://newtab/
✓ Disconnected from browser
```

### 3. Test Full Integration

```bash
# Start MCP server (optional, for Claude Desktop integration)
cd mcp_server
npm run build
node build/server-v2.js

# Or test directly with test scripts
node test-integration-basic.mjs
```

## Common Issues and Solutions

### Issue: "xdotool: command not found"
**Solution:**
```bash
sudo apt install xdotool
```

### Issue: "Error: DISPLAY is not set"
**Solution:**
```bash
# If in desktop session
export DISPLAY=:0

# If using Xvfb
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
```

### Issue: "Failed to connect to browser"
**Solution:**
1. Make sure browser is running with debugging:
   ```bash
   pgrep -a chrome  # or firefox
   # Should show --remote-debugging-port=9222
   ```

2. Check debugging endpoint is accessible:
   ```bash
   curl http://localhost:9222/json/version
   ```

3. Kill existing browser and restart:
   ```bash
   pkill -f remote-debugging-port
   ./scripts/start-browser.sh
   ```

### Issue: "xdotool" operations fail silently
**Solution:**
- This usually means wrong window is focused
- Manually click the browser window to focus it
- Or use `wmctrl` to focus programmatically:
  ```bash
  sudo apt install wmctrl
  wmctrl -a "Google Chrome"
  ```

### Issue: File dialog navigation (Ctrl+L) doesn't work
**Solution:**
- Some Linux file dialogs use different shortcuts
- GTK file dialogs: Ctrl+L works
- Qt file dialogs: May need different approach
- Verify in browser manually:
  1. Open any file upload dialog
  2. Press Ctrl+L
  3. Should show location bar where you can type path

## Platform Differences from macOS

| Feature | macOS | Linux |
|---------|-------|-------|
| Automation tool | AppleScript (osascript) | xdotool |
| Clipboard | pbcopy/pbpaste | xclip |
| File dialog shortcut | Cmd+Shift+G | Ctrl+L |
| Browser focus | "Google Chrome" | Window title match |
| Modifier keys | Command (⌘) | Super/Win key |

## Next Steps

1. **Log into AI chat services** in the browser
   - Claude.ai
   - ChatGPT
   - Gemini
   - Grok
   - Perplexity

2. **Test basic automation:**
   ```bash
   node test-integration-basic.mjs
   ```

3. **Integrate with Claude Desktop** (optional):
   - See main README.md for MCP server configuration
   - Configure Claude Desktop to use this MCP server

4. **Run full test suite** (when user logs into desktop):
   ```bash
   # See TESTING_CHECKLIST.md
   node test-ui-with-screenshots.mjs
   ```

## Performance Notes

- **Chrome/Chromium** generally have better CDP support than Firefox
- **Firefox** is fully supported but may have minor compatibility issues
- **Xvfb** adds ~50-100ms latency to automation vs real display
- **Remote desktop** (VNC/RDP) is recommended for testing/debugging

## Security Considerations

- Browser automation has full access to your logged-in sessions
- File paths are typed directly into file dialogs (visible on screen)
- Consider using separate browser profile for automation:
  ```bash
  --user-data-dir=/tmp/taeys-automation-profile
  ```

## Troubleshooting Tips

1. **Enable verbose logging:**
   ```bash
   DEBUG=taey:* node your-script.js
   ```

2. **Watch what automation is doing:**
   - Connect via VNC/RDP to see automation in real-time
   - Take screenshots at each step (built into test scripts)

3. **Check X11 permissions:**
   ```bash
   xhost +local:
   # Allows local applications to access X display
   ```

4. **Monitor xdotool commands:**
   ```bash
   # In separate terminal
   watch -n 0.5 'xdotool getactivewindow getwindowname'
   # Shows currently focused window
   ```

## Support

- GitHub Issues: [taeys-hands/issues](https://github.com/your-org/taeys-hands/issues)
- Platform-specific bugs: Tag with `linux` label
- Include in bug reports:
  - OS: `uname -a`
  - Node version: `node --version`
  - Browser: `google-chrome --version`
  - DISPLAY: `echo $DISPLAY`
  - xdotool version: `xdotool --version`
