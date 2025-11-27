# ResponseDetectionEngine Integration - Test Guide

## What Was Implemented

The ResponseDetectionEngine has been integrated into the MCP server's `taey_send_message` tool. When you pass `waitForResponse: true`, it will:

1. Send the message (existing behavior)
2. Automatically wait for the AI response using the ResponseDetectionEngine
3. Extract the response when complete
4. Save the response to Neo4j automatically
5. Return the response text in the tool result

## Changes Made

### 1. Modified `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts`

**Import added:**
```typescript
import { ResponseDetectionEngine } from "../../src/core/response-detection.js";
```

**Updated tool description:**
The `taey_send_message` tool now describes the `waitForResponse` parameter as fully functional.

**Updated implementation:**
- When `waitForResponse: true`, creates a ResponseDetectionEngine instance
- Calls `detector.detectCompletion()` to wait for the response
- Automatically extracts response and saves to Neo4j
- Returns enhanced result with response text, detection method, confidence, and timing

### 2. Build Status

✅ TypeScript compilation successful (`npm run build` passed)

## Testing the Integration

### Manual Test via MCP Client

You can test this by calling the MCP tool with `waitForResponse: true`:

```javascript
// 1. Connect to Claude
const connectResult = await mcp.callTool('taey_connect', {
  interface: 'claude',
  newSession: true
});
const sessionId = JSON.parse(connectResult.content[0].text).sessionId;

// 2. Send message and wait for response
const result = await mcp.callTool('taey_send_message', {
  sessionId: sessionId,
  message: 'What is 2+2? Please answer in one sentence.',
  waitForResponse: true  // <-- This triggers the ResponseDetectionEngine
});

// 3. Check result
const response = JSON.parse(result.content[0].text);
console.log('Response:', response.responseText);
console.log('Detection method:', response.detectionMethod);
console.log('Confidence:', response.detectionConfidence);
console.log('Detection time:', response.detectionTime);
```

### Expected Result

When `waitForResponse: true`, the tool should return:

```json
{
  "success": true,
  "sessionId": "...",
  "message": "Message sent and response received",
  "sentText": "What is 2+2? Please answer in one sentence.",
  "waitForResponse": true,
  "responseText": "2+2 equals 4.",
  "responseLength": 13,
  "detectionMethod": "streamingClass",
  "detectionConfidence": 0.95,
  "detectionTime": 1234,
  "timestamp": "2025-11-27T..."
}
```

### Verification Steps

1. **Response is returned**: The `responseText` field contains the AI's response
2. **Detection worked**: The `detectionMethod` shows which strategy was used (e.g., "streamingClass", "buttonAppearance", "stability")
3. **Neo4j storage**: Both the user message and assistant response are saved to Neo4j
4. **Metadata included**: Detection method, confidence, and timing are included in the Neo4j metadata

## How It Works

### Architecture Flow

```
taey_send_message(waitForResponse: true)
  ↓
1. Log user message to Neo4j
  ↓
2. Send message (prepareInput → typeMessage → clickSend)
  ↓
3. Create ResponseDetectionEngine(page, platform)
  ↓
4. Call detector.detectCompletion()
   - Uses platform-specific detection strategy:
     * Claude: streaming class removal (95% confidence)
     * ChatGPT: button appearance (90% confidence)
     * Gemini/Grok: content stability (85% confidence)
     * Perplexity: Labs completion or stability
  ↓
5. Extract response text from detection result
  ↓
6. Log assistant response to Neo4j with detection metadata
  ↓
7. Return response to caller
```

### Platform-Specific Detection

Each platform uses different detection strategies:

- **Claude**: Watches for `result-streaming` class removal (most reliable)
- **ChatGPT**: Watches for Regenerate button to appear
- **Gemini**: Content stability check (handles Deep Research)
- **Grok**: Content stability check
- **Perplexity**: Watches for "Working..." indicator to disappear (Labs mode)

All strategies fall back to content stability if primary detection fails.

## Error Handling

If response detection fails (timeout, error, etc.), the tool returns:

```json
{
  "success": false,
  "sessionId": "...",
  "message": "Message sent but response detection failed",
  "sentText": "...",
  "waitForResponse": true,
  "error": "Detection timeout after 300000ms"
}
```

The user message is still logged to Neo4j, but no assistant response is recorded.

## Performance

Detection timeouts vary by platform and mode:

- **Claude**: 5 minutes (for Extended Thinking)
- **ChatGPT**: 3 minutes (for o1 reasoning)
- **Gemini**: 60 minutes (for Deep Research)
- **Perplexity**: 30 minutes (for Labs)
- **Grok**: 1 minute (standard)

## Next Steps

1. Test with a simple message to Claude
2. Verify response is returned correctly
3. Check Neo4j to confirm both messages are saved
4. Test with other platforms (ChatGPT, Gemini, etc.)
5. Test with extended thinking modes
6. Validate timeout handling

## Files Modified

- `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts` - Main integration
- `/Users/REDACTED/taey-hands/mcp_server/dist/server-v2.js` - Compiled output
- `/Users/REDACTED/taey-hands/test_response_detection.js` - Test script

## Related Documentation

- ResponseDetectionEngine: `/Users/REDACTED/taey-hands/src/core/response-detection.js`
- Session Manager: `/Users/REDACTED/taey-hands/mcp_server/session-manager.ts`
- Conversation Store: `/Users/REDACTED/taey-hands/src/core/conversation-store.js`
