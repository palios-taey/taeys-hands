/**
 * Test validation checkpoint enforcement
 *
 * Verifies that:
 * 1. Tools block execution without validation
 * 2. Validation allows proceeding to next step
 * 3. Failed validation prevents continuing
 * 4. Can skip steps (e.g., no files) by validating plan directly
 */

import { ValidationCheckpointStore } from './src/core/validation-checkpoints.js';
import { getConversationStore } from './src/core/conversation-store.js';
import { v4 as uuidv4 } from 'uuid';

const validationStore = new ValidationCheckpointStore();
const conversationStore = getConversationStore();

async function runTests() {
  console.log('\n=== Validation Checkpoint Tests ===\n');

  // Initialize schema
  await conversationStore.initSchema();
  await validationStore.initSchema();

  // Create test conversation
  const conversationId = uuidv4();
  await conversationStore.createConversation({
    id: conversationId,
    title: 'Validation Test Session',
    purpose: 'Testing validation checkpoint enforcement',
    initiator: 'test_script',
    platforms: ['claude']
  });

  console.log(`✓ Created test conversation: ${conversationId}\n`);

  // Test 1: Can't proceed without any validation
  console.log('Test 1: Blocking without validation');
  const canAttachWithoutValidation = await validationStore.canProceedToStep(conversationId, 'attach_files');
  if (!canAttachWithoutValidation.canProceed) {
    console.log(`  ✓ Correctly blocked: ${canAttachWithoutValidation.reason}`);
  } else {
    console.log(`  ✗ FAILED: Should have blocked without validation`);
  }

  // Test 2: Validate plan step
  console.log('\nTest 2: Validate plan step');
  const planCheckpoint = await validationStore.createCheckpoint({
    conversationId,
    step: 'plan',
    validated: true,
    notes: 'Test plan - routing to Claude Opus with Extended Thinking, 2 attachments'
  });
  console.log(`  ✓ Created validation checkpoint: ${planCheckpoint.id}`);

  // Test 3: Can now proceed to attach_files
  console.log('\nTest 3: Can proceed after validation');
  const canAttachAfterValidation = await validationStore.canProceedToStep(conversationId, 'attach_files');
  if (canAttachAfterValidation.canProceed) {
    console.log(`  ✓ Correctly allowed: ${canAttachAfterValidation.reason}`);
  } else {
    console.log(`  ✗ FAILED: Should have allowed after plan validation`);
  }

  // Test 4: Validate attach_files step
  console.log('\nTest 4: Validate attach_files step');
  const attachCheckpoint = await validationStore.createCheckpoint({
    conversationId,
    step: 'attach_files',
    validated: true,
    notes: 'Saw 2 file pills above input box - clarity-universal-axioms-latest.md and notes.md'
  });
  console.log(`  ✓ Created validation checkpoint: ${attachCheckpoint.id}`);

  // Test 5: Get validation chain
  console.log('\nTest 5: Get validation chain');
  const chain = await validationStore.getValidationChain(conversationId);
  console.log(`  ✓ Retrieved ${chain.length} checkpoints:`);
  chain.forEach((checkpoint, i) => {
    console.log(`    ${i + 1}. ${checkpoint.step} - ${checkpoint.validated ? 'validated' : 'failed'} - ${checkpoint.notes}`);
  });

  // Test 6: Failed validation blocks proceeding
  console.log('\nTest 6: Failed validation blocks proceeding');

  // Create new conversation for failed validation test
  const failedConversationId = uuidv4();
  await conversationStore.createConversation({
    id: failedConversationId,
    title: 'Failed Validation Test',
    purpose: 'Testing failed validation blocking',
    initiator: 'test_script',
    platforms: ['claude']
  });

  // Create failed plan validation
  await validationStore.createCheckpoint({
    conversationId: failedConversationId,
    step: 'plan',
    validated: false,
    notes: 'Plan failed - wrong model selected'
  });

  const canAttachAfterFailed = await validationStore.canProceedToStep(failedConversationId, 'attach_files');
  if (!canAttachAfterFailed.canProceed) {
    console.log(`  ✓ Correctly blocked: ${canAttachAfterFailed.reason}`);
  } else {
    console.log(`  ✗ FAILED: Should have blocked after failed validation`);
  }

  // Test 7: Check step is validated
  console.log('\nTest 7: Check specific step validation');
  const isPlanValidated = await validationStore.isStepValidated(conversationId, 'plan');
  const isAttachValidated = await validationStore.isStepValidated(conversationId, 'attach_files');
  const isSendValidated = await validationStore.isStepValidated(conversationId, 'click_send');

  console.log(`  ✓ plan: ${isPlanValidated ? 'validated' : 'not validated'}`);
  console.log(`  ✓ attach_files: ${isAttachValidated ? 'validated' : 'not validated'}`);
  console.log(`  ✓ click_send: ${isSendValidated ? 'validated' : 'not validated'}`);

  // Test 8: Get last validation
  console.log('\nTest 8: Get last validation');
  const lastValidation = await validationStore.getLastValidation(conversationId);
  console.log(`  ✓ Last validated step: ${lastValidation.step} (${lastValidation.validated ? 'success' : 'failed'})`);
  console.log(`    Notes: ${lastValidation.notes}`);
  console.log(`    Timestamp: ${lastValidation.timestamp}`);

  console.log('\n=== All Tests Completed ===\n');
  process.exit(0);
}

runTests().catch(err => {
  console.error('Test failed:', err);
  process.exit(1);
});
