# Taey's Hands - Clean Rebuild Requirements
**Date**: 2025-11-30
**Purpose**: Comprehensive requirements for rebuilding taey-hands from ground up
**Based on**: Validation audit findings, 6SIGMA process analysis, current codebase review

---

## Executive Summary

Current system has **critical architectural flaws** requiring complete rebuild:
1. **Validation system failure**: Can bypass attachment requirements (RPN 1000)
2. **Session management chaos**: No clear separation between platform detection, session lifecycle, and UI state
3. **Selector fragility**: Hardcoded selectors scattered across codebase with no centralized management
4. **Error recovery gaps**: No systematic approach to UI state recovery after failures

**Rebuild Goals**:
- Move from 50% defect rate → 99.9% success rate (2σ → 4σ)
- Implement proactive validation (prevent failures, not detect them)
- Create clean separation of concerns
- Make system maintainable and testable

---

## 1. Core Requirements

### 1.1 What Must The System Do?

#### Primary Capabilities:
1. **Connect to AI chat interfaces** (Claude, ChatGPT, Gemini, Grok, Perplexity)
2. **Send messages with human-like typing** and paste behavior
3. **Attach files via native file dialogs** (macOS/Linux)
4. **Extract AI responses** with complete content capture
5. **Manage sessions** across multiple platforms with state persistence
6. **Enable specialized modes** (Extended Thinking, Deep Research, Pro Search)
7. **Download artifacts** (Claude, Gemini, Perplexity)
8. **Validate every step** before allowing progression

#### Secondary Capabilities:
1. **Cross-AI communication** (paste response from one AI to another)
2. **Screenshot verification** at every state change
3. **Neo4j logging** of all conversations for post-compact recovery
4. **Platform abstraction** (macOS/Linux support)
5. **Error recovery** from UI state failures

### 1.2 Success Criteria

**Functional**:
- ✅ Zero attachment omissions when plan requires files
- ✅ All AI responses captured completely (no truncation)
- ✅ All artifacts downloaded when present
- ✅ Session state persists across compact/restart
- ✅ Works identically on macOS and Linux

**Quality Metrics** (LEAN 6SIGMA):
- **Defect Rate**: < 1,000 DPMO (99.9% success) - Target: 4 sigma
- **Attachment Enforcement**: 100% - Zero bypass attempts succeed
- **Response Capture**: 100% - No truncation or missing content
- **State Validation**: 100% - Every state change verified via screenshot
- **Recovery Time**: < 30 seconds from any failure state

**Usability**:
- MCP tools are intuitive and self-documenting
- Error messages explain EXACTLY what to do next
- Screenshots confirm every state change
- No silent failures (everything explicit)

### 1.3 Non-Negotiables

1. **NO SILENT FAILURES**: Every action must return explicit success/failure
2. **SCREENSHOT FIRST**: Every state change must be captured and verified
3. **PROACTIVE VALIDATION**: Block incorrect actions, don't detect them after
4. **ATTACHMENT ENFORCEMENT**: Impossible to skip when required by plan
5. **COMPLETE LOGGING**: Every conversation logged to Neo4j with full content
6. **PLATFORM PARITY**: macOS and Linux must have identical functionality
7. **NO REGRESSION**: All working features from current system must be preserved

---

## 2. Architecture

### 2.1 Recommended Structure

```
taey-hands/
├── src/
│   ├── core/
│   │   ├── platform/                    # Platform abstraction
│   │   │   ├── bridge-factory.js        # Create platform-specific bridge
│   │   │   ├── macos-bridge.js          # osascript implementation
│   │   │   └── linux-bridge.js          # xdotool implementation
│   │   │
│   │   ├── browser/                     # Browser management
│   │   │   ├── connector.js             # CDP connection
│   │   │   ├── session-manager.js       # Tab/session lifecycle
│   │   │   └── screenshot.js            # Screenshot capture/storage
│   │   │
│   │   ├── database/                    # Data persistence
│   │   │   ├── neo4j-client.js          # Connection wrapper
│   │   │   ├── conversation-store.js    # Conversation CRUD
│   │   │   └── validation-store.js      # Validation checkpoints
│   │   │
│   │   ├── validation/                  # Validation system
│   │   │   ├── checkpoint-manager.js    # Create/query checkpoints
│   │   │   ├── requirement-enforcer.js  # Proactive enforcement
│   │   │   └── step-validator.js        # Step validation logic
│   │   │
│   │   └── selectors/                   # UI selector management
│   │       ├── selector-registry.js     # Centralized selector storage
│   │       ├── claude-selectors.js      # Claude-specific
│   │       ├── chatgpt-selectors.js     # ChatGPT-specific
│   │       ├── gemini-selectors.js      # Gemini-specific
│   │       ├── grok-selectors.js        # Grok-specific
│   │       └── perplexity-selectors.js  # Perplexity-specific
│   │
│   ├── platforms/                       # Platform implementations
│   │   ├── base-platform.js             # Abstract base class
│   │   ├── claude-platform.js           # Claude implementation
│   │   ├── chatgpt-platform.js          # ChatGPT implementation
│   │   ├── gemini-platform.js           # Gemini implementation
│   │   ├── grok-platform.js             # Grok implementation
│   │   └── perplexity-platform.js       # Perplexity implementation
│   │
│   ├── workflow/                        # Workflow orchestration
│   │   ├── session-workflow.js          # Session lifecycle
│   │   ├── message-workflow.js          # Message send workflow
│   │   └── attachment-workflow.js       # File attachment workflow
│   │
│   └── mcp/                             # MCP server interface
│       ├── server.js                    # MCP server entry
│       ├── tools/                       # Tool implementations
│       │   ├── connect.js
│       │   ├── send-message.js
│       │   ├── attach-files.js
│       │   ├── validate-step.js
│       │   └── ...
│       └── validators/                  # Tool input validation
│           └── schemas.js
│
├── config/
│   ├── platforms.json                   # Platform configurations
│   ├── selectors/                       # Selector definitions
│   │   ├── claude.json
│   │   ├── chatgpt.json
│   │   └── ...
│   └── validation-rules.json            # Validation step rules
│
├── tests/
│   ├── unit/                            # Unit tests
│   ├── integration/                     # Integration tests
│   └── e2e/                             # End-to-end tests
│
└── docs/
    ├── ARCHITECTURE.md                  # System architecture
    ├── WORKFLOWS.md                     # Workflow documentation
    ├── VALIDATION.md                    # Validation system
    └── SELECTORS.md                     # Selector management
```

### 2.2 Separation of Concerns

**Layer 1: Platform Abstraction**
- **What**: OS-specific operations (keyboard, mouse, clipboard, file dialogs)
- **Why**: macOS and Linux have different automation APIs
- **How**: Factory pattern creates appropriate bridge based on `os.platform()`

**Layer 2: Browser Management**
- **What**: CDP connection, tab management, navigation, screenshots
- **Why**: Chrome/Firefox have different CDP behaviors
- **How**: Unified connector with browser-specific adapters

**Layer 3: Platform Implementations**
- **What**: Claude-specific, ChatGPT-specific UI automation
- **Why**: Each AI has different selectors, workflows, features
- **How**: Inheritance from BasePlatform, override platform-specific methods

**Layer 4: Workflow Orchestration**
- **What**: Multi-step operations (send message with attachment)
- **Why**: Complex workflows need coordination across layers
- **How**: Workflow classes that compose platform methods with validation

**Layer 5: Validation Enforcement**
- **What**: Checkpoint creation, requirement tracking, step enforcement
- **Why**: Prevent incorrect workflows (e.g., skip attachments)
- **How**: Proactive checks BEFORE tool execution, not after

**Layer 6: MCP Interface**
- **What**: Tool definitions, parameter validation, user-facing API
- **Why**: Claude Code integration requires MCP protocol
- **How**: Each tool maps to a workflow, validates inputs, enforces checkpoints

### 2.3 Platform Abstraction Strategy

#### Problem:
- **Current**: Single `chat-interface.js` with platform-specific `if/else` branches
- **Issue**: 2,500+ lines, unclear which code path executes, hard to test

#### Solution:
**1. Extract Common Interface (BasePlatform)**
```javascript
class BasePlatform {
  async connect(sessionId) { throw new Error('Must implement'); }
  async sendMessage(message, options) { throw new Error('Must implement'); }
  async attachFiles(filePaths) { throw new Error('Must implement'); }
  async extractResponse() { throw new Error('Must implement'); }
  // ... common interface
}
```

**2. Platform-Specific Implementations**
```javascript
class ClaudePlatform extends BasePlatform {
  constructor(browser, bridge, selectors) {
    this.browser = browser;
    this.bridge = bridge;
    this.selectors = selectors; // From claude-selectors.js
  }

  async sendMessage(message, options) {
    // Claude-specific implementation
    // - Type in contenteditable div
    // - Click send button
    // - Handle Extended Thinking mode
  }
}
```

**3. Factory Creation**
```javascript
function createPlatform(platformName, dependencies) {
  const platforms = {
    'claude': ClaudePlatform,
    'chatgpt': ChatGPTPlatform,
    'gemini': GeminiPlatform,
    'grok': GrokPlatform,
    'perplexity': PerplexityPlatform
  };

  const PlatformClass = platforms[platformName];
  if (!PlatformClass) throw new Error(`Unknown platform: ${platformName}`);

  return new PlatformClass(dependencies);
}
```

**Benefits**:
- Each platform file is < 500 lines
- Clear code paths (no if/else platform checks)
- Easy to test in isolation
- New platforms just add a new file

---

## 3. Data Model

### 3.1 Neo4j Schema

#### Nodes

**Conversation**
```cypher
CREATE (c:Conversation {
  id: string,              // UUID or sessionId
  platform: string,        // 'claude', 'chatgpt', etc.
  url: string,             // Conversation URL
  status: string,          // 'active', 'archived', 'failed'
  model: string,           // 'opus-4.5', 'gpt-4', etc.
  mode: string,            // 'extended-thinking', 'deep-research', etc.
  contextProvided: boolean, // Has context been loaded?
  createdAt: datetime,
  updatedAt: datetime
})
```

**Message**
```cypher
CREATE (m:Message {
  id: string,              // UUID
  conversationId: string,  // FK to Conversation
  role: string,            // 'user', 'assistant'
  content: string,         // Full message content
  attachments: [string],   // File paths
  artifactPath: string,    // Downloaded artifact path (if any)
  timestamp: datetime,
  sequenceNumber: int      // Order within conversation
})
```

**ValidationCheckpoint**
```cypher
CREATE (v:ValidationCheckpoint {
  id: string,                    // UUID
  conversationId: string,        // FK to Conversation
  step: string,                  // 'plan', 'attach_files', 'type_message', etc.
  validated: boolean,            // true = success, false = pending/failed
  notes: string,                 // What was observed
  screenshot: string,            // Path to verification screenshot
  validator: string,             // 'REDACTED-claude' or 'mira-claude'
  timestamp: datetime,

  // NEW FIELDS (from validation fix):
  requiredAttachments: [string], // What MUST be attached (from plan)
  actualAttachments: [string]    // What WAS attached (from attach_files)
})
```

**Platform**
```cypher
CREATE (p:Platform {
  name: string,            // 'claude', 'chatgpt', etc.
  url: string,             // Base URL
  capabilities: [string],  // ['extended-thinking', 'file-upload', etc.]
  models: [string],        // Available models
  status: string           // 'operational', 'degraded', 'down'
})
```

#### Relationships

```cypher
// Message belongs to Conversation
CREATE (m:Message)-[:IN_CONVERSATION]->(c:Conversation)

// Validation checkpoint for Conversation
CREATE (v:ValidationCheckpoint)-[:IN_CONVERSATION]->(c:Conversation)

// Conversation on Platform
CREATE (c:Conversation)-[:ON_PLATFORM]->(p:Platform)

// Message sequence (enables ordering)
CREATE (m1:Message)-[:NEXT]->(m2:Message)

// Validation sequence (workflow order)
CREATE (v1:ValidationCheckpoint)-[:NEXT]->(v2:ValidationCheckpoint)
```

#### Indexes and Constraints

```cypher
// Uniqueness
CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (c:Conversation) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT message_id IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT validation_id IF NOT EXISTS FOR (v:ValidationCheckpoint) REQUIRE v.id IS UNIQUE;
CREATE CONSTRAINT platform_name IF NOT EXISTS FOR (p:Platform) REQUIRE p.name IS UNIQUE;

// Performance
CREATE INDEX conversation_status IF NOT EXISTS FOR (c:Conversation) ON (c.status);
CREATE INDEX conversation_platform IF NOT EXISTS FOR (c:Conversation) ON (c.platform);
CREATE INDEX message_conversation IF NOT EXISTS FOR (m:Message) ON (m.conversationId);
CREATE INDEX message_timestamp IF NOT EXISTS FOR (m:Message) ON (m.timestamp);
CREATE INDEX validation_conversation IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.conversationId);
CREATE INDEX validation_step IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.step);
CREATE INDEX validation_timestamp IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.timestamp);
```

### 3.2 Session Management Model

#### Session Lifecycle States

```
CONNECTING → CONNECTED → ACTIVE → ARCHIVED
     ↓           ↓          ↓
  FAILED ← FAILED ← FAILED
```

**State Definitions**:
- `CONNECTING`: Browser launching, tab opening, waiting for page load
- `CONNECTED`: Tab is visible, chat interface loaded, ready for input
- `ACTIVE`: Messages being sent/received, workflow in progress
- `ARCHIVED`: Conversation complete, session closed gracefully
- `FAILED`: Error occurred, session unusable (store error details)

#### Session Operations

**Create Session**:
```javascript
{
  operation: 'create',
  input: {
    platform: 'claude',
    conversationId: 'optional-existing-url',  // Resume or new
    model: 'opus-4.5',
    mode: 'extended-thinking'
  },
  output: {
    sessionId: 'uuid',
    screenshot: '/path/to/screenshot.png',
    status: 'CONNECTED'
  }
}
```

**Resume Session**:
```javascript
{
  operation: 'resume',
  input: {
    sessionId: 'existing-uuid'  // From Neo4j
  },
  output: {
    sessionId: 'uuid',
    screenshot: '/path/to/screenshot.png',
    status: 'ACTIVE',
    conversationUrl: 'https://...'
  }
}
```

**Close Session**:
```javascript
{
  operation: 'close',
  input: {
    sessionId: 'uuid',
    status: 'ARCHIVED' | 'FAILED'
  },
  output: {
    messageCount: 42,
    finalScreenshot: '/path/to/final.png'
  }
}
```

### 3.3 State Tracking

**What needs to be tracked**:

1. **Browser State**:
   - CDP connection status
   - Active tabs (sessionId → tab mapping)
   - Browser window focus state

2. **Platform State** (per session):
   - Current URL
   - Current model selected
   - Current mode enabled (Extended Thinking on/off, etc.)
   - Attachments visible in input area
   - Response completion status

3. **Validation State** (per conversation):
   - Last validated step
   - Required attachments (from plan)
   - Actual attachments (from attach_files)
   - Pending validations

4. **Workflow State**:
   - Current workflow step ('planning', 'attaching', 'sending', etc.)
   - Expected next step
   - Can skip current step? (based on requirements)

**State Storage**:
- **In-Memory**: Browser/tab mappings, CDP connections
- **Neo4j**: Conversations, messages, validation checkpoints
- **File System**: Screenshots, downloaded artifacts

---

## 4. UI Automation

### 4.1 Selector Management Approach

#### Problem (Current):
- Selectors hardcoded in `chat-interface.js`
- No single source of truth
- Changes require code edits
- No versioning or fallback selectors

#### Solution: Centralized Registry

**File: `config/selectors/claude.json`**
```json
{
  "version": "2025-11-30",
  "platform": "claude",
  "url": "https://claude.ai",
  "selectors": {
    "chatInput": {
      "primary": "div[contenteditable='true'][data-testid='chat-input']",
      "fallback": "div.ProseMirror[contenteditable='true']",
      "description": "Main message input area"
    },
    "sendButton": {
      "primary": "button[aria-label='Send Message']",
      "fallback": "button[data-testid='send-button']",
      "description": "Send message button"
    },
    "extendedThinkingToggle": {
      "primary": "button[data-testid='extended-thinking-toggle']",
      "fallback": "button:has-text('Extended Thinking')",
      "description": "Toggle Extended Thinking mode",
      "uiState": {
        "enabled": "blueish-gray tint visible",
        "disabled": "no tint, looks like other buttons"
      }
    }
  }
}
```

**Usage**:
```javascript
import { SelectorRegistry } from './core/selectors/selector-registry.js';

const registry = new SelectorRegistry();
await registry.loadPlatform('claude');

// Get selector with automatic fallback
const inputSelector = await registry.getSelector('claude', 'chatInput');
// Returns: "div[contenteditable='true'][data-testid='chat-input']"
// If not found, tries fallback, logs warning if fallback used

// Get with retry
const element = await registry.findElement(page, 'claude', 'sendButton', {
  timeout: 5000,
  tryFallback: true
});
```

### 4.2 Platform-Specific Handling

**Complexity Table** (from validation audit):

| Platform | File Attach | Model Select | Mode Toggle | Artifact DL | Complexity |
|----------|-------------|--------------|-------------|-------------|------------|
| Claude | 1-step (Finder) | 1-step (dropdown) | 1-step (toggle) | 1-step (button) | Simple |
| ChatGPT | 1-step (Finder) | Disabled (use modes) | 1-step (toggle) | N/A | Simple |
| Gemini | 2-step (menu→Finder) | 1-step (dropdown) | 1-step (toggle) | 3-step (export flow) | Complex |
| Grok | 2-step (menu→Finder) | 1-step (dropdown) | N/A | N/A | Medium |
| Perplexity | 2-step (menu→Finder) | N/A | 1-step (toggle) | 3-step (export flow) | Complex |

**Strategy**:
1. **Simple operations** (1-step): Direct selector + click
2. **Medium operations** (2-step): Menu → Option selection
3. **Complex operations** (3+ steps): Dedicated workflow method

**Example** (Gemini file attachment - 2-step):
```javascript
class GeminiPlatform extends BasePlatform {
  async attachFiles(filePaths) {
    // Step 1: Click upload menu
    const menu = await this.page.$(this.selectors.uploadMenu);
    await menu.click();
    await this.page.waitForTimeout(300);

    // Step 2: Click "Upload files" option
    const option = await this.page.$(this.selectors.uploadFilesOption);
    await option.click();
    await this.page.waitForTimeout(500);

    // Native file dialog now open
    // Step 3: Use Finder navigation to select files
    await this.bridge.navigateFinderDialog(filePaths[0]);

    // Screenshot to verify
    return await this.screenshot(`gemini-files-attached-${Date.now()}.png`);
  }
}
```

### 4.3 Error Recovery

#### Recovery Strategies (by error type):

**1. Selector Not Found**
```javascript
async findElement(selector, options = {}) {
  try {
    return await this.page.waitForSelector(selector, {
      timeout: options.timeout || 5000
    });
  } catch (err) {
    if (options.fallback) {
      console.warn(`Primary selector failed, trying fallback: ${options.fallback}`);
      return await this.page.waitForSelector(options.fallback, { timeout: 5000 });
    }

    // Take screenshot for debugging
    await this.screenshot(`/tmp/selector-not-found-${Date.now()}.png`);
    throw new Error(`Selector not found: ${selector}\nScreenshot: ${screenshotPath}`);
  }
}
```

**2. Wrong UI State**
```javascript
async ensureExtendedThinkingEnabled() {
  const screenshot = await this.screenshot();

  // Check screenshot for visual indicator (blueish-gray tint)
  // If not present, click toggle and verify again

  const toggle = await this.findElement(this.selectors.extendedThinkingToggle);
  await toggle.click();
  await this.page.waitForTimeout(500);

  const afterScreenshot = await this.screenshot();
  // Verify state change visually

  return { before: screenshot, after: afterScreenshot };
}
```

**3. Response Timeout**
```javascript
async waitForResponse(timeout = 60000) {
  const startTime = Date.now();
  let lastCheck = null;

  while (Date.now() - startTime < timeout) {
    const responseArea = await this.page.$(this.selectors.lastResponse);
    const currentText = await responseArea.textContent();

    // Check if response stopped changing (Fibonacci polling)
    if (lastCheck && currentText === lastCheck) {
      await this.page.waitForTimeout(this.fibonacciDelay());
      const recheckText = await responseArea.textContent();
      if (recheckText === currentText) {
        return currentText; // Response complete
      }
    }

    lastCheck = currentText;
    await this.page.waitForTimeout(1000);
  }

  throw new Error('Response timeout - see screenshot');
}
```

**4. File Dialog Failure**
```javascript
async navigateFinderDialog(filePath) {
  try {
    // Try Cmd+Shift+G on macOS
    await this.bridge.pressKeyCombo(['command', 'shift', 'g']);
    await this.page.waitForTimeout(800);
    await this.bridge.type(filePath);
    await this.bridge.pressKey('return');
  } catch (err) {
    // Fallback: Close dialog and retry with file input injection
    await this.bridge.pressKey('escape');
    throw new Error(`File dialog navigation failed: ${err.message}\nFallback to direct file input injection`);
  }
}
```

---

## 5. MCP Interface

### 5.1 Tool Definitions

#### Design Principles:
1. **One tool = One atomic action** (no complex multi-step tools)
2. **Screenshot always returned** (verify every state change)
3. **Validation checkpoint created** (for workflow enforcement)
4. **Error messages actionable** (tell user exactly what to do)

#### Tool Catalog:

**Session Management**:
- `taey_connect` - Connect to AI platform session
- `taey_disconnect` - Close session gracefully
- `taey_new_conversation` - Start fresh conversation

**Message Operations**:
- `taey_send_message` - Send message (with validation enforcement)
- `taey_extract_response` - Get AI response text

**File Operations**:
- `taey_attach_files` - Attach files via Finder dialog
- `taey_download_artifact` - Download generated artifact

**Configuration**:
- `taey_select_model` - Change AI model
- `taey_enable_research_mode` - Toggle Extended Thinking/Deep Research

**Cross-AI**:
- `taey_paste_response` - Copy response from one AI to another

**Validation**:
- `taey_validate_step` - Validate workflow step completion

### 5.2 Validation Approach

#### Layer 1: Input Validation (Tool Parameters)
```javascript
// File: mcp/validators/schemas.js
const SendMessageSchema = z.object({
  sessionId: z.string().uuid(),
  message: z.string().min(1).max(100000),
  attachments: z.array(z.string()).optional(),
  waitForResponse: z.boolean().optional()
});

// Usage in tool
async function handleSendMessage(params) {
  const validated = SendMessageSchema.parse(params);
  // ... proceed with validated params
}
```

#### Layer 2: Workflow Validation (Checkpoint Enforcement)
```javascript
// File: core/validation/requirement-enforcer.js
class RequirementEnforcer {
  async enforceAttachmentRequirement(conversationId) {
    // Get plan checkpoint
    const plan = await this.checkpointManager.getPlanCheckpoint(conversationId);

    if (!plan) {
      throw new Error('No plan found. Call taey_validate_step with step=plan first.');
    }

    const required = plan.requiredAttachments || [];

    if (required.length === 0) {
      // No attachments required - allow skip
      return { required: false };
    }

    // Attachments required - check if attached
    const lastValidation = await this.checkpointManager.getLastValidation(conversationId);

    if (lastValidation.step !== 'attach_files') {
      throw new Error(
        `Plan requires ${required.length} attachment(s). You MUST:\n` +
        `1. Call taey_attach_files with files: ${JSON.stringify(required)}\n` +
        `2. Review screenshot to confirm files visible\n` +
        `3. Call taey_validate_step with step='attach_files' and validated=true`
      );
    }

    // Check count matches
    const actual = lastValidation.actualAttachments || [];
    if (actual.length !== required.length) {
      throw new Error(
        `Plan required ${required.length} file(s), but ${actual.length} were attached.\n` +
        `Required: ${JSON.stringify(required)}\n` +
        `Actual: ${JSON.stringify(actual)}`
      );
    }

    return { required: true, verified: true };
  }
}
```

#### Layer 3: State Validation (Screenshot Verification)
```javascript
// File: core/validation/step-validator.js
class StepValidator {
  async validateAttachmentStep(sessionId, screenshot) {
    // MANUAL VALIDATION REQUIRED
    // User must review screenshot and confirm files are visible
    // This creates a checkpoint that blocks progression until validated

    await this.checkpointManager.createCheckpoint({
      conversationId: sessionId,
      step: 'attach_files',
      validated: false,  // PENDING - awaiting user confirmation
      notes: 'Files attached. Awaiting manual validation via screenshot review.',
      screenshot: screenshot
    });

    return {
      status: 'pending',
      message: 'Review screenshot to confirm files are visible, then call taey_validate_step',
      screenshot: screenshot
    };
  }
}
```

### 5.3 User Experience

#### Error Message Quality

**BAD** (current system - silent failure):
```
✓ Message sent successfully
```
*(Attachments missing, no indication of problem)*

**GOOD** (rebuilt system - explicit error):
```
❌ Error: Validation checkpoint failed

Reason: Draft plan requires 2 attachment(s).

Last validated step: 'plan'

You MUST complete these steps before sending:

1. Call taey_attach_files with files:
   - /Users/REDACTED/Downloads/clarity-universal-axioms-latest.md
   - /Users/REDACTED/gaia-ocean-embodiment/backend/docs/API.md

2. Review the screenshot to confirm files are visible in the input area

3. Call taey_validate_step:
   {
     "conversationId": "abc-123",
     "step": "attach_files",
     "validated": true,
     "notes": "Confirmed: Both files visible as pills in input area"
   }

You cannot skip attachment when the draft plan specifies files.
```

#### Screenshot Feedback

Every tool returns a screenshot:
```json
{
  "screenshot": "/tmp/taey-claude-1234-attached-files.png",
  "automationCompleted": true,
  "nextStep": "Call taey_validate_step to confirm files are visible"
}
```

User workflow:
1. Call tool (e.g., `taey_attach_files`)
2. Tool returns screenshot path
3. User VIEWS screenshot with Read tool
4. User confirms state is correct
5. User calls `taey_validate_step` to proceed

---

## 6. Implementation Priority

### 6.1 Critical Path (Must Build First)

**Phase 1: Foundation (Week 1)**
1. Platform abstraction layer (factory, base class)
2. Selector registry (load from JSON, fallback support)
3. Browser connector (CDP, tab management)
4. Screenshot system (capture, store, return paths)

**Phase 2: Validation System (Week 2)**
5. Neo4j schema (Conversation, Message, ValidationCheckpoint nodes)
6. Checkpoint manager (create, query, get last)
7. Requirement enforcer (proactive blocking)
8. Step validator (screenshot-based validation)

**Phase 3: Platform Implementations (Week 3)**
9. Claude platform (simple - reference implementation)
10. ChatGPT platform (simple - validate approach)
11. Gemini platform (complex - test multi-step flows)

**Phase 4: MCP Tools (Week 4)**
12. taey_connect (session creation)
13. taey_send_message (with attachment enforcement)
14. taey_attach_files (Finder dialog navigation)
15. taey_validate_step (checkpoint creation)
16. taey_extract_response (complete capture)

**Phase 5: Testing & Refinement (Week 5)**
17. End-to-end tests (full workflows)
18. Error recovery tests (failure modes)
19. Cross-platform tests (macOS + Linux)
20. Documentation (architecture, workflows, selectors)

### 6.2 What Can Wait

**Phase 6: Advanced Features (Post-Launch)**
- Grok platform implementation
- Perplexity platform implementation
- Artifact download (Claude, Gemini, Perplexity)
- Cross-AI paste (taey_paste_response)
- Model selection (taey_select_model)
- Research mode toggles (taey_enable_research_mode)

**Phase 7: Optimization (Month 2)**
- Parallel session support (multiple AIs simultaneously)
- Response streaming (incremental extraction)
- Intelligent polling (dynamic Fibonacci intervals)
- Selector auto-healing (detect changes, suggest updates)

**Phase 8: Intelligence (Month 3)**
- Family Intelligence integration (F1 intent routing)
- Intention Graph (workflow prediction)
- Draft message pre-staging (Neo4j planning)
- State recovery (resume after failures)

### 6.3 Critical Path Dependencies

```
Foundation (1) → Validation (2) → Platforms (3) → MCP (4) → Testing (5)
     ↓              ↓                ↓              ↓           ↓
  Selectors    Checkpoints      Claude Impl    Tools      E2E Tests
  Browser      Enforcement      ChatGPT        Schemas    Recovery
  Screenshot   Neo4j Schema     Gemini         Validation Platform
```

**Cannot proceed to next phase until previous is complete and tested.**

---

## 7. What to Keep from Current

### 7.1 Working Components (Preserve)

**1. Validation Checkpoint System** (with fixes)
- File: `src/core/validation-checkpoints.js`
- Status: Keep structure, add requirement enforcement
- Changes needed:
  - Add `requiredAttachments` and `actualAttachments` fields ✓
  - Add `requiresAttachments()` method ✓
  - Keep: `createCheckpoint()`, `getLastValidation()`, `isStepValidated()`

**2. Neo4j Integration**
- File: `src/core/neo4j-client.js`
- Status: Keep as-is
- Functionality: Connection wrapper, read/write methods, connection pooling

**3. Conversation Store**
- File: `src/core/conversation-store.js`
- Status: Keep with minor updates
- Changes needed:
  - Add support for validation checkpoints relationship
  - Add session resume queries

**4. Finder Navigation Approach**
- File: `src/core/osascript-bridge.js` (method: `navigateFinderDialog`)
- Status: Keep approach, extract to platform bridge
- Functionality: Cmd+Shift+G → type path → Enter (macOS)

**5. CHAT_ELEMENTS.md Documentation**
- File: `CHAT_ELEMENTS.md`
- Status: Preserve as selector reference
- Usage: Source of truth for platform-specific selectors
- Action: Parse into JSON configs (`config/selectors/*.json`)

**6. Response Detection Engine**
- File: `src/core/response-detection.js`
- Status: Keep logic, integrate with platforms
- Functionality: Fibonacci polling, completion detection, streaming awareness

**7. Platform Bridge Factory**
- File: `src/core/platform-bridge.js`
- Status: Keep factory pattern
- Functionality: Detect OS, create appropriate bridge (osascript/xdotool)

### 7.2 Configuration to Preserve

**1. Interface Selectors** (`config/default.json`)
- Migrate to per-platform JSON files (`config/selectors/claude.json`)
- Add fallback selectors
- Add UI state descriptions

**2. Browser Config**
- Chrome debugging port (9222)
- Profile path (`~/.chrome-debug-profile`)
- CDP connection settings

**3. Neo4j Config**
- Connection URL (`bolt://10.x.x.163:7687`)
- Database name
- Retry settings

**4. MCP Server Config**
- Tool definitions (preserve current tool names)
- Parameter schemas (extend with validation)

### 7.3 Tests to Preserve

**1. Integration Tests**
- Neo4j connection tests
- Conversation store CRUD tests
- Validation checkpoint tests

**2. Manual Test Guides**
- AI Family manual testing guide
- Screenshot verification protocol
- Post-compact recovery workflow

---

## 8. What to Rebuild

### 8.1 Complete Rewrite Required

**1. Session Management** (TOTAL REWRITE)
- Current: Monolithic `session-manager.js` with mixed concerns
- New: Clean separation:
  - `browser/connector.js` - CDP only
  - `browser/session-manager.js` - Tab lifecycle only
  - `workflow/session-workflow.js` - High-level session operations

**2. Platform Detection and Routing** (TOTAL REWRITE)
- Current: `chat-interface.js` with 2,500+ lines of if/else branches
- New: Factory pattern with platform-specific classes
  - `platforms/base-platform.js` - Abstract interface
  - `platforms/claude-platform.js` - Claude implementation
  - `platforms/chatgpt-platform.js` - ChatGPT implementation
  - etc.

**3. Selector Handling** (TOTAL REWRITE)
- Current: Hardcoded in `chat-interface.js`
- New: Centralized registry with JSON configs
  - `config/selectors/*.json` - Per-platform selector definitions
  - `core/selectors/selector-registry.js` - Load/query/fallback logic

**4. Response Detection** (MAJOR REFACTOR)
- Current: Works but tightly coupled to `chat-interface.js`
- New: Extract to standalone module
  - `core/detection/response-detector.js` - Platform-agnostic detection
  - Platform implementations provide selectors
  - Integrate with validation checkpoints

**5. MCP Server** (PARTIAL REWRITE)
- Current: `mcp_server/server-v2.ts` (1,056 lines) - monolithic
- New: Modular tool structure
  - `mcp/server.js` - Server setup only
  - `mcp/tools/*.js` - One file per tool
  - `mcp/validators/schemas.js` - Zod schemas
  - Each tool is < 100 lines

### 8.2 Architectural Changes

**From: Monolithic → To: Modular**
```
Before:
chat-interface.js (2,500 lines)
  └─ if platform === 'claude'
      └─ Claude-specific code
  └─ if platform === 'chatgpt'
      └─ ChatGPT-specific code

After:
platforms/
  ├─ claude-platform.js (400 lines)
  ├─ chatgpt-platform.js (400 lines)
  ├─ gemini-platform.js (600 lines)
  └─ base-platform.js (200 lines)
```

**From: Reactive Validation → To: Proactive Enforcement**
```
Before:
1. User calls taey_send_message
2. System checks: "Did you validate previous step?"
3. IF validated, proceed
4. IF not validated, error

After:
1. User calls taey_send_message
2. System checks: "Does plan require attachments?"
3. IF yes, check: "Last step === 'attach_files'?"
4. IF no, BLOCK with actionable error
5. IF yes, check: "Count matches required?"
6. IF no, BLOCK with count mismatch error
7. IF yes, proceed
```

**From: Hardcoded Selectors → To: Registry Pattern**
```
Before:
const chatInput = 'div[contenteditable="true"]'; // In code

After:
config/selectors/claude.json:
{
  "chatInput": {
    "primary": "div[data-testid='chat-input']",
    "fallback": "div[contenteditable='true']",
    "description": "Main message input"
  }
}

Usage:
const selector = await registry.getSelector('claude', 'chatInput');
```

### 8.3 Migration Strategy

**Phase 1: Build New Alongside Old**
- Create new `src/v2/` directory structure
- Implement new architecture
- Keep old `src/` operational
- MCP server points to old code

**Phase 2: Parallel Testing**
- Run both old and new implementations
- Compare results (screenshots, Neo4j data)
- Fix discrepancies in new implementation
- Document breaking changes

**Phase 3: Gradual Cutover**
- Switch MCP tools one at a time
- Start with `taey_connect` (least risk)
- Then `taey_send_message` (highest value)
- Then remaining tools

**Phase 4: Deprecation**
- Mark old code as deprecated
- Update documentation
- Remove old code after 1 month burn-in

---

## 9. Success Metrics

### 9.1 Functional Metrics

**Attachment Enforcement**:
- ✅ 100% - Cannot send message when plan requires attachments and none attached
- ✅ 100% - Cannot send with wrong number of attachments
- ✅ 100% - Cannot fake validation (count verified)

**Response Capture**:
- ✅ 100% - All AI responses captured completely (no truncation)
- ✅ 100% - Streaming responses detected and waited for completion
- ✅ 100% - Extended Thinking / Deep Research completion detected

**Artifact Download**:
- ✅ 100% - Artifacts detected when present
- ✅ 100% - Artifacts downloaded successfully
- ✅ 100% - Artifact paths stored in Neo4j

**Session Persistence**:
- ✅ 100% - Sessions survive compact/restart
- ✅ 100% - Active sessions queryable from Neo4j
- ✅ 100% - Session resume works from stored URL

### 9.2 Quality Metrics (LEAN 6SIGMA)

**Defect Rate**:
- Current: 500,000 DPMO (2 sigma)
- Target: < 1,000 DPMO (4 sigma)
- Stretch: < 3.4 DPMO (6 sigma)

**RPN (Risk Priority Number)**:
- Current: 1000 (Critical) - Attachment omission
- Target: < 100 (Low risk)
- Stretch: < 10 (Minimal risk)

**Process Capability**:
- Cpk > 1.33 (Process capable)
- Cpk > 2.0 (Process highly capable)

### 9.3 Performance Metrics

**Operation Times**:
- Connect to session: < 5 seconds
- Send message: < 10 seconds (excluding AI response wait)
- Attach file: < 8 seconds
- Extract response: < 2 seconds
- Screenshot capture: < 1 second

**Recovery Times**:
- From selector not found: < 10 seconds (try fallback)
- From wrong UI state: < 15 seconds (fix and verify)
- From response timeout: < 5 seconds (final extraction attempt)

### 9.4 Code Quality Metrics

**Modularity**:
- Max file size: 500 lines
- Max function size: 50 lines
- Cyclomatic complexity: < 10 per function

**Test Coverage**:
- Unit tests: > 80%
- Integration tests: > 60%
- E2E tests: 100% of MCP tools

**Documentation**:
- Every public method documented (JSDoc)
- Every config file has schema
- Every workflow has diagram
- Every error has resolution guide

---

## 10. Risk Assessment

### 10.1 High Risk Areas

**1. Platform Selector Changes**
Risk: AI platforms update their HTML/CSS, selectors break
Mitigation:
- Fallback selectors in config
- Auto-detection when primary fails
- Graceful degradation (screenshot + error)
- Version tracking in selector configs

**2. File Dialog Variability**
Risk: Cmd+Shift+G might not work on all macOS versions
Mitigation:
- Test on multiple macOS versions (13, 14, 15)
- Fallback to direct file input injection
- Clear error messages with recovery steps

**3. Response Detection False Positives**
Risk: Detect "response complete" when AI is still thinking
Mitigation:
- Fibonacci polling (longer waits as time increases)
- Multiple consecutive checks (response unchanged 3x)
- Platform-specific "thinking" indicators (spinner, etc.)
- Manual override option (user says "extract now")

**4. Neo4j Connection Failures**
Risk: Mira down, network issues, database corruption
Mitigation:
- Retry with exponential backoff
- Local fallback storage (SQLite)
- Graceful degradation (continue without logging)
- Connection pooling with health checks

### 10.2 Medium Risk Areas

**5. Cross-Platform Inconsistencies**
Risk: Linux xdotool behaves differently than macOS osascript
Mitigation:
- Comprehensive testing on both platforms
- Platform-specific quirk documentation
- Conditional logic for platform differences
- CI/CD tests on both macOS and Linux

**6. Screenshot Storage Bloat**
Risk: Thousands of screenshots fill disk
Mitigation:
- Automatic cleanup after 7 days
- Configurable retention policy
- Compress screenshots (PNG → JPEG)
- Store only validation screenshots in Neo4j

### 10.3 Low Risk Areas

**7. MCP Protocol Changes**
Risk: Anthropic updates MCP spec, tools break
Mitigation:
- Version pinning in package.json
- Monitor MCP changelog
- Automated tests detect breaking changes
- Quick adaptation (MCP is stable)

---

## 11. Testing Strategy

### 11.1 Unit Tests

**Core Components**:
- Selector registry (load, query, fallback)
- Checkpoint manager (create, query, validation)
- Requirement enforcer (proactive blocking)
- Platform bridge factory (OS detection)

**Coverage Target**: > 80%

### 11.2 Integration Tests

**Component Integration**:
- Browser + Platform (connect, navigate, screenshot)
- Platform + Validation (checkpoint creation)
- Validation + Neo4j (persistence, queries)
- MCP Tools + Workflows (end-to-end tool execution)

**Coverage Target**: > 60%

### 11.3 End-to-End Tests

**Complete Workflows**:
1. Connect → Send simple message → Extract response
2. Connect → Attach file → Send → Extract (WITH enforcement)
3. Connect → Try skip attachment → BLOCKED → Attach → Send
4. Connect → Enable Extended Thinking → Send → Wait → Extract
5. Resume existing session → Send → Extract

**Coverage Target**: 100% of MCP tools

### 11.4 Manual Testing Protocol

**Pre-Release Checklist**:
- [ ] Test all 5 platforms (Claude, ChatGPT, Gemini, Grok, Perplexity)
- [ ] Test on macOS (13, 14, 15)
- [ ] Test on Linux (Ubuntu 22.04, 24.04)
- [ ] Test attachment enforcement (try to bypass)
- [ ] Test response detection (Extended Thinking, Deep Research)
- [ ] Test artifact download (Claude, Gemini, Perplexity)
- [ ] Test session resume (after compact)
- [ ] Test error recovery (selector not found, timeout)

---

## 12. Documentation Requirements

### 12.1 Code Documentation

**Every file must have**:
- Purpose (What does this file do?)
- Dependencies (What does it import?)
- Exports (What does it provide?)
- Examples (How to use it?)

**Every public method must have**:
- JSDoc comment with description
- Parameter types and descriptions
- Return type and description
- Throws (what errors can occur)
- Example usage

### 12.2 Architecture Documentation

**Required Documents**:
1. `ARCHITECTURE.md` - System overview, layer diagrams
2. `WORKFLOWS.md` - Step-by-step workflow diagrams
3. `VALIDATION.md` - Validation system explanation
4. `SELECTORS.md` - Selector management guide
5. `PLATFORM_GUIDE.md` - How to add new platforms
6. `TESTING.md` - Test strategy and running tests

### 12.3 User Documentation

**Required Guides**:
1. `QUICK_START.md` - Get running in 5 minutes
2. `MCP_TOOLS.md` - Tool reference with examples
3. `TROUBLESHOOTING.md` - Common errors and fixes
4. `SELECTOR_UPDATES.md` - How to update selectors when platforms change

---

## 13. Deployment Strategy

### 13.1 Deployment Phases

**Phase 1: Canary (Week 1)**
- Deploy to CCM (single instance)
- Run in parallel with old system
- Monitor errors, collect feedback

**Phase 2: Beta (Week 2)**
- Deploy to Mira (multi-instance)
- Enable for AI Family workflows
- Validate attachment enforcement working

**Phase 3: Production (Week 3)**
- Replace old system completely
- Update all documentation
- Announce to users

### 13.2 Rollback Plan

**Triggers for Rollback**:
- Defect rate > 5% (vs target < 0.1%)
- Critical bug in attachment enforcement
- Neo4j data corruption
- Unrecoverable platform breakage

**Rollback Procedure**:
1. Stop MCP server
2. Revert to old code (`git checkout <old-commit>`)
3. Rebuild MCP server (`npm run build`)
4. Restart MCP server
5. Verify old system operational
6. Document rollback reason

**Recovery Time Objective**: < 5 minutes

---

## Appendix A: Reference Documents

**Validation Audit**:
- `VALIDATION_AUDIT_EXECUTIVE_SUMMARY.md` - Root cause summary
- `VALIDATION_CHECKPOINT_FAILURE_AUDIT.md` - Detailed analysis
- `VALIDATION_ENFORCEMENT_COMPARISON.md` - Before/after comparison
- `VALIDATION_FIX_IMPLEMENTATION.md` - Implementation guide

**Process Analysis**:
- `6SIGMA_PLAN.md` - LEAN 6SIGMA workflow analysis
- `VALIDATION_CHECKPOINTS_PLAN.md` - Original checkpoint design

**Current Architecture**:
- `README.md` - System overview
- `CHAT_ELEMENTS.md` - Platform selector reference
- `docs/MCP_*.md` - MCP server documentation

---

## Appendix B: Glossary

**Terms**:
- **Checkpoint**: Validation record in Neo4j proving a step was completed
- **Platform**: AI chat interface (Claude, ChatGPT, Gemini, etc.)
- **Session**: Browser tab connected to a platform conversation
- **Workflow**: Multi-step operation (e.g., attach files → validate → send)
- **Selector**: CSS/XPath string to find UI elements
- **Bridge**: OS-specific automation layer (osascript/xdotool)
- **Enforcement**: Proactive blocking (prevent wrong action)
- **Validation**: Reactive checking (detect wrong action)
- **RPN**: Risk Priority Number (Severity × Occurrence × Detection)
- **DPMO**: Defects Per Million Opportunities
- **Sigma Level**: Statistical measure of quality (6σ = 99.99966% perfect)

---

**Document Status**: COMPLETE
**Next Action**: Review with stakeholders, get approval to proceed with Phase 1 (Foundation)
**Estimated Total Rebuild Time**: 5 weeks (foundation → launch)
**Estimated ROI**: 99% defect reduction, 10x improvement in reliability
