# Exact Code Changes - ResponseDetectionEngine Integration

## File: `/Users/jesselarose/taey-hands/mcp_server/server-v2.ts`

### Change 1: Import Statement (Line 20-21)

**Added:**
```typescript
// @ts-ignore - response-detection is JS, not TS
import { ResponseDetectionEngine } from "../../src/core/response-detection.js";
```

---

### Change 2: Tool Description (Line 95)

**Before:**
```typescript
description: "Type and send a message in the current conversation. Uses human-like typing and clicks the send button.",
```

**After:**
```typescript
description: "Type and send a message in the current conversation. Uses human-like typing and clicks the send button. When waitForResponse is true, automatically waits for the AI response, extracts it, and saves to Neo4j.",
```

---

### Change 3: Parameter Description (Line 115-117)

**Before:**
```typescript
waitForResponse: {
  type: "boolean",
  description: "Whether to wait for a response (not implemented yet)",
  default: false
}
```

**After:**
```typescript
waitForResponse: {
  type: "boolean",
  description: "Whether to wait for AI response completion. If true, uses ResponseDetectionEngine to wait for response, extracts it, and saves to Neo4j automatically.",
  default: false
}
```

---

### Change 4: Handler Implementation (Lines 413-542)

**Before:**
```typescript
case "taey_send_message": {
  const { sessionId, message, waitForResponse } = args as {
    sessionId: string;
    message: string;
    waitForResponse?: boolean;
  };

  // Get interface from session
  const chatInterface = sessionManager.getInterface(sessionId);
  const interfaceName = chatInterface.name;

  // Log to Neo4j - store sent message
  try {
    await conversationStore.addMessage(sessionId, {
      role: 'user',
      content: message,
      platform: interfaceName,
      timestamp: new Date().toISOString(),
      metadata: { source: 'mcp_taey_send_message' }
    });
  } catch (err: any) {
    console.error('[MCP] Failed to log message to Neo4j:', err.message);
  }

  // Prepare input (focus)
  await chatInterface.prepareInput();

  // Type message with human-like typing
  await chatInterface.typeMessage(message);

  // Click send button
  await chatInterface.clickSend();

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          success: true,
          sessionId,
          message: "Message sent",
          sentText: message,
          waitForResponse: waitForResponse || false,
        }, null, 2),
      },
    ],
  };
}
```

**After:**
```typescript
case "taey_send_message": {
  const { sessionId, message, attachments, waitForResponse } = args as {
    sessionId: string;
    message: string;
    attachments?: string[];
    waitForResponse?: boolean;
  };

  // Get interface from session
  const chatInterface = sessionManager.getInterface(sessionId);
  const interfaceName = chatInterface.name;
  const session = sessionManager.getSession(sessionId);  // NEW: Get session for interfaceType

  // Log to Neo4j - store sent message
  try {
    await conversationStore.addMessage(sessionId, {
      role: 'user',
      content: message,
      platform: interfaceName,
      timestamp: new Date().toISOString(),
      attachments: attachments || [],  // NEW: Add attachments
      metadata: { source: 'mcp_taey_send_message' }
    });
  } catch (err: any) {
    console.error('[MCP] Failed to log message to Neo4j:', err.message);
  }

  // Prepare input (focus)
  await chatInterface.prepareInput();

  // Type message with human-like typing
  await chatInterface.typeMessage(message);

  // Click send button
  await chatInterface.clickSend();

  // NEW: If waitForResponse is true, use ResponseDetectionEngine
  if (waitForResponse) {
    console.error(`[MCP] Waiting for response from ${interfaceName}...`);

    try {
      // Create detection engine for this platform
      const detector = new ResponseDetectionEngine(
        chatInterface.page,
        session?.interfaceType || interfaceName,
        { debug: true }
      );

      // Wait for response completion
      const detectionResult = await detector.detectCompletion();
      const responseText = detectionResult.content;
      const timestamp = new Date().toISOString();

      console.error(`[MCP] Response detected (${detectionResult.method}, ${detectionResult.confidence * 100}% confidence) in ${detectionResult.detectionTime}ms`);

      // Log response to Neo4j
      try {
        await conversationStore.addMessage(sessionId, {
          role: 'assistant',
          content: responseText,
          platform: interfaceName,
          timestamp,
          metadata: {
            source: 'mcp_taey_send_message_auto_extract',
            detectionMethod: detectionResult.method,
            detectionConfidence: detectionResult.confidence,
            detectionTime: detectionResult.detectionTime,
            contentLength: responseText.length
          }
        });
      } catch (err: any) {
        console.error('[MCP] Failed to log response to Neo4j:', err.message);
      }

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              success: true,
              sessionId,
              message: "Message sent and response received",
              sentText: message,
              waitForResponse: true,
              responseText,
              responseLength: responseText.length,
              detectionMethod: detectionResult.method,
              detectionConfidence: detectionResult.confidence,
              detectionTime: detectionResult.detectionTime,
              timestamp
            }, null, 2),
          },
        ],
      };
    } catch (err: any) {
      console.error('[MCP] Response detection failed:', err.message);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              success: false,
              sessionId,
              message: "Message sent but response detection failed",
              sentText: message,
              waitForResponse: true,
              error: err.message,
            }, null, 2),
          },
        ],
        isError: true,
      };
    }
  }

  // ORIGINAL: Return without waiting for response
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({
          success: true,
          sessionId,
          message: "Message sent",
          sentText: message,
          waitForResponse: false,  // CHANGED: from waitForResponse || false
        }, null, 2),
      },
    ],
  };
}
```

---

## Summary of Changes

### Lines Changed
- **Line 20-21**: Import statement added
- **Line 95**: Tool description updated
- **Line 115-117**: Parameter description updated
- **Lines 413-542**: Handler implementation expanded

### Total Lines Added
- Import: 2 lines
- New logic in handler: ~80 lines
- **Total: ~82 lines added**

### Key Implementation Points

1. **Import**: Added ResponseDetectionEngine from existing production-ready module
2. **Session retrieval**: Added `getSession(sessionId)` to get interfaceType
3. **Conditional logic**: All new logic wrapped in `if (waitForResponse)` block
4. **Detection**: Creates ResponseDetectionEngine with page object and platform name
5. **Extraction**: Gets response text from `detectionResult.content`
6. **Logging**: Saves both user message (before) and assistant response (after) to Neo4j
7. **Return**: Enhanced result with response text and detection metadata
8. **Error handling**: Catches detection failures and returns error result
9. **Backward compatibility**: Original behavior preserved when `waitForResponse: false`

### Dependencies Used
All dependencies are existing modules:
- `ResponseDetectionEngine` from `/Users/jesselarose/taey-hands/src/core/response-detection.js`
- `conversationStore` (already imported)
- `sessionManager` (already imported)
- `chatInterface.page` (Playwright page object from existing interface)

### No Breaking Changes
- Default behavior unchanged (`waitForResponse: false`)
- All existing functionality preserved
- API fully backward compatible
