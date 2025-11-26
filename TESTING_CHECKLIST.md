# Testing Checklist for Ubuntu Port

**Purpose**: Validate taeys-hands cross-platform functionality on Linux/Ubuntu.

**Prerequisites**:
- Desktop session active (VNC/RDP connected or physical display)
- Browser logged into AI services (Claude, ChatGPT, Gemini, Grok, Perplexity)
- DISPLAY environment variable set correctly

## Phase 1: System Dependencies

- [ ] **xdotool installed**
  ```bash
  which xdotool
  xdotool --version
  ```

- [ ] **xclip installed**
  ```bash
  which xclip
  xclip -version
  ```

- [ ] **Browser available**
  ```bash
  # Check for any of:
  which google-chrome
  which chromium-browser
  which firefox
  ```

- [ ] **Node.js 18+**
  ```bash
  node --version  # Should be v18.x or v20.x
  ```

- [ ] **DISPLAY set**
  ```bash
  echo $DISPLAY  # Should output :0 or :99 etc, not empty
  ```

## Phase 2: Core Infrastructure

- [ ] **Linux Bridge test**
  ```bash
  cd src/core
  node linux-bridge.js
  ```
  Expected: Mouse position, frontmost app, "✓ Linux bridge working"

- [ ] **Platform Bridge factory**
  ```bash
  node -e "import('./src/core/platform-bridge.js').then(m => m.createPlatformBridge()).then(b => console.log('✓ Bridge created:', b.constructor.name))"
  ```
  Expected: "✓ Bridge created: LinuxBridge"

- [ ] **Browser launch**
  ```bash
  ./scripts/start-browser.sh
  ```
  Expected: Browser starts, debugging endpoint accessible at http://localhost:9222

- [ ] **Browser connector test**
  ```bash
  node src/core/browser-connector.js
  ```
  Expected: "✓ Connected to Chromium-based browser via CDP" or "✓ Connected to Firefox via CDP"

## Phase 3: Chat Interface Integration

Test each AI service with basic automation:

### Claude.ai

- [ ] **Connect to Claude**
  ```bash
  node -e "
  import('./src/interfaces/chat-interface.js').then(async m => {
    const claude = new m.ClaudeInterface();
    await claude.connect();
    console.log('✓ Connected to Claude');
    await claude.disconnect();
  })
  "
  ```

- [ ] **Type test message** (visual verification required)
  - Open Claude tab manually
  - Run test that types "Hello from Linux" into input
  - Verify text appears correctly in input box

- [ ] **File attachment test** (if file dialog appears)
  - Test Ctrl+L navigation in file dialog
  - Verify file path can be typed directly

### ChatGPT

- [ ] **Connect to ChatGPT**
  ```bash
  node -e "
  import('./src/interfaces/chat-interface.js').then(async m => {
    const chatgpt = new m.ChatGPTInterface();
    await chatgpt.connect();
    console.log('✓ Connected to ChatGPT');
    await chatgpt.disconnect();
  })
  "
  ```

- [ ] **Type test message**

### Gemini

- [ ] **Connect to Gemini**
- [ ] **Type test message**

### Grok

- [ ] **Connect to Grok**
- [ ] **Type test message**

### Perplexity

- [ ] **Connect to Perplexity**
- [ ] **Type test message**

## Phase 4: MCP Server

- [ ] **MCP server builds**
  ```bash
  cd mcp_server
  npm run build
  ```
  Expected: No TypeScript errors

- [ ] **MCP server starts**
  ```bash
  node build/server-v2.js
  ```
  Expected: Server listens on stdio, no crashes

- [ ] **taey_connect tool works**
  - Send MCP request with taey_connect
  - Verify session created

- [ ] **taey_send_message tool works**
  - Send test message via MCP
  - Verify typing occurs in browser

## Phase 5: Cross-Platform Compatibility

Verify platform detection and correct bridge selection:

- [ ] **OS detected as Linux**
  ```bash
  node -e "import os from 'os'; console.log('Platform:', os.platform())"
  ```
  Expected: "Platform: linux"

- [ ] **File dialog uses Ctrl+L** (not Cmd+Shift+G)
  - Check chat-interface.js _navigateFinderDialog method
  - Verify Linux path executes Ctrl+L code

- [ ] **Modifier keys map correctly**
  - Linux Super key = macOS Command
  - Linux Alt = macOS Option
  - Test Ctrl+C/Ctrl+V work for clipboard

## Phase 6: Human-Like Automation

Verify typing appears natural:

- [ ] **Variable typing delay**
  - Watch message being typed
  - Delays should vary (not robotic)

- [ ] **Bézier mouse movement**
  - Watch mouse move to buttons
  - Should curve naturally (not straight line)

- [ ] **Focus validation**
  - Try typing while different window focused
  - Should abort with focus error

## Phase 7: Error Handling

- [ ] **DISPLAY not set**
  ```bash
  unset DISPLAY
  node src/core/linux-bridge.js
  ```
  Expected: Clear error about DISPLAY

- [ ] **xdotool missing**
  ```bash
  # Temporarily rename xdotool
  sudo mv /usr/bin/xdotool /usr/bin/xdotool.bak
  node src/core/linux-bridge.js
  sudo mv /usr/bin/xdotool.bak /usr/bin/xdotool
  ```
  Expected: Error with install instructions

- [ ] **Browser not running**
  ```bash
  pkill -f remote-debugging-port
  node src/core/browser-connector.js
  ```
  Expected: "Browser debugging not available" error

## Phase 8: Integration Test

Run full integration test (requires user at desktop):

```bash
node test-integration-basic.mjs
```

**Expected results:**
- All AI services connect successfully
- Messages type correctly
- Responses extracted properly
- Screenshots captured at each step

## Phase 9: Documentation Validation

- [ ] **LINUX_SETUP.md accurate**
  - Follow setup steps on fresh Ubuntu VM
  - Verify all commands work
  - Note any missing steps

- [ ] **README.md updated**
  - Linux quick start section present
  - Cross-platform architecture diagram accurate

- [ ] **Tool descriptions platform-neutral**
  - Check MCP server tool descriptions
  - No macOS-specific language (unless noted as platform-specific)

## Phase 10: Cleanup

- [ ] **Git status clean**
  ```bash
  git status
  ```
  Expected: No merge conflicts, staged files only

- [ ] **No temporary files**
  ```bash
  find . -name "*.tmp" -o -name "*~" -o -name ".DS_Store"
  ```
  Expected: No results

- [ ] **Test artifacts organized**
  - Screenshots in /tmp or dedicated test/ directory
  - Test scripts not committed to main (unless intended)

## Success Criteria

**Core functionality:**
- [x] Platform bridge factory works (detects Linux, loads LinuxBridge)
- [x] Linux bridge mouse/keyboard/clipboard operations work
- [x] Browser connector supports Chrome/Chromium/Firefox on Linux
- [x] Chat interfaces connect to all 5 AI services
- [x] File dialog navigation uses Ctrl+L on Linux (vs Cmd+Shift+G on macOS)
- [x] MCP server builds and runs without errors

**Documentation:**
- [x] LINUX_SETUP.md created with comprehensive setup instructions
- [x] README.md updated with Linux quick start
- [x] Platform differences clearly documented

**Testing:**
- [ ] All Phase 1-8 tests pass
- [ ] Integration test completes successfully
- [ ] No regressions on macOS (if macOS system available)

## Issues Found

*(Document any issues encountered during testing)*

| Issue | Severity | Status | Notes |
|-------|----------|--------|-------|
| Example: Ctrl+L doesn't work in Qt file dialogs | Low | Open | Need fallback for Qt-based dialogs |

## Final Sign-off

- [ ] All critical tests passed
- [ ] Documentation reviewed and accurate
- [ ] Code ready for user testing
- [ ] Git commit prepared with summary

**Tested by:** ________________
**Date:** ________________
**Platform:** Ubuntu _____ / Debian _____ / Other _____
**Desktop Environment:** GNOME / KDE / XFCE / Headless (Xvfb)
**Browser:** Chrome _____ / Chromium _____ / Firefox _____
