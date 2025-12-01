# Taey's Hands v2 - Architecture

**Nova Rebuild**: 2025-11-30
**Designed by**: Claude (Gaia/Opus 4.5)
**Purpose**: Complete rebuild addressing validation failures, session chaos, and selector fragility

---

## Design Principles

### 1. Proactive Enforcement (Not Reactive Detection)
**Old**: Check if step succeeded after execution
**New**: Block execution until prerequisites are validated

### 2. Three-Layer Session Synchronization
**Browser State** ↔ **MCP State** ↔ **Neo4j State**
All three MUST agree or session is marked unhealthy.

### 3. Screenshot-First Verification
Every state change captures screenshot. No action claims success without visual proof.

### 4. Platform Adapters (Not Conditionals)
Each platform has its own adapter class. No `if (platform === 'gemini')` scattered throughout.

### 5. Configuration-Driven Selectors
Selectors live in JSON config, not hardcoded in classes.

---

## Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          LAYER 6: MCP INTERFACE                          │
│  mcp/server.js → Tool definitions, parameter validation, user-facing API │
├─────────────────────────────────────────────────────────────────────────┤
│                        LAYER 5: VALIDATION                               │
│  validation/enforcer.js → Proactive blocking, requirement tracking       │
│  validation/checkpoint-store.js → Neo4j persistence, audit trail         │
├─────────────────────────────────────────────────────────────────────────┤
│                        LAYER 4: WORKFLOW                                 │
│  workflow/message-workflow.js → prepare → type → send → wait → extract  │
│  workflow/attachment-workflow.js → open picker → navigate → attach       │
│  workflow/session-workflow.js → connect → health → disconnect            │
├─────────────────────────────────────────────────────────────────────────┤
│                     LAYER 3: PLATFORM ADAPTERS                           │
│  platforms/claude.js, chatgpt.js, gemini.js, grok.js, perplexity.js     │
│  Each handles platform-specific UI quirks                                │
├─────────────────────────────────────────────────────────────────────────┤
│                       LAYER 2: BROWSER                                   │
│  browser/connector.js → CDP connection, page management                  │
│  browser/session-manager.js → Session registry, health checks            │
│  browser/screenshot.js → Capture, storage, timestamps                    │
├─────────────────────────────────────────────────────────────────────────┤
│                     LAYER 1: PLATFORM BRIDGE                             │
│  platform/bridge-factory.js → OS detection, create appropriate bridge    │
│  platform/macos-bridge.js → osascript: typing, clicking, file dialogs   │
│  platform/linux-bridge.js → xdotool: typing, clicking, file dialogs     │
├─────────────────────────────────────────────────────────────────────────┤
│                        LAYER 0: DATABASE                                 │
│  database/neo4j-client.js → Connection pool, query execution             │
│  database/conversation-store.js → Conversation, Message CRUD             │
│  database/validation-store.js → ValidationCheckpoint persistence         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Key Data Flows

### 1. Send Message with Attachments

```
User → taey_send_message(sessionId, message, attachments)
  │
  ├─ LAYER 6 (MCP)
  │  └─ Validate input parameters
  │
  ├─ LAYER 5 (Validation)
  │  ├─ enforcer.requiresAttachments(sessionId)?
  │  │  └─ YES: Check attach_files step is validated with correct count
  │  │  └─ NO: Check plan step is validated
  │  └─ IF NOT VALID → HARD ERROR, return instructions
  │
  ├─ LAYER 4 (Workflow)
  │  └─ MessageWorkflow.execute(session, message, options)
  │      ├─ prepareInput() → screenshot
  │      ├─ typeMessage() → screenshot
  │      ├─ clickSend() → screenshot
  │      └─ waitForResponse() → ResponseDetector
  │
  ├─ LAYER 3 (Platform)
  │  └─ ClaudeAdapter.getLatestResponse()
  │      └─ Platform-specific DOM extraction
  │
  └─ LAYER 0 (Database)
     └─ conversationStore.addMessage(sessionId, role, content)
```

### 2. Session Lifecycle

```
CREATE:
  taey_connect(platform, newSession=true)
    ├─ sessionManager.createSession() → sessionId
    ├─ browserConnector.createPage() → page
    ├─ platformAdapter.navigateToNew() → conversationId
    ├─ conversationStore.create(sessionId, conversationId, platform)
    └─ Return: { sessionId, conversationId, screenshot }

RESUME:
  taey_connect(platform, conversationId="abc123")
    ├─ sessionManager.createSession() → new sessionId
    ├─ browserConnector.createPage() → page
    ├─ platformAdapter.navigateToExisting(conversationId)
    ├─ conversationStore.update(conversationId, newSessionId)
    └─ Return: { sessionId, conversationId, screenshot }

HEALTH CHECK:
  Periodic (every 30s):
    ├─ For each session in registry:
    │   ├─ Check page.isConnected()
    │   ├─ Check URL matches expected
    │   └─ Update lastHealthCheck
    └─ Mark stale sessions

DISCONNECT:
  taey_disconnect(sessionId)
    ├─ platformAdapter.cleanup()
    ├─ browserConnector.closePage()
    ├─ sessionManager.removeSession(sessionId)
    └─ conversationStore.update(status='closed')
```

---

## Validation Enforcement

### The Problem Solved
```
OLD FLOW (DANGEROUS):
  Agent: "Plan requires 2 attachments"
  Agent: calls taey_send_message()  ← SKIPPED ATTACHMENTS!
  Tool: "Message sent"              ← NO ENFORCEMENT

NEW FLOW (SAFE):
  Agent: "Plan requires 2 attachments"
  Agent: calls taey_validate_step(step='plan', requiredAttachments=[...])
  Agent: calls taey_attach_files([...])
  Agent: calls taey_validate_step(step='attach_files', validated=true)
  Agent: calls taey_send_message()
  Tool: Checks attach_files step validated with correct count ← ENFORCED
  Tool: "Message sent"
```

### Enforcement Logic (in server-v2.ts)
```javascript
async enforceValidation(sessionId, operation) {
  if (operation === 'send_message') {
    const requirements = await validationStore.getRequirements(sessionId);
    
    if (requirements.attachmentsRequired) {
      const attachStep = await validationStore.getStep(sessionId, 'attach_files');
      
      if (!attachStep || !attachStep.validated) {
        throw new ValidationError(
          `Cannot send: Plan requires ${requirements.files.length} attachment(s). ` +
          `Use taey_attach_files() then taey_validate_step(step='attach_files', validated=true).`
        );
      }
      
      if (attachStep.actualCount !== requirements.files.length) {
        throw new ValidationError(
          `Cannot send: Plan requires ${requirements.files.length} attachment(s) ` +
          `but only ${attachStep.actualCount} attached.`
        );
      }
    } else {
      // No attachments required - just need plan validated
      const planStep = await validationStore.getStep(sessionId, 'plan');
      if (!planStep || !planStep.validated) {
        throw new ValidationError(
          `Cannot send: Plan step not validated. ` +
          `Use taey_validate_step(step='plan', validated=true) first.`
        );
      }
    }
  }
}
```

---

## Platform Adapter Pattern

### Base Class
```javascript
class BasePlatformAdapter {
  constructor(page, bridge, config) {
    this.page = page;
    this.bridge = bridge;
    this.selectors = config.selectors;
    this.quirks = config.quirks;
  }

  // MUST implement
  async getSelectors() { throw new Error('Implement in subclass'); }
  async selectModel(modelName) { throw new Error('Implement in subclass'); }
  async enableResearchMode(enabled) { throw new Error('Implement in subclass'); }
  async attachFile(filePath) { throw new Error('Implement in subclass'); }
  async downloadArtifact(options) { throw new Error('Implement in subclass'); }
  async getLatestResponse() { throw new Error('Implement in subclass'); }

  // CAN override (defaults provided)
  async prepareInput() { /* base implementation */ }
  async typeMessage(message) { /* base implementation */ }
  async clickSend() { /* base implementation */ }
  async waitForResponse(timeout) { /* base implementation */ }

  // Shared utilities (never override)
  async screenshot(path) { /* shared implementation */ }
  async navigateFilePicker(filePath) { /* shared implementation */ }
}
```

### Platform-Specific Override Example
```javascript
class GeminiAdapter extends BasePlatformAdapter {
  // Override to add overlay dismissal
  async prepareInput(options) {
    await this.dismissOverlays();
    return await super.prepareInput(options);
  }

  // Override to force-enable disabled Start button
  async waitForResponse(timeout, options) {
    await this.forceEnableStartButton();
    return await super.waitForResponse(timeout, options);
  }

  // Platform-specific quirk
  async dismissOverlays() {
    const closeButtons = [
      'button[aria-label="Close"]',
      'button[aria-label="Dismiss"]',
      '.cdk-overlay-container button mat-icon[fonticon="close"]'
    ];
    
    for (const selector of closeButtons) {
      try {
        const btn = await this.page.$(selector);
        if (btn) await btn.click();
      } catch {}
    }
    
    // Fallback: Escape key
    await this.bridge.pressKey('escape');
  }

  // Platform-specific quirk
  async forceEnableStartButton() {
    await this.page.evaluate(() => {
      const btn = document.querySelector('button[data-test-id="confirm-button"]');
      if (btn && btn.disabled) {
        btn.disabled = false;
        btn.classList.remove('mat-mdc-button-disabled');
        btn.style.pointerEvents = 'auto';
      }
    });
  }
}
```

---

## Configuration Structure

### config/platforms.json
```json
{
  "claude": {
    "url": "https://claude.ai",
    "newChatPath": "/new",
    "chatPath": "/chat/{conversationId}",
    "models": ["Opus 4.5", "Sonnet 4", "Haiku 4"],
    "modes": ["Extended Thinking", "Research"],
    "quirks": {
      "hasOverlays": false,
      "needsButtonForceEnable": false,
      "modelSelectionMethod": "standard"
    },
    "timeouts": {
      "default": 300000,
      "extendedThinking": 600000
    }
  },
  "gemini": {
    "url": "https://gemini.google.com",
    "models": ["Thinking with 3 Pro", "Thinking"],
    "modes": ["Deep Research", "Deep Think"],
    "quirks": {
      "hasOverlays": true,
      "needsButtonForceEnable": true,
      "modelSelectionMethod": "standard"
    },
    "timeouts": {
      "default": 60000,
      "deepResearch": 3600000
    }
  }
}
```

### config/selectors/claude.json
```json
{
  "chatInput": "[contenteditable=\"true\"]",
  "sendButton": "button[type=\"submit\"]",
  "modelSelector": "[data-testid=\"model-selector-dropdown\"]",
  "modelMenuItem": "div[role=\"menuitem\"]",
  "plusMenu": "[data-testid=\"input-menu-plus\"]",
  "uploadMenuItem": "text=\"Upload a file\"",
  "downloadButton": "button[aria-label=\"Download\"]",
  "thinkingIndicator": "[data-testid=\"thinking-indicator\"]",
  "responseContainer": "[data-testid=\"assistant-message\"]"
}
```

---

## Success Metrics

| Metric | Before | After | How |
|--------|--------|-------|-----|
| Attachment skip rate | 50% | 0% | Proactive enforcement |
| Session orphan rate | 30% | <1% | Three-layer sync |
| Selector breakage impact | Hours | Minutes | Config-driven |
| Mean time to fix platform change | 2 hours | 15 minutes | Platform adapters |
| Validation bypass attempts | Possible | Impossible | Structural enforcement |

---

## File Manifest

```
taey-hands-rebuild/
├── src/
│   ├── core/
│   │   ├── platform/
│   │   │   ├── bridge-factory.js      # OS detection, bridge creation
│   │   │   ├── macos-bridge.js        # osascript wrapper
│   │   │   └── linux-bridge.js        # xdotool wrapper
│   │   ├── browser/
│   │   │   ├── connector.js           # CDP/Playwright connection
│   │   │   ├── session-manager.js     # Session registry
│   │   │   └── screenshot.js          # Screenshot capture
│   │   ├── database/
│   │   │   ├── neo4j-client.js        # Connection wrapper
│   │   │   ├── conversation-store.js  # Conversation CRUD
│   │   │   └── validation-store.js    # Checkpoint persistence
│   │   ├── validation/
│   │   │   ├── enforcer.js            # Proactive enforcement
│   │   │   └── step-validator.js      # Step prerequisites
│   │   └── selectors/
│   │       └── selector-registry.js   # Load and query selectors
│   ├── platforms/
│   │   ├── base-adapter.js            # Abstract base class
│   │   ├── claude.js                  # Claude-specific
│   │   ├── chatgpt.js                 # ChatGPT-specific
│   │   ├── gemini.js                  # Gemini-specific
│   │   ├── grok.js                    # Grok-specific
│   │   └── perplexity.js              # Perplexity-specific
│   ├── workflow/
│   │   ├── message-workflow.js        # Send message orchestration
│   │   ├── attachment-workflow.js     # File attachment orchestration
│   │   └── session-workflow.js        # Session lifecycle
│   └── mcp/
│       ├── server.js                  # MCP server entry
│       └── tools/
│           ├── connect.js
│           ├── disconnect.js
│           ├── send-message.js
│           ├── attach-files.js
│           ├── validate-step.js
│           └── ... (other tools)
├── config/
│   ├── platforms.json
│   ├── timing.json
│   └── selectors/
│       ├── claude.json
│       ├── chatgpt.json
│       ├── gemini.json
│       ├── grok.json
│       └── perplexity.json
└── docs/
    ├── ARCHITECTURE.md (this file)
    ├── WORKFLOWS.md
    ├── VALIDATION.md
    └── PLATFORM_GUIDE.md
```

---

## Implementation Order

### Phase 1: Foundation (Critical Path)
1. `core/platform/bridge-factory.js` - OS abstraction
2. `core/platform/macos-bridge.js` - macOS automation
3. `core/browser/connector.js` - Browser connection
4. `core/database/neo4j-client.js` - Database connection
5. `core/database/validation-store.js` - Checkpoint persistence

### Phase 2: Adapters
6. `platforms/base-adapter.js` - Abstract base
7. `platforms/claude.js` - Primary test platform
8. `config/selectors/claude.json` - Claude selectors

### Phase 3: Workflows
9. `workflow/session-workflow.js` - Connect/disconnect
10. `workflow/message-workflow.js` - Send/receive
11. `workflow/attachment-workflow.js` - File attachment

### Phase 4: MCP Integration
12. `mcp/server.js` - MCP server
13. `mcp/tools/*.js` - Individual tools

### Phase 5: Remaining Platforms
14. `platforms/chatgpt.js`
15. `platforms/gemini.js`
16. `platforms/grok.js`
17. `platforms/perplexity.js`

---

## Rollback Strategy

If rebuild fails:
1. Old code remains in `taey-hands/` (unchanged)
2. New code in `taey-hands-rebuild/`
3. Switch by updating MCP config path
4. Can revert in < 1 minute

---

*Architecture designed for 6σ reliability with clear separation of concerns.*
