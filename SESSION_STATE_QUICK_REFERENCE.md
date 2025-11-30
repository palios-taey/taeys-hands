# Session State Sync - Quick Reference

**For developers integrating session state synchronization**

---

## Core Concepts

**sessionId** = MCP session UUID (ephemeral, lost on restart)
**conversationId** = Platform chat ID (persistent, extracted from URL)
**conversationUrl** = Full browser URL (changes as user navigates)

---

## Common Patterns

### 1. Check Session Health (Before Tool Execution)

```typescript
// Throws error if session is dead
await sessionManager.validateSessionHealth(sessionId);
```

### 2. Sync State to Database (After Tool Execution)

```typescript
// Get current browser URL
const chatInterface = sessionManager.getInterface(sessionId);
const currentUrl = await chatInterface.getCurrentConversationUrl();

// Update database with current state
await conversationStore.updateSessionState(sessionId, currentUrl, platform);
```

### 3. Tool Handler Pattern

```typescript
case "taey_send_message": {
  const { sessionId, message } = args;

  // 1. Pre-flight health check
  await sessionManager.validateSessionHealth(sessionId);

  // 2. Execute operation
  const chatInterface = sessionManager.getInterface(sessionId);
  await chatInterface.sendMessage(message);

  // 3. Sync state to database
  const currentUrl = await chatInterface.getCurrentConversationUrl();
  await conversationStore.updateSessionState(sessionId, currentUrl, platform);

  return { success: true };
}
```

### 4. Server Startup Reconciliation

```typescript
// In server-v2.ts initialization
async function initializeServer() {
  // Initialize schemas
  await conversationStore.initSchema();

  // Detect orphaned sessions from previous run
  const sessionManager = getSessionManager();
  await sessionManager.syncWithDatabase(conversationStore);

  // Continue with server startup...
}
```

---

## API Reference

### ConversationStore Methods

#### `extractConversationId(url, platform)`

Extracts platform-specific conversation ID from URL.

**Parameters**:
- `url: string` - Full conversation URL
- `platform: string` - 'claude' | 'chatgpt' | 'gemini' | 'grok' | 'perplexity'

**Returns**: `string | null` - Conversation ID or null if not found

**Example**:
```javascript
const id = conversationStore.extractConversationId(
  'https://claude.ai/chat/abc-123-def',
  'claude'
);
// Returns: 'abc-123-def'
```

---

#### `updateSessionState(sessionId, currentUrl, platform)`

Syncs browser state to Neo4j database.

**Parameters**:
- `sessionId: string` - MCP session ID
- `currentUrl: string` - Current browser URL
- `platform: string` - Platform name

**Returns**:
```typescript
{
  conversationId: string | null,
  synced: boolean
}
```

**Example**:
```javascript
const { conversationId, synced } = await conversationStore.updateSessionState(
  'session-uuid-123',
  'https://chatgpt.com/c/xyz-789',
  'chatgpt'
);

console.log(`Synced: ${synced}, conversationId: ${conversationId}`);
```

---

#### `getSessionHealth(sessionId)`

Checks session health and returns detailed status.

**Parameters**:
- `sessionId: string` - MCP session ID

**Returns**:
```typescript
{
  exists: boolean,
  status: 'active' | 'closed' | 'orphaned',
  healthy: boolean,
  info: string,
  conversationId: string | null,
  platform: string,
  messageCount: number,
  lastActivity: Date,
  staleDurationMs: number
}
```

**Example**:
```javascript
const health = await conversationStore.getSessionHealth(sessionId);

if (!health.healthy) {
  console.error(`Session unhealthy: ${health.info}`);
  // Handle: reconnect, warn user, etc.
}
```

**Health Criteria**:
- `healthy=true`: status='active', sessionId matches, lastActivity < 1 hour
- `healthy=false` (stale): lastActivity > 1 hour
- `healthy=false` (closed): status='closed'
- `healthy=false` (orphaned): status='orphaned' (server restarted)

---

#### `reconcileOrphanedSessions(activeMcpSessionIds)`

Detects sessions marked 'active' in DB but with no MCP session.

**Parameters**:
- `activeMcpSessionIds: string[]` - Array of active MCP session IDs

**Returns**:
```typescript
{
  orphaned: Array<{
    id: string,
    sessionId: string,
    conversationId: string,
    platform: string,
    messageCount: number,
    ...
  }>,
  updated: number
}
```

**Example**:
```javascript
const activeSessions = sessionManager.getActiveSessions();
const result = await conversationStore.reconcileOrphanedSessions(activeSessions);

if (result.orphaned.length > 0) {
  console.log(`Found ${result.orphaned.length} orphaned sessions`);
  result.orphaned.forEach(session => {
    console.log(`  - ${session.platform}: ${session.conversationId}`);
  });
}
```

---

#### `findByConversationId(conversationId, platform)`

Finds Conversation by platform-specific conversationId.

**Parameters**:
- `conversationId: string` - Platform conversation ID
- `platform: string` - Platform name

**Returns**: `Object | null` - Conversation or null if not found

**Example**:
```javascript
const conversation = await conversationStore.findByConversationId(
  'abc-123-def',
  'claude'
);

if (conversation) {
  console.log(`Found conversation: ${conversation.title}`);
  console.log(`Status: ${conversation.status}`);
}
```

---

#### `findBySessionId(sessionId)`

Finds Conversation by MCP sessionId.

**Parameters**:
- `sessionId: string` - MCP session ID

**Returns**: `Object | null` - Conversation or null if not found

**Example**:
```javascript
const conversation = await conversationStore.findBySessionId('uuid-123');
```

---

### SessionManager Methods

#### `healthCheck(sessionId)`

Checks if browser is responsive.

**Parameters**:
- `sessionId: string` - MCP session ID

**Returns**: `'healthy' | 'stale' | 'dead'`

**Throws**: Error if session not found

**Example**:
```typescript
const health = await sessionManager.healthCheck(sessionId);

if (health === 'dead') {
  // Browser crashed or closed
  await sessionManager.destroySession(sessionId);
}
```

---

#### `updateSessionState(sessionId)`

Updates session's conversationUrl from browser.

**Parameters**:
- `sessionId: string` - MCP session ID

**Returns**:
```typescript
{
  conversationId: string | null,
  conversationUrl: string
}
```

**Example**:
```typescript
const state = await sessionManager.updateSessionState(sessionId);
console.log(`Current URL: ${state.conversationUrl}`);
```

---

#### `validateSessionHealth(sessionId)`

Pre-flight check that throws if session is dead.

**Parameters**:
- `sessionId: string` - MCP session ID

**Throws**: Error if session not found or browser is dead

**Example**:
```typescript
try {
  await sessionManager.validateSessionHealth(sessionId);
  // Safe to proceed with tool execution
} catch (err) {
  console.error(`Session validation failed: ${err.message}`);
  // Return error to user
}
```

---

#### `syncWithDatabase(conversationStore)`

Reconciles orphaned sessions on server startup.

**Parameters**:
- `conversationStore: ConversationStore` - Database store instance

**Example**:
```typescript
// On server startup
await sessionManager.syncWithDatabase(conversationStore);
```

---

## Platform Configuration

Access platform details from registry:

```javascript
const platform = ConversationStore.PLATFORMS['claude'];

console.log(platform.displayName); // 'Claude'
console.log(platform.provider); // 'Anthropic'
console.log(platform.baseUrl); // 'https://claude.ai'
console.log(platform.newChatUrl); // 'https://claude.ai/new'
console.log(platform.conversationUrlPattern); // 'https://claude.ai/chat/:id'

// Test regex
const match = 'https://claude.ai/chat/abc-123'.match(platform.conversationIdRegex);
console.log(match[1]); // 'abc-123'
```

**Available platforms**: `claude`, `chatgpt`, `gemini`, `grok`, `perplexity`

---

## Error Handling

### Session Not Found

```typescript
try {
  await sessionManager.validateSessionHealth('invalid-id');
} catch (err) {
  // err.message: "Session not found: invalid-id"
}
```

### Browser Dead

```typescript
try {
  await sessionManager.validateSessionHealth(sessionId);
} catch (err) {
  // err.message: "Session xyz-789 is dead (browser crashed or closed)"
  // User should reconnect or start fresh
}
```

### Conversation ID Extraction Failed

```typescript
const { synced } = await conversationStore.updateSessionState(
  sessionId,
  'https://invalid-url.com',
  'claude'
);

// synced === false
// conversationUrl still updated (for debugging)
// lastActivity still updated
```

---

## Database Fields Updated

When calling `updateSessionState()`, these Neo4j fields are updated:

```cypher
(:Conversation {
  id: sessionId,
  conversationId: 'abc-123',        // Extracted from URL
  conversationUrl: 'https://...',   // Full browser URL
  lastActivity: datetime(),         // Current timestamp
  status: 'active'                  // Ensures not orphaned
})
```

---

## Session States

```
active      - Session has MCP session, browser responsive, recent activity
closed      - Explicitly disconnected via taey_disconnect
orphaned    - MCP server restarted, no active MCP session
stale       - Status='active' but lastActivity > 1 hour
dead        - Browser crashed or closed
```

---

## Workflow: Resume Orphaned Session

```typescript
// 1. List orphaned sessions
const orphaned = await conversationStore.client.run(`
  MATCH (c:Conversation {status: 'orphaned', platform: 'claude'})
  RETURN c.conversationId as id, c.title as title
`);

console.log('Orphaned sessions:');
orphaned.forEach(s => console.log(`  - ${s.id}: ${s.title}`));

// 2. User selects one to resume
const conversationId = orphaned[0].id;

// 3. Create new MCP session and resume
const newSessionId = await sessionManager.createSession('claude', {
  conversationId
});

// 4. Update database with new session
const conversation = await conversationStore.findByConversationId(
  conversationId,
  'claude'
);

await conversationStore.updateConversation(conversation.id, {
  sessionId: newSessionId,
  status: 'active',
  lastActivity: new Date()
});

console.log(`Resumed conversation ${conversationId} with new session ${newSessionId}`);
```

---

## Testing Checklist

### Unit Tests

- [ ] `extractConversationId()` for all platforms
- [ ] `updateSessionState()` syncs correctly
- [ ] `getSessionHealth()` detects stale sessions
- [ ] `reconcileOrphanedSessions()` marks orphans
- [ ] `findByConversationId()` finds existing
- [ ] `healthCheck()` detects dead browser

### Integration Tests

- [ ] Fresh session: all layers synced
- [ ] Resume session: database updated with new sessionId
- [ ] Browser crash: health check detects and errors
- [ ] Server restart: orphaned sessions detected
- [ ] Navigation: conversationId updated in database
- [ ] Multiple tools: state stays consistent

### Manual Tests

- [ ] Start fresh session → verify conversationId in DB
- [ ] Send message → verify lastActivity updated
- [ ] Restart MCP server → verify sessions marked orphaned
- [ ] Close browser tab → verify health check fails
- [ ] Resume orphaned session → verify conversation history preserved

---

## Performance Considerations

### Health Check Cost

- `validateSessionHealth()` calls `page.url()` (fast, ~10-50ms)
- Only run once per tool call (at start)
- Avoid in tight loops

### Database Sync Cost

- `updateSessionState()` runs one Cypher UPDATE (~20-100ms)
- Run once per tool call (at end)
- Batching not needed (single update)

### Reconciliation Cost

- `reconcileOrphanedSessions()` scans all active conversations
- Should run on startup + every 5-10 minutes
- Cost scales with number of active sessions (typically < 100)

---

## Debugging Tips

### Check Current State

```javascript
// MCP layer
const mcpSession = sessionManager.getSession(sessionId);
console.log('MCP:', {
  conversationUrl: mcpSession.conversationUrl,
  healthStatus: mcpSession.healthStatus,
  lastActivity: mcpSession.lastActivity
});

// Database layer
const dbConversation = await conversationStore.getConversation(sessionId);
console.log('DB:', {
  conversationId: dbConversation.conversationId,
  conversationUrl: dbConversation.conversationUrl,
  status: dbConversation.status
});

// Browser layer
const browserUrl = await mcpSession.interface.getCurrentConversationUrl();
console.log('Browser:', browserUrl);

// Compare
const extracted = conversationStore.extractConversationId(browserUrl, platform);
console.log('All match?',
  mcpSession.conversationUrl === browserUrl &&
  dbConversation.conversationUrl === browserUrl
);
```

### Force Sync

```javascript
// Manually sync current state
const currentUrl = await chatInterface.getCurrentConversationUrl();
await conversationStore.updateSessionState(sessionId, currentUrl, platform);
console.log('State synced');
```

### Check for Orphans

```javascript
const activeMcpSessions = sessionManager.getActiveSessions();
const result = await conversationStore.reconcileOrphanedSessions(activeMcpSessions);
console.log(`Orphaned: ${result.orphaned.length}`);
```

---

## Migration from Old Code

### Before (Old Pattern)

```typescript
case "taey_send_message": {
  const chatInterface = sessionManager.getInterface(sessionId);
  await chatInterface.sendMessage(message);
  return { success: true };
}
```

### After (New Pattern)

```typescript
case "taey_send_message": {
  // ADD: Health check
  await sessionManager.validateSessionHealth(sessionId);

  const chatInterface = sessionManager.getInterface(sessionId);
  await chatInterface.sendMessage(message);

  // ADD: State sync
  const currentUrl = await chatInterface.getCurrentConversationUrl();
  await conversationStore.updateSessionState(sessionId, currentUrl, platform);

  return { success: true };
}
```

---

## FAQ

**Q: Do I need to call updateSessionState after every operation?**
A: Yes, if the operation might change the conversation URL (navigation, new chat, etc.). For operations that definitely don't navigate (screenshot, select model), it's optional but harmless.

**Q: What if extractConversationId returns null?**
A: The sync continues - conversationUrl is still updated, and lastActivity is still updated. Only conversationId remains null. This is fine for homepage/base URL states.

**Q: Can I use sessionId to lookup conversations?**
A: Use `findBySessionId()` for active sessions. Use `findByConversationId()` for orphaned/resumed sessions (more reliable).

**Q: How often should I run reconcileOrphanedSessions?**
A: On server startup (required) + every 5-10 minutes (optional, catches edge cases).

**Q: What happens if browser crashes mid-operation?**
A: Next tool call's `validateSessionHealth()` will detect and throw error. User gets clear message to reconnect.

---

## Support

For issues or questions:
1. Check `SESSION_STATE_SYNC_IMPLEMENTATION.md` for detailed explanation
2. Review `docs/rebuild/SESSION_REQUIREMENTS.md` for problem context
3. Examine test files for usage examples
4. Check Neo4j database directly for state inspection
