# MCP Background/Async Tool Execution Research

**Date**: 2025-12-02
**Purpose**: Understand how to implement background execution for `taey_wait_for_response` and prevent concurrent message sending
**Sources**: builder-taey MCP servers, taey-hands current implementation

---

## Executive Summary

MCP protocol **does NOT support native background/async tool execution**. However, builder-taey demonstrates a proven pattern using **file-based job tracking with detached processes**. This research outlines:

1. How builder-taey implements background processes
2. Why taey-hands needs a different approach (blocking is intentional)
3. Alternative solutions for the "response pending" problem
4. Integration with existing notification-detection.js

**Key Finding**: The real problem isn't making `taey_wait_for_response` async - it's **preventing parallel execution** when a response is already being waited for.

---

## 1. MCP Protocol Reality Check

### What MCP Supports
- **Synchronous tools**: Request → Tool executes → Response
- **stdio transport**: JSON-RPC over stdin/stdout
- **Tool timeout**: Client-side timeout enforcement

### What MCP Does NOT Support
- Native background task tracking
- Progress notifications during tool execution
- Tool-to-tool blocking (one tool blocking another)
- Async callbacks or webhooks

### Implication for Taey-Hands
**MCP tools are blocking by design**. When Claude Code calls a tool, it waits for the response before proceeding. This is actually GOOD for our use case because:
- `taey_wait_for_response` should block Claude from sending more messages
- We don't want Claude calling `taey_send_message` while waiting for a response
- Blocking prevents race conditions and parallel execution bugs

---

## 2. Builder-Taey Background Process Pattern

### Architecture Overview

```
BackgroundProcessManager (Python)
├── ProcessState: Tracks each background process
├── start_process(): Spawns asyncio subprocess
├── check_status(): Incremental output (no duplicates)
├── list_processes(): View all running processes
└── terminate_process(): Kill and cleanup

MCP Tool Layer
├── background_command: Start process, return immediately
├── check_process_status: Poll for updates (no reminders)
├── list_background_processes: List all
└── get_process_output: Paginated historical output
```

### Key Implementation Details

**File**: `/Users/REDACTED/builder-taey/mcp_servers/native_tools/background_process.py`

```python
class BackgroundProcessManager:
    """Manages background processes with controlled reminder behavior."""

    async def start_process(self, command: str, remind_mode: str = "silent"):
        # Start subprocess
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # Create state tracking
        state = ProcessState(
            process_id=self._generate_id(),
            pid=proc.pid,
            status="running",
            output_buffer=[],
            read_position=0  # Track what Claude has read
        )

        # Start background task to capture output
        asyncio.create_task(self._capture_output(process_id, timeout))

        return {"process_id": process_id, "status": "running"}

    async def check_status(self, process_id: str):
        """Returns ONLY NEW output since last check (incremental)."""
        state = self.processes[process_id]

        # Get new lines since last read
        new_lines = state.output_buffer[state.read_position:]
        state.read_position = len(state.output_buffer)

        return {
            "status": state.status,
            "new_output_lines": new_lines,  # No duplicates!
            "total_lines": len(state.output_buffer)
        }
```

### Critical Features

1. **Silent by Default**: No automatic reminders (prevents context pollution)
2. **Incremental Output**: Only returns new lines since last check
3. **Read Position Tracking**: Prevents duplicate output
4. **Remind Modes**: "silent", "on_completion", "on_error"
5. **Pagination**: `get_output(from_line, max_lines)` for historical access

### Why This Works for builder-taey

builder-taey runs **long-running infrastructure commands**:
- `vllm serve model` (model loading, takes minutes)
- `docker-compose up` (service startup)
- `pytest` (test suites)

These are truly background tasks that Claude can check on periodically while doing other work.

---

## 3. Why Taey-Hands is Different

### Use Case Analysis

Taey-hands doesn't need background execution because:

1. **Sequential Workflow**: Send message → Wait for response → Extract → Send next message
2. **No Parallel Work**: Claude shouldn't do anything else while waiting for AI response
3. **Blocking is Intentional**: Prevents race conditions where Claude tries to send messages to busy AI
4. **Response Detection is Active**: Uses notification-detection.js with polling strategies

### Current Implementation (Correct Design)

```typescript
case "taey_wait_for_response": {
    // This BLOCKS until response is complete (GOOD!)
    const detector = new ResponseDetectionEngine(page, platform);
    const detectionResult = await detector.detectCompletion();

    // Claude Code is blocked here - cannot call other tools
    // This prevents parallel message sending

    return { responseText: detectionResult.content };
}
```

### The Real Problem

The issue isn't that `taey_wait_for_response` blocks - it's that **nothing prevents Claude from calling `taey_send_message` again** if it gets confused or loses context.

**Example failure scenario**:
1. Claude calls `taey_send_message` (sends message A)
2. Claude calls `taey_wait_for_response` (starts waiting)
3. *Long wait (5+ minutes for Deep Research)*
4. Claude context switches or gets impatient
5. Claude calls `taey_send_message` again (sends message B while A is still processing!)
6. Race condition: Two messages in flight, responses interleaved

---

## 4. Solution: Session State Blocking

Instead of making `taey_wait_for_response` background, implement **session-level state blocking**.

### Architecture

```typescript
// session-manager.ts
export interface SessionState {
    sessionId: string;
    interfaceType: string;
    responseInProgress: boolean;  // NEW: Block parallel sends
    lastMessageSentAt: Date | null;
    lastResponseReceivedAt: Date | null;
}

export class SessionManager {
    // Track response state per session
    private responseInProgress: Map<string, boolean> = new Map();

    markResponsePending(sessionId: string): void {
        this.responseInProgress.set(sessionId, true);
    }

    markResponseComplete(sessionId: string): void {
        this.responseInProgress.set(sessionId, false);
    }

    isResponsePending(sessionId: string): boolean {
        return this.responseInProgress.get(sessionId) || false;
    }
}
```

### Implementation in server-v2.ts

```typescript
case "taey_send_message": {
    const { sessionId, message } = args;

    // PRE-FLIGHT: Check if response is already pending
    if (sessionManager.isResponsePending(sessionId)) {
        throw new Error(
            `Cannot send message: response is already in progress for session ${sessionId}. ` +
            `Wait for current response to complete before sending another message.`
        );
    }

    // Send message
    await chatInterface.typeMessage(message);
    await chatInterface.clickSend();

    // Mark response as pending
    sessionManager.markResponsePending(sessionId);

    return { success: true, message: "Message sent. Use taey_wait_for_response to wait." };
}

case "taey_wait_for_response": {
    const { sessionId, maxWaitSeconds = 600 } = args;

    // Validate that response is actually pending
    if (!sessionManager.isResponsePending(sessionId)) {
        console.warn('[MCP] taey_wait_for_response called but no pending response');
    }

    try {
        // This BLOCKS (intentionally) until response complete
        const detector = new ResponseDetectionEngine(page, platform);
        const detectionResult = await detector.detectCompletion();

        // Mark response as complete
        sessionManager.markResponseComplete(sessionId);

        return { success: true, responseText: detectionResult.content };
    } catch (err) {
        // Even on error, clear pending state
        sessionManager.markResponseComplete(sessionId);
        throw err;
    }
}
```

### Benefits

1. **Mathematically Prevents Parallel Sends**: Cannot send message B while waiting for response to message A
2. **No Background Complexity**: Keeps blocking behavior (simpler, more reliable)
3. **Clear Error Messages**: Claude gets immediate feedback if attempting parallel send
4. **Session-Level Safety**: Each session tracked independently
5. **Works with Existing Detection**: No changes to notification-detection.js

---

## 5. Alternative: Timeout-Based Status Tool (Not Recommended)

If you REALLY wanted background-style execution:

### New Tool: `taey_check_response_status`

```typescript
{
    name: "taey_check_response_status",
    description: "Check if AI response is complete (non-blocking). Use this to poll while doing other work.",
    inputSchema: {
        sessionId: { type: "string" }
    }
}

// Implementation
case "taey_check_response_status": {
    const { sessionId } = args;

    // Quick check without blocking
    const isComplete = await quickResponseCheck(page, platform);

    if (isComplete) {
        const responseText = await extractResponse(page, platform);
        sessionManager.markResponseComplete(sessionId);
        return { complete: true, responseText };
    } else {
        return {
            complete: false,
            message: "Response still in progress. Check again in 5-10 seconds."
        };
    }
}
```

### Why This is NOT Recommended

1. **Adds Complexity**: Claude must poll repeatedly instead of blocking once
2. **Context Pollution**: Multiple tool calls to check status
3. **Timing Issues**: Claude might give up or context-switch
4. **No Real Benefit**: Claude can't do useful work while waiting anyway
5. **Breaks Validation Chain**: Harder to enforce sequential workflow

---

## 6. Integration with notification-detection.js

### Current Detection Flow

```javascript
// notification-detection.js
export class NotificationDetectionEngine {
    constructor(page, platform, options = {}) {
        this.page = page;
        this.platform = platform;
    }

    async initializeNotificationListener() {
        // Monkey-patch Notification API
        await this.page.evaluate(() => {
            window.Notification = function(...args) {
                // Detect completion keywords
                if (isCompletion) {
                    window.dispatchEvent(new CustomEvent('ai-response-complete'));
                }
                return new OriginalNotification(...args);
            };
        });
    }

    async waitForNotification(timeout = 30000) {
        // Wait for custom event (< 100ms detection)
        // Fallback to polling if no notification
    }
}
```

### How Response Detection Already Works

```javascript
// response-detection.js
export class ResponseDetectionEngine {
    async detectCompletion() {
        // Strategy 1: Notification API (< 100ms, 98% confidence)
        try {
            const notificationEngine = new NotificationDetectionEngine(page, platform);
            return await notificationEngine.detect();
        } catch {
            // Strategy 2: Streaming class removal (< 500ms, 95% confidence)
            return await this.detectViaStreamingClass();
        }
        // Strategy 3: Button appearance (< 1s, 90% confidence)
        // Strategy 4: Fibonacci stability polling (1-55s, 85% confidence)
    }
}
```

### Key Insight

Response detection **already handles long waits elegantly**:
- Tries instant notification detection first
- Falls back to streaming class removal
- Falls back to button appearance
- Finally uses Fibonacci polling (1s → 55s intervals)

**No need to change this**. It's optimized for both instant responses and long-running operations (Deep Research, Extended Thinking).

---

## 7. Recommended Implementation Plan

### Phase 1: Add Session State Blocking (CRITICAL)

**Files to modify**:
- `/Users/REDACTED/taey-hands/mcp_server/session-manager.ts`
- `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts`

**Changes**:
1. Add `responseInProgress: Map<string, boolean>` to SessionManager
2. Add methods: `markResponsePending()`, `markResponseComplete()`, `isResponsePending()`
3. Block `taey_send_message` if response is pending
4. Update `taey_wait_for_response` to set/clear pending state

**Test cases**:
```typescript
// Should PASS
taey_send_message → taey_wait_for_response → taey_send_message

// Should FAIL with clear error
taey_send_message → taey_send_message (without waiting)
taey_send_message → taey_wait_for_response (called twice in parallel)
```

### Phase 2: Enhanced Status Logging (OPTIONAL)

Log session state transitions to Neo4j:
```cypher
CREATE (e:SessionEvent {
    sessionId: $sessionId,
    eventType: 'response_pending',
    timestamp: datetime(),
    waitStarted: datetime()
})
```

This helps debug:
- How long Claude waits for responses
- If Claude is attempting parallel sends
- Patterns in conversation flow

### Phase 3: Timeout Protection (OPTIONAL)

Add maximum wait time before forcing state reset:
```typescript
// Auto-clear pending state after timeout
const MAX_WAIT_TIME = 3600000; // 1 hour
setTimeout(() => {
    if (sessionManager.isResponsePending(sessionId)) {
        console.warn(`Force-clearing pending state for ${sessionId} after timeout`);
        sessionManager.markResponseComplete(sessionId);
    }
}, MAX_WAIT_TIME);
```

---

## 8. Code Patterns from builder-taey That Work

### Pattern 1: Incremental Output (No Duplicates)

```python
# Track read position per client
state.read_position = 0

async def check_status(process_id):
    # Only return NEW lines
    new_lines = state.output_buffer[state.read_position:]
    state.read_position = len(state.output_buffer)
    return new_lines
```

**Application**: If you add `taey_get_partial_response`, use this pattern to avoid sending duplicate content.

### Pattern 2: Silent by Default (No Context Pollution)

```python
remind_mode: str = "silent"  # Default

# Only add reminder if explicitly requested
if remind_mode == "on_completion" and status == "completed":
    result["reminder"] = "Process completed"
```

**Application**: Don't auto-notify Claude about response completion. Let Claude poll when ready.

### Pattern 3: State Machine Pattern

```python
status: str  # "running", "completed", "failed", "killed"

# Prevent invalid transitions
if state.status != "running":
    return {"error": "Process not running"}
```

**Application**: Enforce valid state transitions for response detection:
- `idle` → `message_sent` → `waiting_for_response` → `response_complete` → `idle`

### Pattern 4: Graceful Cleanup

```python
async def terminate_process(process_id):
    proc.terminate()  # SIGTERM
    await proc.wait()
    state.status = "killed"
    state.completed_at = datetime.now()
```

**Application**: Handle browser crashes or timeout during `taey_wait_for_response`:
```typescript
try {
    await detector.detectCompletion();
} finally {
    // Always clear pending state, even on error
    sessionManager.markResponseComplete(sessionId);
}
```

---

## 9. What NOT to Do

### ❌ Don't Add Background Process Manager to Taey-Hands

builder-taey's BackgroundProcessManager is for **infrastructure commands**, not AI responses. Taey-hands doesn't need:
- Process spawning
- Output buffering
- Incremental reading
- Multiple concurrent tasks

### ❌ Don't Create Polling Tools

```typescript
// BAD: Adds complexity, no benefit
taey_check_response_status() // Poll repeatedly
taey_get_partial_response()  // Get streaming content
```

These fragment the workflow and make validation harder.

### ❌ Don't Try to Make MCP Async

MCP protocol is synchronous by design. Fighting this creates more problems:
- Client-side complexity (tracking background tasks)
- Server-side complexity (detached processes, IPC)
- Reliability issues (task cleanup, orphaned processes)
- No actual benefit (Claude must wait anyway)

### ❌ Don't Break Validation Checkpoints

Current checkpoint system works:
```
plan → attach_files → type_message → click_send → wait_response → extract_response
```

Adding background execution breaks this chain and makes bugs harder to diagnose.

---

## 10. Final Recommendation

### Implement Session State Blocking (Phase 1)

This solves the actual problem:
- **Prevents parallel message sending**
- **No background complexity**
- **Works with existing detection**
- **Clear error messages for Claude**
- **Maintains sequential workflow**

### Keep taey_wait_for_response Blocking

Blocking is the correct behavior:
- Claude should NOT do other work while waiting
- Prevents race conditions
- Simplifies state management
- Response detection already handles long waits efficiently

### Don't Add Background Execution

The complexity isn't worth it:
- No real benefit (Claude must wait anyway)
- Adds failure modes
- Breaks validation chain
- Harder to debug

---

## 11. Code Example: Complete Implementation

### session-manager.ts

```typescript
export class SessionManager {
    private sessions: Map<string, SessionState> = new Map();
    private responseInProgress: Map<string, boolean> = new Map();

    markResponsePending(sessionId: string): void {
        console.error(`[SessionManager] ⏳ Response pending for ${sessionId}`);
        this.responseInProgress.set(sessionId, true);

        // Update session metadata
        const session = this.sessions.get(sessionId);
        if (session) {
            session.lastMessageSentAt = new Date();
        }
    }

    markResponseComplete(sessionId: string): void {
        console.error(`[SessionManager] ✓ Response complete for ${sessionId}`);
        this.responseInProgress.set(sessionId, false);

        // Update session metadata
        const session = this.sessions.get(sessionId);
        if (session) {
            session.lastResponseReceivedAt = new Date();
        }
    }

    isResponsePending(sessionId: string): boolean {
        return this.responseInProgress.get(sessionId) || false;
    }

    getSessionWaitTime(sessionId: string): number | null {
        const session = this.sessions.get(sessionId);
        if (!session || !session.lastMessageSentAt) return null;

        const now = new Date();
        return now.getTime() - session.lastMessageSentAt.getTime();
    }
}
```

### server-v2.ts (taey_send_message)

```typescript
case "taey_send_message": {
    const { sessionId, message, attachments } = args;

    // PRE-FLIGHT: Validate session health
    await sessionManager.validateSessionHealth(sessionId);

    // CRITICAL: Block if response is already pending
    if (sessionManager.isResponsePending(sessionId)) {
        const waitTime = sessionManager.getSessionWaitTime(sessionId);
        throw new Error(
            `Cannot send message to session ${sessionId}: response already in progress. ` +
            `Current wait time: ${Math.floor(waitTime! / 1000)}s. ` +
            `Call taey_wait_for_response to complete current response before sending new message.`
        );
    }

    // VALIDATION CHECKPOINT: Ensure attachments if required
    await requirementEnforcer.ensureCanSendMessage(sessionId);

    // Get interface from session
    const chatInterface = sessionManager.getInterface(sessionId);

    // Prepare input (focus)
    await chatInterface.prepareInput();

    // Type message with human-like typing
    await chatInterface.typeMessage(message);

    // Click send button
    await chatInterface.clickSend();

    // CRITICAL: Mark response as pending AFTER send succeeds
    sessionManager.markResponsePending(sessionId);

    console.error(`[MCP] ✓ Message sent. Response now pending. Use taey_wait_for_response.`);

    return {
        content: [{
            type: "text",
            text: JSON.stringify({
                success: true,
                sessionId,
                responsePending: true,
                message: "Message sent successfully. Response is now pending. Call taey_wait_for_response to wait for completion.",
                nextStep: "taey_wait_for_response",
            }, null, 2),
        }],
    };
}
```

### server-v2.ts (taey_wait_for_response)

```typescript
case "taey_wait_for_response": {
    const { sessionId, maxWaitSeconds = 600 } = args;

    await sessionManager.validateSessionHealth(sessionId);

    // Validate that response is actually pending
    if (!sessionManager.isResponsePending(sessionId)) {
        console.warn(
            '[MCP] ⚠️ taey_wait_for_response called but no pending response. ' +
            'Did you call taey_send_message first?'
        );
    }

    const chatInterface = sessionManager.getInterface(sessionId);
    const interfaceName = chatInterface.name;

    console.error(`[MCP] ⏳ Waiting for response from ${interfaceName} (max ${maxWaitSeconds}s)...`);

    try {
        // Create detection engine with platform-specific timeout
        const detector = new ResponseDetectionEngine(
            chatInterface.page,
            sessionManager.getSession(sessionId)?.interfaceType || interfaceName,
            { debug: true }
        );

        // BLOCKS HERE until response is complete (INTENTIONAL!)
        const startTime = Date.now();
        const detectionResult = await detector.detectCompletion();
        const responseText = detectionResult.content;
        const waitTime = Math.round((Date.now() - startTime) / 1000);

        console.error(
            `[MCP] ✓ Response detected (${detectionResult.method}, ` +
            `${detectionResult.confidence * 100}% confidence) after ${waitTime}s`
        );

        // CRITICAL: Mark response as complete
        sessionManager.markResponseComplete(sessionId);

        // Log response to Neo4j
        try {
            await conversationStore.addMessage(sessionId, {
                role: 'assistant',
                content: responseText,
                platform: interfaceName,
                timestamp: new Date().toISOString(),
                metadata: {
                    source: 'mcp_taey_wait_for_response',
                    detectionMethod: detectionResult.method,
                    detectionConfidence: detectionResult.confidence,
                    waitTimeSeconds: waitTime,
                }
            });
        } catch (err: any) {
            console.error('[MCP] Failed to log response to Neo4j:', err.message);
        }

        return {
            content: [{
                type: "text",
                text: JSON.stringify({
                    success: true,
                    sessionId,
                    responseText,
                    responseLength: responseText.length,
                    waitTimeSeconds: waitTime,
                    detectionMethod: detectionResult.method,
                    detectionConfidence: detectionResult.confidence,
                    responsePending: false,
                    timestamp: new Date().toISOString()
                }, null, 2),
            }],
        };

    } catch (err: any) {
        console.error('[MCP] ❌ Response detection failed:', err.message);

        // CRITICAL: Even on error, clear pending state
        sessionManager.markResponseComplete(sessionId);

        return {
            content: [{
                type: "text",
                text: JSON.stringify({
                    success: false,
                    sessionId,
                    error: err.message,
                    responsePending: false,
                    message: `Failed to detect response within ${maxWaitSeconds}s. Use taey_extract_response to manually extract if response is visible.`
                }, null, 2),
            }],
            isError: true,
        };
    }
}
```

---

## 12. Testing Strategy

### Test Case 1: Normal Flow (Should Pass)

```typescript
// 1. Send message
taey_send_message({ sessionId: "test", message: "Hello" })
// → Success, responsePending=true

// 2. Wait for response
taey_wait_for_response({ sessionId: "test" })
// → Success, responsePending=false, responseText="..."

// 3. Send another message
taey_send_message({ sessionId: "test", message: "Follow-up" })
// → Success, responsePending=true
```

### Test Case 2: Blocked Parallel Send (Should Fail)

```typescript
// 1. Send message
taey_send_message({ sessionId: "test", message: "Hello" })
// → Success, responsePending=true

// 2. Try to send another message (should be BLOCKED)
taey_send_message({ sessionId: "test", message: "Oops" })
// → Error: "Cannot send message: response already in progress..."
```

### Test Case 3: Wait Without Send (Should Warn)

```typescript
// 1. Call wait without sending (edge case)
taey_wait_for_response({ sessionId: "test" })
// → Warning logged, but continues (might extract old response)
```

### Test Case 4: Timeout Recovery (Should Reset State)

```typescript
// 1. Send message
taey_send_message({ sessionId: "test", message: "Hello" })
// → Success, responsePending=true

// 2. Wait for response (times out)
taey_wait_for_response({ sessionId: "test", maxWaitSeconds: 10 })
// → Error: timeout, but responsePending=false (state cleared)

// 3. Can send again (state was reset)
taey_send_message({ sessionId: "test", message: "Retry" })
// → Success, responsePending=true
```

---

## 13. Summary

### What Works in builder-taey
- **BackgroundProcessManager**: Spawns detached processes for infrastructure commands
- **Incremental output**: Prevents duplicate data in context
- **Silent mode**: No automatic reminders (context pollution prevention)
- **State tracking**: Clear process lifecycle (running → completed → killed)

### What Taey-Hands Needs (Different Use Case)
- **Session state blocking**: Prevent parallel message sending
- **Synchronous wait**: Block Claude until response complete (intentional!)
- **No background complexity**: Sequential workflow is correct
- **Clear error messages**: Guide Claude to correct usage

### Implementation Priority
1. **HIGH**: Add session state blocking to prevent parallel sends
2. **MEDIUM**: Enhanced logging for debugging conversation flow
3. **LOW**: Timeout protection for zombie sessions
4. **NOT NEEDED**: Background task execution, polling tools, async complexity

### Key Insight
The problem isn't that `taey_wait_for_response` blocks - it's that nothing prevents Claude from making mistakes. **Add guardrails, not async complexity.**

---

## Appendix: File Locations

### Builder-Taey Files
- Background process manager: `/Users/REDACTED/builder-taey/mcp_servers/native_tools/background_process.py`
- MCP server: `/Users/REDACTED/builder-taey/mcp_servers/native_tools/server.py`
- Test suite: `/Users/REDACTED/builder-taey/tests/mcp/test_background_process.py`
- Manual test: `/Users/REDACTED/builder-taey/tests/mcp/manual_test_background.py`

### Taey-Hands Files
- MCP server: `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts`
- Session manager: `/Users/REDACTED/taey-hands/mcp_server/session-manager.ts`
- Response detection: `/Users/REDACTED/taey-hands/src/core/response-detection.js`
- Notification detection: `/Users/REDACTED/taey-hands/src/core/notification-detection.js`
- Job manager (unused): `/Users/REDACTED/taey-hands/mcp_server/job-manager.ts`

### Configuration
- builder-taey MCP config: `/Users/REDACTED/builder-taey/.mcp.json`
- Test results: `/Users/REDACTED/builder-taey/MCP_SERVER_TEST_RESULTS.md`
