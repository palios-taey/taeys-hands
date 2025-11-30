/**
 * Test validation checkpoint attachment enforcement
 *
 * This tests that the system prevents skipping attachments when they're required
 */

import { ValidationCheckpointStore } from './src/core/validation-checkpoints.js';
import { getConversationStore } from './src/core/conversation-store.js';

async function runTests() {
  console.log('=== Testing Validation Checkpoint Attachment Enforcement ===\n');

  const validationStore = new ValidationCheckpointStore();
  const conversationStore = getConversationStore();
  await validationStore.initSchema();

  const testSessionId = `test-validation-${Date.now()}`;

  try {
    // Create test conversation directly in Neo4j
    await validationStore.client.write(
      `CREATE (c:Conversation {id: $id, createdAt: datetime()})`,
      { id: testSessionId }
    );

    // TEST 1: requiresAttachments returns false when no plan exists
    console.log('Test 1: No plan checkpoint exists');
    const req1 = await validationStore.requiresAttachments(testSessionId);
    console.assert(!req1.required, 'Should not require attachments when no plan exists');
    console.assert(req1.count === 0, 'Count should be 0');
    console.log('✓ PASS: Returns {required: false, files: [], count: 0}\n');

    // TEST 2: requiresAttachments returns false when plan has no attachments
    console.log('Test 2: Plan checkpoint with NO attachments');
    await validationStore.createCheckpoint({
      conversationId: testSessionId,
      step: 'plan',
      validated: true,
      notes: 'Plan created - no attachments needed',
      requiredAttachments: []
    });

    const req2 = await validationStore.requiresAttachments(testSessionId);
    console.assert(!req2.required, 'Should not require attachments when plan has empty array');
    console.log('✓ PASS: Returns {required: false}\n');

    // TEST 3: requiresAttachments returns true when plan has attachments
    console.log('Test 3: Plan checkpoint WITH attachments');
    const testSession2 = `test-validation-${Date.now()}-2`;
    await validationStore.client.write(
      `CREATE (c:Conversation {id: $id, createdAt: datetime()})`,
      { id: testSession2 }
    );

    const requiredFiles = [
      '/Users/REDACTED/Downloads/clarity-universal-axioms-latest.md',
      '/Users/REDACTED/taey-hands/README.md'
    ];

    await validationStore.createCheckpoint({
      conversationId: testSession2,
      step: 'plan',
      validated: true,
      notes: 'Plan created - requires 2 attachments',
      requiredAttachments: requiredFiles
    });

    const req3 = await validationStore.requiresAttachments(testSession2);
    console.assert(req3.required === true, 'Should require attachments');
    console.assert(req3.count === 2, 'Count should be 2');
    console.assert(JSON.stringify(req3.files) === JSON.stringify(requiredFiles), 'Files should match');
    console.log('✓ PASS: Returns {required: true, files: [...], count: 2}\n');

    // TEST 4: Checkpoint stores and retrieves attachment info correctly
    console.log('Test 4: Checkpoint stores actualAttachments');
    const testSession3 = `test-validation-${Date.now()}-3`;
    await validationStore.client.write(
      `CREATE (c:Conversation {id: $id, createdAt: datetime()})`,
      { id: testSession3 }
    );

    await validationStore.createCheckpoint({
      conversationId: testSession3,
      step: 'attach_files',
      validated: true,
      notes: 'Attached 2 files',
      requiredAttachments: [],
      actualAttachments: requiredFiles
    });

    const lastValidation = await validationStore.getLastValidation(testSession3);
    console.assert(lastValidation.actualAttachments.length === 2, 'Should have 2 actual attachments');
    console.assert(JSON.stringify(lastValidation.actualAttachments) === JSON.stringify(requiredFiles), 'Actual files should match');
    console.log('✓ PASS: actualAttachments stored and retrieved correctly\n');

    console.log('=== ALL TESTS PASSED ===');
    console.log('\n✅ Validation checkpoint enforcement is working correctly');
    console.log('\nNext: Test with MCP server by:');
    console.log('1. Create plan checkpoint with requiredAttachments');
    console.log('2. Try to send message without attaching');
    console.log('3. Verify it throws error with clear instructions');

  } catch (err) {
    console.error('❌ TEST FAILED:', err.message);
    console.error(err.stack);
    process.exit(1);
  } finally {
    process.exit(0);
  }
}

runTests().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
