# Validation Checkpoint Fix - Implementation Guide

**Based on**: VALIDATION_CHECKPOINT_FAILURE_AUDIT.md
**Estimated Time**: 2-3 hours
**Priority**: CRITICAL

---

## Quick Summary

**Problem**: Agent can skip attachment step when plan requires attachments.

**Root Cause**: Validation is REACTIVE (checks steps) not PROACTIVE (enforces requirements).

**Fix**: Store attachment requirements in 'plan' checkpoint, enforce in send_message.

---

## Implementation Steps

### Step 1: Update ValidationCheckpointStore Schema

**File**: `src/core/validation-checkpoints.js`

**Line 66-75**: Add new fields to checkpoint object:
```javascript
async createCheckpoint(options) {
  const checkpoint = {
    id: uuidv4(),
    conversationId: options.conversationId,
    step: options.step,
    validated: options.validated,
    notes: options.notes,
    screenshot: options.screenshot || null,
    validator: options.validator || this.getValidatorIdentity(),
    timestamp: new Date().toISOString(),
    // ADD THESE TWO LINES:
    requiredAttachments: options.requiredAttachments || [],
    actualAttachments: options.actualAttachments || []
  };
```

**Line 76-92**: Update Cypher query to include new fields:
```javascript
await this.client.write(
  `MATCH (c:Conversation {id: $conversationId})
   CREATE (v:ValidationCheckpoint {
     id: $id,
     conversationId: $conversationId,
     step: $step,
     validated: $validated,
     notes: $notes,
     screenshot: $screenshot,
     validator: $validator,
     timestamp: datetime($timestamp),
     requiredAttachments: $requiredAttachments,
     actualAttachments: $actualAttachments
   })
   CREATE (v)-[:IN_CONVERSATION]->(c)
   RETURN v`,
  checkpoint
);
```

**After line 239**: Add new method `requiresAttachments()`:
```javascript
/**
 * Check if the plan for this conversation requires attachments
 *
 * @param {string} conversationId
 * @returns {Object} {required: boolean, files: Array<string>, count: number}
 */
async requiresAttachments(conversationId) {
  // Get the 'plan' checkpoint for this conversation
  const result = await this.client.read(
    `MATCH (v:ValidationCheckpoint {conversationId: $conversationId, step: 'plan'})
     RETURN v
     ORDER BY v.timestamp DESC
     LIMIT 1`,
    { conversationId }
  );

  if (!result || result.length === 0) {
    return { required: false, files: [], count: 0 };
  }

  const checkpoint = result[0].v.properties || result[0].v;
  const requiredFiles = checkpoint.requiredAttachments || [];

  return {
    required: requiredFiles.length > 0,
    files: requiredFiles,
    count: requiredFiles.length
  };
}
```

---

### Step 2: Update taey_attach_files to Store Actual Attachments

**File**: `mcp_server/server-v2.ts`

**Lines 735-741**: Update checkpoint creation to include actualAttachments:
```typescript
// Create pending validation checkpoint (must be validated before continuing)
await validationStore.createCheckpoint({
  conversationId: sessionId,
  step: 'attach_files',
  validated: false,
  notes: `Attached ${attachmentResults.length} file(s). Awaiting manual validation. MUST call taey_validate_step with validated=true after reviewing screenshot.`,
  screenshot: lastScreenshot,
  // ADD THESE TWO LINES:
  requiredAttachments: [],     // Already stored in 'plan' checkpoint
  actualAttachments: filePaths // What was actually attached
});
```

---

### Step 3: Replace taey_send_message Validation Logic

**File**: `mcp_server/server-v2.ts`

**REPLACE lines 461-487** with this context-aware validation:

```typescript
// VALIDATION CHECKPOINT: Check if attachments are required by the plan
const attachmentRequirement = await validationStore.requiresAttachments(sessionId);

if (attachmentRequirement.required) {
  // Attachments were specified in plan - MUST have attach_files validated
  const lastValidation = await validationStore.getLastValidation(sessionId);

  if (!lastValidation) {
    throw new Error(
      `Validation checkpoint failed: Draft plan requires ${attachmentRequirement.count} attachment(s).\n` +
      `No validation checkpoints found. You must:\n` +
      `1. Call taey_attach_files with files: ${JSON.stringify(attachmentRequirement.files)}\n` +
      `2. Review screenshot to confirm files are visible\n` +
      `3. Call taey_validate_step with step='attach_files' and validated=true`
    );
  }

  // If attachments required, last validated step MUST be 'attach_files'
  if (lastValidation.step !== 'attach_files') {
    throw new Error(
      `Validation checkpoint failed: Draft plan requires ${attachmentRequirement.count} attachment(s).\n` +
      `Last validated step was '${lastValidation.step}'.\n` +
      `You MUST:\n` +
      `1. Call taey_attach_files with files: ${JSON.stringify(attachmentRequirement.files)}\n` +
      `2. Review screenshot to confirm files are visible\n` +
      `3. Call taey_validate_step with step='attach_files' and validated=true\n\n` +
      `You cannot skip attachment when the draft plan specifies files.`
    );
  }

  // Check that attachment step is validated (not pending)
  if (!lastValidation.validated) {
    throw new Error(
      `Validation checkpoint failed: Attachment step is pending validation (validated=false).\n` +
      `You must review the screenshot and call taey_validate_step with validated=true.\n` +
      `Notes from pending checkpoint: ${lastValidation.notes}`
    );
  }

  // Verify correct number of attachments were actually attached
  const actualCount = lastValidation.actualAttachments?.length || 0;
  if (actualCount !== attachmentRequirement.count) {
    throw new Error(
      `Validation checkpoint failed: Plan required ${attachmentRequirement.count} file(s), ` +
      `but only ${actualCount} were attached.\n` +
      `Required files: ${JSON.stringify(attachmentRequirement.files)}\n` +
      `Actual files: ${JSON.stringify(lastValidation.actualAttachments || [])}`
    );
  }

  console.error(`[MCP] ✓ Attachment validation passed: ${actualCount} file(s) verified`);

} else {
  // No attachments required - original validation logic
  const lastValidation = await validationStore.getLastValidation(sessionId);

  if (!lastValidation) {
    throw new Error(
      `Validation checkpoint failed: No validation checkpoints found. ` +
      `You must validate the 'plan' step before sending a message.`
    );
  }

  if (!lastValidation.validated) {
    throw new Error(
      `Validation checkpoint failed: Step '${lastValidation.step}' is pending validation (validated=false). ` +
      `Call taey_validate_step with validated=true after reviewing screenshot.\n` +
      `Notes from pending checkpoint: ${lastValidation.notes}`
    );
  }

  const validSteps = ['plan', 'attach_files'];
  if (!validSteps.includes(lastValidation.step)) {
    throw new Error(
      `Validation checkpoint failed: Last validated step was '${lastValidation.step}'. ` +
      `Must validate one of: ${validSteps.join(', ')} before sending.`
    );
  }

  console.error(`[MCP] ✓ No attachments required - proceeding with '${lastValidation.step}' validation`);
}
```

---

### Step 4: Store Required Attachments in Plan Checkpoint

**Context**: This requires integration with draft message system. Since we don't have a unified draft creation flow in MCP yet, we need to handle it when plan validation is created.

**Option A - If using draft-message.js**:

Update `createDraftMessage()` to store attachments in plan checkpoint:
```javascript
// After creating draft
await validationStore.createCheckpoint({
  conversationId: plan.conversationId,
  step: 'plan',
  validated: false,
  notes: `Plan created - pending validation`,
  validator: this.sender,
  requiredAttachments: plan.attachments || [],
  actualAttachments: []
});
```

**Option B - Manual (current workflow)**:

When agent creates plan manually, they must call taey_validate_step with attachment info:

**Update taey_validate_step tool description** to include requiredAttachments parameter:

```typescript
{
  name: "taey_validate_step",
  description: "Validate a workflow step after reviewing screenshot...",
  inputSchema: {
    type: "object",
    properties: {
      conversationId: { type: "string" },
      step: { type: "string", enum: [...] },
      validated: { type: "boolean" },
      notes: { type: "string" },
      screenshot: { type: "string" },
      // ADD THIS:
      requiredAttachments: {
        type: "array",
        items: { type: "string" },
        description: "For 'plan' step: Array of file paths that MUST be attached before sending"
      }
    },
    required: ["conversationId", "step", "validated", "notes"]
  }
}
```

**Update taey_validate_step handler** (lines 923-958):
```typescript
case "taey_validate_step": {
  const { conversationId, step, validated, notes, screenshot, requiredAttachments } = args as {
    conversationId: string;
    step: string;
    validated: boolean;
    notes: string;
    screenshot?: string;
    requiredAttachments?: string[];
  };

  // Create validation checkpoint
  const checkpoint = await validationStore.createCheckpoint({
    conversationId,
    step,
    validated,
    notes,
    screenshot: screenshot || null,
    // ADD THESE:
    requiredAttachments: requiredAttachments || [],
    actualAttachments: []
  });

  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        success: true,
        validationId: checkpoint.id,
        step,
        validated,
        timestamp: checkpoint.timestamp,
        requiredAttachments: checkpoint.requiredAttachments,
        message: validated
          ? `✓ Step '${step}' validated. Can proceed to next step.`
          : `✗ Step '${step}' marked as failed. Fix and retry before proceeding.`
      }, null, 2)
    }]
  };
}
```

---

## Testing Protocol

### Test 1: Enforce Attachment When Required

```javascript
// Create plan checkpoint with required attachments
await taey_validate_step({
  conversationId: 'test-session-1',
  step: 'plan',
  validated: true,
  notes: 'Plan created for Grok - need to attach clarity axioms',
  requiredAttachments: ['/Users/REDACTED/Downloads/clarity-universal-axioms-latest.md']
});

// Try to send WITHOUT attaching
try {
  await taey_send_message({
    sessionId: 'test-session-1',
    message: 'Hello Grok'
  });
  console.log('❌ FAIL: Should have been blocked');
  process.exit(1);
} catch (err) {
  console.log('✓ PASS: Blocked correctly');
  console.log('  Error:', err.message);
  assert(err.message.includes('Draft plan requires 1 attachment'));
}
```

### Test 2: Verify Attachment Count

```javascript
// Attach files
await taey_attach_files({
  sessionId: 'test-session-2',
  filePaths: ['/Users/REDACTED/Downloads/file1.md']
});

// Validate with correct count
await taey_validate_step({
  conversationId: 'test-session-2',
  step: 'attach_files',
  validated: true,
  notes: 'Saw 1 file pill'
});

// Should succeed
await taey_send_message({
  sessionId: 'test-session-2',
  message: 'Test'
});

console.log('✓ PASS: Sent successfully with correct attachment count');
```

### Test 3: Allow Skip When No Attachments

```javascript
// Create plan with NO attachments
await taey_validate_step({
  conversationId: 'test-session-3',
  step: 'plan',
  validated: true,
  notes: 'Plan created - no attachments needed',
  requiredAttachments: []
});

// Should allow direct send
await taey_send_message({
  sessionId: 'test-session-3',
  message: 'Quick question'
});

console.log('✓ PASS: Sent successfully without attachments');
```

---

## Verification Checklist

After implementation:

- [ ] `src/core/validation-checkpoints.js` has requiredAttachments/actualAttachments fields
- [ ] `src/core/validation-checkpoints.js` has requiresAttachments() method
- [ ] `mcp_server/server-v2.ts` taey_attach_files stores actualAttachments
- [ ] `mcp_server/server-v2.ts` taey_send_message checks attachment requirements
- [ ] `mcp_server/server-v2.ts` taey_validate_step accepts requiredAttachments parameter
- [ ] Test 1 passes (blocks send when attachments required but not attached)
- [ ] Test 2 passes (allows send when correct attachments attached)
- [ ] Test 3 passes (allows send when no attachments required)
- [ ] Run `npm run build` to compile TypeScript
- [ ] Run full integration test with real AI Family sessions
- [ ] Commit with message: "fix: Enforce attachment requirements in validation checkpoints"

---

## Rollback Plan

If issues arise:

1. Revert to commit before changes: `git reset --hard HEAD~1`
2. Neo4j data persists - old checkpoints won't have new fields (will be null/empty arrays)
3. New code handles missing fields gracefully with `|| []` defaults
4. No data loss, only validation enforcement removed

---

## Success Metrics

**Before**: Agent could skip attachments, happened 5 times in one session
**After**: Mathematically impossible to skip when plan requires attachments

**RPN Reduction**: 1000 → 10 (99% risk reduction)

---

## Estimated Time Breakdown

- Step 1 (ValidationCheckpointStore): 30 min
- Step 2 (taey_attach_files): 10 min
- Step 3 (taey_send_message validation): 45 min
- Step 4 (taey_validate_step update): 20 min
- Testing: 30 min
- Documentation update: 15 min

**Total**: ~2.5 hours

---

**Ready to implement**. Start with Step 1, test each step independently, then integration test.
