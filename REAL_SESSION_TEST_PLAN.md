# Real Session Test Plan - v2 Rebuild Verification

## Purpose
Verify the v2 rebuild works with a real AI Family session to test all new components.

## Test Scenario
Test the complete workflow that previously failed: creating a plan with attachments, attaching files, and sending a message.

## Components to Test
1. **RequirementEnforcer** - Prevents attachment bypass
2. **SelectorRegistry** - Uses platform-specific selectors
3. **newSession** - Creates fresh session
4. **Session State Sync** - Keeps DB in sync

## Test Steps

### Test 1: Fresh Session Creation (newSession fix)
```javascript
// This should create an actually fresh session
const result = await taey_connect({
  interface: 'grok',
  newSession: true
});

// Expected: Empty input field, no conversation history
// Verifies: newSession bug is fixed
```

### Test 2: Plan with Attachments (RequirementEnforcer)
```javascript
// Create plan checkpoint with required attachments
await taey_validate_step({
  conversationId: sessionId,
  step: 'plan',
  validated: true,
  notes: 'Plan created - requires clarity axioms attachment',
  requiredAttachments: ['/Users/jesselarose/Downloads/clarity-universal-axioms-latest.md']
});

// Expected: Plan validated, attachment requirement stored
// Verifies: RequirementEnforcer stores requirements
```

### Test 3: Try to Send Without Attaching (RequirementEnforcer enforcement)
```javascript
// This should FAIL with clear error
try {
  await taey_send_message({
    sessionId: sessionId,
    message: 'Hello Grok'
  });
  console.log('❌ FAIL: Should have been blocked');
} catch (err) {
  console.log('✅ PASS: Blocked correctly');
  console.log('Error:', err.message);
  // Expected: Error telling us to attach files first
}

// Verifies: RequirementEnforcer prevents attachment bypass
```

### Test 4: Attach Files (Platform selectors + state sync)
```javascript
// Attach the required file
const attachResult = await taey_attach_files({
  sessionId: sessionId,
  filePaths: ['/Users/jesselarose/Downloads/clarity-universal-axioms-latest.md']
});

// Expected: File pill visible in screenshot
// Verifies: Platform-specific selector works (Grok button[aria-label="Attach"])
```

### Test 5: Validate Attachment
```javascript
await taey_validate_step({
  conversationId: sessionId,
  step: 'attach_files',
  validated: true,
  notes: 'File pill visible in screenshot'
});

// Expected: Attachment validated, can proceed to send
// Verifies: Validation checkpoint created
```

### Test 6: Send Message (Complete workflow)
```javascript
// Now this should SUCCEED
const sendResult = await taey_send_message({
  sessionId: sessionId,
  message: 'Hello Grok - test message',
  waitForResponse: false
});

// Expected: Message sent successfully
// Verifies: Complete workflow works end-to-end
```

### Test 7: Session State Sync
```javascript
// Check that session state is synced to Neo4j
const session = await conversationStore.findBySessionId(sessionId);

// Expected: Session has current conversationId, lastActivity updated
// Verifies: Session state sync working
```

## Expected Outcomes

✅ **newSession creates fresh session** (not loading old conversation)
✅ **RequirementEnforcer prevents send without attachment** (RPN 1000 → 10)
✅ **Grok attach button uses correct selector** (button[aria-label="Attach"])
✅ **Complete workflow succeeds** (plan → attach → validate → send)
✅ **Session state synced to Neo4j** (conversationId, lastActivity)

## Failure Scenarios to Test

### Scenario 1: Skip Attachment
- Plan requires attachment
- Try to send without attaching
- **Expected**: Clear error with instructions

### Scenario 2: Wrong Attachment Count
- Plan requires 2 files
- Attach only 1 file
- Validate attachment
- Try to send
- **Expected**: Error about count mismatch

### Scenario 3: Attach Without Plan
- Try to attach files without validating plan first
- **Expected**: Error requiring plan validation

## Success Criteria

- [ ] Fresh session created (empty conversation)
- [ ] Plan with attachments stored correctly
- [ ] Send blocked when attachments missing
- [ ] Attach uses correct Grok selector
- [ ] Complete workflow succeeds
- [ ] Session state synced to Neo4j
- [ ] All error messages clear and actionable

## Notes

This is a REAL test with REAL browser automation and REAL Neo4j database.
If any test fails, we can debug and fix before declaring v2 production-ready.
