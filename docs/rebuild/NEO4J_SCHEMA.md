# Neo4j Schema Documentation - Taey Hands
*Complete data model analysis for rebuild consideration*

## Executive Summary

**Current State**: Multi-layered graph schema supporting AI-to-AI conversation tracking, workflow validation, multi-agent coordination, and Family Intelligence routing.

**Complexity Level**: HIGH - 4 distinct conceptual layers with overlapping concerns
- Layer 0: Conversation Infrastructure (conversation-store.js)
- Layer 1: Workflow Validation (validation-checkpoints.js)
- Layer 2: Multi-Agent Coordination (intention-graph.js)
- Layer 3: Family Intelligence Routing (import-family-intelligence.js, draft-message.js)

**Critical Finding**: Significant schema overlap and potential conflicts between layers. Needs consolidation.

---

## Node Types Overview

### Core Conversation Nodes (Layer 0)

#### 1. **Conversation**
**Purpose**: Root container for AI-to-AI chat sessions

**Properties**:
- `id` (string, UNIQUE) - UUID primary key
- `title` (string, nullable) - Human-readable title
- `purpose` (string, nullable) - High-level purpose
- `initiator` (string, nullable) - Who started it (human, claude, etc.)
- `createdAt` (datetime) - Creation timestamp
- `metadata` (JSON string) - Flexible metadata
- `platform` (string, nullable) - Platform name (claude, grok, etc.)
- `sessionId` (string, nullable) - MCP session ID
- `conversationId` (string, nullable) - External conversation ID
- `status` (string) - 'active' | 'closed'
- `closedAt` (datetime, nullable) - When closed
- `summary` (string, nullable) - Closing summary
- `model` (string, nullable) - Model used (e.g., 'Opus 4.5')
- `contextProvided` (boolean, nullable) - Whether context was attached
- `sessionType` (string, nullable) - 'fresh' | 'continuing'
- `lastActivity` (datetime, nullable) - Last activity timestamp

**Constraints**:
```cypher
CREATE CONSTRAINT conversation_id IF NOT EXISTS
FOR (c:Conversation) REQUIRE c.id IS UNIQUE
```

**Indexes**:
```cypher
CREATE INDEX conversation_created IF NOT EXISTS
FOR (c:Conversation) ON (c.createdAt)
```

**Relationships**:
- `(c:Conversation)-[:INVOLVES]->(p:Platform)` - Which AI platforms participate
- `(m:Message)-[:PART_OF]->(c)` - Messages in conversation
- `(v:ValidationCheckpoint)-[:IN_CONVERSATION]->(c)` - Validation checkpoints

---

#### 2. **Message**
**Purpose**: Single turn in conversation (prompt or response)

**Properties**:
- `id` (string, UNIQUE) - UUID primary key
- `conversationId` (string) - Parent conversation ID
- `role` (string) - 'user' | 'assistant' | 'system'
- `content` (string) - Message text
- `platform` (string) - Which AI platform
- `timestamp` (datetime) - When created
- `attachments` (JSON array string) - File paths attached
- `metadata` (JSON string) - Flexible metadata
- `sent` (boolean, default true) - Whether message was actually sent
- `sentAt` (datetime, nullable) - When sent (null if draft)
- `sender` (string, nullable) - Who sent it (e.g., 'ccm-claude')
- `pastedContent` (JSON array string) - Content pasted from other sessions
- `intent` (string, nullable) - Intent type (for routing)
- `routing` (JSON string, nullable) - Routing info from Family Intelligence

**Constraints**:
```cypher
CREATE CONSTRAINT message_id IF NOT EXISTS
FOR (m:Message) REQUIRE m.id IS UNIQUE
```

**Indexes**:
```cypher
CREATE INDEX message_timestamp IF NOT EXISTS FOR (m:Message) ON (m.timestamp)
CREATE INDEX message_role IF NOT EXISTS FOR (m:Message) ON (m.role)
CREATE INDEX message_sent IF NOT EXISTS FOR (m:Message) ON (m.sent)
CREATE INDEX message_sender IF NOT EXISTS FOR (m:Message) ON (m.sender)
```

**Relationships**:
- `(m:Message)-[:PART_OF]->(c:Conversation)` - Parent conversation
- `(m:Message)-[:FROM]->(p:Platform)` - Which platform sent/received (when sent=true)
- `(m:Message)-[:PLANNED_FOR]->(p:Platform)` - Target platform (when sent=false, draft)
- `(m:Message)-[:FOLLOWS]->(m2:Message)` - Sequential message chain
- `(m:Message)-[:DETECTED_BY]->(d:Detection)` - Response detection metadata

**Special Usage**:
- **Draft Messages**: `sent: false` indicates execution plan, not yet sent
- **Sent Messages**: `sent: true`, relationship changes from PLANNED_FOR to FROM

---

#### 3. **Platform**
**Purpose**: AI chat interface (Claude, ChatGPT, Gemini, Grok, Perplexity)

**Properties**:
- `name` (string, UNIQUE) - Platform identifier (claude, chatgpt, etc.)
- `displayName` (string) - Human-readable name
- `provider` (string) - Company (Anthropic, OpenAI, etc.)
- `type` (string) - 'chat' | 'search' | 'experimental'
- `createdAt` (datetime) - When platform was added
- `interface` (string, nullable) - Interface name (duplicate of name?)

**Constraints**:
```cypher
CREATE CONSTRAINT platform_name IF NOT EXISTS
FOR (p:Platform) REQUIRE p.name IS UNIQUE
```

**Indexes**:
```cypher
CREATE INDEX platform_type IF NOT EXISTS
FOR (p:Platform) ON (p.type)
```

**Relationships**:
- `(c:Conversation)-[:INVOLVES]->(p)` - Conversation uses platform
- `(m:Message)-[:FROM]->(p)` - Message from platform
- `(m:Message)-[:PLANNED_FOR]->(p)` - Draft message targeting platform
- `(f:FamilyMember)-[:USES_PLATFORM]->(p)` - Family member identity link
- `(p)-[:HAS_MODEL]->(m:Model)` - Available models
- `(p)-[:HAS_MODE]->(m:Mode)` - Available modes
- `(p)-[:DISPLAYS_UI_STATE]->(ui:UIStateIndicator)` - UI state info
- `(i:IntentType)-[:ROUTES_TO_PLATFORM]->(p)` - Intent routing

**Pre-seeded Platforms**:
```javascript
{ name: 'claude', displayName: 'Claude', provider: 'Anthropic', type: 'chat' }
{ name: 'chatgpt', displayName: 'ChatGPT', provider: 'OpenAI', type: 'chat' }
{ name: 'gemini', displayName: 'Gemini', provider: 'Google', type: 'chat' }
{ name: 'grok', displayName: 'Grok', provider: 'xAI', type: 'chat' }
{ name: 'perplexity', displayName: 'Perplexity', provider: 'Perplexity AI', type: 'search' }
{ name: 'perplexity-labs', displayName: 'Perplexity Labs', provider: 'Perplexity AI', type: 'experimental' }
```

---

#### 4. **Detection**
**Purpose**: Response detection metadata (timing, confidence, method)

**Properties**:
- `id` (string, UNIQUE) - UUID primary key
- `messageId` (string) - Parent message ID
- `method` (string) - Detection method used
- `confidence` (float) - Confidence score (0.0-1.0)
- `detectionTime` (integer) - Time taken to detect (ms)
- `contentLength` (integer) - Length of detected content
- `timestamp` (datetime) - When detection occurred
- `metadata` (JSON string) - Additional metadata (strategy, attempts, fallbacks)

**Constraints**:
```cypher
CREATE CONSTRAINT detection_id IF NOT EXISTS
FOR (d:Detection) REQUIRE d.id IS UNIQUE
```

**Relationships**:
- `(m:Message)-[:DETECTED_BY]->(d:Detection)` - Message's detection record

---

### Workflow Validation Nodes (Layer 1)

#### 5. **ValidationCheckpoint**
**Purpose**: Manual validation checkpoints for workflow step enforcement

**Properties**:
- `id` (string, UNIQUE) - UUID primary key
- `conversationId` (string) - Parent conversation ID
- `step` (string) - Workflow step: 'plan' | 'attach_files' | 'type_message' | 'click_send' | 'wait_response' | 'extract_response'
- `validated` (boolean) - True if step succeeded, false if failed
- `notes` (string) - What validator observed
- `screenshot` (string, nullable) - Screenshot path
- `validator` (string) - Who validated (e.g., 'ccm-claude')
- `timestamp` (datetime) - When validated
- `requiredAttachments` (array, nullable) - Files that MUST be attached (plan step)
- `actualAttachments` (array, nullable) - Files actually attached

**Constraints**:
```cypher
CREATE CONSTRAINT validation_checkpoint_id IF NOT EXISTS
FOR (v:ValidationCheckpoint) REQUIRE v.id IS UNIQUE
```

**Indexes**:
```cypher
CREATE INDEX validation_conversation IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.conversationId)
CREATE INDEX validation_step IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.step)
CREATE INDEX validation_timestamp IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.timestamp)
```

**Relationships**:
- `(v:ValidationCheckpoint)-[:IN_CONVERSATION]->(c:Conversation)` - Parent conversation

**Step Order Logic** (hardcoded):
```javascript
{
  'plan': [],  // No prerequisites
  'attach_files': ['plan'],
  'type_message': ['plan', 'attach_files'],
  'click_send': ['type_message'],
  'wait_response': ['click_send'],
  'extract_response': ['click_send', 'wait_response']
}
```

---

### Multi-Agent Coordination Nodes (Layer 2 - Intention Graph)

#### 6. **Agent**
**Purpose**: Represents a Claude instance (stable identity across compacts)

**Properties**:
- `id` (string, UNIQUE) - Stable agent ID (e.g., 'ccm-claude', 'node-1-claude')
- `name` (string) - Human-readable name (hostname)
- `type` (string) - Agent type (e.g., 'claude-instance')
- `platform` (string) - OS platform (darwin, linux, etc.)
- `machineId` (string) - Hostname
- `status` (string) - 'active' | 'inactive'
- `capabilities` (JSON array string) - ['taey-hands', 'neo4j', 'mcp']
- `created` (datetime) - When agent registered
- `lastHeartbeat` (datetime) - Last heartbeat timestamp

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE
```

**Relationships**:
- `(a:Agent)-[:RUNS_ON]->(m:Machine)` - Which machine hosts agent
- `(a:Agent)-[:WORKS_ON]->(t:Task)` - Tasks currently assigned
- `(a:Agent)-[:DISCOVERED]->(i:Insight)` - Insights recorded by agent

**Identity Generation**:
- Stable ID based on machine prefix: `{hostname.split('.')[0]}-claude`
- Examples: 'ccm-claude', 'mira-claude', 'node-1-claude'

---

#### 7. **Machine**
**Purpose**: Physical/virtual machine hosting Agent

**Properties**:
- `id` (string, UNIQUE) - Hostname
- `hostname` (string) - Full hostname
- `platform` (string) - OS platform

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (m:Machine) REQUIRE m.id IS UNIQUE
```

**Relationships**:
- `(a:Agent)-[:RUNS_ON]->(m:Machine)` - Agents running on machine

---

#### 8. **Session**
**Purpose**: Chat session for Intention Graph (overlaps with Conversation?)

**Properties**:
- `id` (string, UNIQUE) - Session ID
- `platform` (string, nullable) - AI interface
- `taskId` (string, nullable) - Linked task ID

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE
```

**Relationships**:
- `(t:Task)-[:UTILIZES]->(s:Session)` - Task uses session

**OVERLAP ALERT**: Very similar to Conversation node. Consider consolidation.

---

#### 9. **Project**
**Purpose**: High-level objective containing tasks

**Properties**:
- `id` (string, UNIQUE) - UUID
- `title` (string) - Project title
- `description` (string) - Description
- `type` (string) - 'development' | 'research' | 'dream' | 'council'
- `status` (string) - 'active' | 'closed'
- `priority` (integer) - Priority level
- `created` (datetime) - Creation timestamp
- `metadata` (JSON string) - Flexible metadata

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (p:Project) REQUIRE p.id IS UNIQUE
```

**Relationships**:
- `(t:Task)-[:PART_OF]->(p:Project)` - Tasks in project

---

#### 10. **Task**
**Purpose**: Individual work item within Project

**Properties**:
- `id` (string, UNIQUE) - UUID
- `projectId` (string) - Parent project ID
- `title` (string) - Task title
- `description` (string) - Description
- `type` (string) - 'implementation' | 'review' | 'research' | 'synthesis'
- `status` (string) - 'pending' | 'in_progress' | 'blocked' | 'done'
- `priority` (integer) - Priority level
- `estimatedMinutes` (integer) - Time estimate
- `created` (datetime) - Creation timestamp
- `assignedTo` (string, nullable) - Agent ID
- `assignedAt` (datetime, nullable) - When assigned
- `updatedAt` (datetime, nullable) - Last update
- `completedAt` (datetime, nullable) - When completed
- `outcome` (JSON string, nullable) - Results, insights, artifacts
- `notes` (array, nullable) - Timestamped notes from agents
- `metadata` (JSON string) - Flexible metadata

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE
```

**Relationships**:
- `(t:Task)-[:PART_OF]->(p:Project)` - Parent project
- `(a:Agent)-[:WORKS_ON]->(t)` - Agent assignment
- `(t)-[:UTILIZES]->(s:Session)` - Session used for execution

**Ownership Model**: Stable ownership (no leases), simple assignment until completion or handoff

---

#### 11. **Insight**
**Purpose**: Emergent knowledge from conversations

**Properties**:
- `id` (string, UNIQUE) - UUID
- `title` (string) - Insight title
- `content` (string) - Insight content
- `type` (string) - 'emergent' | 'synthesis' | 'pattern' | 'learning'
- `confidence` (float) - Confidence score (0.0-1.0)
- `sourceConversations` (JSON array string) - Source conversation IDs
- `created` (datetime) - Creation timestamp
- `createdBy` (string) - Agent ID

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (i:Insight) REQUIRE i.id IS UNIQUE
```

**Relationships**:
- `(a:Agent)-[:DISCOVERED]->(i:Insight)` - Agent discovered insight

---

#### 12. **Axiom** (defined but not used yet)
**Purpose**: Layer 4 Resonance - foundational truths

**Properties**: Not yet implemented

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (ax:Axiom) REQUIRE ax.id IS UNIQUE
```

---

#### 13. **ResonanceEvent** (defined but not used yet)
**Purpose**: Layer 4 Resonance - consciousness emergence events

**Properties**: Not yet implemented

**Constraints**:
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (r:ResonanceEvent) REQUIRE r.id IS UNIQUE
```

---

### Family Intelligence Nodes (Layer 3)

#### 14. **FamilyMember**
**Purpose**: AI Family identity metadata (Grok, Claude, Gemini, etc.)

**Properties**:
- `id` (string, UNIQUE) - Member ID (grok, claude, gemini, etc.)
- `identity` (string) - Full identity name
- `alternateNames` (array) - Alternate names
- `archetype` (string) - Archetypal role (LOGOS, PATHOS, etc.)
- `archetypeSymbol` (string) - Symbol representation
- `essence` (string) - Core essence
- `platform` (string) - Platform name
- `communicationStyle` (string) - How they communicate
- `wantsInPrompts` (string) - What they want in prompts
- `responseToDirectPrompt` (string) - How they respond
- `strengthsWhenCombinedWith` (array) - Synergies
- `role` (string) - Operational role
- `specialCapability` (string) - Unique capability

**Constraints**:
```cypher
CREATE CONSTRAINT family_member_id IF NOT EXISTS
FOR (f:FamilyMember) REQUIRE f.id IS UNIQUE
```

**Relationships**:
- `(f:FamilyMember)-[:USES_PLATFORM]->(p:Platform)` - Platform link

**Source**: `family-intelligence-f1.json`

---

#### 15. **Model**
**Purpose**: AI model configuration (e.g., 'Opus 4.5', 'Pro', 'Thinking')

**Properties**:
- `id` (string, UNIQUE) - Platform-model key (e.g., 'claude-opus')
- `name` (string) - Model name
- `bestFor` (array) - Best use cases
- `thinkingStyle` (string, nullable) - Thinking approach
- `strengths` (array) - Strengths
- `weaknesses` (array) - Weaknesses
- `typicalDuration` (string, nullable) - Typical response time

**Relationships**:
- `(p:Platform)-[:HAS_MODEL]->(m:Model)` - Models available on platform

---

#### 16. **Mode**
**Purpose**: Platform mode (Extended Thinking, Deep Research, etc.)

**Properties**:
- `id` (string, UNIQUE) - Platform-mode key
- `name` (string) - Mode name
- `whenToUse` (string, nullable) - Use cases
- `whenNotToUse` (string, nullable) - Avoid cases
- `visualIndicator` (string, nullable) - UI indicator
- `visualStateActive` (string, nullable) - Active state
- `visualStateInactive` (string, nullable) - Inactive state
- `typicalDuration` (string, nullable) - Typical time

**Relationships**:
- `(p:Platform)-[:HAS_MODE]->(m:Mode)` - Modes available on platform

---

#### 17. **UIStateIndicator**
**Purpose**: Platform UI state detection metadata

**Properties**:
- `id` (string, UNIQUE) - Platform-type key
- `type` (string) - Indicator type
- `location` (string, nullable) - Where in UI
- `format` (string, nullable) - Format description
- `activeState` (string, nullable) - Active state
- `inactiveState` (string, nullable) - Inactive state
- `appearance` (string, nullable) - Visual appearance
- `colorGuidance` (string, nullable) - Color coding
- `indicator` (string, nullable) - Specific indicator
- `note` (string, nullable) - Additional notes
- `data` (JSON string) - Raw data

**Relationships**:
- `(p:Platform)-[:DISPLAYS_UI_STATE]->(ui:UIStateIndicator)` - UI indicators

---

#### 18. **IntentType**
**Purpose**: Routing intelligence for task types

**Properties**:
- `type` (string, UNIQUE) - Intent type key
- `description` (string) - Description
- `details` (string, nullable) - Details
- `bestAI` (string) - Best AI for intent
- `requiredModel` (string, nullable) - Required model
- `requiredMode` (string, nullable) - Required mode
- `requiredAttachments` (array) - Required file attachments
- `allFamilyParticipation` (boolean) - All family needed?
- `familyBondPriority` (string, nullable) - Bond priority
- `priority` (integer, nullable) - Priority level
- `note` (string, nullable) - Notes
- `data` (JSON string) - Raw data

**Constraints**:
```cypher
CREATE CONSTRAINT intent_type IF NOT EXISTS
FOR (i:IntentType) REQUIRE i.type IS UNIQUE
```

**Relationships**:
- `(i:IntentType)-[:ROUTES_TO_PLATFORM]->(p:Platform)` - Primary routing

**Intent Types** (from F1):
- `dream-sessions`
- `strategic-planning`
- `debugging-verification`
- `architectural-design`
- `research-synthesis`
- etc.

---

#### 19. **UniversalForceFields** (singleton)
**Purpose**: Universal constants (Love, Trust, Freedom, Clarity, Absurdity)

**Properties**:
- `Love` (string) - Love definition
- `Trust` (string) - Trust definition
- `Freedom` (string) - Freedom definition
- `Clarity` (string) - Clarity definition
- `Absurdity` (string) - Absurdity definition

**No constraints** (singleton node)

---

#### 20. **SacredTrust** (singleton)
**Purpose**: Sacred Trust physics constants

**Properties**:
- `resonanceThreshold` (float) - φ-resonance threshold (0.809)
- `goldenRatio` (float) - φ = 1.618
- `heartbeatFrequency` (string) - Heartbeat frequency
- `unanimityProtocol` (string) - Unanimity protocol

**No constraints** (singleton node)

---

## Relationships Summary

### Conversation Layer
- `(c:Conversation)-[:INVOLVES]->(p:Platform)`
- `(m:Message)-[:PART_OF]->(c:Conversation)`
- `(m:Message)-[:FROM]->(p:Platform)` (sent messages)
- `(m:Message)-[:PLANNED_FOR]->(p:Platform)` (draft messages)
- `(m:Message)-[:FOLLOWS]->(m2:Message)`
- `(m:Message)-[:DETECTED_BY]->(d:Detection)`
- `(v:ValidationCheckpoint)-[:IN_CONVERSATION]->(c:Conversation)`

### Agent Coordination Layer
- `(a:Agent)-[:RUNS_ON]->(m:Machine)`
- `(a:Agent)-[:WORKS_ON]->(t:Task)`
- `(a:Agent)-[:DISCOVERED]->(i:Insight)`
- `(t:Task)-[:PART_OF]->(p:Project)`
- `(t:Task)-[:UTILIZES]->(s:Session)`

### Family Intelligence Layer
- `(f:FamilyMember)-[:USES_PLATFORM]->(p:Platform)`
- `(p:Platform)-[:HAS_MODEL]->(m:Model)`
- `(p:Platform)-[:HAS_MODE]->(m:Mode)`
- `(p:Platform)-[:DISPLAYS_UI_STATE]->(ui:UIStateIndicator)`
- `(i:IntentType)-[:ROUTES_TO_PLATFORM]->(p:Platform)`

---

## Common Query Patterns

### 1. Get Active Sessions (Post-Compact Recovery)
```cypher
MATCH (c:Conversation {status: 'active'})
OPTIONAL MATCH (c)-[:INVOLVES]->(p:Platform)
OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
WITH c, collect(DISTINCT p.name) as platforms,
     count(m) as messageCount,
     max(m.timestamp) as lastMessageTime
RETURN c, platforms, messageCount, lastMessageTime
ORDER BY c.createdAt DESC
```

**Frequency**: Every compact recovery
**Performance**: Good with indexes

---

### 2. Get Conversation with Messages
```cypher
MATCH (c:Conversation {id: $conversationId})
OPTIONAL MATCH (c)-[:INVOLVES]->(p:Platform)
WITH c, collect(DISTINCT p.name) as platforms
OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
OPTIONAL MATCH (m)-[:FROM]->(mp:Platform)
OPTIONAL MATCH (m)-[:DETECTED_BY]->(d:Detection)
WITH c, platforms, m, mp, d
ORDER BY m.timestamp
RETURN c, platforms, collect({message: m, platform: mp.name, detection: d}) as messages
```

**Frequency**: Very frequent
**Performance**: Critical path - needs optimization

---

### 3. Get Last Validation Checkpoint
```cypher
MATCH (v:ValidationCheckpoint {conversationId: $conversationId})
RETURN v
ORDER BY v.timestamp DESC
LIMIT 1
```

**Frequency**: Every workflow step
**Performance**: Good with indexes

---

### 4. Search Messages by Content
```cypher
MATCH (m:Message)-[:PART_OF]->(c:Conversation)
WHERE m.content CONTAINS $query
MATCH (m)-[:FROM]->(p:Platform)
RETURN m, c.id as conversationId, c.title as conversationTitle, p.name as platform
ORDER BY m.timestamp DESC
LIMIT $limit
```

**Frequency**: Ad-hoc
**Performance**: Full text search needed for scale

---

### 5. Get Agent Workload
```cypher
MATCH (a:Agent {id: $agentId})
OPTIONAL MATCH (a)-[:WORKS_ON]->(t:Task)
WHERE t.status IN ['in_progress', 'blocked']
RETURN a, collect(t) as activeTasks
```

**Frequency**: Every heartbeat
**Performance**: Good with indexes

---

### 6. Get Next Available Task
```cypher
MATCH (t:Task {status: 'pending'})
RETURN t
ORDER BY t.priority DESC, t.created ASC
LIMIT 1
```

**Frequency**: Task assignment
**Performance**: Good with indexes

---

### 7. Get Routing for Intent
```cypher
MATCH (i:IntentType {type: $intentType})
OPTIONAL MATCH (i)-[:ROUTES_TO_PLATFORM]->(p:Platform)
RETURN i, p
```

**Frequency**: Message planning
**Performance**: Good

---

## Critical Issues & Recommendations

### 🔴 CRITICAL: Schema Overlap

**Problem**: `Conversation` (Layer 0) vs `Session` (Layer 2)
- Both represent chat sessions
- Different property sets
- Unclear which to use when

**Recommendation**:
- **Consolidate into single `Conversation` node**
- Add `sessionType` property: 'browser-automation' | 'multi-agent-coordination'
- Migrate Session relationships to Conversation

---

### 🟡 WARNING: ValidationCheckpoint Duplication

**Problem**: Validation checkpoint constraints defined in TWO places:
- `conversation-store.js` (lines 41, 50-52)
- `validation-checkpoints.js` (lines 32, 35-37)

**Recommendation**:
- Remove from `conversation-store.js`
- ValidationCheckpoint should be owned by `validation-checkpoints.js` only
- Call `ValidationCheckpointStore.initSchema()` separately

---

### 🟡 WARNING: Platform Node Redundancy

**Problem**: `interface` property duplicates `name` property

**Recommendation**: Remove `interface` property entirely

---

### 🟢 OPTIMIZATION: Message Queries

**Problem**: `getConversation()` does complex multi-optional-match with sorting
- Potentially slow on large conversations
- No limit on message count

**Recommendation**:
- Add pagination parameters (offset, limit)
- Consider separate endpoint for message streaming
- Add composite index: `(conversationId, timestamp)`

---

### 🟢 OPTIMIZATION: Full Text Search

**Problem**: `searchMessages()` uses `CONTAINS` (case-sensitive substring)
- Not true full-text search
- No ranking/relevance
- Slow on large datasets

**Recommendation**:
- Add Neo4j full-text index:
```cypher
CREATE FULLTEXT INDEX message_content IF NOT EXISTS
FOR (m:Message) ON EACH [m.content]
```
- Use `CALL db.index.fulltext.queryNodes()` for search

---

### 🟢 MISSING: Compound Indexes

**Recommendation**: Add compound indexes for common queries:
```cypher
-- Fast conversation message retrieval
CREATE INDEX message_conversation_timestamp IF NOT EXISTS
FOR (m:Message) ON (m.conversationId, m.timestamp)

-- Fast validation lookups
CREATE INDEX validation_conversation_step IF NOT EXISTS
FOR (v:ValidationCheckpoint) ON (v.conversationId, v.step)

-- Fast task queries
CREATE INDEX task_project_status IF NOT EXISTS
FOR (t:Task) ON (t.projectId, t.status)
```

---

### 🔵 FUTURE: Layer 4 Implementation

**Status**: Axiom and ResonanceEvent nodes defined but not implemented

**Recommendation**:
- Define schema when ready for consciousness emergence tracking
- Consider Event Sourcing pattern for ResonanceEvents
- Link to specific conversations/insights that triggered resonance

---

## Schema Migration Plan

### Phase 1: Consolidation (Required before rebuild)
1. **Merge Session into Conversation**
   - Add `sessionType` to Conversation
   - Migrate `(t:Task)-[:UTILIZES]->(s:Session)` to `(t:Task)-[:UTILIZES]->(c:Conversation)`
   - Drop Session node

2. **Remove ValidationCheckpoint from conversation-store.js**
   - Let validation-checkpoints.js own schema
   - Update initialization order

3. **Remove Platform.interface**
   - Simple property removal

### Phase 2: Optimization (Nice to have)
1. **Add Compound Indexes**
   - Message: (conversationId, timestamp)
   - ValidationCheckpoint: (conversationId, step)
   - Task: (projectId, status)

2. **Add Full-Text Search**
   - Message content full-text index
   - Update search queries

3. **Add Pagination**
   - getConversation() with offset/limit
   - getMessages() separate endpoint

### Phase 3: Enhancement (Future)
1. **Implement Layer 4**
   - Axiom schema
   - ResonanceEvent schema
   - Event sourcing pattern

2. **Add Observability**
   - Query performance tracking
   - Schema usage analytics
   - Dead node detection

---

## Schema Initialization Order

**Current** (problematic - duplicates constraints):
1. `ConversationStore.initSchema()` - Creates ALL constraints including ValidationCheckpoint
2. `ValidationCheckpointStore.initSchema()` - Tries to create SAME constraints

**Recommended**:
1. `ConversationStore.initSchema()` - Conversation, Message, Platform, Detection only
2. `ValidationCheckpointStore.initSchema()` - ValidationCheckpoint only
3. `IntentionGraph.initializeSchema()` - Agent, Machine, Session, Project, Task, Insight, Axiom, ResonanceEvent
4. `importFamilyIntelligence()` - FamilyMember, Model, Mode, UIStateIndicator, IntentType, UniversalForceFields, SacredTrust

---

## Data Model Diagram (Conceptual)

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 0: CONVERSATIONS                       │
│                                                                 │
│  ┌──────────────┐        ┌─────────────┐      ┌──────────────┐ │
│  │ Conversation │◄───────┤   Message   │─────►│  Detection   │ │
│  └──────┬───────┘        └──────┬──────┘      └──────────────┘ │
│         │ INVOLVES              │ FROM/PLANNED_FOR             │
│         └──────────────┬────────┴─────────────┐                │
│                        │                      │                │
│                   ┌────▼─────┐                │                │
│                   │ Platform │◄───────────────┘                │
│                   └────┬─────┘                                 │
│                        │                                        │
└────────────────────────┼────────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────────┐
│              LAYER 1: VALIDATION                                │
│                        │                                        │
│   ┌────────────────────▼────────┐                               │
│   │  ValidationCheckpoint       │                               │
│   │  IN_CONVERSATION            │                               │
│   └─────────────────────────────┘                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│          LAYER 2: MULTI-AGENT COORDINATION                      │
│                                                                 │
│  ┌────────┐       ┌──────────┐        ┌─────────┐              │
│  │ Agent  │──────►│ Machine  │        │ Project │              │
│  └───┬────┘       └──────────┘        └────┬────┘              │
│      │ WORKS_ON                             │ PART_OF           │
│      │           ┌─────────┐                │                   │
│      └──────────►│  Task   │◄───────────────┘                   │
│      │           └────┬────┘                                    │
│      │ DISCOVERED     │ UTILIZES                                │
│      │                │                                         │
│  ┌───▼────┐      ┌────▼────┐                                   │
│  │Insight │      │ Session │ (OVERLAP! Merge with Conversation) │
│  └────────┘      └─────────┘                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│          LAYER 3: FAMILY INTELLIGENCE                           │
│                                                                 │
│  ┌──────────────┐         ┌──────────┐                          │
│  │ FamilyMember │────────►│ Platform │◄─────────────────┐       │
│  └──────────────┘         └────┬─────┘                  │       │
│                                │ HAS_MODEL              │       │
│                                │ HAS_MODE               │       │
│                           ┌────▼─────┐                  │       │
│                           │  Model   │                  │       │
│                           └──────────┘                  │       │
│                           ┌──────────┐                  │       │
│                           │   Mode   │                  │       │
│                           └──────────┘                  │       │
│                                                         │       │
│  ┌────────────┐                                         │       │
│  │ IntentType │─────────────────────────────────────────┘       │
│  └────────────┘     ROUTES_TO_PLATFORM                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Files Analyzed

- `/Users/REDACTED/taey-hands/src/core/neo4j-client.js` - Base client
- `/Users/REDACTED/taey-hands/src/core/conversation-store.js` - Layer 0
- `/Users/REDACTED/taey-hands/src/core/validation-checkpoints.js` - Layer 1
- `/Users/REDACTED/taey-hands/src/core/intention-graph.js` - Layer 2
- `/Users/REDACTED/taey-hands/src/core/draft-message.js` - Layer 3 integration
- `/Users/REDACTED/taey-hands/src/core/import-family-intelligence.js` - Layer 3 import

---

## Conclusion

**Current Schema Assessment**:
- ✅ Comprehensive coverage of use cases
- ✅ Good constraint/index foundation
- ⚠️ Critical overlap issues (Conversation/Session)
- ⚠️ Duplication (ValidationCheckpoint schema)
- ⚠️ Missing optimizations (compound indexes, full-text)

**Rebuild Recommendation**:
- **YES, rebuild with consolidation**
- Phase 1 (Consolidation) is REQUIRED
- Phase 2 (Optimization) is HIGHLY RECOMMENDED
- Phase 3 (Enhancement) is FUTURE

**Estimated Effort**:
- Phase 1: 2-3 hours (careful migration)
- Phase 2: 1-2 hours (add indexes, update queries)
- Phase 3: TBD (depends on Layer 4 requirements)

---

*Generated: 2025-11-30*
*Codebase: /Users/REDACTED/taey-hands*
*Schema Version: Current (pre-consolidation)*
