# MCP Long-Running Operations - Implementation Guide

## Problem Statement

`taey_send_message` with `waitForResponse=true` is failing because:

```
User Request
    ↓
MCP Tool Call (taey_send_message)
    ↓
Timeout Clock Started: 0s
    ↓
Send message: 1-2s ✓
    ↓
Start response detection: 2s elapsed
    ↓
Wait for Extended Thinking completion: 300s+ ✗
    ↓
Timeout fires at: 60s (TypeScript SDK limit)
    ↗
MCP Disconnects - Tool execution terminated
```

## Solution: Asynchronous Hand-Off Pattern

Recommended by MCP spec and proven in production.

```
User Request (Send message)
    ↓
MCP Tool 1: taey_send_message
    ├─ Send message: 1-2s
    ├─ Return immediately: sessionId
    ↓ (Timeout at 60s doesn't matter - we finished!)
[Tool completes - fresh timeout]

User Request (Wait for response)
    ↓
MCP Tool 2: taey_wait_for_response
    ├─ Fresh 60s+ timeout clock
    ├─ Poll for completion every 10s
    ├─ Report progress: "Still waiting (30s)..."
    ├─ Extended Thinking finishes at 300s
    ├─ Response detected
    ├─ Extract and return: response text
    ↓ (Timeout at 60s not an issue - our operation took 300s but it finished!)
[Tool completes - success]
```

## Architecture: Three-Tool Async Pattern

### Tool 1: taey_send_message (UNCHANGED)
```typescript
taey_send_message(sessionId: string, message: string, attachments?: string[])
  → Returns: { success: true, sessionId }
  → Duration: 2-5 seconds
  → No waiting for response
```

### Tool 2: taey_response_status (NEW - OPTIONAL)
```typescript
taey_response_status(sessionId: string)
  → Returns: {
      complete: boolean,
      method?: string,
      confidence?: number,
      detectionTime?: number
    }
  → Duration: 2-10 seconds (quick check)
  → Useful for: UI polling without blocking
```

### Tool 3: taey_wait_for_response (NEW - REPLACES waitForResponse)
```typescript
taey_wait_for_response(
  sessionId: string,
  maxWaitSeconds?: number = 600,
  pollIntervalSeconds?: number = 10
)
  → Returns: {
      success: boolean,
      responseText: string,
      waitTime: number,
      detectionMethod: string
    }
  → Duration: 0 to maxWaitSeconds (full wait)
  → Handles: Extended Thinking (5-15min), Deep Research (2-10min)
```

## Full Implementation

### Step 1: Update Tool Definitions

**Location**: `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts` (lines 56-336)

Remove `waitForResponse` from `taey_send_message` tool:
```typescript
// OLD - REMOVE waitForResponse parameter
{
  name: "taey_send_message",
  inputSchema: {
    properties: {
      waitForResponse: {  // ← DELETE THIS
        type: "boolean",
        description: "Whether to wait for AI response...",
        default: false
      }
    }
  }
}

// NEW - Just send, don't wait
{
  name: "taey_send_message",
  inputSchema: {
    properties: {
      // sessionId, message, attachments only
      sessionId: { type: "string" },
      message: { type: "string" },
      attachments: { type: "array", default: [] }
    }
  }
}
```

Add new tools after `taey_send_message`:
```typescript
{
  name: "taey_response_status",
  description: "Check if response generation is complete. Quick status check (<10s).",
  inputSchema: {
    type: "object",
    properties: {
      sessionId: {
        type: "string",
        description: "Session ID returned from taey_connect"
      }
    },
    required: ["sessionId"]
  }
},

{
  name: "taey_wait_for_response",
  description: "Wait for AI response with configurable timeout. Handles long-running operations (Extended Thinking, Deep Research). Emits progress updates every N seconds.",
  inputSchema: {
    type: "object",
    properties: {
      sessionId: {
        type: "string",
        description: "Session ID returned from taey_connect"
      },
      maxWaitSeconds: {
        type: "number",
        description: "Maximum wait time in seconds. Default 600 (10 min). Set higher for Extended Thinking (900 for 15 min)",
        default: 600
      },
      pollIntervalSeconds: {
        type: "number",
        description: "How often to report progress. Default 10 seconds",
        default: 10
      }
    },
    required: ["sessionId"]
  }
}
```

### Step 2: Implement Tool Handlers

**Location**: `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts` (case statements)

Remove the `if (waitForResponse)` block from `taey_send_message` handler:
```typescript
// REMOVE lines 604-680:
if (waitForResponse) {
  console.error(`[MCP] Waiting for response from ${interfaceName}...`);
  try {
    const detector = new ResponseDetectionEngine(...);
    const detectionResult = await detector.detectCompletion();
    // ... all of this ...
  }
}
```

The handler should now end at line 696:
```typescript
return {
  content: [{
    type: "text",
    text: JSON.stringify({
      success: true,
      sessionId,
      message: "Message sent",
      sentText: message,
      waitForResponse: false,  // Remove this line
    }, null, 2),
  }],
};
```

Add handler for `taey_response_status`:
```typescript
case "taey_response_status": {
  const { sessionId } = args as { sessionId: string };

  try {
    await sessionManager.validateSessionHealth(sessionId);
    const chatInterface = sessionManager.getInterface(sessionId);
    const interfaceName = chatInterface.name;

    // Quick check - just see if response is visible
    const detector = new ResponseDetectionEngine(
      chatInterface.page,
      interfaceName,
      { debug: false }  // No debug logging for quick check
    );

    // Try to detect with very short timeout
    try {
      const result = await Promise.race([
        detector.detectCompletion(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Still generating')), 5000)
        )
      ]);

      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            sessionId,
            complete: true,
            method: result.method,
            confidence: result.confidence,
            detectionTime: result.detectionTime
          }, null, 2)
        }]
      };
    } catch (err) {
      // Still generating
      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            sessionId,
            complete: false,
            message: "Response still being generated..."
          }, null, 2)
        }]
      };
    }
  } catch (err: any) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: false,
          error: err.message
        }, null, 2)
      }],
      isError: true
    };
  }
}
```

Add handler for `taey_wait_for_response`:
```typescript
case "taey_wait_for_response": {
  const { sessionId, maxWaitSeconds = 600, pollIntervalSeconds = 10 } = args as {
    sessionId: string;
    maxWaitSeconds?: number;
    pollIntervalSeconds?: number;
  };

  try {
    await sessionManager.validateSessionHealth(sessionId);
    const chatInterface = sessionManager.getInterface(sessionId);
    const interfaceName = chatInterface.name;

    console.error(`[MCP] Starting response wait (max ${maxWaitSeconds}s, report every ${pollIntervalSeconds}s)`);

    const detector = new ResponseDetectionEngine(
      chatInterface.page,
      interfaceName,
      { debug: true }
    );

    const startTime = Date.now();
    const maxWaitMs = maxWaitSeconds * 1000;
    const pollIntervalMs = pollIntervalSeconds * 1000;
    let lastProgressTime = startTime;

    // Keep trying until we detect response or timeout
    while (Date.now() - startTime < maxWaitMs) {
      try {
        // Try to detect response
        const result = await detector.detectCompletion();
        const responseText = result.content;
        const totalWaitTime = Date.now() - startTime;

        console.error(`[MCP] Response detected after ${totalWaitTime}ms (${result.method}, ${(result.confidence * 100).toFixed(0)}% confidence)`);

        // Log to Neo4j
        try {
          await conversationStore.addMessage(sessionId, {
            role: 'assistant',
            content: responseText,
            platform: interfaceName,
            timestamp: new Date().toISOString(),
            metadata: {
              source: 'mcp_taey_wait_for_response',
              detectionMethod: result.method,
              detectionConfidence: result.confidence,
              detectionTime: result.detectionTime,
              totalWaitTime,
              contentLength: responseText.length
            }
          });
        } catch (logErr: any) {
          console.error('[MCP] Failed to log response to Neo4j:', logErr.message);
        }

        // Update session state
        try {
          const currentUrl = await chatInterface.getCurrentConversationUrl();
          await conversationStore.updateSessionState(sessionId, currentUrl, interfaceName);
        } catch (syncErr: any) {
          console.error('[MCP] Failed to sync session state:', syncErr.message);
        }

        return {
          content: [{
            type: "text",
            text: JSON.stringify({
              success: true,
              sessionId,
              message: "Response detected and extracted",
              responseText,
              responseLength: responseText.length,
              waitTime: totalWaitTime,
              detectionMethod: result.method,
              detectionConfidence: result.confidence,
              detectionTime: result.detectionTime,
              timestamp: new Date().toISOString()
            }, null, 2)
          }]
        };
      } catch (detectionErr: any) {
        // Detection failed - check if we should report progress
        const elapsedMs = Date.now() - startTime;
        const elapsedSeconds = Math.round(elapsedMs / 1000);

        if (elapsedMs - lastProgressTime >= pollIntervalMs) {
          console.error(`[MCP] Still waiting for response (${elapsedSeconds}s / ${maxWaitSeconds}s)...`);
          lastProgressTime = Date.now();
        }

        // Wait before retrying (don't hammer the page)
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    }

    // Timeout reached
    const elapsedSeconds = Math.round((Date.now() - startTime) / 1000);
    console.error(`[MCP] Response wait timeout after ${elapsedSeconds}s`);

    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: false,
          sessionId,
          error: `Response timeout after ${maxWaitSeconds} seconds`,
          elapsedSeconds,
          message: "No response detected within timeout period. Response may still be generating."
        }, null, 2)
      }],
      isError: true
    };
  } catch (err: any) {
    return {
      content: [{
        type: "text",
        text: JSON.stringify({
          success: false,
          sessionId,
          error: err.message,
          message: "Failed to wait for response"
        }, null, 2)
      }],
      isError: true
    };
  }
}
```

### Step 3: Update MCP Configuration

**If deploying via Claude Desktop:**

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": [
        "/Users/REDACTED/taey-hands/mcp_server/dist/server-v2.js"
      ],
      "timeout": 600000
    }
  }
}
```

**If deploying as stdio server:**

Ensure the server has sufficient timeout:
```bash
# When launching MCP server, ensure these env vars set
export MCP_TIMEOUT=600000  # 10 minutes
```

### Step 4: Update ResponseDetectionEngine (Optional Enhancement)

**Location**: `/Users/REDACTED/taey-hands/src/core/response-detection.js`

Add abort signal support for clean cancellation:
```javascript
detectCompletion(options = {}) {
  const {
    maxWaitTime = 600000,  // 10 minutes
    abortSignal = null,
    onProgress = null
  } = options;

  // Check abort signal periodically
  const checkAbort = () => {
    if (abortSignal?.aborted) {
      throw new Error('Detection cancelled');
    }
  };

  // Existing detection logic...
  // Add checkAbort() calls in polling loops

  // Call progress callback every 10s
  if (onProgress) {
    onProgress({
      elapsedSeconds: Math.round(elapsedMs / 1000),
      maxSeconds: Math.round(maxWaitTime / 1000)
    });
  }
}
```

## Usage Examples

### Example 1: Simple Message + Wait

```javascript
// Send message
const sendResult = await taey_send_message({
  sessionId: "session_123",
  message: "What is the capital of France?"
});
// Returns immediately

// Wait for response (will detect quickly for simple question)
const response = await taey_wait_for_response({
  sessionId: "session_123",
  maxWaitSeconds: 60
});

console.log(response.responseText);
```

### Example 2: Extended Thinking

```javascript
// Send complex problem
const sendResult = await taey_send_message({
  sessionId: "session_456",
  message: "Prove the Riemann Hypothesis step by step"
});

// Wait longer for Extended Thinking
const response = await taey_wait_for_response({
  sessionId: "session_456",
  maxWaitSeconds: 900,  // 15 minutes
  pollIntervalSeconds: 30  // Report every 30s
});

console.log(`Wait time: ${response.waitTime}ms`);
console.log(`Detection method: ${response.detectionMethod}`);
console.log(response.responseText);
```

### Example 3: With Status Polling (For UI)

```javascript
// Send message
await taey_send_message({
  sessionId: "session_789",
  message: "Research the history of AI"
});

// Poll status in UI loop
let isComplete = false;
while (!isComplete) {
  const status = await taey_response_status({
    sessionId: "session_789"
  });

  console.log(`Complete: ${status.complete}`);

  if (status.complete) {
    isComplete = true;
  } else {
    // Wait 5 seconds before next check
    await sleep(5000);
  }
}

// Extract when ready
const response = await taey_wait_for_response({
  sessionId: "session_789",
  maxWaitSeconds: 60  // Should return immediately since already complete
});
```

## Testing the Implementation

### Test 1: Verify Split Works

```javascript
const test1 = async () => {
  console.log('Test 1: Verify taey_send_message no longer waits');

  const sessionId = await taey_connect({interface: 'claude'});
  const start = Date.now();

  const result = await taey_send_message({
    sessionId,
    message: "Complex problem needing Extended Thinking"
  });

  const duration = Date.now() - start;
  console.assert(duration < 5000, `Send should be <5s, was ${duration}ms`);
  console.log(`✓ taey_send_message returned in ${duration}ms`);
};
```

### Test 2: Verify Wait Handles Long Operations

```javascript
const test2 = async () => {
  console.log('Test 2: Verify taey_wait_for_response handles 10+ min operations');

  const sessionId = await taey_connect({interface: 'claude'});
  await taey_enable_research_mode({sessionId});

  const start = Date.now();

  await taey_send_message({
    sessionId,
    message: "Complex mathematical proof requiring extended thinking"
  });

  const response = await taey_wait_for_response({
    sessionId,
    maxWaitSeconds: 900,  // 15 minutes
    pollIntervalSeconds: 30
  });

  const duration = Date.now() - start;
  console.assert(response.success, 'Wait should succeed');
  console.assert(response.responseText.length > 100, 'Response should have content');
  console.log(`✓ taey_wait_for_response succeeded after ${duration}ms`);
};
```

## Backward Compatibility

The change is **NOT backward compatible** for code using `waitForResponse: true`.

Migration path:
```javascript
// OLD CODE - Won't work anymore
const result = await taey_send_message({
  sessionId,
  message: "Hello",
  waitForResponse: true
});

// NEW CODE - Split into two calls
await taey_send_message({
  sessionId,
  message: "Hello"
});
const result = await taey_wait_for_response({
  sessionId,
  maxWaitSeconds: 60
});
```

Update any existing code that uses `waitForResponse` before deploying.

## Deployment Checklist

- [ ] Remove `waitForResponse` parameter from `taey_send_message` schema
- [ ] Remove response detection code from `taey_send_message` handler
- [ ] Add `taey_response_status` tool definition and handler
- [ ] Add `taey_wait_for_response` tool definition and handler
- [ ] Update MCP config with `timeout: 600000`
- [ ] Test with simple message (should complete in <60s)
- [ ] Test with Extended Thinking (should handle 5-15 min)
- [ ] Test with Deep Research (should handle 2-10 min)
- [ ] Update documentation for users
- [ ] Update any internal tools using `waitForResponse`
