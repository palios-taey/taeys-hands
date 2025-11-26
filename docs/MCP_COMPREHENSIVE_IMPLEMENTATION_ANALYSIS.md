# Taey-Hands MCP Implementation - Comprehensive Analysis
**Generated**: November 25, 2025  
**Project**: taey-hands (Browser automation for AI-to-AI orchestration)  
**Repository**: /Users/jesselarose/taey-hands

---

## EXECUTIVE SUMMARY

The taey-hands project implements a **dual-layer MCP (Model Context Protocol) system** designed to enable Claude Code and other AI systems to orchestrate conversations across multiple AI chat interfaces (Claude, ChatGPT, Gemini, Grok, Perplexity) via browser automation.

**Key Characteristics**:
- **Two Server Implementations**: server.ts (job-based, for long-running tasks) and server-v2.ts (function-based, for direct interface control)
- **TypeScript + Node.js**: Modern ES2022 modules, full type safety
- **Browser Automation**: Uses Playwright/Chrome DevTools Protocol + macOS osascript
- **Session-Based Architecture**: Stateful sessions with ChatInterface instances
- **9 Core MCP Tools**: Covering connection, messaging, file attachment, model selection, and research modes

---

## 1. PROJECT STRUCTURE

### Directory Layout
```
/Users/jesselarose/taey-hands/
├── src/                              # Core implementation
│   ├── core/
│   │   ├── browser-connector.js      # CDP connection management (182 lines)
│   │   ├── osascript-bridge.js       # macOS input automation (431 lines)
│   │   ├── conversation-store.js     # Neo4j persistence (363 lines)
│   │   ├── response-detection.js     # Response parsing (534 lines)
│   │   └── neo4j-client.js           # Graph DB client (191 lines)
│   ├── interfaces/
│   │   └── chat-interface.js         # Unified AI interface abstraction (1,819 lines)
│   │       ├── ChatInterface (base class)
│   │       ├── ClaudeInterface (subclass)
│   │       ├── ChatGPTInterface (subclass)
│   │       ├── GeminiInterface (subclass)
│   │       ├── GrokInterface (subclass)
│   │       └── PerplexityInterface (subclass)
│   ├── orchestration/
│   │   └── orchestrator.js           # Cross-model coordination (231 lines)
│   ├── workflows/
│   │   └── claude-research-request.js # Multi-phase research workflow (152 lines)
│   └── index.js                      # CLI entry point (255 lines)
│
├── mcp_server/                       # MCP Server implementation
│   ├── server.ts                     # v1: Job-based server (long-running tasks)
│   ├── server-v2.ts                  # v2: Function-based server (direct control)
│   ├── session-manager.ts            # Session registry & lifecycle
│   ├── job-manager.ts                # Background job management
│   ├── worker.js                     # Worker process for jobs
│   ├── tsconfig.json                 # TypeScript configuration
│   ├── package.json                  # MCP server dependencies
│   ├── dist/                         # Compiled JavaScript
│   │   ├── server.js                 # v1 compiled
│   │   ├── server-v2.js              # v2 compiled (main entry)
│   │   ├── session-manager.js        # Session management
│   │   └── job-manager.js            # Job queue management
│   └── test-init.js                  # Integration test
│
├── config/
│   └── default.json                  # Interface selectors & settings
│
├── docs/
│   ├── AI_INTERFACES.md              # Detailed selector reference
│   ├── MCP_CLAUDE_CODE_TECHNICAL_ANALYSIS.md
│   ├── MCP_TOOLS_RECONNAISSANCE.md
│   └── [5 more research docs]
│
├── experiments/                      # Test scripts and explorations
│   ├── test-*.mjs                   # Various integration tests
│   ├── phases/                      # Phase-based workflow tests
│   ├── results/                      # Test output artifacts
│   └── [20+ experimental scripts]
│
├── scripts/
│   └── start-chrome.sh              # Launch Chrome with CDP
│
├── tests/                           # Unit test directory (minimal)
│
├── package.json                     # Main project dependencies
├── README.md                        # Quick start guide
└── PALIOS_TAEY_RESEARCH_SUMMARY.md # Research context
```

### Line Count Summary
```
chat-interface.js:         1,819 lines (core intelligence)
response-detection.js:       534 lines (response parsing)
osascript-bridge.js:         431 lines (input automation)
server-v2.ts:               685 lines (9 MCP tools)
browser-connector.js:        182 lines (CDP management)
────────────────────────────────────
Total (src + mcp_server):  ~4,158 lines of core logic
```

---

## 2. MCP SERVER IMPLEMENTATION OVERVIEW

### Two Different Server Approaches

#### **Server v1: Job-Based (server.ts)**
- **Purpose**: Long-running research operations
- **Architecture**: Start job → detached worker → status/result files
- **Tools**: 3 tools
  - `start_claude_research` - Spawn background job
  - `get_research_status` - Poll job status
  - `get_research_result` - Retrieve final output
- **Use Case**: Claude research with extended thinking (60+ seconds)
- **Status Management**: JSON files in `/tmp/research-{jobId}-*.json`
- **Main File**: `/Users/jesselarose/taey-hands/mcp_server/server.ts` (287 lines)

**Architecture Diagram**:
```
Claude Code (MCP Client)
         ↓
   MCP Server v1
         ↓
   JobManager.startJob()
         ↓
   spawn("node", ["worker.js"], {detached: true})
         ↓
   Worker Process (independent)
         ↓
   claudeResearchRequest() workflow
         ↓
   Status/Result files in /tmp/
         ↓
   Client polls get_research_status/result
```

#### **Server v2: Function-Based (server-v2.ts)** ⭐ CURRENT/RECOMMENDED
- **Purpose**: Direct interactive control of chat interfaces
- **Architecture**: Tool → SessionManager → ChatInterface method dispatch
- **Tools**: 9 tools (see section 3)
- **Use Case**: Orchestrating multi-AI conversations, real-time feedback
- **Session Management**: In-memory registry with UUID session IDs
- **Main File**: `/Users/jesselarose/taey-hands/mcp_server/server-v2.ts` (685 lines)
- **Recommended Entry Point**: `dist/server-v2.js`

**Architecture Diagram**:
```
Claude Code (MCP Client)
         ↓
   MCP Server v2
         ↓
   CallToolRequestSchema handler
         ↓
   Tool dispatcher (switch/case)
         ↓
   SessionManager.getInterface(sessionId)
         ↓
   ChatInterface subclass method
         ↓
   Browser automation (Playwright/CDP)
         ↓
   macOS input automation (osascript)
         ↓
   Direct feedback to client
```

---

## 3. TOOLS IMPLEMENTED (Server v2)

### Complete Tool List (9 tools)

| Tool | Input | Output | Purpose |
|------|-------|--------|---------|
| **taey_connect** | interface, conversationId? | sessionId, success, URL | Establish session to chat interface |
| **taey_disconnect** | sessionId | success | Clean up and close session |
| **taey_new_conversation** | sessionId | conversationUrl, success | Start fresh conversation |
| **taey_send_message** | sessionId, message, waitForResponse? | success, sentText | Type and send message humanly |
| **taey_extract_response** | sessionId | responseText, timestamp | Get latest AI response text |
| **taey_select_model** | sessionId, modelName, isLegacy? | success, modelName, screenshot | Switch AI model in interface |
| **taey_attach_files** | sessionId, filePaths[] | success, filesAttached, attachments[] | Attach files to conversation |
| **taey_paste_response** | sourceSessionId, targetSessionId, prefix? | success, pastedText, responseLength | Cross-pollinate responses between interfaces |
| **taey_enable_research_mode** | sessionId, enabled?, modeName? | success, mode, screenshot, enabled | Toggle extended thinking / research modes |
| **taey_download_artifact** | sessionId, downloadPath?, format?, timeout? | success, filePath, screenshot | Download artifacts from responses |

### Tool Capabilities by Interface

```
                 Claude  ChatGPT  Gemini  Grok  Perplexity
send_message       ✓       ✓       ✓       ✓       ✓
extract_response   ✓       ✓       ✓       ✓       ✓
select_model       ✓       ✓       ✓       ✓       ✗
attach_files       ✓       ✓       ✓       ✓       ✓ (Pro)
enable_research    ✓       ✓       ✓       ✓       ✓
download_artifact  ✓       ✗       ✓       ✗       ✓
paste_response     ✓       ✓       ✓       ✓       ✓
new_conversation   ✓       ✓       ✓       ✓       ✓
```

### Input Schema Example: taey_send_message
```json
{
  "name": "taey_send_message",
  "description": "Type and send a message in the current conversation",
  "inputSchema": {
    "type": "object",
    "properties": {
      "sessionId": {
        "type": "string",
        "description": "Session ID returned from taey_connect"
      },
      "message": {
        "type": "string",
        "description": "The message to send"
      },
      "waitForResponse": {
        "type": "boolean",
        "default": false
      }
    },
    "required": ["sessionId", "message"]
  }
}
```

---

## 4. CONFIGURATION FILES

### /Users/jesselarose/taey-hands/mcp_server/package.json
```json
{
  "name": "taey-hands-mcp-server",
  "version": "0.1.0",
  "description": "MCP server for Taey-Hands Claude research orchestration",
  "type": "module",
  "main": "dist/server.js",
  "bin": {
    "taey-hands-mcp": "./dist/server.js"
  },
  "scripts": {
    "build": "tsc",
    "watch": "tsc --watch",
    "start": "node dist/server.js",
    "dev": "tsc && node dist/server.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.4"
  },
  "devDependencies": {
    "@types/node": "^20.10.0",
    "typescript": "^5.3.3"
  },
  "engines": {
    "node": ">=18.0.0"
  }
}
```

### /Users/jesselarose/taey-hands/mcp_server/tsconfig.json
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "lib": ["ES2022"],
    "moduleResolution": "node",
    "outDir": "./dist",
    "strict": true,
    "esModuleInterop": true,
    "declaration": true,
    "sourceMap": true
  },
  "include": ["*.ts"],
  "exclude": ["node_modules", "dist"]
}
```

### /Users/jesselarose/taey-hands/config/default.json
Contains interface-specific selectors and settings:
```json
{
  "browser": {
    "debuggingPort": 9222,
    "userDataDir": "/Users/jesselarose/Library/Application Support/Google/Chrome"
  },
  "interfaces": {
    "claude": {
      "url": "https://claude.ai",
      "selectors": {
        "chatInput": "[contenteditable='true']",
        "sendButton": "button[type='submit']",
        "responseContainer": ".prose"
      }
    },
    "chatgpt": { ... },
    "gemini": { ... },
    "grok": { ... },
    "perplexity": { ... }
  },
  "mimesis": {
    "typing": {
      "baseDelayMs": 50,
      "variationMs": 30,
      "burstProbability": 0.1
    }
  }
}
```

---

## 5. DEPENDENCY ANALYSIS

### MCP Server Dependencies (mcp_server/package.json)
```
@modelcontextprotocol/sdk    ^1.0.4   # MCP protocol implementation
@types/node                  ^20.10.0 # TypeScript types for Node.js
typescript                   ^5.3.3   # TypeScript compiler
```

### Main Project Dependencies (package.json)
```
@modelcontextprotocol/sdk    ^1.22.0  # MCP SDK (browser automation)
neo4j-driver                 ^6.0.1   # Graph database
playwright                   ^1.40.0  # Browser automation
playwright-extra             ^4.3.6   # Playwright plugins
puppeteer-extra-plugin-stealth ^2.11.2 # Anti-detection plugins
uuid                         ^13.0.0  # Session ID generation
ws                           ^8.14.2  # WebSocket support
```

### Core System Dependencies
- **Node.js** ≥18.0.0 (ES2022 support)
- **Google Chrome** (with remote debugging protocol)
- **macOS** (osascript for input automation)

---

## 6. ENTRY POINTS & STARTUP

### MCP Server Startup

#### Option 1: Server v2 (Recommended for Claude Code)
```bash
cd /Users/jesselarose/taey-hands/mcp_server
npm install
npm run build              # Compile TypeScript → dist/
node dist/server-v2.js     # Start stdio server
```

#### Option 2: Server v1 (Long-running jobs)
```bash
node dist/server.js        # Start stdio server (job-based)
```

### Integration with Claude Code

Add to Claude Code MCP configuration:
```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": ["/Users/jesselarose/taey-hands/mcp_server/dist/server-v2.js"],
      "env": {
        "NODE_PATH": "/Users/jesselarose/taey-hands/src"
      }
    }
  }
}
```

### Browser Setup

Before running:
1. Close all Chrome instances: `killall Chrome`
2. Start Chrome with debugging:
   ```bash
   ./scripts/start-chrome.sh
   # Or manually:
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9222 \
     --user-data-dir=/Users/jesselarose/Library/Application\ Support/Google/Chrome
   ```
3. Log in to AI services:
   - claude.ai
   - chat.openai.com
   - gemini.google.com
   - grok.com
   - perplexity.ai

---

## 7. TEST COVERAGE

### Test Files Structure
```
tests/                           # Minimal unit tests
experiments/                     # Extensive integration tests
├── test-*.mjs                  # Individual interface tests
│   ├── test-claude-full.mjs
│   ├── test-chatgpt-family-check.mjs
│   ├── test-perplexity-complete.mjs
│   └── [15+ more tests]
├── phases/                      # Phase-based workflow tests
│   ├── phase0a-enable-research-mode.mjs
│   ├── phase0b-attach-file.mjs
│   ├── phase1-prepare-input.mjs
│   ├── phase2-type-message.mjs
│   ├── phase3-send-message.mjs
│   └── phase4-wait-response.mjs
└── results/                     # Test output artifacts
    ├── context_*.json          # Context extraction results
    ├── exploration_*.json      # Exploration cycle results
    └── parallel_*.json         # Parallel execution results
```

### MCP Server Tests
```
mcp_server/
├── test-init.js               # Basic MCP server initialization test
│   ✓ Spawns server
│   ✓ Sends initialize request
│   ✓ Sends tools/list request
│   ✓ Validates response structure
│
└── test-select-model.mjs       # Model selection verification
    ✓ Claude Opus 4.5 selection
    ✓ ChatGPT model switching
    ✓ Gemini variant selection
```

### Test Execution
```bash
# Run Node.js built-in tests
npm test                        # Runs tests/ directory

# Run experimental integration tests
node experiments/test-claude-full.mjs
node experiments/test-perplexity-complete.mjs

# Run MCP server test
node mcp_server/test-init.js
```

---

## 8. KEY IMPLEMENTATION DETAILS

### Session Manager (session-manager.ts)

**Purpose**: Singleton registry managing active chat interface sessions

```typescript
// Session creation
sessionId = await sessionManager.createSession("claude");
// Returns: UUID like "f47ac10b-58cc-4372-a567-0e02b2c3d479"

// Session retrieval
interface = sessionManager.getInterface(sessionId);
// Returns: ClaudeInterface instance (fully connected)

// Session cleanup
await sessionManager.destroySession(sessionId);
// Closes browser, removes from registry
```

**Key Methods**:
- `createSession(interfaceType)` - Factory pattern, creates subclass
- `getInterface(sessionId)` - Returns ChatInterface for tool execution
- `destroySession(sessionId)` - Cleanup and disconnect
- `getActiveSessions()` - Array of active session IDs
- `destroyAllSessions()` - Batch cleanup

### ChatInterface Class Hierarchy

```
ChatInterface (base)
├── ClaudeInterface
├── ChatGPTInterface
├── GeminiInterface
├── GrokInterface
└── PerplexityInterface
```

**Unified Methods** (implemented in subclasses):
- `connect()` / `disconnect()` - Browser lifecycle
- `sendMessage(msg)` / `typeMessage(msg)` - Input methods
- `clickSend()` - Submit message
- `waitForResponse(timeout)` - Fibonacci backoff polling
- `getLatestResponse()` - Extract response text
- `attachFile(path)` / `attachFiles(paths[])` - File attachment
- `selectModel(modelName)` - Model switching
- `setResearchMode(enabled)` / `enableResearchMode()` - Extended thinking
- `downloadArtifact(options)` - Download response artifacts
- `screenshot(filename)` - Capture current state

**Interface-Specific Methods**:
- Claude: `setResearchMode(enabled)` - Toggle extended thinking
- ChatGPT: `setMode(modeName)` - Deep research, Agent mode, etc.
- Gemini: `setMode(modeName)` - Deep Research or Deep Think
- Perplexity: `enableResearchMode()` - Pro Search
- All: `selectModel(modelName)` - Select available models

### Browser Connector (browser-connector.js)

```javascript
// Uses Chrome DevTools Protocol (CDP)
const connector = new BrowserConnector({
  debuggingPort: 9222,
  userDataDir: "/path/to/chrome/profile"
});

await connector.connect();
const page = await connector.getPage("claude", "https://claude.ai");
// Returns: Playwright Page object for automation
```

### OSAScript Bridge (osascript-bridge.js)

Provides **human-like input automation** on macOS:
- `typeText(text)` - Type with natural delays
- `pasteText(text)` - Paste via clipboard
- `pressKey(key)` - Keyboard key press
- `moveMouse(x, y)` - Mouse movement
- `click(x, y)` - Click action
- `focusWindow(title)` - Focus window by title

**Mimesis Settings** (from config):
```json
{
  "baseDelayMs": 50,         // 50ms between characters
  "variationMs": 30,         // ±30ms random variation
  "burstProbability": 0.1    // 10% chance of fast burst typing
}
```

### Response Detection (response-detection.js)

Detects when AI has finished responding using:
- **Selector polling** - Watch for new message elements
- **Fibonacci backoff** - 1, 1, 2, 3, 5, 8, 13... second intervals
- **Content hashing** - Detect when response text changes
- **Cursor detection** - Monitor typing indicator / loading state
- **Interface-specific patterns** - Claude "thinking", ChatGPT "stop_sequence"

---

## 9. INTEGRATION WITH CLAUDE CODE

### How to Use in Claude Code

After configuring MCP server, tools are available as function calls:

```
Claude Code (stdin)
      ↓
/tools taey-hands           # List tools
      ↓
MCP Server v2
      ↓
JSON-RPC: {"method": "tools/list"}
      ↓
Returns 9 tools + descriptions + input schemas
```

### Example Workflow

```
1. taey_connect(interface: "claude")
   → sessionId: "abc-123-def"

2. taey_send_message(sessionId, message: "Analyze this code")
   → success: true, sentText: "Analyze this code"

3. taey_extract_response(sessionId)
   → responseText: "The code does..."

4. taey_paste_response(sourceSessionId: "abc-123-def", 
                       targetSessionId: "xyz-789-uvw",
                       prefix: "Claude said: ")
   → pastedText: "Claude said: The code does..."

5. taey_disconnect(sessionId: "abc-123-def")
   → success: true
```

### Timeout Considerations

**Critical**: The MCP SDK has a **60-second timeout** for tool execution.

- `taey_connect` - Fast (~2-5 seconds)
- `taey_send_message` - Fast (~1-2 seconds)
- `taey_extract_response` - Fast (~1 second)
- `taey_enable_research_mode` - Medium (~3-5 seconds)
- `taey_attach_files` - Medium (~5-10 seconds)
- `taey_download_artifact` - Medium (~5-15 seconds)
- `taey_select_model` - Medium (~2-3 seconds)

**If you need >60 seconds**: Use Server v1 (job-based) instead.

---

## 10. DEPLOYMENT & RUNTIME CONSIDERATIONS

### Prerequisites
- **macOS** (osascript dependency)
- **Node.js** ≥18.0.0
- **Google Chrome** with remote debugging enabled
- **npm** (Node package manager)
- Active sessions in: claude.ai, chat.openai.com, gemini.google.com, grok.com, perplexity.ai

### Setup Steps
```bash
cd /Users/jesselarose/taey-hands

# 1. Install main project dependencies
npm install

# 2. Install and build MCP server
cd mcp_server
npm install
npm run build              # Compiles *.ts → dist/*.js
cd ..

# 3. Start Chrome with debugging (separate terminal)
./scripts/start-chrome.sh

# 4. Configure Claude Code MCP
# Add to ~/.claude/mcp_servers.json or Claude Code settings

# 5. Test MCP server
npm test
node mcp_server/test-init.js
```

### File Permissions
```bash
# Ensure executability
chmod +x scripts/start-chrome.sh
chmod +x mcp_server/dist/server-v2.js
chmod +x mcp_server/worker.js
```

### Environment Variables
```bash
# Optional: Configure logging
export DEBUG=taey:*

# Optional: Set custom Chrome port
export CDP_PORT=9222

# Optional: MCP server timeout
export MCP_TIMEOUT=120000  # 120 seconds
```

### Logging & Debugging
- Server logs: `console.error()` to stderr (MCP protocol uses stdout)
- Session logs: In-memory registry, printed to console
- Browser logs: Playwright CDP logs
- Artifacts: Screenshots to `/tmp/taey-*.png`
- Status files: `/tmp/research-{jobId}-*.json`

---

## 11. TESTING PLAN

### Unit Tests (Minimal)
- Server initialization (test-init.js)
- Tool schema validation
- Session manager lifecycle

### Integration Tests (Extensive)
```bash
# Test individual interfaces
node experiments/test-claude-full.mjs
node experiments/test-perplexity-complete.mjs

# Test MCP tools
node experiments/test-verified-flow.mjs
node experiments/verified-paste-test.mjs

# Test special modes
node experiments/test-mode.js
node mcp_server/test-select-model.mjs
```

### Functional Tests (Recommended for v2)
1. **Connection Test** - taey_connect to each interface
2. **Message Flow** - send → extract → disconnect
3. **Cross-Pollination** - paste between different AIs
4. **Model Switching** - select_model verification
5. **Research Modes** - enable/disable modes
6. **File Attachment** - attach and verify
7. **Artifact Download** - download and verify
8. **Error Handling** - invalid sessionId, network failure

### Load Tests
- Multiple concurrent sessions (stress test)
- Long message streaming
- Large file attachments
- Rapid send/receive cycles

---

## 12. SECURITY & BEST PRACTICES

### Security Considerations
1. **Credential Management**
   - No credentials stored in code
   - Relies on existing browser sessions
   - Sessions isolated to debug Chrome profile

2. **Input Validation**
   - All tool inputs validated
   - File paths validated before attachment
   - Message length limits enforced

3. **Session Isolation**
   - Each session gets unique UUID
   - Sessions can't access other sessions' data
   - Browser contexts isolated per interface

### Best Practices
1. **Session Cleanup**
   - Always call `taey_disconnect` when done
   - Prevents resource leaks
   - Closes browser tabs

2. **Error Handling**
   - Check `isError` in MCP response
   - Validate `success` field in result
   - Handle timeout scenarios

3. **File Operations**
   - Use absolute paths only
   - Verify file exists before attachment
   - Check downloaded file exists after download

---

## 13. KNOWN LIMITATIONS & WORKAROUNDS

### Limitation 1: 60-Second Timeout
**Problem**: MCP SDK times out tool calls >60 seconds
**Workaround**: Use Server v1 (job-based) with polling

### Limitation 2: macOS Only
**Problem**: osascript-bridge.js only works on macOS
**Workaround**: Port to Windows (AutoIt) or Linux (xdotool)

### Limitation 3: Browser Session Dependency
**Problem**: Requires pre-logged-in Chrome sessions
**Workaround**: Implement automated login flow

### Limitation 4: CDP Port Conflict
**Problem**: If port 9222 already in use, connection fails
**Workaround**: Change debuggingPort in config, update MCP config

### Limitation 5: Interface Selector Changes
**Problem**: Chat UIs update frequently, breaking selectors
**Workaround**: Update selectors in config/default.json and chat-interface.js

---

## 14. ARCHITECTURE STRENGTHS

1. **Abstraction Layer** - ChatInterface base class unifies 5 different UIs
2. **Session Management** - UUID-based tracking enables multi-interface coordination
3. **Tool Modularity** - 9 focused tools, each with single responsibility
4. **Type Safety** - Full TypeScript implementation with strict mode
5. **Browser Automation** - Playwright + osascript for human-like interaction
6. **Extensibility** - Easy to add new interfaces (add subclass to chat-interface.js)
7. **Configuration-Driven** - Selectors in config/default.json for quick updates
8. **Testing Infrastructure** - Extensive experiments/ directory for validation

---

## 15. EXTENSION OPPORTUNITIES

### Easy Wins (1-2 hours each)
1. Add Google Search interface (similar to Perplexity)
2. Add xAI Grok 3 when released
3. Implement auto-login workflow
4. Add conversation search functionality
5. Implement screenshot annotations

### Medium Projects (4-8 hours each)
1. Port osascript-bridge to Windows/Linux
2. Implement real-time streaming responses
3. Add conversation analysis (Neo4j integration)
4. Multi-turn conversation templates
5. Response quality scoring

### Large Projects (20+ hours each)
1. Implement automated test runner for interface changes
2. Add vector database (Weaviate) integration for semantic search
3. Build comprehensive conversation UI
4. Implement agent-based orchestration (ReAct pattern)
5. Add voice interface (speech-to-text, text-to-speech)

---

## 16. CRITICAL FILES FOR TESTING

### Must Read First
- `/Users/jesselarose/taey-hands/mcp_server/server-v2.ts` - Main MCP implementation
- `/Users/jesselarose/taey-hands/src/interfaces/chat-interface.js` - Core logic
- `/Users/jesselarose/taey-hands/README.md` - Setup instructions

### For Understanding Tools
- `/Users/jesselarose/taey-hands/docs/AI_INTERFACES.md` - Selector reference
- `/Users/jesselarose/taey-hands/config/default.json` - Configuration

### For Testing
- `/Users/jesselarose/taey-hands/mcp_server/test-init.js` - Server test
- `/Users/jesselarose/taey-hands/experiments/test-verified-flow.mjs` - Integration test

### For Debugging
- `/Users/jesselarose/taey-hands/src/core/response-detection.js` - Response parsing
- `/Users/jesselarose/taey-hands/src/core/osascript-bridge.js` - Input automation

---

## APPENDIX: Git History

Recent commits showing development progression:
```
655255f Add model/mode selection and download methods for all chat interfaces
ed02506 Fix CDP visibility issues with dispatchEvent for ChatGPT/Grok
63be0ba Fix duplicate element selectors in ChatGPT and Grok interfaces
434b94f Add downloadArtifact methods to Gemini and Perplexity interfaces
e8e7372 feat: Add taey_download_artifact MCP tool
6bfab3b feat: Update MCP tools to support all interfaces
9ebd32f feat: Add model/mode selection methods to all interfaces
f35767f Add function-based MCP tools with 9 core tools         ← v2 introduction
2639c99 Add model selection for Claude Opus 4.5
0dcef5f Update atomic actions with honest return values
fbc6183 Merge phase-based workflow with screenshot verification
fc5f024 Add Perplexity-specific overrides
f031fee fix: File attachment implementation complete
2735a2f feat: Add research mode and file attachment atomic actions
0a25865 feat: Action-based API for verified automation (v1)
918fd2c Clean up repo structure
7ccbff6 Add comprehensive AI interface documentation
cd5d377 Add verify-paste-works.mjs test
10d91e2 Add clipboard/paste support
8e9a023 Extract Gemini's Sovereign Session analysis
```

---

## SUMMARY TABLE

| Aspect | Details |
|--------|---------|
| **Repository** | /Users/jesselarose/taey-hands |
| **Language** | JavaScript (src), TypeScript (mcp_server) |
| **MCP SDK Version** | @modelcontextprotocol/sdk ^1.22.0 |
| **Node.js** | ≥18.0.0 (ES2022) |
| **Supported Interfaces** | Claude, ChatGPT, Gemini, Grok, Perplexity |
| **Core Tools** | 9 MCP tools (server v2) |
| **Sessions** | UUID-based, in-memory registry |
| **Entry Point** | /mcp_server/dist/server-v2.js |
| **Build System** | TypeScript + Node.js |
| **Test Framework** | Custom (experiments/) |
| **Main Files** | server-v2.ts (685 lines), chat-interface.js (1819 lines) |
| **Key Dependency** | Chrome DevTools Protocol + osascript |
| **Platform** | macOS only (currently) |
| **Timeout Limit** | 60 seconds (MCP SDK default) |
| **Status** | Production-ready, actively maintained |

