# Session Management Requirements Analysis
**Taey-Hands MCP Server v2**

Date: 2025-11-30
Analyzed by: CCM (Claude Code on Mac)

---

## Executive Summary

The current session management has **THREE distinct but confused layers**:

1. **Browser Session** (Playwright/Puppeteer) - The actual browser tab state
2. **MCP Session** (SessionManager in-memory) - Runtime session registry
3. **Database Session** (Neo4j Conversation) - Persistent session records

**THE CORE PROBLEM**: These three layers don't synchronize properly, leading to:
- `newSession=true` doesn't actually create a fresh conversation (just reuses browser state)
- `conversationId` parameter gets ignored after initial connect
- Database shows "active" sessions that have no corresponding browser/MCP session
- No way to resume an existing session after MCP server restart

---

## 1. Session Lifecycle Requirements

### 1.1 What Constitutes a Session?

A session has **THREE components that MUST stay synchronized**:

```
┌─────────────────────────────────────────────────────────────┐
│ SESSION = Browser State + MCP State + Database State        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Browser Layer (Playwright/Puppeteer):                      │
│  - Active browser context/page                              │
│  - Current conversation URL (claude.ai/chat/abc123)         │
│  - DOM state (input field, messages, etc.)                  │
│                                                              │
│  MCP Layer (SessionManager):                                │
│  - sessionId (UUID)                                          │
│  - ChatInterface instance (ClaudeInterface, etc.)           │
│  - interfaceType ('claude', 'chatgpt', etc.)                │
│  - connected: boolean                                        │
│  - createdAt: Date                                           │
│                                                              │
│  Database Layer (Neo4j Conversation):                       │
│  - Conversation node (id, platform, status)                 │
│  - Message history (user/assistant turns)                   │
│  - conversationId (platform-specific chat ID)               │
│  - sessionId (links to MCP session)                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**INVARIANT**: All three layers MUST agree on session state or be marked as disconnected.

### 1.2 Session Creation (Fresh vs Resume)

#### Fresh Session Requirements

**Trigger**: `newSession=true` parameter to `taey_connect`

**Expected behavior**:
```
1. Generate new UUID for sessionId
2. Create new browser context/page
3. Navigate to platform base URL (e.g., claude.ai)
4. Click "New Chat" button OR navigate to /new route
5. Create NEW Conversation node in Neo4j with status='active'
6. Store sessionId → ChatInterface mapping in SessionManager
7. Return screenshot showing EMPTY input (no prior messages)
```

**CURRENT BUG**: Steps 4-5 don't happen. Browser just goes to platform homepage, which may resume last conversation from cookies/local storage.

**Root cause**: `connect()` in chat-interface.js just navigates to `this.url` (e.g., `https://claude.ai`), which loads whatever the browser's cookies remember.

#### Resume Existing Session Requirements

**Trigger**: `conversationId` parameter to `taey_connect` (with or without `sessionId`)

**Expected behavior**:
```
1. If sessionId provided:
   - Look up existing SessionManager entry
   - Verify browser session still alive
   - If alive: navigate to conversationId URL
   - If dead: error (session disconnected)

2. If sessionId NOT provided (new MCP session, resuming DB conversation):
   - Generate new UUID for sessionId
   - Create new browser context/page
   - Navigate directly to conversationId URL (e.g., claude.ai/chat/abc123)
   - Query Neo4j for existing Conversation with conversationId
   - If found: update with new sessionId, set status='active'
   - If not found: create new Conversation node
   - Store sessionId → ChatInterface mapping in SessionManager

3. Return screenshot showing EXISTING conversation with prior messages
```

**CURRENT BUG**: `conversationId` gets passed to `goToConversation()` only AFTER `connect()` completes. But `connect()` already navigated to base URL, so you get:
- Navigate to claude.ai → loads default/last conversation
- THEN navigate to claude.ai/chat/abc123 → extra navigation, confusing state

**Root cause**: Logic split between `server-v2.ts` (lines 383-389) and `chat-interface.js`. Should be atomic.

### 1.3 Session State Transitions

```
┌─────────────┐
│  CREATING   │  (Browser launching, SessionManager allocating)
└──────┬──────┘
       │
       v
┌─────────────┐
│   ACTIVE    │  (Browser connected, MCP session exists, DB status='active')
└──────┬──────┘
       │
       ├──────> User calls taey_disconnect
       │        │
       │        v
       │  ┌─────────────┐
       │  │ DISCONNECTED│  (Browser closed, SessionManager removed, DB status='closed')
       │  └─────────────┘
       │
       ├──────> MCP server restarts (crash, compact, etc.)
       │        │
       │        v
       │  ┌─────────────┐
       │  │  ORPHANED   │  (No browser, no MCP session, DB status='active')
       │  └──────┬──────┘
       │         │
       │         ├──────> User calls taey_connect with conversationId
       │         │        │
       │         │        v
       │         │  Resume (create new MCP session, attach to existing DB conversation)
       │         │
       │         └──────> User calls cleanup script
       │                  │
       │                  v
       │            Mark DB status='closed', abandon
       │
       └──────> Browser crashes
                │
                v
          ┌─────────────┐
          │   STALE     │  (MCP thinks alive, browser actually dead)
          └─────────────┘
                │
                └──────> Next tool call detects dead browser, throws error
```

**MISSING**: State validation on every tool call. No health checks.

### 1.4 Session Cleanup

**Explicit cleanup** (taey_disconnect):
```
1. Call chatInterface.disconnect() → closes browser page/context
2. Remove sessionId from SessionManager.sessions Map
3. Update Neo4j Conversation: status='closed', closedAt=now
4. Log cleanup completion
```

**Implicit cleanup** (MCP server shutdown):
```
CURRENT: Nothing happens - browser stays open, SessionManager lost, DB orphaned

REQUIRED:
1. Process exit handler registered at server startup
2. On SIGTERM/SIGINT: call SessionManager.destroyAllSessions()
3. Each session: update DB status='orphaned', record lastKnownSessionId
4. Graceful exit with cleanup report
```

**Post-compact recovery** (user-initiated):
```
CURRENT: check-sessions-before-connect.mjs shows orphaned sessions but doesn't fix

REQUIRED:
1. Tool: taey_list_orphaned_sessions → queries DB for status='orphaned' or 'active' with no MCP session
2. Tool: taey_resume_orphaned → takes conversationId, creates new MCP session, attaches to DB conversation
3. Tool: taey_cleanup_orphaned → marks all orphaned conversations as status='abandoned', closedAt=now
```

---

## 2. Session State Requirements

### 2.1 What Needs to Be Tracked Per Session?

#### Browser Layer State
```javascript
{
  // Playwright/Puppeteer objects
  browserContext: BrowserContext,
  page: Page,

  // Current location
  currentUrl: string,  // e.g., "https://claude.ai/chat/abc123"
  conversationId: string | null,  // Platform-specific chat ID from URL

  // Health
  isResponsive: boolean,  // Can we send commands?
  lastHealthCheck: Date
}
```

#### MCP Layer State
```typescript
interface Session {
  sessionId: string;           // UUID - our identifier
  interface: ChatInterface;    // ClaudeInterface | ChatGPTInterface | etc.
  interfaceType: InterfaceType; // 'claude' | 'chatgpt' | 'gemini' | 'grok' | 'perplexity'
  createdAt: Date;
  connected: boolean;          // Browser alive?

  // NEW - track browser state
  conversationId: string | null;  // Current conversation we're in
  conversationUrl: string | null; // Full URL
  lastActivity: Date;             // Last tool call timestamp

  // NEW - health tracking
  healthStatus: 'healthy' | 'stale' | 'dead';
  lastHealthCheck: Date;
}
```

#### Database Layer State
```cypher
// Conversation node
(:Conversation {
  id: string,              // Same as sessionId for active sessions
  platform: string,        // 'claude', 'chatgpt', etc.
  sessionId: string,       // Current MCP session ID (null if orphaned)
  conversationId: string,  // Platform-specific chat ID (from URL)

  status: string,          // 'active' | 'closed' | 'orphaned' | 'abandoned'

  title: string,
  purpose: string,
  initiator: string,

  createdAt: datetime,
  closedAt: datetime,      // When explicitly disconnected
  lastActivity: datetime,  // Last message timestamp

  // Context management
  contextProvided: boolean,  // Did we attach clarity-universal-axioms.md?
  model: string,            // Current model selected
  sessionType: string,      // 'fresh' | 'continuing'

  metadata: string          // JSON blob
})
```

### 2.2 Platform Identification

**Problem**: Three different identifiers floating around:
1. `interfaceType` - MCP's name ('claude', 'chatgpt', etc.)
2. `platform` - Neo4j's name (should be same as interfaceType)
3. Platform node names - Separate nodes like `(:Platform {name: 'claude'})`

**REQUIREMENT**: Use single source of truth
```javascript
const PLATFORMS = {
  claude: {
    name: 'claude',
    displayName: 'Claude',
    provider: 'Anthropic',
    baseUrl: 'https://claude.ai',
    conversationUrlPattern: 'https://claude.ai/chat/:id',
    newChatUrl: 'https://claude.ai/new'
  },
  chatgpt: {
    name: 'chatgpt',
    displayName: 'ChatGPT',
    provider: 'OpenAI',
    baseUrl: 'https://chatgpt.com',
    conversationUrlPattern: 'https://chatgpt.com/c/:id',
    newChatUrl: 'https://chatgpt.com'  // Auto-creates new
  },
  // ... etc
};

// Use PLATFORMS[interfaceType] everywhere
// Create Platform nodes from this config
// Validate all platform references against this registry
```

### 2.3 Conversation ID vs Session ID

**THE CONFUSION**:

```
conversationId = Platform-specific chat identifier
                 Examples:
                 - Claude:      UUID from URL /chat/abc-def-123
                 - ChatGPT:     Short hash from URL /c/abc123xyz
                 - Gemini:      Long hex from URL /app/abc123def456
                 - Grok:        UUID from URL /chat/abc-def-123
                 - Perplexity:  UUID from URL /search/abc-def-123

                 This PERSISTS across MCP sessions
                 Stored in browser URL, accessible via page.url()
                 Stored in Neo4j Conversation.conversationId

sessionId      = MCP session identifier (our UUID)
                 Generated by SessionManager.createSession()
                 Lifetime: from taey_connect to taey_disconnect
                 EPHEMERAL - lost on MCP server restart
                 Stored in Neo4j Conversation.sessionId (may be null if orphaned)
```

**REQUIREMENT**: Clear separation
```javascript
// When creating fresh session
const sessionId = randomUUID();  // Our identifier
const conversationId = null;     // Don't know platform ID yet

// After connect completes
const currentUrl = await chatInterface.getCurrentConversationUrl();
const conversationId = extractConversationId(currentUrl, interfaceType);

// Update both MCP and DB
session.conversationId = conversationId;
await conversationStore.updateConversation(sessionId, { conversationId });

// When resuming existing conversation
const sessionId = randomUUID();  // New MCP session
const conversationId = args.conversationId;  // User-provided

// Query DB for existing conversation
const existing = await conversationStore.findByConversationId(conversationId, interfaceType);
if (existing) {
  // Update existing conversation with new sessionId
  await conversationStore.updateConversation(existing.id, {
    sessionId,
    status: 'active',
    lastActivity: new Date()
  });
} else {
  // Create new conversation
  await conversationStore.createConversation({
    id: sessionId,  // Use sessionId as Conversation.id
    sessionId,
    conversationId,
    platform: interfaceType,
    // ... other fields
  });
}
```

### 2.4 Message History Management

**REQUIREMENT**: Every message MUST be associated with correct conversation

```cypher
// Message node structure
(:Message {
  id: string,              // UUID
  conversationId: string,  // Links to Conversation.id (NOT platform conversationId!)

  role: string,            // 'user' | 'assistant' | 'system'
  content: string,
  platform: string,        // Redundant but useful for queries

  timestamp: datetime,

  // Draft message tracking
  sent: boolean,           // False if message typed but not sent
  sentAt: datetime,
  sender: string,          // 'human' | 'mcp_tool' | 'cross_pollination'

  // Attachments
  attachments: string,     // JSON array of file paths
  pastedContent: string,   // JSON array of pasted responses (cross-pollination)

  // Context
  intent: string,          // 'question' | 'command' | 'continuation'
  metadata: string         // JSON blob
})

// Relationships
(m:Message)-[:PART_OF]->(c:Conversation)
(m:Message)-[:FROM]->(p:Platform)
(m:Message)-[:FOLLOWS]->(prev:Message)  // Conversation thread order
(m:Message)-[:DETECTED_BY]->(d:Detection)  // Response detection metadata
```

**CRITICAL**: Use `Conversation.id` (our sessionId) NOT `Conversation.conversationId` (platform's ID) for linking messages.

---

## 3. Current Problems Analysis

### 3.1 Why `newSession=true` Doesn't Create Fresh Sessions

**Code path**:
```typescript
// server-v2.ts line 354-356
if (newSession) {
  sessionId = await sessionManager.createSession(interfaceType);
  // Creates Conversation in Neo4j...
}

// Line 383-384
const chatInterface = sessionManager.getInterface(sessionId);
const connectResult = await chatInterface.connect({ sessionId });

// Line 386-389
if (conversationId) {
  conversationUrl = await chatInterface.goToConversation(conversationId);
}
```

**Problem**: `chatInterface.connect()` just navigates to base URL
```javascript
// chat-interface.js line 39-66
async connect(options = {}) {
  await this.browser.connect();
  this.page = await this.browser.getPage(this.name, this.url);  // ← Goes to base URL
  // ... screenshot ...
  return { screenshot, sessionId };
}
```

**What actually happens**:
1. `newSession=true` → creates new sessionId, new Conversation in DB
2. `connect()` → navigates to https://claude.ai
3. Browser cookies/localStorage load PREVIOUS conversation (e.g., `/chat/old-chat-123`)
4. Screenshot shows old conversation, not empty input
5. User thinks it's a fresh session but it's not

**Fix required**:
```javascript
async connect(options = {}) {
  await this.browser.connect();

  if (options.newConversation) {
    // Navigate directly to new chat URL
    this.page = await this.browser.getPage(this.name, this.getNewChatUrl());
    await this.page.waitForSelector(this.selectors.chatInput);
  } else if (options.conversationId) {
    // Navigate directly to specific conversation
    const url = this.buildConversationUrl(options.conversationId);
    this.page = await this.browser.getPage(this.name, url);
    await this.page.waitForSelector(this.selectors.chatInput);
  } else {
    // Navigate to base URL (resume whatever is there)
    this.page = await this.browser.getPage(this.name, this.url);
  }

  // ... rest of connect ...
}
```

### 3.2 Confusion Between conversationId and sessionId

**Problem locations**:

1. **server-v2.ts line 368**: Uses `sessionId` as Neo4j Conversation.id
   ```typescript
   await conversationStore.createConversation({
     id: sessionId,  // ← Conversation.id = MCP sessionId
     // ...
     conversationId: conversationId || null  // ← Platform chat ID
   });
   ```
   This is CORRECT but confusing because:
   - Neo4j Conversation.id = MCP sessionId (ephemeral)
   - Neo4j Conversation.conversationId = Platform chat ID (persistent)

2. **taey_validate_step parameter**: Uses `conversationId` to mean sessionId
   ```typescript
   // server-v2.ts line 272
   conversationId: {
     type: "string",
     description: "Conversation ID (same as sessionId)"  // ← WRONG terminology
   }
   ```

3. **check-sessions-before-connect.mjs**: No way to query by platform conversationId
   ```javascript
   // Can only filter by platform name, not by conversationId
   const relevant = platformHint
     ? activeSessions.filter(s => s.platforms.includes(platformHint))
     : activeSessions;
   ```

**Fix required**: Consistent naming
```
MCP Session ID    → Always call it "sessionId"
Platform Chat ID  → Always call it "conversationId"
Neo4j Conversation.id → Clarify this equals sessionId for active sessions
Neo4j Conversation.conversationId → Clarify this equals platform chat ID
```

Add helper methods:
```javascript
// conversation-store.js
async findByConversationId(conversationId, platform) {
  return await this.client.run(
    `MATCH (c:Conversation {conversationId: $conversationId, platform: $platform})
     RETURN c`,
    { conversationId, platform }
  );
}

async findBySessionId(sessionId) {
  return await this.client.run(
    `MATCH (c:Conversation {sessionId: $sessionId})
     RETURN c`,
    { sessionId }
  );
}
```

### 3.3 Database vs In-Memory Session State Mismatch

**Problem**: Three-way split with no reconciliation

```
SessionManager (in-memory Map)
  ↕ No sync mechanism
Neo4j ConversationStore (persistent DB)
  ↕ No sync mechanism
Browser State (Playwright page)
```

**Failure scenarios**:

1. **MCP server restart**:
   - SessionManager.sessions Map wiped (empty)
   - Neo4j has Conversations with status='active'
   - Browsers still running but orphaned
   - Result: No way to reconnect to existing browsers

2. **Browser crash**:
   - SessionManager thinks session alive (connected=true)
   - Neo4j has Conversation with status='active'
   - Browser actually dead
   - Result: Tool calls fail with cryptic Playwright errors

3. **Manual disconnect of one layer**:
   - User closes browser tab manually
   - SessionManager still has session (connected=true)
   - Neo4j still has Conversation (status='active')
   - Result: Stale state everywhere

**Fix required**: State synchronization protocol

```javascript
// session-manager.ts
class SessionManager {
  async healthCheck(sessionId) {
    const session = this.sessions.get(sessionId);
    if (!session) return 'not_found';

    try {
      // Try to get page URL (will fail if browser dead)
      await session.interface.page.url();
      session.lastHealthCheck = new Date();
      session.healthStatus = 'healthy';
      return 'healthy';
    } catch (err) {
      session.healthStatus = 'dead';
      return 'dead';
    }
  }

  async syncWithDatabase(conversationStore) {
    // Get all active conversations from DB
    const dbSessions = await conversationStore.getActiveSessions();

    // Check each one
    for (const dbSession of dbSessions) {
      const mcpSession = this.sessions.get(dbSession.sessionId);

      if (!mcpSession) {
        // DB says active but no MCP session → mark orphaned
        await conversationStore.updateConversation(dbSession.id, {
          status: 'orphaned',
          sessionId: null
        });
      } else {
        // Check if browser still alive
        const health = await this.healthCheck(dbSession.sessionId);
        if (health === 'dead') {
          await conversationStore.updateConversation(dbSession.id, {
            status: 'orphaned',
            sessionId: null
          });
          this.sessions.delete(dbSession.sessionId);
        }
      }
    }
  }
}

// Call on MCP server startup
await sessionManager.syncWithDatabase(conversationStore);

// Call periodically (every 60s?)
setInterval(() => {
  sessionManager.syncWithDatabase(conversationStore).catch(console.error);
}, 60000);
```

---

## 4. Requirements for Rebuild

### 4.1 Clear Session State Model

**Single source of truth pattern**:

```
┌─────────────────────────────────────────────────────────────┐
│                    SESSION STATE MACHINE                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  State: CREATING                                             │
│    - MCP: sessionId allocated, ChatInterface instantiated   │
│    - Browser: Launching/connecting                          │
│    - DB: Not yet created                                     │
│    → Transition: Browser ready → CONNECTING                  │
│                                                              │
│  State: CONNECTING                                           │
│    - MCP: Interface.connect() in progress                   │
│    - Browser: Navigating to URL                             │
│    - DB: Conversation created with status='active'          │
│    → Transition: Page loaded → ACTIVE                        │
│                                                              │
│  State: ACTIVE                                               │
│    - MCP: connected=true, healthStatus='healthy'            │
│    - Browser: Page responsive, can send commands            │
│    - DB: status='active', lastActivity updated on tool call │
│    → Transitions:                                            │
│      - User disconnect → DISCONNECTING                       │
│      - Browser crash → STALE                                 │
│      - MCP restart → ORPHANED (from DB perspective)          │
│                                                              │
│  State: STALE                                                │
│    - MCP: connected=true but healthStatus='dead'            │
│    - Browser: Crashed/closed                                │
│    - DB: status='active' (not yet detected)                 │
│    → Transition: Health check fails → CLEANUP                │
│                                                              │
│  State: ORPHANED                                             │
│    - MCP: No session (server restarted)                     │
│    - Browser: May still be running (user hasn't closed)     │
│    - DB: status='orphaned', sessionId=null                  │
│    → Transitions:                                            │
│      - User resume → RECONNECTING                            │
│      - User cleanup → ABANDONED                              │
│                                                              │
│  State: RECONNECTING                                         │
│    - MCP: New sessionId, new ChatInterface                  │
│    - Browser: Navigating to conversationId URL              │
│    - DB: Update existing Conversation with new sessionId    │
│    → Transition: Page loaded → ACTIVE                        │
│                                                              │
│  State: DISCONNECTING                                        │
│    - MCP: Interface.disconnect() called                     │
│    - Browser: Closing page/context                          │
│    - DB: Updating status='closed', closedAt=now             │
│    → Transition: Cleanup complete → CLOSED                   │
│                                                              │
│  State: CLOSED                                               │
│    - MCP: Session removed from registry                     │
│    - Browser: Page/context closed                           │
│    - DB: status='closed', permanent record                  │
│    → Terminal state                                          │
│                                                              │
│  State: ABANDONED                                            │
│    - MCP: No session                                         │
│    - Browser: Unknown (user may have closed)                │
│    - DB: status='abandoned', marked for cleanup             │
│    → Terminal state                                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Enforcement**:
- Every tool call MUST validate state before executing
- State transitions MUST update all three layers atomically
- Health checks run periodically to detect ACTIVE → STALE
- Startup reconciliation detects ORPHANED sessions

### 4.2 Session Creation Flow (Fresh)

```javascript
async function createFreshSession(interfaceType) {
  // 1. Generate identifiers
  const sessionId = randomUUID();

  // 2. Create ChatInterface
  const chatInterface = await createInterface(interfaceType);

  // 3. Connect browser WITH newConversation flag
  await chatInterface.connect({
    sessionId,
    newConversation: true  // ← Forces navigation to /new URL
  });

  // 4. Extract conversationId from URL
  const currentUrl = await chatInterface.getCurrentConversationUrl();
  const conversationId = extractConversationId(currentUrl, interfaceType);

  // 5. Create database record
  await conversationStore.createConversation({
    id: sessionId,
    sessionId,
    conversationId,
    platform: interfaceType,
    status: 'active',
    title: `New ${interfaceType} session`,
    createdAt: new Date(),
    lastActivity: new Date()
  });

  // 6. Store in SessionManager
  sessionManager.sessions.set(sessionId, {
    sessionId,
    interface: chatInterface,
    interfaceType,
    conversationId,
    connected: true,
    healthStatus: 'healthy',
    createdAt: new Date(),
    lastActivity: new Date(),
    lastHealthCheck: new Date()
  });

  // 7. Return unified state
  return {
    sessionId,
    conversationId,
    interfaceType,
    url: currentUrl,
    status: 'active'
  };
}
```

### 4.3 Session Resumption Flow

```javascript
async function resumeSession(interfaceType, conversationId, sessionId = null) {
  // 1. Check if conversationId exists in DB
  const existing = await conversationStore.findByConversationId(conversationId, interfaceType);

  // 2. Determine if this is MCP session resume or DB conversation resume
  if (sessionId && sessionManager.has(sessionId)) {
    // MCP session exists - just navigate to conversationId
    const chatInterface = sessionManager.getInterface(sessionId);
    await chatInterface.goToConversation(conversationId);

    // Update session state
    const session = sessionManager.getSession(sessionId);
    session.conversationId = conversationId;
    session.lastActivity = new Date();

    // Update DB
    if (existing) {
      await conversationStore.updateConversation(existing.id, {
        sessionId,
        status: 'active',
        lastActivity: new Date()
      });
    }

    return { sessionId, conversationId, resumed: 'mcp_session' };
  }

  // 3. No MCP session - create new one and attach to DB conversation
  const newSessionId = randomUUID();

  // 4. Create ChatInterface
  const chatInterface = await createInterface(interfaceType);

  // 5. Connect browser directly to conversationId
  await chatInterface.connect({
    sessionId: newSessionId,
    conversationId  // ← Connect knows to go to this URL
  });

  // 6. Update or create database record
  if (existing) {
    await conversationStore.updateConversation(existing.id, {
      sessionId: newSessionId,
      status: 'active',
      lastActivity: new Date()
    });
  } else {
    await conversationStore.createConversation({
      id: newSessionId,
      sessionId: newSessionId,
      conversationId,
      platform: interfaceType,
      status: 'active',
      title: `Resumed ${interfaceType} conversation`,
      createdAt: new Date(),
      lastActivity: new Date()
    });
  }

  // 7. Store in SessionManager
  sessionManager.sessions.set(newSessionId, {
    sessionId: newSessionId,
    interface: chatInterface,
    interfaceType,
    conversationId,
    connected: true,
    healthStatus: 'healthy',
    createdAt: new Date(),
    lastActivity: new Date(),
    lastHealthCheck: new Date()
  });

  return {
    sessionId: newSessionId,
    conversationId,
    resumed: 'db_conversation'
  };
}
```

### 4.4 State Persistence Needs

**What must survive MCP server restart**:

```javascript
// Neo4j Conversation node (already persisted)
{
  id: string,              // Last known sessionId
  sessionId: string,       // null after restart (orphaned)
  conversationId: string,  // CRITICAL - how we reconnect
  platform: string,        // CRITICAL - which interface
  status: 'orphaned',      // Set by shutdown handler

  // Recovery hints
  lastKnownUrl: string,    // Last conversation URL we were at
  lastActivity: datetime,  // When we were last active

  // Context restoration
  contextProvided: boolean,
  model: string,
  sessionType: string,

  metadata: string  // JSON: { attachments, settings, etc. }
}
```

**What can be reconstructed**:

```javascript
// SessionManager state - rebuild on startup
await sessionManager.syncWithDatabase(conversationStore);

// For each orphaned conversation:
// - User decides: resume or abandon
// - If resume: call resumeSession(platform, conversationId)
// - If abandon: mark status='abandoned'
```

**What is lost (acceptable)**:

- In-memory message buffers (can re-query from DB)
- Playwright page state (reconstructed by navigating to URL)
- ValidationCheckpoint pending states (reset on startup)

**NOT acceptable to lose**:

- Conversation history (persisted in Neo4j)
- File attachments (paths stored in Message nodes)
- Detection metadata (persisted in Detection nodes)
- Platform conversationId (needed to reconstruct URL)

---

## 5. Implementation Recommendations

### 5.1 Immediate Fixes (Critical Path)

**Priority 1: Fix newSession behavior**
```javascript
// chat-interface.js
async connect(options = {}) {
  await this.browser.connect();

  // Determine target URL
  let targetUrl;
  if (options.newConversation) {
    targetUrl = this._getNewChatUrl();
  } else if (options.conversationId) {
    targetUrl = this.buildConversationUrl(options.conversationId);
  } else {
    targetUrl = this.url;  // Base URL
  }

  this.page = await this.browser.getPage(this.name, targetUrl);
  await this.page.waitForSelector(this.selectors.chatInput, { timeout: 15000 });

  // Extract actual conversationId from URL
  const currentUrl = await this.getCurrentConversationUrl();
  const conversationId = this._extractConversationId(currentUrl);

  // ... rest of connect ...

  return {
    screenshot,
    sessionId,
    conversationId  // ← Return what we actually landed on
  };
}

_getNewChatUrl() {
  // Override per platform
  // Claude: https://claude.ai/new
  // ChatGPT: https://chatgpt.com (auto-creates)
  // etc.
}
```

**Priority 2: Separate conversationId from sessionId in API**
```typescript
// server-v2.ts - taey_connect
case "taey_connect": {
  const {
    interface: interfaceType,
    sessionId: providedSessionId,  // Reuse existing MCP session
    newSession,                     // Create fresh conversation
    conversationId                  // Resume specific platform conversation
  } = args;

  // Validation
  if (providedSessionId && newSession) {
    throw new Error('Cannot reuse sessionId and create newSession simultaneously');
  }
  if (newSession && conversationId) {
    throw new Error('Cannot create newSession and resume conversationId simultaneously');
  }

  // ... dispatch to appropriate flow ...
}
```

**Priority 3: Add health checks**
```javascript
// session-manager.ts
async validateSessionHealth(sessionId) {
  const session = this.sessions.get(sessionId);
  if (!session) throw new Error(`Session not found: ${sessionId}`);

  try {
    await session.interface.page.url();
    session.healthStatus = 'healthy';
    session.lastHealthCheck = new Date();
    return true;
  } catch (err) {
    session.healthStatus = 'dead';
    throw new Error(`Session ${sessionId} is dead (browser crashed)`);
  }
}

// Call before EVERY tool execution
getInterface(sessionId) {
  this.validateSessionHealth(sessionId);  // Throws if dead
  return this.sessions.get(sessionId).interface;
}
```

### 5.2 Architecture Changes (Medium Term)

**1. Unified session state class**
```typescript
class ManagedSession {
  // Identifiers
  sessionId: string;           // MCP UUID
  conversationId: string;      // Platform chat ID
  platform: InterfaceType;

  // Components
  interface: ChatInterface;
  dbStore: ConversationStore;

  // State
  state: SessionState;  // Enum: CREATING | ACTIVE | STALE | etc.

  // Sync methods
  async syncToDB() {
    await this.dbStore.updateConversation(this.sessionId, {
      conversationId: this.conversationId,
      status: this.stateToDbStatus(),
      lastActivity: new Date()
    });
  }

  async syncFromBrowser() {
    const url = await this.interface.getCurrentConversationUrl();
    this.conversationId = extractConversationId(url, this.platform);
  }

  async healthCheck() {
    try {
      await this.interface.page.url();
      this.state = SessionState.ACTIVE;
    } catch {
      this.state = SessionState.STALE;
      await this.syncToDB();
      throw new Error(`Session ${this.sessionId} is stale`);
    }
  }

  // Tool execution wrapper
  async execute(toolFn) {
    await this.healthCheck();
    const result = await toolFn(this.interface);
    await this.syncFromBrowser();
    await this.syncToDB();
    return result;
  }
}
```

**2. Startup reconciliation**
```javascript
// server-v2.ts startup
async function initializeServer() {
  // Initialize schemas
  await conversationStore.initSchema();
  await validationStore.initSchema();

  // Reconcile orphaned sessions
  const orphaned = await conversationStore.getActiveSessions();
  if (orphaned.length > 0) {
    console.error(`[MCP] Found ${orphaned.length} orphaned sessions from previous run`);

    for (const session of orphaned) {
      await conversationStore.updateConversation(session.id, {
        status: 'orphaned',
        sessionId: null
      });
    }

    console.error('[MCP] Orphaned sessions marked. Use check-sessions-before-connect to review.');
  }

  // Register shutdown handler
  process.on('SIGTERM', async () => {
    console.error('[MCP] Shutting down gracefully...');
    await sessionManager.destroyAllSessions();
    process.exit(0);
  });
}
```

**3. Recovery tools**
```typescript
// New MCP tools
{
  name: "taey_list_sessions",
  description: "List all sessions (active, orphaned, recent closed). Use before connecting to avoid context loss.",
  inputSchema: {
    type: "object",
    properties: {
      platform: {
        type: "string",
        enum: ["claude", "chatgpt", "gemini", "grok", "perplexity"],
        description: "Optional: Filter by platform"
      },
      status: {
        type: "string",
        enum: ["active", "orphaned", "closed"],
        description: "Optional: Filter by status"
      }
    }
  }
}

{
  name: "taey_resume_session",
  description: "Resume an orphaned session by conversationId. Creates new MCP session attached to existing conversation.",
  inputSchema: {
    type: "object",
    properties: {
      conversationId: {
        type: "string",
        description: "Platform conversation ID from Neo4j"
      },
      platform: {
        type: "string",
        enum: ["claude", "chatgpt", "gemini", "grok", "perplexity"]
      }
    },
    required: ["conversationId", "platform"]
  }
}
```

### 5.3 Testing Requirements

**Unit tests**:
```javascript
describe('SessionManager', () => {
  test('createSession with newSession=true navigates to /new', async () => {
    const sessionId = await sessionManager.createSession('claude', { newSession: true });
    const session = sessionManager.getSession(sessionId);
    const url = await session.interface.page.url();
    expect(url).toContain('/new');
  });

  test('resumeSession navigates to conversationId', async () => {
    const sessionId = await sessionManager.resumeSession('claude', 'abc-123-def');
    const session = sessionManager.getSession(sessionId);
    const url = await session.interface.page.url();
    expect(url).toContain('abc-123-def');
  });

  test('healthCheck detects dead browser', async () => {
    const sessionId = await sessionManager.createSession('claude');
    const session = sessionManager.getSession(sessionId);

    // Kill browser manually
    await session.interface.page.close();

    // Health check should detect
    await expect(sessionManager.validateSessionHealth(sessionId)).rejects.toThrow('dead');
  });
});
```

**Integration tests**:
```javascript
describe('MCP Server Session Flow', () => {
  test('fresh session creates empty conversation', async () => {
    const result = await mcpClient.callTool('taey_connect', {
      interface: 'claude',
      newSession: true
    });

    expect(result.sessionId).toBeDefined();
    expect(result.conversationId).toBeDefined();

    // Verify in DB
    const conversation = await conversationStore.getConversation(result.sessionId);
    expect(conversation.status).toBe('active');
    expect(conversation.platform).toBe('claude');
  });

  test('resume session attaches to existing conversation', async () => {
    // Create initial session
    const session1 = await mcpClient.callTool('taey_connect', {
      interface: 'claude',
      newSession: true
    });

    // Send message
    await mcpClient.callTool('taey_send_message', {
      sessionId: session1.sessionId,
      message: 'Test message'
    });

    // Disconnect
    await mcpClient.callTool('taey_disconnect', {
      sessionId: session1.sessionId
    });

    // Simulate server restart
    await restartMcpServer();

    // Resume by conversationId
    const session2 = await mcpClient.callTool('taey_resume_session', {
      conversationId: session1.conversationId,
      platform: 'claude'
    });

    // Verify same conversation
    const messages = await conversationStore.getMessages(session2.sessionId);
    expect(messages.length).toBeGreaterThan(0);
    expect(messages[0].content).toBe('Test message');
  });
});
```

---

## 6. Migration Strategy

### 6.1 Backward Compatibility

**Problem**: Existing code/scripts call `taey_connect` with old assumptions

**Solution**: Deprecation path
```typescript
// Phase 1: Support both old and new API
case "taey_connect": {
  const { interface, sessionId, newSession, conversationId } = args;

  // OLD API COMPATIBILITY
  if (!sessionId && !newSession && !conversationId) {
    console.error('[DEPRECATED] taey_connect without explicit session control. ' +
                  'Please use newSession=true or provide conversationId. ' +
                  'Defaulting to newSession=true for now.');
    args.newSession = true;
  }

  // ... rest of logic ...
}

// Phase 2 (1 month later): Warn loudly
if (!sessionId && !newSession && !conversationId) {
  throw new Error('BREAKING CHANGE: taey_connect requires explicit session management. ' +
                  'Use newSession=true for fresh sessions or conversationId to resume.');
}
```

### 6.2 Data Migration

**Problem**: Existing Conversation nodes may not have conversationId field

**Solution**: Backfill script
```javascript
// migrate-conversations.mjs
async function migrateConversations() {
  // Find conversations without conversationId
  const conversations = await conversationStore.client.run(
    `MATCH (c:Conversation)
     WHERE c.conversationId IS NULL
     RETURN c`
  );

  console.log(`Found ${conversations.length} conversations to migrate`);

  for (const conv of conversations) {
    // Extract from metadata if stored there
    const metadata = JSON.parse(conv.metadata || '{}');
    const conversationId = metadata.conversationId || null;

    if (conversationId) {
      await conversationStore.updateConversation(conv.id, { conversationId });
      console.log(`  ✓ Migrated ${conv.id} → ${conversationId}`);
    } else {
      console.log(`  ⚠ No conversationId for ${conv.id}, skipping`);
    }
  }
}
```

### 6.3 Rollout Plan

**Week 1**: Core fixes
- Fix `connect()` to respect newSession flag
- Add conversationId tracking to SessionManager
- Separate conversationId from sessionId in DB schema
- Add health checks
- Deploy, test with new sessions only

**Week 2**: Recovery tools
- Add taey_list_sessions
- Add taey_resume_session
- Add startup reconciliation
- Test orphaned session recovery

**Week 3**: State synchronization
- Implement ManagedSession wrapper
- Add periodic health checks
- Add graceful shutdown handler
- Test browser crash scenarios

**Week 4**: Testing & documentation
- Write integration tests
- Update TOOL_REFERENCE.md
- Update AI Family Communication Protocol
- Update check-sessions-before-connect.mjs

---

## 7. Open Questions

1. **Should we support multiple browser sessions per MCP session?**
   - Current: 1 MCP session = 1 browser page
   - Alternative: 1 MCP session = multiple tabs (cross-pollination within session)
   - Decision needed

2. **How to handle conversationId extraction failures?**
   - Some platforms may use non-standard URL patterns
   - Fallback to null? Throw error? Retry?
   - Need platform-specific regex/parsing

3. **Should conversationId be required for resume?**
   - Could we resume by Conversation.id alone?
   - Risk: Confusing two different IDs
   - Recommendation: Always use conversationId + platform

4. **Validation checkpoint interaction with session state?**
   - Checkpoints use conversationId (=sessionId currently)
   - After fix: Should use Conversation.id (which equals sessionId)
   - But what about orphaned sessions?
   - Need to link checkpoints to conversationId (platform ID) not sessionId

5. **Browser profile persistence?**
   - Current: New incognito context each time (cookies lost)
   - Alternative: Persistent profile (stays logged in)
   - Trade-off: Persistence vs isolation
   - Affects: Login state, conversation history in browser

---

## 8. Success Criteria

A successful rebuild will satisfy:

### Functional Requirements

✅ **Fresh session creation**:
- `taey_connect({ interface: 'claude', newSession: true })` shows empty input
- No prior messages visible
- Database Conversation.status = 'active'
- ConversationId extracted from URL

✅ **Session resumption**:
- `taey_connect({ interface: 'claude', conversationId: 'abc-123' })` shows existing conversation
- Prior messages visible
- Database Conversation updated with new sessionId
- Session state synchronized across all layers

✅ **Orphaned session detection**:
- MCP server restart marks all active sessions as orphaned
- `taey_list_sessions()` shows orphaned sessions
- User can resume with `taey_resume_session()`
- User can abandon with cleanup

✅ **Browser crash handling**:
- Health check detects dead browser
- Session marked as stale
- Database updated to status='orphaned'
- Next tool call fails with clear error message

✅ **Graceful shutdown**:
- SIGTERM handler closes all browsers
- Database updated with status='closed'
- No orphaned sessions left

### Non-Functional Requirements

✅ **State consistency**:
- Browser URL, SessionManager state, and Database all agree on conversationId
- State transitions update all three layers atomically
- Health checks run periodically to detect drift

✅ **Terminology clarity**:
- sessionId always means MCP session UUID
- conversationId always means platform chat ID
- Documentation updated everywhere
- API parameters renamed for clarity

✅ **Recovery resilience**:
- Any session can be resumed after MCP restart
- Conversation history preserved across restarts
- No data loss on clean shutdown
- Minimal data loss on crash (only in-flight messages)

✅ **Developer experience**:
- Clear error messages when session invalid
- Health check failures provide remediation steps
- Database inspection tools (taey_list_sessions)
- Integration tests cover all failure modes

---

## Appendix: Code Locations Reference

### Key Files
- `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts` - MCP tool handlers
- `/Users/REDACTED/taey-hands/mcp_server/session-manager.ts` - Session registry
- `/Users/REDACTED/taey-hands/src/interfaces/chat-interface.js` - Browser automation
- `/Users/REDACTED/taey-hands/src/core/conversation-store.js` - Neo4j persistence
- `/Users/REDACTED/taey-hands/check-sessions-before-connect.mjs` - Database inspection

### Critical Functions
- `SessionManager.createSession()` - Line 54-90 of session-manager.ts
- `ChatInterface.connect()` - Line 39-66 of chat-interface.js
- `ChatInterface.goToConversation()` - Line 812-824 of chat-interface.js
- `ConversationStore.createConversation()` - Line 101-146 of conversation-store.js
- `server-v2.ts taey_connect handler` - Line 336-409 of server-v2.ts

### Bug Locations
- **newSession doesn't create fresh**: chat-interface.js line 45 (navigates to base URL)
- **conversationId ignored**: server-v2.ts line 386-389 (called after connect)
- **No health checks**: session-manager.ts has no validation methods
- **No orphan detection**: server-v2.ts has no startup reconciliation
- **Terminology confusion**: taey_validate_step uses "conversationId" to mean sessionId (line 272)

---

**End of Requirements Document**
