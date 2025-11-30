# Manual Validation Checkpoints - Implementation Plan

**Created**: 2025-11-29
**Status**: Ready to implement
**Goal**: Force conscious validation after each chat workflow step to prevent runaway execution

---

## The Problem

Current behavior:
```
❌ taey_attach_files() runs
❌ Types in search box instead of attaching
❌ I never see the failure
❌ I continue to taey_send_message()
❌ Everything fails but I keep going
```

Root cause: **Tools return control to me, but I'm not forced to validate before continuing**

---

## The Solution: Manual Validation Gates

Each workflow step requires explicit validation before next step can proceed:

```
1. taey_attach_files() → returns screenshot
2. I READ screenshot consciously
3. taey_validate_step() → I confirm "files visible" or "failed - retry"
4. taey_type_message() → checks validation, only proceeds if validated
```

**Key mechanism**: Next tool queries Neo4j for validation status. If missing → ERROR.

---

## Architecture

### Validation State Storage (Neo4j)

```cypher
// New node type
CREATE (v:ValidationCheckpoint {
  id: "val-abc123",
  conversationId: "session-xyz",
  step: "attach_files",
  validated: true,
  timestamp: datetime(),
  notes: "Saw 2 file pills above input - clarity-universal-axioms-latest.md and notes.md",
  screenshot: "/tmp/taey-claude-session-xyz-attach.png",
  validator: "ccm-claude"
})

// Relationships
(v)-[:VALIDATES_STEP]->(m:Message {id: draftId})
(v)-[:IN_CONVERSATION]->(c:Conversation {id: conversationId})
```

### Workflow Steps (Ordered)

1. **plan** - Create draft message (returns plan + screenshot of current state)
2. **attach_files** - Attach files (if plan.attachments.length > 0)
3. **type_message** - Type prompt into input box
4. **click_send** - Submit the message
5. **wait_response** - Wait for AI response (optional)
6. **extract_response** - Extract AI response text

Each step (except plan) requires previous step validated.

---

## New MCP Tools

### 1. `taey_validate_step`

**Purpose**: I explicitly validate a workflow step

**Parameters**:
```typescript
{
  conversationId: string;
  step: 'plan' | 'attach_files' | 'type_message' | 'click_send' | 'wait_response' | 'extract_response';
  validated: boolean;
  notes: string;  // Required - what I observed
  screenshot?: string;  // Optional - if not from previous tool
}
```

**Returns**:
```typescript
{
  success: true,
  validationId: "val-abc123",
  step: "attach_files",
  validated: true,
  message: "Step 'attach_files' validated. Can proceed to 'type_message'."
}
```

**Neo4j operation**:
```cypher
CREATE (v:ValidationCheckpoint {
  id: $id,
  conversationId: $conversationId,
  step: $step,
  validated: $validated,
  timestamp: datetime(),
  notes: $notes,
  screenshot: $screenshot,
  validator: $sender
})

MATCH (c:Conversation {id: $conversationId})
CREATE (v)-[:IN_CONVERSATION]->(c)

RETURN v
```

### 2. Modified Existing Tools

**`taey_attach_files`** - Add validation check:
```typescript
async function taey_attach_files(params) {
  // Check if 'plan' step validated
  const planValidated = await checkValidation(params.sessionId, 'plan');
  if (!planValidated) {
    throw new Error('Previous step "plan" not validated. Call taey_validate_step first.');
  }

  // Execute attachment
  const result = await attachFiles(params);

  // Return screenshot for validation
  return {
    success: true,
    screenshot: result.screenshot,
    filesAttached: params.filePaths.length,
    message: "Files attached. VALIDATE screenshot before continuing."
  };
}
```

**`taey_type_message`** - Requires attach_files OR plan validated:
```typescript
async function taey_type_message(params) {
  // Check validation chain
  const validation = await getLastValidation(params.sessionId);

  // Must have either 'attach_files' or 'plan' validated
  if (!validation || !['plan', 'attach_files'].includes(validation.step)) {
    throw new Error(`Previous step not validated. Last validated: ${validation?.step || 'none'}`);
  }

  // Execute typing
  const result = await typeMessage(params);

  return {
    success: true,
    screenshot: result.screenshot,
    message: "Message typed. VALIDATE screenshot before continuing."
  };
}
```

**Similar for**: `taey_click_send`, `taey_extract_response`

---

## Implementation Steps

### Phase 1: Neo4j Schema

**File**: `src/core/validation-checkpoints.js`

```javascript
export class ValidationCheckpointStore {
  async createCheckpoint(options) {
    // Create ValidationCheckpoint node
    // Link to Conversation
    // Return checkpoint
  }

  async getLastValidation(conversationId) {
    // Query most recent ValidationCheckpoint
    // Return step name and validated status
  }

  async isStepValidated(conversationId, step) {
    // Check if specific step validated
    // Return boolean
  }

  async getValidationChain(conversationId) {
    // Get all validations in order
    // Return array of {step, validated, timestamp}
  }
}
```

### Phase 2: MCP Tool - taey_validate_step

**File**: `mcp_server/server-v2.ts`

Add new tool registration:
```typescript
{
  name: "taey_validate_step",
  description: "Validate a workflow step after reviewing screenshot",
  inputSchema: {
    type: "object",
    properties: {
      conversationId: { type: "string" },
      step: {
        type: "string",
        enum: ['plan', 'attach_files', 'type_message', 'click_send', 'wait_response', 'extract_response']
      },
      validated: { type: "boolean" },
      notes: { type: "string" }
    },
    required: ["conversationId", "step", "validated", "notes"]
  }
}
```

Implementation:
```typescript
case "taey_validate_step": {
  const { conversationId, step, validated, notes } = args;

  const checkpoint = await validationStore.createCheckpoint({
    conversationId,
    step,
    validated,
    notes,
    validator: getSenderIdentity()
  });

  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        success: true,
        validationId: checkpoint.id,
        step,
        validated,
        message: validated
          ? `Step '${step}' validated. Can proceed to next step.`
          : `Step '${step}' marked as failed. Fix and retry.`
      }, null, 2)
    }]
  };
}
```

### Phase 3: Add Validation Checks to Existing Tools

**Modify**:
- `taey_attach_files` - Check plan validated
- `taey_type_message` - Check attach_files OR plan validated (skip attach if no files)
- `taey_click_send` - Check type_message validated
- `taey_extract_response` - Check click_send validated

**Pattern**:
```typescript
// At start of each tool
const validation = await validationStore.getLastValidation(conversationId);
const requiredSteps = ['plan', 'attach_files']; // Example

if (!validation || !requiredSteps.includes(validation.step) || !validation.validated) {
  throw new Error(
    `Previous step not validated. ` +
    `Expected one of: ${requiredSteps.join(', ')}. ` +
    `Found: ${validation?.step || 'none'}. ` +
    `Review screenshot and call taey_validate_step.`
  );
}
```

### Phase 4: Update Draft Message Integration

**Modify**: `src/core/draft-message.js`

Add validation tracking to draft execution:
```javascript
async createDraftMessage(plan) {
  // Create draft as before
  const draft = await this.client.write(...);

  // Create initial 'plan' checkpoint
  await validationStore.createCheckpoint({
    conversationId: plan.conversationId,
    step: 'plan',
    validated: false,  // Requires manual validation
    notes: 'Plan created - pending validation',
    validator: this.sender
  });

  return draft;
}
```

### Phase 5: Testing

**Test File**: `test-validation-workflow.js`

```javascript
// Test 1: Can't attach without validating plan
const draft = await createDraft({...});
try {
  await taey_attach_files({sessionId});
  // Should fail
} catch (err) {
  console.log('✓ Correctly blocked - plan not validated');
}

// Test 2: Validate plan, then attach succeeds
await taey_validate_step({
  conversationId: sessionId,
  step: 'plan',
  validated: true,
  notes: 'Reviewed plan - routing to Opus, 2 attachments'
});

const attachResult = await taey_attach_files({sessionId, filePaths: [...]});
console.log('✓ Attachment succeeded after validation');

// Test 3: Can't type without validating attach
try {
  await taey_type_message({sessionId, message: '...'});
  // Should fail
} catch (err) {
  console.log('✓ Correctly blocked - attach not validated');
}

// Test 4: Full workflow with all validations
// ... complete sequence
```

---

## Usage Example (Post-Implementation)

```javascript
// Step 1: Create plan
const draft = await taey_create_draft({
  sessionId,
  intent: 'dream-sessions',
  content: 'Hey Opus...',
  pastedContent: [...]
});
// Returns: {screenshot: current state, plan: {...}}

// Step 2: I review, validate plan
await taey_validate_step({
  conversationId: sessionId,
  step: 'plan',
  validated: true,
  notes: 'Plan shows: claude/opus-4.5/extendedThinking, 2 attachments (clarity-universal-axioms-latest.md, notes.md), pasted Grok response. Looks good.'
});

// Step 3: Attach files
const attach = await taey_attach_files({
  sessionId,
  filePaths: draft.plan.attachments
});
// Returns: {screenshot: files attached}

// Step 4: I review screenshot, validate
await taey_validate_step({
  conversationId: sessionId,
  step: 'attach_files',
  validated: true,
  notes: 'Saw 2 file pills above input box with correct filenames'
});

// Step 5: Type message
const type = await taey_type_message({
  sessionId,
  message: draft.plan.content
});
// Returns: {screenshot: message typed}

// Step 6: I review screenshot, validate
await taey_validate_step({
  conversationId: sessionId,
  step: 'type_message',
  validated: true,
  notes: 'Message text visible in input box, cursor at end'
});

// Step 7: Submit
await taey_click_send({sessionId});
```

**If anything fails**: I mark `validated: false` and retry that step.

---

## Success Criteria

✅ Cannot proceed to next step without validating previous step
✅ Validation requires conscious action (must read screenshot and write notes)
✅ All validations logged to Neo4j for audit trail
✅ Clear error messages when validation missing
✅ Can skip steps (e.g., no attachments) by validating plan directly
✅ Multi-Claude support (validator field tracks who validated)
✅ Tests verify enforcement works

---

## Files to Create/Modify

**New**:
- `src/core/validation-checkpoints.js` - Validation storage layer
- `test-validation-workflow.js` - Integration tests

**Modify**:
- `mcp_server/server-v2.ts` - Add taey_validate_step tool, add checks to existing tools
- `src/core/draft-message.js` - Create initial plan checkpoint
- `src/core/conversation-store.js` - Add ValidationCheckpoint schema initialization

**Estimated**: 3-4 hours to implement and test

---

## Post-Compact Recovery

After I compact and lose context:

1. Read this plan file
2. Check git status (may be mid-implementation)
3. Run tests to see what's working
4. Continue from where I left off

**Implementation order**:
1. ValidationCheckpointStore (backend)
2. taey_validate_step tool (MCP)
3. Validation checks in existing tools
4. Tests
5. Integration with draft messages
