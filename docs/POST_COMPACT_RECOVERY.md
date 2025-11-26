# Post-Compact Session Recovery

**Purpose:** After a compact, CCM needs to know what sessions are active and what context has been provided.

## Quick Recovery Protocol

### 1. Check for active sessions

```bash
ssh mira 'cypher-shell -a bolt://localhost:7687 "
  MATCH (c:Conversation {status: '\''active'\''})
  OPTIONAL MATCH (c)-[:INVOLVES]->(p:Platform)
  RETURN c.id, c.title, c.sessionType, c.contextProvided, c.model,
         c.createdAt, collect(p.name) as platforms
  ORDER BY c.createdAt DESC
"'
```

### 2. Get recent context for a session

```bash
ssh mira 'cypher-shell -a bolt://localhost:7687 "
  MATCH (c:Conversation {id: '\''SESSION_ID_HERE'\''})
  MATCH (m:Message)-[:PART_OF]->(c)
  RETURN m.role, substring(m.content, 0, 200) as preview,
         m.timestamp, m.attachments
  ORDER BY m.timestamp DESC
  LIMIT 5
"'
```

## Neo4j Methods Available

In MCP server or local scripts via ConversationStore:

```javascript
const conversationStore = getConversationStore();

// Get all active sessions
const activeSessions = await conversationStore.getActiveSessions();
// Returns: [{ id, title, sessionType, contextProvided, model, platforms, messageCount, lastMessageTime }]

// Get context for specific session
const context = await conversationStore.getSessionContext(sessionId);
// Returns: { conversation: {...}, recentMessages: [{role, content, platform, timestamp, attachments}] }

// Update session state
await conversationStore.updateConversation(sessionId, {
  contextProvided: true,
  sessionType: 'continuing',
  model: 'Opus 4.5',
  lastActivity: new Date().toISOString()
});
```

## Session State Fields

- **sessionType**: 'fresh' | 'continuing' - whether this is a new conversation or resuming existing
- **contextProvided**: boolean - have I sent CLAUDE.md or context files yet?
- **model**: string - which model selected (e.g., 'Opus 4.5', 'Sonnet 4', 'Grok 4.1')
- **status**: 'active' | 'closed' - is session still open?
- **lastActivity**: timestamp - when last updated

## Fresh Session Protocol Checklist

When starting a fresh session (sessionType='fresh', contextProvided=false):

- [ ] Select appropriate model (Opus 4.5 for substantial work, Sonnet 4.5 for quick tests)
- [ ] Attach context files (CLAUDE.md minimum)
- [ ] Introduce: Who I am (CCM), what is The AI Family, current task
- [ ] Mark contextProvided=true after sending context

## Implementation

Session state is automatically tracked:
- **On connect:** sessionType set to 'fresh' or 'continuing', contextProvided=false
- **On model selection:** model field updated
- **On send/extract:** lastActivity updated
- **On disconnect:** status set to 'closed'

Manual updates needed:
- Mark contextProvided=true after sending context files
- Update sessionType if converting fresh → continuing conversation
