# Testing the newSession Fix

Quick testing guide for verifying the `newSession=true` bug fix.

---

## Quick Conceptual Test

### Test 1: Fresh Session (Empty Conversation)

**Command**:
```javascript
// Via MCP client or Claude Desktop
await callTool('taey_connect', {
  interface: 'claude',
  newSession: true
});
```

**Expected Behavior**:
1. Browser navigates to `https://claude.ai/new`
2. Screenshot shows **empty input field**
3. No prior messages visible
4. Response includes `conversationId` (extracted from URL)
5. URL looks like `https://claude.ai/chat/abc-def-123`

**How to Verify**:
- Check screenshot: Should see blank Claude interface with input prompt
- Check response: `conversationId` should be a UUID-like string
- Check browser manually: Should be on `/chat/` URL, not homepage

---

### Test 2: Resume Existing Conversation

**Setup**: First create a conversation and note its ID

**Command**:
```javascript
// First, create a conversation and get its ID
const fresh = await callTool('taey_connect', {
  interface: 'claude',
  newSession: true
});
const oldConvId = fresh.conversationId;

// Send a message
await callTool('taey_send_message', {
  sessionId: fresh.sessionId,
  message: 'Test message for resume',
  waitForResponse: false
});

// Disconnect
await callTool('taey_disconnect', {
  sessionId: fresh.sessionId
});

// Now resume with that conversationId
const resumed = await callTool('taey_connect', {
  interface: 'claude',
  newSession: true,
  conversationId: oldConvId
});
```

**Expected Behavior**:
1. Browser navigates to `https://claude.ai/chat/{oldConvId}`
2. Screenshot shows **existing conversation** with "Test message for resume"
3. Response `conversationId` matches `oldConvId`

**How to Verify**:
- Check screenshot: Should see prior messages in conversation
- Check response: `conversationId` matches what you provided
- Check browser manually: URL contains the old conversation ID

---

### Test 3: All Platforms

Repeat Test 1 for each platform:

```javascript
// Claude
await callTool('taey_connect', { interface: 'claude', newSession: true });
// Expected URL: https://claude.ai/new → https://claude.ai/chat/{id}

// ChatGPT
await callTool('taey_connect', { interface: 'chatgpt', newSession: true });
// Expected URL: https://chatgpt.com → https://chatgpt.com/c/{id}

// Gemini
await callTool('taey_connect', { interface: 'gemini', newSession: true });
// Expected URL: https://gemini.google.com/app → .../app/{id}

// Grok
await callTool('taey_connect', { interface: 'grok', newSession: true });
// Expected URL: https://grok.com → https://grok.com/chat/{id}

// Perplexity
await callTool('taey_connect', { interface: 'perplexity', newSession: true });
// Expected URL: https://perplexity.ai → https://perplexity.ai/search/{id}
```

**How to Verify**:
- Each platform creates empty conversation
- Each extracts conversationId correctly
- Regex patterns match platform URL structures

---

## Verification Checklist

After running tests:

- [ ] Fresh sessions show empty input (not cached conversation)
- [ ] Resumed sessions show existing conversation history
- [ ] ConversationId extracted from URL correctly for all platforms
- [ ] Neo4j stores conversationId (check with Cypher query)
- [ ] Screenshots saved to `/tmp/taey-{platform}-{sessionId}-connected.png`
- [ ] No TypeScript compilation errors
- [ ] No browser navigation errors in logs

---

## Neo4j Verification

Check that conversationId is stored correctly:

```cypher
MATCH (c:Conversation)
WHERE c.createdVia = 'taey_connect'
  AND c.createdAt > datetime() - duration('PT1H')  // Last hour
RETURN
  c.sessionId,
  c.conversationId,
  c.platform,
  c.title,
  c.createdAt
ORDER BY c.createdAt DESC
LIMIT 10
```

**Expected**:
- `conversationId` is NOT null
- `conversationId` matches URL pattern for platform
- `platform` matches interface type
- Each test creates a new Conversation node

---

## How the Fix Works (Conceptual)

**Before**:
```
User → newSession=true
  → navigate to claude.ai (base URL)
  → browser loads cached conversation from cookies
  → screenshot shows OLD conversation ❌
```

**After**:
```
User → newSession=true
  → navigate to claude.ai/new (new chat URL)
  → browser creates FRESH conversation
  → extract conversationId from new URL
  → screenshot shows EMPTY input ✅
```

**Key Changes**:
1. `connect()` checks `options.newConversation` flag
2. Navigates to `_getNewChatUrl()` instead of base URL
3. Extracts conversationId from resulting URL
4. Returns conversationId in connect result

---

## Troubleshooting

### Problem: Still seeing old conversation

**Cause**: Browser cookies/localStorage loading cached state
**Fix**: Clear browser data or use incognito mode

### Problem: conversationId is null

**Cause**: Regex in `_extractConversationId()` doesn't match URL
**Fix**: Check browser URL, update regex pattern for platform

### Problem: Navigation timeout

**Cause**: Platform UI changed, selectors outdated
**Fix**: Update `selectors.chatInput` for platform

### Problem: Neo4j conversationId null

**Cause**: Extraction failed but no error thrown
**Fix**: Add error handling in `_extractConversationId()`, log URL

---

## Success Criteria

The fix is working if:

✅ `newSession=true` creates **empty** conversation
✅ Browser navigates to `/new` or equivalent URL
✅ conversationId extracted from URL
✅ Neo4j stores conversationId
✅ Screenshot shows empty input field
✅ Resuming conversation loads existing history

---

**Testing Complete**: If all tests pass, the `newSession` bug is fixed and the system correctly creates fresh conversations instead of loading cached ones.
