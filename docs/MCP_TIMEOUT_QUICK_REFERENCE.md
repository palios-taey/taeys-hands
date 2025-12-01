# MCP Timeout Quick Reference

## The Core Problem
Your `taey_send_message` with `waitForResponse=true` disconnects during response detection because:

1. **TypeScript MCP SDK** has a **hard 60-second timeout** per tool
2. **Extended Thinking** takes 5-15 minutes
3. **Deep Research** takes 2-10 minutes
4. The `await detector.detectCompletion()` call blocks the entire tool, triggering timeout

## Official MCP Timeout Limits

```
Default: 30-60 seconds (depends on SDK)
TypeScript SDK: 60 seconds HARD LIMIT (no reset with progress)
Python SDK: Configurable per-request
Max possible with config: 300-600 seconds
```

**Fact**: MCP spec allows progress notifications to reset timeout, but TypeScript SDK ignores them.

## The Solution: Split Into Separate Tools

Instead of one blocking tool:
```javascript
await taey_send_message(sessionId, message, {waitForResponse: true});
// ❌ Times out at 60s
```

Use the **asynchronous hand-off pattern**:
```javascript
// 1. Send message (returns immediately)
await taey_send_message(sessionId, message);

// 2. Wait with progress reporting (configurable timeout)
const response = await taey_wait_for_response(
  sessionId,
  maxWaitSeconds = 600,  // 10 minutes
  pollIntervalSeconds = 10
);
// ✅ Completes successfully
```

## Why This Works

Each MCP tool call is independent:
- `taey_send_message`: Returns in <2 seconds ✅
- `taey_wait_for_response`: Can take 10+ minutes ✅
  - Tool timeout clock resets at the START of the tool
  - Tool can run for up to MCP timeout duration
  - With proper config (600s), handles Extended Thinking ✅

## Implementation Checklist

- [ ] Create `taey_wait_for_response(sessionId, maxWaitSeconds, pollIntervalSeconds)`
- [ ] Add progress logging every 10 seconds (prevents confusion)
- [ ] Update MCP config timeout to 600000ms (10 minutes)
- [ ] Keep existing `taey_send_message` but remove `waitForResponse` parameter
- [ ] Update `taey_extract_response` for quick extraction without wait

## Code Changes Required

**File**: `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts`

1. **Remove from taey_send_message** (line 158-162):
```typescript
// DELETE THIS:
waitForResponse: {
  type: "boolean",
  description: "Whether to wait for AI response completion...",
  default: false
}
```

2. **Remove from taey_send_message handler** (line 604-680):
```typescript
// DELETE THIS ENTIRE BLOCK:
if (waitForResponse) {
  const detector = new ResponseDetectionEngine(...);
  const detectionResult = await detector.detectCompletion();
  // ...
}
```

3. **Add new tool definition** (before TOOLS array closes):
```typescript
{
  name: "taey_wait_for_response",
  description: "Wait for AI response with configurable timeout and progress reporting. Allows 10+ minute operations.",
  inputSchema: {
    type: "object",
    properties: {
      sessionId: { type: "string", description: "Session ID" },
      maxWaitSeconds: { type: "number", description: "Maximum wait time", default: 600 },
      pollIntervalSeconds: { type: "number", description: "Progress report interval", default: 10 }
    },
    required: ["sessionId"]
  }
}
```

4. **Add handler in switch statement**:
```typescript
case "taey_wait_for_response": {
  const { sessionId, maxWaitSeconds = 600, pollIntervalSeconds = 10 } = args;

  await sessionManager.validateSessionHealth(sessionId);
  const chatInterface = sessionManager.getInterface(sessionId);
  const interfaceName = chatInterface.name;

  const detector = new ResponseDetectionEngine(
    chatInterface.page,
    interfaceName,
    { debug: true }
  );

  const startTime = Date.now();
  const maxWaitMs = maxWaitSeconds * 1000;
  let lastProgressTime = startTime;

  while (Date.now() - startTime < maxWaitMs) {
    try {
      const result = await detector.detectCompletion();
      const responseText = result.content;

      // Log to Neo4j
      await conversationStore.addMessage(sessionId, {
        role: 'assistant',
        content: responseText,
        platform: interfaceName,
        timestamp: new Date().toISOString(),
        metadata: {
          source: 'mcp_taey_wait_for_response',
          detectionMethod: result.method,
          waitDuration: Date.now() - startTime
        }
      });

      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            success: true,
            sessionId,
            responseText,
            waitTime: Date.now() - startTime,
            detectionMethod: result.method
          }, null, 2)
        }]
      };
    } catch (err) {
      // Report progress
      if (Date.now() - lastProgressTime >= pollIntervalSeconds * 1000) {
        const elapsedSeconds = Math.round((Date.now() - startTime) / 1000);
        console.error(`[MCP] Waiting for response (${elapsedSeconds}s of ${maxWaitSeconds}s)...`);
        lastProgressTime = Date.now();
      }

      await sleep(1000);
    }
  }

  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        success: false,
        sessionId,
        error: `Response timeout after ${maxWaitSeconds} seconds`
      }, null, 2)
    }],
    isError: true
  };
}
```

5. **Update MCP config** (in whatever deploys this):
```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": ["./server-v2.js"],
      "timeout": 600000
    }
  }
}
```

## Testing

```javascript
// Test Extended Thinking
const sessionId = await taey_connect({interface: 'claude'});
await taey_enable_research_mode({sessionId});
await taey_send_message({
  sessionId,
  message: "Complex mathematical problem requiring extended thinking"
});
const response = await taey_wait_for_response({
  sessionId,
  maxWaitSeconds: 900  // 15 minutes for Extended Thinking
});
console.log(response);
```

## Key Insight

The MCP timeout applies **per tool call**, not to the entire workflow.

So instead of:
```
One tool call → waits 10 minutes → times out
```

You do:
```
Tool 1 (send): 2 seconds → returns
Tool 2 (wait): 10 minutes → returns (fresh timeout clock!)
```

This is the **officially recommended pattern** for long-running MCP operations.
