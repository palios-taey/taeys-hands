# Taey-Hands MCP Testing - Quick Start Guide

## 5-Minute Setup

### 1. Install & Build
```bash
cd /Users/REDACTED/taey-hands
npm install
cd mcp_server
npm install
npm run build
cd ..
```

### 2. Start Chrome (in separate terminal)
```bash
./scripts/start-chrome.sh
# Login to: claude.ai, chat.openai.com, gemini.google.com, grok.com, perplexity.ai
```

### 3. Run MCP Server Test
```bash
node mcp_server/test-init.js
```

Expected output:
```
Testing MCP server initialization...
Server output: Taey-Hands MCP server running on stdio
✓ Server initialized successfully
✓ Server responded to requests
Tools available: 9
  - taey_connect
  - taey_disconnect
  - taey_new_conversation
  ...
```

---

## Comprehensive Test Suite

### Unit Tests
```bash
npm test                           # Basic Node.js tests (tests/ directory)
```

### MCP Server Tests
```bash
# Test server initialization
node mcp_server/test-init.js

# Test model selection
node mcp_server/test-select-model.mjs
```

### Integration Tests (Experiments)
```bash
# Test Claude interface
node experiments/test-claude-full.mjs

# Test ChatGPT interface
node experiments/test-chatgpt-family-check.mjs

# Test Perplexity interface
node experiments/test-perplexity-complete.mjs

# Test verified workflow
node experiments/test-verified-flow.mjs

# Test cross-AI paste
node experiments/verified-paste-test.mjs
```

### Phase-Based Tests
```bash
# Test individual automation phases
node experiments/phases/phase0a-enable-research-mode.mjs
node experiments/phases/phase0b-attach-file.mjs
node experiments/phases/phase1-prepare-input.mjs
node experiments/phases/phase2-type-message.mjs
node experiments/phases/phase3-send-message.mjs
node experiments/phases/phase4-wait-response.mjs
```

---

## Manual Testing with Claude Code

### 1. Configure MCP in Claude Code

Add to MCP configuration (e.g., ~/.claude/mcp_servers.json):
```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": ["/Users/REDACTED/taey-hands/mcp_server/dist/server-v2.js"]
    }
  }
}
```

### 2. Restart Claude Code

### 3. Test Tools
```
/tools taey-hands              # List all 9 tools
```

### 4. Use Tools
```
# Single AI conversation
taey_connect(interface: "claude")
taey_send_message(sessionId: "...", message: "Analyze this code")
taey_extract_response(sessionId: "...")
taey_disconnect(sessionId: "...")

# Multi-AI orchestration
taey_connect(interface: "claude")
taey_connect(interface: "chatgpt")
taey_paste_response(sourceSessionId: "claude-id", 
                   targetSessionId: "chatgpt-id",
                   prefix: "Claude said: ")
```

---

## Key Test Files by Purpose

| Purpose | File | Command |
|---------|------|---------|
| Server starts | test-init.js | `node mcp_server/test-init.js` |
| Tools are callable | test-select-model.mjs | `node mcp_server/test-select-model.mjs` |
| Claude works | test-claude-full.mjs | `node experiments/test-claude-full.mjs` |
| ChatGPT works | test-chatgpt-family-check.mjs | `node experiments/test-chatgpt-family-check.mjs` |
| Perplexity works | test-perplexity-complete.mjs | `node experiments/test-perplexity-complete.mjs` |
| Full workflow | test-verified-flow.mjs | `node experiments/test-verified-flow.mjs` |
| Cross-AI copy | verified-paste-test.mjs | `node experiments/verified-paste-test.mjs` |

---

## Debugging Failed Tests

### Issue: "Chrome not found"
```bash
# Fix: Start Chrome with debugging
./scripts/start-chrome.sh
# Or manually: killall Chrome first if needed
```

### Issue: "Port 9222 already in use"
```bash
# Check what's using port 9222
lsof -i :9222

# Kill existing process
kill -9 <PID>

# Or change port in config/default.json
```

### Issue: "Session timeout"
```bash
# Tools taking longer than expected (>60s)?
# This is the MCP SDK timeout limit
# Use Server v1 (job-based) instead:
node mcp_server/dist/server.js
```

### Issue: "Not logged in"
```bash
# Chrome debug window is open but not logged in?
# In the debug Chrome window, navigate to:
# - https://claude.ai - login
# - https://chat.openai.com - login
# - https://gemini.google.com - login
# - https://grok.com - login
# - https://perplexity.ai - login
# Sessions persist in ~/.chrome-debug-profile
```

### Issue: "Selector not found"
```bash
# If tests fail with "selector not found":
# 1. Check AI interface hasn't updated (selectors change frequently)
# 2. Update selectors in config/default.json
# 3. Update chat-interface.js methods
# See docs/AI_INTERFACES.md for detailed selectors
```

---

## Expected Test Output

### Successful Test
```
✓ Connection established
✓ Message sent: "Hello, what is consciousness?"
✓ Response received: 1245 characters
✓ Screenshot saved: /tmp/taey-claude-1234567890.png
✓ Session disconnected
```

### Test with Error
```
✗ Connection failed: Session timeout
Error: Session not found after 30 seconds
Debug: Check Chrome is running with --remote-debugging-port=9222
```

---

## Performance Targets

| Operation | Target | Observed |
|-----------|--------|----------|
| Connect to interface | <5s | 2-4s |
| Send message | <2s | 1-2s |
| Extract response (ready) | <1s | 0.5-1s |
| Select model | <3s | 2-3s |
| Attach file | <10s | 5-8s |
| Download artifact | <15s | 8-12s |
| Disconnect | <2s | 1-2s |

---

## Monitoring Test Results

### Check Test Results Directory
```bash
ls -la experiments/results/
# Shows: context_*.json, exploration_*.json, parallel_*.json
```

### Parse Test Output
```bash
# Extract responses from test output
cat experiments/results/context_*.json | jq '.sessionResponses'
```

---

## Quick Troubleshooting Checklist

- [ ] Chrome is running with `--remote-debugging-port=9222`
- [ ] You're logged into all AI services in debug Chrome window
- [ ] `npm install && npm run build` completed successfully in mcp_server/
- [ ] Port 9222 is not already in use
- [ ] Node.js version ≥18.0.0 (`node --version`)
- [ ] file permissions on scripts: `chmod +x scripts/start-chrome.sh`
- [ ] Check Chrome is NOT the regular non-debug instance (close it first: `killall Chrome`)

---

## Next Steps

1. **Run test-init.js** - Verify MCP server starts
2. **Run test-claude-full.mjs** - Verify Claude interface works
3. **Configure Claude Code MCP** - Add to settings
4. **Test taey_tools in Claude Code** - Use real tool calls
5. **Scale to multi-AI** - Use paste_response tool

---

For detailed documentation, see:
- **Implementation Details**: MCP_COMPREHENSIVE_IMPLEMENTATION_ANALYSIS.md
- **Tool Reference**: AI_INTERFACES.md
- **Architecture**: README.md

