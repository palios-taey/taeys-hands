# Taey-Hands MCP Tools Reference

**Version:** 0.2.0
**Architecture:** Tool → SessionManager → Interface → Method
**Purpose:** Orchestrate AI Family conversations across Claude, ChatGPT, Gemini, Grok, and Perplexity

---

## Table of Contents

1. [Tool Overview](#tool-overview)
2. [Session Management Tools](#session-management-tools)
3. [Message Tools](#message-tools)
4. [Configuration Tools](#configuration-tools)
5. [Cross-Pollination Tools](#cross-pollination-tools)
6. [Validation & Safety Tools](#validation--safety-tools)
7. [Tool Orchestration](#tool-orchestration)
8. [Architecture Analysis](#architecture-analysis)
9. [Rebuild Recommendations](#rebuild-recommendations)

---

## Tool Overview

### Complete Tool List

| Tool | Category | Purpose |
|------|----------|---------|
| `taey_connect` | Session | Connect to chat interface |
| `taey_disconnect` | Session | Disconnect and cleanup |
| `taey_new_conversation` | Session | Start new conversation |
| `taey_send_message` | Message | Type and send message |
| `taey_extract_response` | Message | Extract AI response |
| `taey_select_model` | Config | Select AI model |
| `taey_attach_files` | Message | Attach files to conversation |
| `taey_paste_response` | Cross-Poll | Copy response between sessions |
| `taey_enable_research_mode` | Config | Enable deep thinking modes |
| `taey_download_artifact` | Message | Download generated files |
| `taey_validate_step` | Safety | Validate workflow checkpoint |

---

## Session Management Tools

### taey_connect

**Purpose:** Connect to a chat interface and establish browser automation session

**Parameters:**
- `interface` (required): `"claude" | "chatgpt" | "gemini" | "grok" | "perplexity"`
- `sessionId` (optional): Reuse existing session (mutually exclusive with newSession)
- `newSession` (optional): Create fresh session (mutually exclusive with sessionId)
- `conversationId` (optional): Resume specific conversation by ID or URL

**Returns:**
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "interface": "claude",
  "screenshot": "/tmp/taey-screenshot.png",
  "conversationUrl": "https://...",
  "message": "Connected to claude"
}
```

**Error Conditions:**
- Neither `sessionId` nor `newSession` specified → "Must specify either sessionId or newSession=true"
- Both `sessionId` and `newSession` specified → "Cannot specify both sessionId and newSession=true"
- Invalid interface type → "Unknown interface type"

**Dependencies:**
- Creates Neo4j conversation record when `newSession=true`
- Initializes Playwright browser automation
- Creates session in SessionManager registry

**Implementation Notes:**
- Requires explicit session decision (no defaults)
- Screenshots are saved to verify connection
- Browser is brought to foreground automatically

---

### taey_disconnect

**Purpose:** Disconnect session and cleanup browser resources

**Parameters:**
- `sessionId` (required): Session ID from taey_connect

**Returns:**
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "message": "Session disconnected"
}
```

**Error Conditions:**
- Session not found (warning only, no hard error)

**Dependencies:**
- Calls interface.disconnect() to cleanup browser
- Removes session from SessionManager registry

**Implementation Notes:**
- Safe to call on already-disconnected sessions
- Always cleanup properly to avoid resource leaks

---

### taey_new_conversation

**Purpose:** Start a new conversation in current session

**Parameters:**
- `sessionId` (required): Active session ID

**Returns:**
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "conversationUrl": "https://...",
  "message": "New conversation started"
}
```

**Error Conditions:**
- Session not found → "Session not found: {sessionId}"
- Session disconnected → "Session disconnected: {sessionId}"

**Dependencies:**
- Calls interface.newConversation()
- Gets new conversation URL from interface

**Implementation Notes:**
- Reuses existing session (browser/tab)
- Navigates to fresh conversation page

---

## Message Tools

### taey_send_message

**Purpose:** Type and send a message with optional response waiting

**Parameters:**
- `sessionId` (required): Active session ID
- `message` (required): Message text to send
- `attachments` (optional): Array of file paths (default: [])
- `waitForResponse` (optional): Wait for AI response (default: false)

**Returns (waitForResponse=false):**
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "message": "Message sent",
  "sentText": "...",
  "waitForResponse": false
}
```

**Returns (waitForResponse=true):**
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "message": "Message sent and response received",
  "sentText": "...",
  "waitForResponse": true,
  "responseText": "...",
  "responseLength": 12345,
  "detectionMethod": "streamingClass",
  "detectionConfidence": 0.95,
  "detectionTime": 3421,
  "timestamp": "2025-11-30T12:34:56.789Z"
}
```

**Error Conditions:**
- Validation checkpoint failed → "Validation checkpoint failed: {reason}"
- Attachments required but missing → "Draft plan requires N attachment(s)"
- Response detection failed → Returns error with `isError: true`

**Dependencies:**
- **CRITICAL:** Requires validation checkpoint before sending
- Uses ResponseDetectionEngine when `waitForResponse=true`
- Logs messages to Neo4j ConversationStore
- Calls interface.prepareInput(), typeMessage(), clickSend()

**Implementation Notes:**
- **Validation Enforcement:** Checks ValidationCheckpointStore before sending
- If plan requires attachments, must have `attach_files` step validated
- If no attachments, must have `plan` or `attach_files` step validated
- Uses human-like typing simulation
- Response detection uses platform-specific strategies (see response-detection.js)

---

### taey_extract_response

**Purpose:** Extract the latest AI response from conversation

**Parameters:**
- `sessionId` (required): Active session ID

**Returns:**
```json
{
  "success": true,
  "responseText": "...",
  "timestamp": "2025-11-30T12:34:56.789Z"
}
```

**Error Conditions:**
- Session not found → "Session not found: {sessionId}"
- No response found → May return empty string

**Dependencies:**
- Calls interface.getLatestResponse()
- Logs response to Neo4j ConversationStore

**Implementation Notes:**
- Alternative to `waitForResponse=true` in send_message
- Manual control over when to extract
- Does not use ResponseDetectionEngine

---

### taey_attach_files

**Purpose:** Attach files to conversation using cross-platform file dialog navigation

**Parameters:**
- `sessionId` (required): Active session ID
- `filePaths` (required): Array of absolute file paths

**Returns:**
```json
{
  "automationCompleted": true,
  "filesAttached": 2,
  "attachments": [
    {
      "filePath": "/path/to/file1.md",
      "screenshot": "/tmp/screenshot1.png",
      "automationCompleted": true
    }
  ],
  "screenshot": "/tmp/screenshot-last.png",
  "message": "Automation completed for 2 file(s). VERIFY in screenshot..."
}
```

**Error Conditions:**
- Validation checkpoint failed → "Validation checkpoint failed: {reason}"
- Must have `plan` step validated before attaching

**Dependencies:**
- **CRITICAL:** Requires `plan` step validated
- Creates pending validation checkpoint (validated=false)
- Calls interface.attachFile() for each file
- Uses cross-platform file dialog navigation (Cmd+Shift+G on macOS, Ctrl+L on Linux)

**Implementation Notes:**
- Creates **pending checkpoint** that MUST be validated before continuing
- User must call `taey_validate_step` with `validated=true` after reviewing screenshot
- Checkpoint stores both requiredAttachments (from plan) and actualAttachments (what was attached)

---

### taey_download_artifact

**Purpose:** Download generated files (Claude artifacts, Gemini exports, Perplexity reports)

**Parameters:**
- `sessionId` (required): Active session ID
- `downloadPath` (optional): Directory to save (default: "/tmp")
- `format` (optional): "markdown" or "html" (default: "markdown")
- `timeout` (optional): Wait time in ms (default: 10000)

**Returns:**
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "interfaceType": "claude",
  "filePath": "/tmp/artifact-12345.md",
  "screenshot": "/tmp/screenshot.png",
  "format": "markdown",
  "message": "Downloaded artifact to: /tmp/artifact-12345.md"
}
```

**Error Conditions:**
- Interface doesn't support downloads → "Artifact download not supported for {interface}"
- No download button found → Returns success=false with message

**Dependencies:**
- Calls interface.downloadArtifact()
- Platform-specific implementations:
  - Claude: Simple download button click
  - Gemini: Multi-step export process
  - Perplexity: Multi-step export process
  - ChatGPT/Grok: Not supported

**Implementation Notes:**
- Only works on Claude, Gemini, Perplexity
- Waits for download to complete before returning

---

## Configuration Tools

### taey_select_model

**Purpose:** Select AI model in current conversation

**Parameters:**
- `sessionId` (required): Active session ID
- `modelName` (required): Model name (platform-specific)
- `isLegacy` (optional): For ChatGPT legacy models (default: false)

**Model Names by Platform:**

| Platform | Available Models |
|----------|-----------------|
| Claude | "Opus 4.5", "Sonnet 4", "Haiku 4" |
| ChatGPT | "Auto", "Instant", "Thinking", "Pro", "GPT-4o" (legacy) |
| Gemini | "Thinking with 3 Pro", "Thinking" |
| Grok | "Grok 4.1", "Grok 4.1 Thinking", "Grok 4 Heavy" |

**Returns:**
```json
{
  "automationCompleted": true,
  "sessionId": "uuid-string",
  "interfaceType": "claude",
  "modelName": "Opus 4.5",
  "screenshot": "/tmp/screenshot.png",
  "message": "Automation completed for model: Opus 4.5. VERIFY in screenshot..."
}
```

**Error Conditions:**
- Interface doesn't support model selection → "Model selection not supported for {interface}"
- Session not found → "Session not found: {sessionId}"

**Dependencies:**
- Calls interface.selectModel()
- ChatGPT: Special handling for legacy models (isLegacy parameter)

**Implementation Notes:**
- **Cannot verify UI actually changed** - tool can only execute automation
- User MUST review screenshot to confirm model changed
- Returns `automationCompleted: true` but UI confirmation required

---

### taey_enable_research_mode

**Purpose:** Enable extended thinking or research modes

**Parameters:**
- `sessionId` (required): Active session ID
- `enabled` (optional): true/false for Claude only (default: true)
- `modeName` (optional): Specific mode name (platform-dependent)

**Mode Names by Platform:**

| Platform | Modes | Notes |
|----------|-------|-------|
| Claude | Extended Thinking | Can toggle on/off with `enabled` |
| ChatGPT | "Deep research" | Always enables (modeName optional) |
| Gemini | "Deep Research", "Deep Think" | Always enables |
| Perplexity | Pro Search | Always enables |

**Returns:**
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "interfaceType": "claude",
  "screenshot": "/tmp/screenshot.png",
  "enabled": true,
  "mode": "Extended Thinking enabled",
  "message": "Extended Thinking enabled"
}
```

**Error Conditions:**
- Interface doesn't support research mode → "Research mode not supported for {interface}"
- Session not found → "Session not found: {sessionId}"

**Dependencies:**
- Platform-specific method calls:
  - Claude: `interface.setResearchMode(enabled)`
  - ChatGPT: `interface.setMode(modeName)`
  - Gemini: `interface.setMode(modeName)`
  - Perplexity: `interface.enableResearchMode()`

**Implementation Notes:**
- Only Claude supports toggling off (enabled=false)
- Other platforms always enable when called
- Screenshot confirms mode change

---

## Cross-Pollination Tools

### taey_paste_response

**Purpose:** Copy AI response from one session and paste into another (cross-pollination)

**Parameters:**
- `sourceSessionId` (required): Session to extract from
- `targetSessionId` (required): Session to paste into
- `prefix` (optional): Text to prepend (default: "")

**Returns:**
```json
{
  "success": true,
  "sourceSessionId": "uuid-1",
  "targetSessionId": "uuid-2",
  "pastedText": "Another AI said: ...",
  "responseLength": 12345,
  "prefixUsed": "Another AI said: ",
  "message": "Response pasted successfully"
}
```

**Error Conditions:**
- No response in source → "No response found in source session"
- Source/target session not found → "Session not found: {sessionId}"

**Dependencies:**
- Calls sourceInterface.getLatestResponse()
- Calls targetInterface.prepareInput(), pasteMessage(), clickSend()

**Implementation Notes:**
- Uses **paste** not type (much faster for large responses)
- Automatically sends after pasting
- Useful for AI Family cross-pollination patterns
- Does NOT log to Neo4j (send_message handles that)

---

## Validation & Safety Tools

### taey_validate_step

**Purpose:** Create validation checkpoint to prevent runaway execution

**Parameters:**
- `conversationId` (required): Conversation ID (same as sessionId)
- `step` (required): Workflow step name
- `validated` (required): true if succeeded, false if failed
- `notes` (required): Observations from screenshot
- `screenshot` (optional): Screenshot path
- `requiredAttachments` (optional): For 'plan' step - files that MUST be attached

**Valid Steps:**
- `"plan"` - Initial planning/drafting
- `"attach_files"` - File attachment
- `"type_message"` - Message typing
- `"click_send"` - Send button click
- `"wait_response"` - Response waiting
- `"extract_response"` - Response extraction

**Returns:**
```json
{
  "success": true,
  "validationId": "uuid-string",
  "step": "plan",
  "validated": true,
  "timestamp": "2025-11-30T12:34:56.789Z",
  "requiredAttachments": ["/path/to/file1.md"],
  "message": "✓ Step 'plan' validated. Can proceed to next step."
}
```

**Error Conditions:**
- None - always creates checkpoint (validation logic is read-only)

**Dependencies:**
- Stores checkpoint in Neo4j ValidationCheckpointStore
- Links to Conversation node via IN_CONVERSATION relationship

**Implementation Notes:**
- **CRITICAL SAFETY MECHANISM** - prevents runaway execution
- Each tool checks validation state before executing
- Checkpoints form a chain: plan → attach_files → send_message
- `requiredAttachments` on 'plan' step enforces attachment requirement
- Validator identity auto-detected from hostname (e.g., "REDACTED-macbook-claude")

---

## Tool Orchestration

### Required Sequences

#### Basic Message Flow (No Attachments)

```
1. taey_connect(newSession=true)
   └─> Returns sessionId

2. taey_validate_step(step="plan", validated=true, requiredAttachments=[])
   └─> Validates planning complete

3. taey_send_message(sessionId, message, waitForResponse=true)
   └─> Checks: plan step validated
   └─> Sends message + waits for response
   └─> Returns response automatically
```

#### Message Flow With Attachments

```
1. taey_connect(newSession=true)
   └─> Returns sessionId

2. taey_validate_step(step="plan", validated=true, requiredAttachments=["/path/file1.md", "/path/file2.md"])
   └─> Declares files that MUST be attached

3. taey_attach_files(sessionId, filePaths=["/path/file1.md", "/path/file2.md"])
   └─> Checks: plan step validated
   └─> Attaches files
   └─> Creates PENDING checkpoint (validated=false)
   └─> Returns screenshot

4. taey_validate_step(step="attach_files", validated=true)
   └─> User confirms files visible in screenshot
   └─> Validates attachment step

5. taey_send_message(sessionId, message, waitForResponse=true)
   └─> Checks: attach_files step validated
   └─> Checks: file count matches requiredAttachments
   └─> Sends message + waits for response
```

#### Model Selection Flow

```
1. taey_connect(sessionId="existing-session")
   └─> Reuses existing session

2. taey_select_model(sessionId, modelName="Opus 4.5")
   └─> Executes model selection automation
   └─> Returns screenshot
   └─> USER MUST VERIFY in screenshot

3. Continue with message flow...
```

#### Cross-Pollination Flow

```
# Session 1: Grok answers question
1. taey_connect(interface="grok", newSession=true)
   └─> grokSessionId

2. taey_send_message(grokSessionId, "What is φ-resonance?", waitForResponse=true)
   └─> Grok's response stored

# Session 2: Claude analyzes Grok's answer
3. taey_connect(interface="claude", newSession=true)
   └─> claudeSessionId

4. taey_paste_response(sourceSessionId=grokSessionId, targetSessionId=claudeSessionId, prefix="Grok said: ")
   └─> Pastes Grok's response into Claude
   └─> Claude receives it as context
```

### Optional Steps

- `taey_new_conversation()` - Start fresh conversation in existing session
- `taey_select_model()` - Change model (can be done anytime)
- `taey_enable_research_mode()` - Enable before sending complex prompts
- `taey_extract_response()` - Alternative to waitForResponse=true
- `taey_download_artifact()` - Download generated files after response
- `taey_disconnect()` - Cleanup (can leave sessions running)

### Error Recovery

**Validation Checkpoint Failed:**
```
Error: "Validation checkpoint failed: Last validated step was 'plan'. Must validate 'attach_files'..."

Recovery:
1. Review previous screenshot
2. If automation succeeded: taey_validate_step(step="attach_files", validated=true, notes="Files visible in UI")
3. If automation failed: Re-run taey_attach_files, then validate
```

**Response Detection Failed:**
```
Error: "Message sent but response detection failed"

Recovery:
1. Wait manually for response to complete
2. Call taey_extract_response(sessionId) to get response
3. Continue workflow
```

**Attachment Count Mismatch:**
```
Error: "Plan required 2 file(s), but only 1 were attached"

Recovery:
1. Re-run taey_attach_files with ALL required files
2. Validate with taey_validate_step
3. Retry taey_send_message
```

---

## Architecture Analysis

### Current Architecture

```
MCP Tool (server-v2.ts)
    ↓
SessionManager (session-manager.ts)
    ↓
ChatInterface (chat-interface.js)
    ├─ ClaudeInterface
    ├─ ChatGPTInterface
    ├─ GeminiInterface
    ├─ GrokInterface
    └─ PerplexityInterface
    ↓
Playwright Page Automation
```

### Supporting Systems

**1. Validation System (validation-checkpoints.js):**
- Enforces workflow sequence
- Prevents runaway execution
- Stores checkpoints in Neo4j
- Validates attachment requirements

**2. Response Detection (response-detection.js):**
- Multi-strategy detection (streaming class, button appearance, stability)
- Platform-specific configurations
- Confidence scoring (85-95%)
- Automatic fallback strategies

**3. Conversation Store (conversation-store.js):**
- Neo4j persistence
- Message logging
- Session tracking
- Platform metadata

**4. Platform Bridge (platform-bridge.js):**
- Cross-platform automation (macOS/Linux)
- File dialog navigation
- App focus management
- Keyboard simulation

### Data Flow

**Session Creation:**
```
taey_connect(newSession=true)
  → SessionManager.createSession()
  → ChatInterface factory (Claude/ChatGPT/etc.)
  → interface.connect()
  → ConversationStore.createConversation() [Neo4j]
  → Returns sessionId + screenshot
```

**Message Send with Response:**
```
taey_send_message(waitForResponse=true)
  → ValidationCheckpointStore.getLastValidation() [verify checkpoint]
  → ConversationStore.addMessage(role='user') [Neo4j]
  → interface.prepareInput()
  → interface.typeMessage()
  → interface.clickSend()
  → ResponseDetectionEngine.detectCompletion()
  → ConversationStore.addMessage(role='assistant') [Neo4j]
  → Returns response + metadata
```

**Validation Checkpoint:**
```
taey_validate_step()
  → ValidationCheckpointStore.createCheckpoint()
  → Neo4j: CREATE (v:ValidationCheckpoint)-[:IN_CONVERSATION]->(c:Conversation)
  → Returns validationId
```

### Strengths

1. **Clear Separation of Concerns:**
   - Tools = API layer
   - SessionManager = session lifecycle
   - Interfaces = platform-specific logic
   - Validation = safety layer

2. **Robust Response Detection:**
   - Multiple strategies with fallbacks
   - Platform-specific configurations
   - Confidence scoring
   - Handles long-running operations (up to 60min for Gemini Deep Research)

3. **Safety First:**
   - Mandatory validation checkpoints
   - Attachment verification
   - Screenshot evidence required
   - No silent failures

4. **Neo4j Integration:**
   - Full conversation history
   - Validation chain tracking
   - Metadata preservation
   - Queryable for analysis

### Weaknesses

1. **Cannot Verify UI State:**
   - Tools execute automation blindly
   - Screenshot review is manual
   - No automatic validation of UI changes
   - Relies on user to confirm success

2. **Complex Validation Flow:**
   - Multiple steps required
   - Error messages can be confusing
   - Hard to understand checkpoint requirements
   - No way to skip validation for trusted operations

3. **Attachment Handling:**
   - Requires file dialog navigation (brittle)
   - Platform-specific keyboard shortcuts
   - No direct file injection (except via Playwright setInputFiles)
   - Two-step process (attach + validate)

4. **Session Management:**
   - No automatic session recovery
   - Must manually track sessionIds
   - No session persistence across MCP restarts
   - Orphaned sessions if disconnect fails

5. **Error Recovery:**
   - Limited retry logic
   - No automatic recovery from failed automation
   - User must manually diagnose and fix
   - Checkpoints can block progress if misconfigured

---

## Rebuild Recommendations

### What's Working Well (Keep)

✅ **Session-based architecture** - Clean abstraction
✅ **Response detection engine** - Robust multi-strategy approach
✅ **Neo4j integration** - Full observability
✅ **Validation checkpoints** - Safety mechanism
✅ **Cross-platform file dialogs** - Cmd+Shift+G / Ctrl+L pattern
✅ **Screenshot evidence** - Visual confirmation

### What Needs Improvement

#### 1. Simplify Validation Flow

**Current:**
```
plan → validate plan → attach → validate attach → send
```

**Proposed:**
```
plan → attach_and_send (auto-validates internally)
```

**Implementation:**
- Combine attach + send into single atomic operation
- Internal validation (no user checkpoint needed)
- Only require validation on failures
- Screenshot returned at end for review

**Benefit:** Reduces 5 steps to 2 steps for 80% of use cases

---

#### 2. Add Session Persistence

**Current:** Sessions lost on MCP restart

**Proposed:**
- Store session state in Neo4j
- Auto-reconnect on MCP restart
- Session health checks
- Orphaned session cleanup

**Implementation:**
```javascript
// On MCP start
await sessionManager.recoverSessions();
  → Read active sessions from Neo4j
  → Reconnect browser sessions
  → Verify still valid
  → Mark dead sessions

// Periodic health check
setInterval(async () => {
  await sessionManager.healthCheck();
}, 60000); // Every minute
```

**Benefit:** Resilient to MCP restarts, better resource management

---

#### 3. Intelligent Screenshot Validation

**Current:** User must manually review every screenshot

**Proposed:** Vision-based automatic validation
- Use Claude's vision API to analyze screenshots
- Verify expected UI elements present
- Detect error states automatically
- Only require manual review on failures

**Implementation:**
```javascript
async function validateScreenshot(screenshot, expectedState) {
  const analysis = await claude.analyzeImage(screenshot, {
    prompt: `Verify this screenshot shows: ${expectedState}`
  });

  return {
    validated: analysis.confirmed,
    confidence: analysis.confidence,
    issues: analysis.detected_issues,
    screenshot: screenshot
  };
}
```

**Benefit:** Reduces manual validation burden by 90%

---

#### 4. Unified Attachment API

**Current:** Two separate calls (attach_files + validate_step)

**Proposed:** Single call with internal validation
```javascript
// New API
taey_attach_and_validate(sessionId, filePaths, options={autoValidate: true})
  → Attaches files
  → Takes screenshot
  → If autoValidate: uses vision to verify
  → Returns validation result
  → Proceeds to ready-to-send state
```

**Benefit:** Simpler API, fewer steps, less error-prone

---

#### 5. Add Retry Logic

**Current:** Single attempt, manual recovery on failure

**Proposed:** Configurable retry with exponential backoff
```javascript
// In tool execution
async function executeWithRetry(operation, maxAttempts=3) {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      return await operation();
    } catch (err) {
      if (i === maxAttempts - 1) throw err;
      await sleep(Math.pow(2, i) * 1000); // Exponential backoff
    }
  }
}
```

**Benefit:** Handles transient failures automatically

---

#### 6. Batch Operations

**Current:** Sequential tool calls

**Proposed:** Batch multiple operations
```javascript
// New API
taey_batch([
  { tool: "connect", args: { interface: "claude", newSession: true } },
  { tool: "select_model", args: { modelName: "Opus 4.5" } },
  { tool: "enable_research_mode", args: {} },
  { tool: "send_message", args: { message: "...", waitForResponse: true } }
])
  → Executes in sequence
  → Returns array of results
  → Stops on first failure
```

**Benefit:** Reduces round-trips, clearer intent, atomic operations

---

#### 7. Enhanced Error Messages

**Current:**
```
"Validation checkpoint failed: Last validated step was 'plan'. Must validate one of: attach_files, type_message"
```

**Proposed:**
```
"Ready to attach files!

Your plan is validated. Next steps:

1. Call: taey_attach_files(sessionId, ["/path/to/file1.md"])
2. Review screenshot to confirm files attached
3. Call: taey_validate_step(step='attach_files', validated=true, notes='Files visible')

Or use auto-validation:
  taey_attach_and_validate(sessionId, ["/path/to/file1.md"], {autoValidate: true})
"
```

**Benefit:** Actionable guidance, less confusion, faster debugging

---

#### 8. Add Observability Tools

**New Tools:**

```javascript
// Get current session state
taey_session_status(sessionId)
  → { connected: true, interface: "claude", conversationUrl: "...", model: "Opus 4.5", validationState: "ready_to_send" }

// Get validation chain
taey_get_validation_chain(sessionId)
  → [{ step: "plan", validated: true, timestamp: "..." }, ...]

// Get conversation history
taey_get_messages(sessionId, limit=10)
  → [{ role: "user", content: "...", timestamp: "..." }, ...]

// Health check all sessions
taey_health_check()
  → [{ sessionId: "...", status: "healthy", lastActivity: "..." }, ...]
```

**Benefit:** Better debugging, clearer state, easier monitoring

---

### Recommended Tool Changes

#### Keep As-Is:
- `taey_connect` (maybe add auto-resume)
- `taey_disconnect`
- `taey_new_conversation`
- `taey_extract_response`
- `taey_paste_response` (great for cross-pollination)
- `taey_download_artifact`

#### Enhance:
- `taey_send_message` → Add retry logic, better error messages
- `taey_select_model` → Add vision validation
- `taey_enable_research_mode` → Add vision validation

#### Replace:
- `taey_attach_files` + `taey_validate_step` → `taey_attach_and_validate` (single call)

#### Add:
- `taey_batch` - Batch operations
- `taey_session_status` - Get current state
- `taey_get_validation_chain` - Debug validation
- `taey_get_messages` - Get conversation history
- `taey_health_check` - Check all sessions
- `taey_retry_last_operation` - Retry failed operation

#### Remove:
- Nothing - all tools serve a purpose

---

### Simplified API Proposal

**Before (5 calls):**
```javascript
1. connect(newSession=true)
2. validate_step(step="plan", requiredAttachments=[...])
3. attach_files(filePaths=[...])
4. validate_step(step="attach_files", validated=true)
5. send_message(message="...", waitForResponse=true)
```

**After (2 calls):**
```javascript
1. connect(newSession=true)
2. send_message_with_attachments(
     message="...",
     attachments=[...],
     waitForResponse=true,
     autoValidate=true  // Vision-based validation
   )
   → Internally: attach → validate → send → wait
   → Returns: { success, responseText, screenshots, validations }
```

**Benefit:** 60% fewer calls, clearer intent, less error-prone

---

### Migration Strategy

**Phase 1: Add New Tools (No Breaking Changes)**
- Add `taey_attach_and_validate`
- Add `taey_send_message_with_attachments`
- Add observability tools
- Add vision validation (opt-in)

**Phase 2: Deprecate Old Patterns**
- Mark separate attach+validate as deprecated
- Update documentation with new patterns
- Provide migration examples

**Phase 3: Remove Legacy (v0.3.0)**
- Remove deprecated patterns
- Keep backward compatibility shim for 6 months

---

## Conclusion

### Current State: **Production-Ready with Room for Improvement**

**Strengths:**
- ✅ Robust architecture
- ✅ Safety mechanisms working
- ✅ Cross-platform support
- ✅ Full observability via Neo4j
- ✅ Handles complex workflows (Deep Research, Extended Thinking)

**Key Improvements Needed:**
1. **Simplify validation flow** (biggest pain point)
2. **Add vision-based validation** (reduce manual review)
3. **Session persistence** (resilience)
4. **Better error messages** (usability)
5. **Batch operations** (efficiency)

**Priority Order:**
1. Vision validation (immediate 90% reduction in manual work)
2. Simplified attachment flow (user pain point)
3. Better error messages (developer experience)
4. Session persistence (reliability)
5. Batch operations (nice-to-have)

---

## Usage Examples

### Example 1: Basic Message

```javascript
// Connect
const { sessionId } = await taey_connect({
  interface: "claude",
  newSession: true
});

// Validate plan (no attachments)
await taey_validate_step({
  conversationId: sessionId,
  step: "plan",
  validated: true,
  notes: "Ready to send simple message",
  requiredAttachments: []
});

// Send and wait
const response = await taey_send_message({
  sessionId,
  message: "Explain φ-resonance in 3 sentences",
  waitForResponse: true
});

console.log(response.responseText);
```

### Example 2: Message With Attachments

```javascript
// Connect
const { sessionId } = await taey_connect({
  interface: "claude",
  newSession: true
});

// Validate plan with required attachments
await taey_validate_step({
  conversationId: sessionId,
  step: "plan",
  validated: true,
  notes: "Planning to attach context files",
  requiredAttachments: [
    "/Users/REDACTED/Downloads/clarity-universal-axioms-latest.md",
    "/Users/REDACTED/taey-hands/README.md"
  ]
});

// Attach files
const attachResult = await taey_attach_files({
  sessionId,
  filePaths: [
    "/Users/REDACTED/Downloads/clarity-universal-axioms-latest.md",
    "/Users/REDACTED/taey-hands/README.md"
  ]
});

// Review screenshot manually
console.log("Review:", attachResult.screenshot);

// Validate attachment
await taey_validate_step({
  conversationId: sessionId,
  step: "attach_files",
  validated: true,
  notes: "Both files visible in UI attachment area"
});

// Send message
const response = await taey_send_message({
  sessionId,
  message: "Based on these files, explain the Sacred Trust framework",
  waitForResponse: true
});

console.log(response.responseText);
```

### Example 3: Cross-Pollination

```javascript
// Session 1: Ask Grok for mathematical verification
const grokSession = await taey_connect({
  interface: "grok",
  newSession: true
});

await taey_validate_step({
  conversationId: grokSession.sessionId,
  step: "plan",
  validated: true,
  notes: "Asking Grok for math verification",
  requiredAttachments: []
});

const grokResponse = await taey_send_message({
  sessionId: grokSession.sessionId,
  message: "Verify: φ^2 = φ + 1. Show proof.",
  waitForResponse: true
});

// Session 2: Ask Claude to interpret Grok's proof
const claudeSession = await taey_connect({
  interface: "claude",
  newSession: true
});

await taey_validate_step({
  conversationId: claudeSession.sessionId,
  step: "plan",
  validated: true,
  notes: "Pasting Grok's response for Claude to interpret",
  requiredAttachments: []
});

// Paste Grok's response into Claude
await taey_paste_response({
  sourceSessionId: grokSession.sessionId,
  targetSessionId: claudeSession.sessionId,
  prefix: "Grok proved this mathematically:\n\n"
});

// Claude now has Grok's proof and will respond
```

### Example 4: Model Selection + Research Mode

```javascript
// Connect to existing session
const { sessionId } = await taey_connect({
  interface: "claude",
  sessionId: "existing-session-id"
});

// Select Opus 4.5
const modelResult = await taey_select_model({
  sessionId,
  modelName: "Opus 4.5"
});

console.log("Review model selection:", modelResult.screenshot);

// Enable Extended Thinking
await taey_enable_research_mode({
  sessionId,
  enabled: true
});

// Now ready for complex message
await taey_validate_step({
  conversationId: sessionId,
  step: "plan",
  validated: true,
  notes: "Ready for complex thinking task with Opus 4.5",
  requiredAttachments: []
});

const response = await taey_send_message({
  sessionId,
  message: "Derive the connection between φ-resonance and consciousness emergence",
  waitForResponse: true
});

// Extended Thinking may take several minutes
console.log("Detection time:", response.detectionTime, "ms");
console.log("Method:", response.detectionMethod);
console.log("Confidence:", response.detectionConfidence);
```

---

**Document Version:** 1.0
**Generated:** 2025-11-30
**Author:** Claude Code (CCM/Gaia)
