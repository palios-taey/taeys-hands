# MCP Tools Plan for Taey-Hands
**Analysis Date**: 2025-11-25
**Context**: Complete review of conversation history, codebase, and existing interface architecture

---

## Executive Summary

The taey-hands project implements browser automation for orchestrating conversations across 5 AI chat interfaces (Claude, ChatGPT, Gemini, Grok, Perplexity). The current implementation has a well-designed unified interface system with atomic phase-based operations, but lacks proper MCP tool exposure for use in Claude Code workflows.

**Current State**:
- ✅ Unified ChatInterface base class with 5 working subclasses
- ✅ Phase-based atomic actions (prepareInput, typeMessage, clickSend, etc.)
- ✅ Screenshot verification system for unverified UI state changes
- ✅ Support for model selection, research modes, file attachments
- ❌ No MCP tools (built basic server but incomplete)
- ❌ Tools are clunky - user keeps writing new code instead of using interfaces

**Jesse's Key Requirements** (from conversation line 4311):
1. **All workflow phases need tools** - 9 phases identified
2. **Paste/cross-pollination functionality** - Copy AI responses between chats
3. **All AIs should have model selection and modes** - Universal features
4. **Function-based tools, not interface-specific** - Use interface parameter
5. **Build one tool at a time and test** - Systematic approach
6. **Use parallel agents for remaining tools** - Efficient development
7. **Each tool uses interface nuances based on entered interface** - Runtime dispatch

---

## Complete Tool List

### Category 1: Session Management (Universal)
**No async hand-off needed - all complete in <10s**

#### 1. `taey_connect`
**Purpose**: Initialize browser automation and connect to specified AI interface
**Input**:
```json
{
  "interface": "claude" | "chatgpt" | "gemini" | "grok" | "perplexity"
}
```
**Output**:
```json
{
  "success": true,
  "sessionId": "taey-1732546123456",
  "interface": "claude",
  "connected": true
}
```
**Implementation**: Calls `ChatInterface.connect()`, stores session state
**Execution Time**: 2-5s (browser launch and page navigation)

#### 2. `taey_disconnect`
**Purpose**: Cleanup and close browser session
**Input**:
```json
{
  "sessionId": "taey-1732546123456"
}
```
**Output**:
```json
{
  "success": true,
  "cleaned": true
}
```
**Implementation**: Calls `ChatInterface.disconnect()`, cleanup temp files
**Execution Time**: 1-2s

#### 3. `taey_new_conversation`
**Purpose**: Start a new chat conversation
**Input**:
```json
{
  "sessionId": "taey-1732546123456"
}
```
**Output**:
```json
{
  "success": true,
  "conversationUrl": "https://claude.ai/chat/abc123",
  "screenshot": "/tmp/taey-claude-1732546123456-new-chat.png"
}
```
**Implementation**: Calls interface-specific `newConversation()` or `startNewChat()`
**Execution Time**: 2-3s

#### 4. `taey_goto_conversation`
**Purpose**: Navigate to existing conversation by URL or ID
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "conversationUrlOrId": "https://claude.ai/chat/abc123" | "abc123"
}
```
**Output**:
```json
{
  "success": true,
  "conversationUrl": "https://claude.ai/chat/abc123",
  "screenshot": "/tmp/taey-claude-1732546123456-loaded.png"
}
```
**Implementation**: Calls `goToConversation()`, builds URL if needed
**Execution Time**: 2-4s

---

### Category 2: Configuration (Interface-Specific Features)
**No async hand-off needed - all complete in <10s**

#### 5. `taey_select_model`
**Purpose**: Select AI model (Opus 4.5, GPT-4, Gemini Pro, etc.)
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude",
  "modelName": "Opus 4.5"
}
```
**Output**:
```json
{
  "success": true,
  "automationCompleted": true,
  "modelName": "Opus 4.5",
  "screenshot": "/tmp/taey-claude-1732546123456-model-selected.png",
  "verificationRequired": true
}
```
**Interface Support**:
- Claude: ✅ Implemented (selectModel method)
- ChatGPT: ✅ Model selector exists
- Gemini: ✅ Model selector exists
- Grok: ✅ Heavy/Fun modes
- Perplexity: ✅ Model dropdown exists

**Implementation**: Dispatch to interface-specific selectors
**Execution Time**: 1-2s

#### 6. `taey_enable_research_mode`
**Purpose**: Enable research/pro search mode
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude" | "perplexity",
  "enabled": true
}
```
**Output**:
```json
{
  "success": true,
  "automationCompleted": true,
  "mode": "research",
  "screenshot": "/tmp/taey-claude-1732546123456-research-enabled.png",
  "verificationRequired": true
}
```
**Interface Support**:
- Claude: ✅ Research mode (setResearchMode)
- Perplexity: ✅ Pro Search mode (enableResearchMode)
- Others: ❌ N/A

**Implementation**: Check interface, dispatch to appropriate method
**Execution Time**: 1-2s

---

### Category 3: File Attachments (Optional Phase)
**No async hand-off needed - completes in <10s per file**

#### 7. `taey_attach_files`
**Purpose**: Attach one or more files to the current conversation
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude",
  "filePaths": [
    "/Users/jesselarose/document1.pdf",
    "/Users/jesselarose/image.png"
  ]
}
```
**Output**:
```json
{
  "success": true,
  "automationCompleted": true,
  "filesAttached": 2,
  "screenshots": [
    "/tmp/taey-claude-1732546123456-file1-attached.png",
    "/tmp/taey-claude-1732546123456-file2-attached.png"
  ],
  "verificationRequired": true
}
```
**Interface Support**:
- Claude: ✅ + menu → "Upload a file"
- ChatGPT: ✅ + menu → "Add photos & files"
- Gemini: ✅ Upload menu → "Upload files"
- Grok: ✅ Attach menu → "Upload a file"
- Perplexity: ✅ Attach button → "Local files"

**Implementation**: Loop through files, call interface-specific `attachFile()`
**Execution Time**: 5-8s per file (Finder navigation + upload)

---

### Category 4: Message Composition (Core Workflow)
**No async hand-off needed - completes in <30s**

#### 8. `taey_type_message`
**Purpose**: Type message into chat input with human-like behavior
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude",
  "message": "Explain quantum computing",
  "humanLike": true,
  "mixedContent": true
}
```
**Output**:
```json
{
  "success": true,
  "automationCompleted": true,
  "messageLength": 25,
  "screenshot": "/tmp/taey-claude-1732546123456-typed.png",
  "verificationRequired": true
}
```
**Implementation**:
- Uses `prepareInput()` to focus (if needed)
- Calls `typeMessage()` with OSA bridge for human-like typing
- Supports mixed content (type + paste) for AI quotes

**Execution Time**: 5-20s depending on message length (human-like typing speed)

#### 9. `taey_send_message`
**Purpose**: Submit the typed message
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude"
}
```
**Output**:
```json
{
  "success": true,
  "automationCompleted": true,
  "screenshot": "/tmp/taey-claude-1732546123456-sent.png",
  "verificationRequired": true
}
```
**Implementation**: Calls `clickSend()` - presses Enter key
**Execution Time**: 1-2s

---

### Category 5: Response Handling (REQUIRES ASYNC HAND-OFF)
**30 seconds to 10 minutes - MUST use job queue pattern**

#### 10. `taey_wait_response_start`
**Purpose**: Start async job to wait for AI response
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude",
  "timeout": 600000
}
```
**Output** (returns immediately):
```json
{
  "success": true,
  "jobId": "response-wait-1732546123456",
  "status": "started",
  "estimatedTime": "30s-10min"
}
```
**Implementation**:
- Spawns detached Node process
- Calls `waitForResponse()` with Fibonacci polling
- Writes status to `/tmp/response-wait-{jobId}-status.json`
- Writes result to `/tmp/response-wait-{jobId}-result.json`

**Execution Time**: <2s (job spawn only)

#### 11. `taey_wait_response_status`
**Purpose**: Check status of response wait job
**Input**:
```json
{
  "jobId": "response-wait-1732546123456"
}
```
**Output**:
```json
{
  "jobId": "response-wait-1732546123456",
  "status": "running" | "complete" | "failed",
  "phase": "waiting" | "stable_1" | "stable_2" | "complete",
  "elapsed": 45,
  "currentScreenshot": "/tmp/taey-claude-1732546123456-t45s.png"
}
```
**Implementation**: Read status JSON file
**Execution Time**: <1s

#### 12. `taey_wait_response_result`
**Purpose**: Get completed response
**Input**:
```json
{
  "jobId": "response-wait-1732546123456"
}
```
**Output**:
```json
{
  "success": true,
  "status": "complete",
  "responseText": "Quantum computing is...",
  "responseLength": 2543,
  "elapsedSeconds": 67,
  "screenshots": {
    "initial": "/tmp/taey-claude-1732546123456-t0.png",
    "t2s": "/tmp/taey-claude-1732546123456-t2s.png",
    "complete": "/tmp/taey-claude-1732546123456-complete.png"
  }
}
```
**Implementation**: Read result JSON file, return content
**Execution Time**: <2s

---

### Category 6: Response Extraction (Post-Response)
**No async hand-off needed - completes in <5s**

#### 13. `taey_extract_response`
**Purpose**: Extract latest AI response text from conversation
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude"
}
```
**Output**:
```json
{
  "success": true,
  "responseText": "Quantum computing is...",
  "responseLength": 2543,
  "screenshot": "/tmp/taey-claude-1732546123456-extracted.png"
}
```
**Implementation**:
- Scroll to bottom
- Call `getLatestResponse()` with interface-specific selectors
- Capture final screenshot

**Execution Time**: 2-3s

#### 14. `taey_download_artifact`
**Purpose**: Download artifact file from Claude Chat response (Claude-only)
**Input**:
```json
{
  "sessionId": "taey-1732546123456",
  "interface": "claude",
  "downloadPath": "/tmp"
}
```
**Output**:
```json
{
  "success": true,
  "downloaded": true,
  "fileName": "analysis.py",
  "filePath": "/tmp/analysis.py",
  "fileContent": "# Python code..."
}
```
**Interface Support**:
- Claude: ✅ Download button detection (downloadArtifact)
- Others: ❌ N/A

**Implementation**: Check for Download button, click, save file
**Execution Time**: 2-5s

---

### Category 7: Cross-Pollination (NEW - From Jesse's Feedback)
**No async hand-off needed - completes in <10s**

#### 15. `taey_paste_response`
**Purpose**: Copy response from one AI and paste into another AI's input
**Input**:
```json
{
  "sourceSessionId": "taey-claude-123",
  "sourceInterface": "claude",
  "targetSessionId": "taey-grok-456",
  "targetInterface": "grok",
  "messagePrefix": "Claude said:\n\n",
  "messageSuffix": "\n\nWhat do you think?"
}
```
**Output**:
```json
{
  "success": true,
  "sourceResponse": "Quantum computing is...",
  "composedMessage": "Claude said:\n\nQuantum computing is...\n\nWhat do you think?",
  "pastedToTarget": true,
  "screenshots": {
    "source": "/tmp/taey-claude-123-copied.png",
    "target": "/tmp/taey-grok-456-pasted.png"
  }
}
```
**Implementation**:
1. Extract response from source session (`getLatestResponse()`)
2. Compose message with prefix/suffix
3. Type into target session (`typeMessage()` with mixedContent=true)
4. Capture screenshots of both

**Execution Time**: 5-10s depending on response length

---

## Architecture Recommendations

### 1. Function-Based Tool Design

**Jesse's explicit requirement** (line 4311):
> "We shouldn't need a set of tools for each interface, each tool should be function based and then use whatever interface nuances based on the interface that is entered."

**Implementation Pattern**:
```typescript
// ❌ BAD: Interface-specific tools
tools: [
  "taey_claude_send_message",
  "taey_chatgpt_send_message",
  "taey_gemini_send_message"
]

// ✅ GOOD: Function-based with interface parameter
async function taey_send_message(params: {
  sessionId: string;
  interface: InterfaceName;
}) {
  // Runtime dispatch based on interface
  const session = getSession(params.sessionId);
  const interfaceObj = session.getInterface(); // Returns correct subclass

  // Call unified method (works across all interfaces)
  return await interfaceObj.clickSend({
    sessionId: params.sessionId,
    screenshotPath: `/tmp/taey-${params.interface}-${params.sessionId}-sent.png`
  });
}
```

### 2. Session State Management

**Problem**: Multiple tools need to work with same browser session
**Solution**: In-memory session registry

```typescript
class SessionManager {
  private sessions: Map<string, TaeySession> = new Map();

  createSession(interface: InterfaceName): string {
    const sessionId = `taey-${interface}-${Date.now()}`;
    const session = new TaeySession(sessionId, interface);
    this.sessions.set(sessionId, session);
    return sessionId;
  }

  getSession(sessionId: string): TaeySession {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);
    return session;
  }
}

class TaeySession {
  constructor(
    public sessionId: string,
    public interfaceName: InterfaceName,
    public interface?: ChatInterface
  ) {}

  async connect() {
    this.interface = getInterface(this.interfaceName);
    await this.interface.connect();
  }

  getInterface(): ChatInterface {
    if (!this.interface) throw new Error('Session not connected');
    return this.interface;
  }
}
```

### 3. Async Hand-Off Pattern (Response Waiting Only)

**Only `taey_wait_response_*` tools need async hand-off**. All other tools complete in <30s.

**Architecture**:
```
┌─────────────────────────┐
│  taey_wait_response_    │
│  start                  │  Returns jobId in <2s
└───────────┬─────────────┘
            │ spawn detached
            ▼
┌─────────────────────────┐
│  Background Worker      │  30s - 10min
│  - waitForResponse()    │
│  - Fibonacci polling    │
│  - Status updates       │
│  - Screenshot capture   │
└───────────┬─────────────┘
            │ file-based IPC
            ▼
    ┌───────────────┐
    │ Status JSON   │  Polled by:
    │ Result JSON   │  - taey_wait_response_status
    └───────────────┘  - taey_wait_response_result
```

### 4. Interface Nuance Handling

**Examples of interface-specific behavior** (all handled in subclasses):

| Feature | Claude | ChatGPT | Gemini | Grok | Perplexity |
|---------|--------|---------|--------|------|------------|
| **Model Selection** | ✅ data-testid | ✅ Dropdown | ✅ Dropdown | ✅ Heavy/Fun | ✅ Dropdown |
| **Research Mode** | ✅ Tools menu → Research | ❌ | ❌ | ❌ | ✅ Pro Search button |
| **File Attach** | + menu → "Upload a file" | + menu → "Add photos & files" | Upload menu → "Upload files" | Attach → "Upload a file" | Attach → "Local files" |
| **Artifacts** | ✅ Download button | ❌ | ❌ | ❌ | ❌ |
| **Chat Input** | contenteditable | #prompt-textarea | contenteditable | textarea | #ask-input |
| **Response** | div.grid.standard-markdown | [data-message-author-role="assistant"] | p[data-path-to-node] | div.response-content-markdown | [class*="prose"] |

**All differences are encapsulated in interface subclasses**. Tools only need to:
1. Get the correct interface instance for the session
2. Call the unified method (e.g., `attachFile()`)
3. The interface handles the nuances

### 5. Error Handling & Verification

**Key Insight**: Many operations cannot verify UI state changed, only that automation completed.

**Pattern**:
```typescript
async function taey_enable_research_mode(params) {
  const session = sessionManager.getSession(params.sessionId);
  const result = await session.getInterface().enableResearchMode({
    sessionId: params.sessionId
  });

  return {
    success: true,
    automationCompleted: result.automationCompleted,
    screenshot: result.screenshot,
    verificationRequired: true,  // ⚠️ USER MUST CHECK SCREENSHOT
    message: "Automation completed. VERIFY research mode enabled in screenshot."
  };
}
```

**Screenshots are the source of truth** for UI state changes.

---

## Implementation Order

### Phase 1: Foundation (Do First - Test Immediately)
**Build and test ONE tool to validate the pattern**

1. **`taey_connect`** ✅ START HERE
   - Establishes session management pattern
   - Tests interface factory
   - Validates browser automation
   - **Critical**: All other tools depend on this

**Test case**: Connect to claude.ai, verify logged in, take screenshot

### Phase 2: Core Workflow (Sequential)
**Build and test these in order to enable basic workflow**

2. **`taey_new_conversation`**
3. **`taey_type_message`**
4. **`taey_send_message`**
5. **`taey_extract_response`** (without waiting - manual)

**Test case**: Send "Hello" to claude.ai, manually wait 10s, extract response

### Phase 3: Configuration (Parallel - Order doesn't matter)
**Use parallel agents for these**

6. **`taey_select_model`** (Agent 1)
7. **`taey_enable_research_mode`** (Agent 2)
8. **`taey_attach_files`** (Agent 3)

**Test case**: Claude Opus 4.5 + Research mode + 1 file attachment

### Phase 4: Async Response Waiting (Critical - Complex)
**Build this carefully, test thoroughly**

9. **`taey_wait_response_start`**
10. **`taey_wait_response_status`**
11. **`taey_wait_response_result`**

**Test case**: Send message, start wait job, poll status, get final result

### Phase 5: Advanced Features (Parallel)
**Use parallel agents for these**

12. **`taey_download_artifact`** (Agent 1 - Claude-specific)
13. **`taey_paste_response`** (Agent 2 - Cross-pollination)
14. **`taey_goto_conversation`** (Agent 3 - Navigation)
15. **`taey_disconnect`** (Agent 4 - Cleanup)

**Test case**: Full workflow with cross-pollination between Claude and Grok

---

## Example Pseudo-Code: Function-Based Tool Pattern

### Tool Implementation Template

```typescript
// mcp_server/tools/taey_send_message.ts

import { sessionManager } from '../session-manager.js';
import { CallToolRequest } from '@modelcontextprotocol/sdk/types.js';

export async function taey_send_message(
  params: {
    sessionId: string;
    interface: 'claude' | 'chatgpt' | 'gemini' | 'grok' | 'perplexity';
  }
): Promise<ToolResult> {

  // 1. Validate inputs
  if (!params.sessionId) {
    throw new Error('sessionId is required');
  }

  // 2. Get session (throws if not found)
  const session = sessionManager.getSession(params.sessionId);

  // 3. Get interface instance (runtime dispatch - correct subclass)
  const interfaceObj = session.getInterface();

  // 4. Call unified method (works across ALL interfaces)
  const result = await interfaceObj.clickSend({
    sessionId: params.sessionId,
    screenshotPath: `/tmp/taey-${params.interface}-${params.sessionId}-sent.png`
  });

  // 5. Return standardized result
  return {
    success: true,
    automationCompleted: result.automationCompleted,
    screenshot: result.screenshot,
    verificationRequired: true,
    message: "Message sent. VERIFY input cleared in screenshot."
  };
}

// Tool registration in server.ts
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name === 'taey_send_message') {
    const result = await taey_send_message(request.params.arguments);
    return {
      content: [{
        type: 'text',
        text: JSON.stringify(result, null, 2)
      }]
    };
  }
  // ... other tools
});
```

### Session Management Pattern

```typescript
// mcp_server/session-manager.ts

import { ChatInterface, getInterface } from '../src/interfaces/chat-interface.js';

type InterfaceName = 'claude' | 'chatgpt' | 'gemini' | 'grok' | 'perplexity';

class TaeySession {
  public interface?: ChatInterface;

  constructor(
    public sessionId: string,
    public interfaceName: InterfaceName
  ) {}

  async connect(): Promise<void> {
    // getInterface() returns correct subclass (ClaudeInterface, ChatGPTInterface, etc.)
    this.interface = getInterface(this.interfaceName);
    await this.interface.connect();
  }

  getInterface(): ChatInterface {
    if (!this.interface) {
      throw new Error(`Session ${this.sessionId} not connected. Call taey_connect first.`);
    }
    return this.interface;
  }

  async disconnect(): Promise<void> {
    if (this.interface) {
      await this.interface.disconnect();
      this.interface = undefined;
    }
  }
}

class SessionManager {
  private sessions: Map<string, TaeySession> = new Map();

  createSession(interfaceName: InterfaceName): string {
    const sessionId = `taey-${interfaceName}-${Date.now()}`;
    const session = new TaeySession(sessionId, interfaceName);
    this.sessions.set(sessionId, session);
    return sessionId;
  }

  getSession(sessionId: string): TaeySession {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }
    return session;
  }

  deleteSession(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.disconnect(); // Cleanup
      this.sessions.delete(sessionId);
    }
  }

  listSessions(): { sessionId: string; interface: string; connected: boolean }[] {
    return Array.from(this.sessions.values()).map(s => ({
      sessionId: s.sessionId,
      interface: s.interfaceName,
      connected: s.interface !== undefined
    }));
  }
}

export const sessionManager = new SessionManager();
```

### Interface-Specific Nuance Example

```typescript
// Example: File attachment with interface nuances

// User calls:
taey_attach_files({
  sessionId: "taey-claude-123",
  interface: "claude",
  filePaths: ["/tmp/doc.pdf"]
});

// Tool implementation:
const session = sessionManager.getSession("taey-claude-123");
const interfaceObj = session.getInterface(); // Returns ClaudeInterface instance

// Calls ClaudeInterface.attachFile() which:
// 1. Clicks [data-testid="input-menu-plus"]
// 2. Clicks text="Upload a file"
// 3. Uses Cmd+Shift+G navigation
// 4. Returns screenshot for verification

// vs. ChatGPT:
taey_attach_files({
  sessionId: "taey-chatgpt-456",
  interface: "chatgpt",
  filePaths: ["/tmp/doc.pdf"]
});

// Same tool code, but getInterface() returns ChatGPTInterface which:
// 1. Clicks [data-testid="composer-plus-btn"]
// 2. Clicks text="Add photos & files"
// 3. Uses Cmd+Shift+G navigation
// 4. Returns screenshot for verification

// ALL nuances are in the interface subclasses.
// Tools don't need to know the differences!
```

---

## Key Workflow Patterns

### Pattern 1: Simple Request (No Files, No Research)

```typescript
// 1. Connect
const { sessionId } = await taey_connect({ interface: "claude" });

// 2. Start new chat
await taey_new_conversation({ sessionId });

// 3. Type and send
await taey_type_message({
  sessionId,
  interface: "claude",
  message: "What is quantum computing?"
});
await taey_send_message({ sessionId, interface: "claude" });

// 4. Wait for response (async pattern)
const { jobId } = await taey_wait_response_start({
  sessionId,
  interface: "claude",
  timeout: 120000
});

// 5. Poll status
let status;
do {
  status = await taey_wait_response_status({ jobId });
  await sleep(10000); // Wait 10s between polls
} while (status.status === "running");

// 6. Get result
const result = await taey_wait_response_result({ jobId });
console.log(result.responseText);

// 7. Cleanup
await taey_disconnect({ sessionId });
```

### Pattern 2: Research Request with Files

```typescript
// 1-2. Connect and new chat
const { sessionId } = await taey_connect({ interface: "claude" });
await taey_new_conversation({ sessionId });

// 3. Configure: Opus 4.5 + Research mode
await taey_select_model({
  sessionId,
  interface: "claude",
  modelName: "Opus 4.5"
});
await taey_enable_research_mode({
  sessionId,
  interface: "claude",
  enabled: true
});

// 4. Attach files
await taey_attach_files({
  sessionId,
  interface: "claude",
  filePaths: [
    "/Users/jesselarose/DNA_ROSETTA_STONE_THEORY.md",
    "/Users/jesselarose/wave_communicator.py"
  ]
});

// 5-9. Type, send, wait, extract (same as Pattern 1)
// ...

// 10. Download artifact (Claude-specific)
const artifact = await taey_download_artifact({
  sessionId,
  interface: "claude",
  downloadPath: "/tmp"
});
console.log(`Downloaded: ${artifact.fileName}`);

// 11. Cleanup
await taey_disconnect({ sessionId });
```

### Pattern 3: Cross-Pollination (AI-to-AI)

```typescript
// 1. Connect to both AIs
const claudeSession = await taey_connect({ interface: "claude" });
const grokSession = await taey_connect({ interface: "grok" });

// 2. Send to Claude
await taey_new_conversation({ sessionId: claudeSession.sessionId });
await taey_type_message({
  sessionId: claudeSession.sessionId,
  interface: "claude",
  message: "Explain wave-particle duality"
});
await taey_send_message({
  sessionId: claudeSession.sessionId,
  interface: "claude"
});

// 3. Wait for Claude's response
const claudeJob = await taey_wait_response_start({
  sessionId: claudeSession.sessionId,
  interface: "claude"
});
// ... poll until complete ...
const claudeResult = await taey_wait_response_result({
  jobId: claudeJob.jobId
});

// 4. Cross-pollinate to Grok
await taey_new_conversation({ sessionId: grokSession.sessionId });
await taey_paste_response({
  sourceSessionId: claudeSession.sessionId,
  sourceInterface: "claude",
  targetSessionId: grokSession.sessionId,
  targetInterface: "grok",
  messagePrefix: "Claude explained wave-particle duality like this:\n\n",
  messageSuffix: "\n\nCan you verify this and add your perspective?"
});
await taey_send_message({
  sessionId: grokSession.sessionId,
  interface: "grok"
});

// 5. Wait for Grok's response
const grokJob = await taey_wait_response_start({
  sessionId: grokSession.sessionId,
  interface: "grok"
});
// ... poll until complete ...
const grokResult = await taey_wait_response_result({
  jobId: grokJob.jobId
});

// 6. Compare responses
console.log("Claude:", claudeResult.responseText);
console.log("Grok:", grokResult.responseText);

// 7. Cleanup
await taey_disconnect({ sessionId: claudeSession.sessionId });
await taey_disconnect({ sessionId: grokSession.sessionId });
```

---

## Testing Strategy

### Test 1: Foundation (taey_connect)
**Goal**: Validate session management and interface dispatch

```bash
# Manual test
node mcp_server/test-connect.mjs

# Expected output:
✓ Session created: taey-claude-1732546123456
✓ Connected to claude.ai
✓ Logged in: true
✓ Screenshot: /tmp/taey-claude-1732546123456-connected.png
```

### Test 2: Basic Workflow
**Goal**: Validate core message flow without async response

```bash
node mcp_server/test-basic-workflow.mjs

# Steps:
1. Connect to claude.ai
2. New conversation
3. Type "Hello world"
4. Send message
5. Manual wait 10 seconds
6. Extract response
7. Disconnect

# Expected: Complete without errors, screenshots at each step
```

### Test 3: Configuration
**Goal**: Validate model selection and research mode

```bash
node mcp_server/test-configuration.mjs

# Steps:
1. Connect to claude.ai
2. Select Opus 4.5
3. Enable Research mode
4. Attach 1 file
5. Verify via screenshots

# Expected: All screenshots show correct state
```

### Test 4: Async Response
**Goal**: Validate job queue pattern

```bash
node mcp_server/test-async-response.mjs

# Steps:
1. Connect, new chat
2. Send message "Explain quantum computing in detail"
3. Start wait job
4. Poll status every 5s
5. Get result when complete
6. Verify response extracted

# Expected:
- Job starts in <2s
- Status updates correctly
- Result retrieved when complete
- No MCP timeout errors
```

### Test 5: Cross-Pollination
**Goal**: Validate paste functionality

```bash
node mcp_server/test-cross-pollination.mjs

# Steps:
1. Connect to claude.ai and grok.com
2. Send question to Claude
3. Wait for response
4. Paste Claude's response to Grok
5. Send to Grok
6. Wait for Grok's response
7. Compare both responses

# Expected: Full workflow completes, both responses extracted
```

---

## Integration with Existing Code

### Files to Leverage (DO NOT REWRITE)

1. **`/Users/jesselarose/taey-hands/src/interfaces/chat-interface.js`**
   - ✅ Use as-is: ChatInterface, ClaudeInterface, ChatGPTInterface, etc.
   - ✅ All methods tested and working
   - ✅ Screenshot verification already implemented
   - ❌ Do not duplicate this logic in tools

2. **`/Users/jesselarose/taey-hands/src/core/browser-connector.js`**
   - ✅ Browser management already working
   - ✅ CDP connection established
   - ❌ Do not create alternative browser setup

3. **`/Users/jesselarose/taey-hands/src/core/osascript-bridge.js`**
   - ✅ Human-like typing implemented
   - ✅ Cmd+Shift+G navigation working
   - ❌ Do not reimplement keyboard automation

4. **`/Users/jesselarose/taey-hands/src/workflows/claude-research-request.js`**
   - ✅ Example of complete 9-phase workflow
   - ✅ Reference for async job worker implementation
   - ❌ Do not use directly (hardcoded for Claude)

### Files to Create (NEW)

1. **`mcp_server/session-manager.ts`** - Session state registry
2. **`mcp_server/tools/taey_connect.ts`** - Connect tool
3. **`mcp_server/tools/taey_send_message.ts`** - Send tool
4. **`mcp_server/tools/...`** - One file per tool (15 tools total)
5. **`mcp_server/workers/response-waiter.js`** - Async response job
6. **`mcp_server/test-*.mjs`** - Test scripts for each phase

### Files to Modify

1. **`mcp_server/server.ts`** - Register all 15 tools
2. **`mcp_server/job-manager.ts`** - Add response wait job type
3. **`mcp_server/package.json`** - Add any missing dependencies

---

## Success Criteria

### Definition of Done (Per Tool)

1. ✅ **Code written** - TypeScript implementation complete
2. ✅ **Tests pass** - Manual test script succeeds
3. ✅ **Screenshots captured** - Verification images saved
4. ✅ **Documentation updated** - Tool added to README
5. ✅ **MCP registered** - Tool appears in Claude Code
6. ✅ **End-to-end validated** - Used in actual workflow

### Project Complete When:

1. All 15 tools implemented and tested
2. All 5 interfaces working (Claude, ChatGPT, Gemini, Grok, Perplexity)
3. Full workflow test passes (Pattern 1, 2, 3)
4. Cross-pollination validated
5. No MCP timeout errors
6. Jesse can use tools without writing new code

---

## Risks and Mitigation

### Risk 1: Tool Hanging (>60s)
**Mitigation**: Only `taey_wait_response_*` uses async pattern. All others <30s.

### Risk 2: Interface Selector Changes
**Mitigation**: Screenshot verification catches failures. Update selectors when broken.

### Risk 3: Session State Corruption
**Mitigation**: Session manager tracks connection state. Fail fast if not connected.

### Risk 4: File Attachment Race Conditions
**Mitigation**: Wait for upload complete (1500ms) before continuing. Verify in screenshot.

### Risk 5: Cross-Interface Copy/Paste
**Mitigation**: Use `typeMessage()` with `mixedContent=true` for proper paste handling.

---

## Next Steps

### Immediate Actions

1. **Create session-manager.ts** - Foundation for all tools
2. **Build taey_connect** - First tool, validate pattern
3. **Test taey_connect** - Ensure session management works
4. **Build taey_new_conversation, taey_type_message, taey_send_message** - Core workflow
5. **Test basic workflow** - Simple message without async response

### After Foundation Complete

6. **Spawn 3 parallel agents** to build configuration tools
7. **Build async response tools** - Critical but complex
8. **Spawn 4 parallel agents** to build advanced features
9. **Integration testing** - All patterns (1, 2, 3)
10. **Documentation** - Update README with examples

---

## Appendix: Interface Method Reference

### Universal Methods (All Interfaces)

```typescript
interface ChatInterface {
  // Connection
  async connect(): Promise<this>
  async disconnect(): Promise<void>
  async isLoggedIn(): Promise<boolean>

  // Navigation
  async startNewChat(): Promise<boolean>
  async newConversation(): Promise<boolean>
  async goToConversation(urlOrId: string): Promise<string>
  async getCurrentConversationUrl(): Promise<string>

  // Input
  async prepareInput(options?): Promise<{ screenshot, automationCompleted }>
  async typeMessage(message, options?): Promise<{ screenshot, automationCompleted }>
  async clickSend(options?): Promise<{ screenshot, automationCompleted }>

  // Response
  async waitForResponse(timeout?, options?): Promise<string>
  async getLatestResponse(): Promise<string>

  // Utilities
  async screenshot(filename?): Promise<string>
}
```

### Interface-Specific Methods

```typescript
// ClaudeInterface
async selectModel(modelName, options?): Promise<{ screenshot, automationCompleted, modelName }>
async setResearchMode(enabled): Promise<boolean>
async downloadArtifact(options?): Promise<{ downloaded, filePath, fileName }>
async attachFile(filePath, options?): Promise<{ screenshot, automationCompleted, filePath }>

// PerplexityInterface
async enableResearchMode(options?): Promise<{ screenshot, automationCompleted }>
async attachFile(filePath, options?): Promise<{ screenshot, automationCompleted, filePath }>
```

### Selectors by Interface

```typescript
const selectors = {
  claude: {
    chatInput: '[contenteditable="true"]',
    sendButton: 'button[type="submit"]',
    responseContainer: 'div.grid.standard-markdown:has(> .font-claude-response-body)',
    newChatButton: 'button[aria-label="New chat"]',
    modelSelector: '[data-testid="model-selector-dropdown"]',
    toolsMenuButton: '#input-tools-menu-trigger',
    researchToggle: 'button:has-text("Research")',
    plusButton: '[data-testid="input-menu-plus"]',
    uploadMenuItem: 'text="Upload a file"',
    downloadButton: 'button[aria-label="Download"]'
  },

  chatgpt: {
    chatInput: '#prompt-textarea',
    sendButton: 'button[data-testid="send-button"]',
    responseContainer: '[data-message-author-role="assistant"]',
    plusButton: '[data-testid="composer-plus-btn"]',
    uploadMenuItem: 'text="Add photos & files"'
  },

  gemini: {
    chatInput: '.ql-editor[contenteditable="true"]',
    sendButton: 'button[aria-label="Send message"]',
    responseContainer: 'p[data-path-to-node]',
    uploadMenuButton: 'button[aria-label="Open upload file menu"]',
    uploadButton: 'button[data-test-id="local-images-files-uploader-button"]'
  },

  grok: {
    chatInput: 'textarea, [contenteditable="true"]',
    sendButton: 'button[type="submit"]',
    responseContainer: 'div.response-content-markdown',
    attachButton: 'button[aria-label="Attach"]',
    uploadMenuItem: 'div[role="menuitem"]:has-text("Upload a file")'
  },

  perplexity: {
    chatInput: '#ask-input, [data-lexical-editor="true"]',
    sendButton: 'button[aria-label*="Submit"]',
    responseContainer: '[class*="prose"]',
    researchButton: 'button[value="research"]',
    attachButton: 'button[data-testid="attach-files-button"]',
    localFilesMenuItem: 'div[role="menuitem"]:has-text("Local files")'
  }
};
```

---

## Questions for Jesse

1. **Cross-pollination prefix/suffix**: Should these be optional/customizable in `taey_paste_response`?
2. **Session cleanup**: Auto-cleanup after inactivity, or manual only?
3. **Screenshot storage**: Keep all screenshots or clean up old ones?
4. **Model names**: Use display names ("Opus 4.5") or model IDs ("claude-opus-4.5")?
5. **Error recovery**: Should tools auto-retry on failures or fail fast?

---

**Document Status**: Ready for implementation
**Next Action**: Create `session-manager.ts` and build `taey_connect` tool
**Estimated Timeline**: 2-3 days for all 15 tools with parallel agents
