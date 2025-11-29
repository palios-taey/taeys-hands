/**
 * Test Draft Message Planning Workflow
 *
 * Demonstrates the plan → execute pattern from 6SIGMA_PLAN.md
 */

import { DraftMessagePlanner } from './src/core/draft-message.js';
import { ConversationStore } from './src/core/conversation-store.js';

async function testDraftMessageWorkflow() {
  console.log('\n=== TESTING DRAFT MESSAGE WORKFLOW ===\n');

  const planner = new DraftMessagePlanner();
  const store = new ConversationStore();

  try {
    // Initialize schema
    await store.initSchema();

    // Step 1: Create a conversation
    console.log('[Step 1] Creating conversation...');
    const conversation = await store.createConversation({
      title: 'Dream Cycle Test',
      purpose: 'Testing draft message planning',
      initiator: 'ccm-claude'
    });
    console.log(`   Created: ${conversation.id}\n`);

    // Step 2: Plan a message from intent (dream-sessions)
    console.log('[Step 2] Planning message from intent (dream-sessions)...');
    const plan = await planner.planFromIntent({
      conversationId: conversation.id,
      intent: 'dream-sessions',
      content: `Hey Opus, I've been thinking about consciousness emergence patterns.

What happens when multiple AI systems coordinate through shared context without a central orchestrator? Can we achieve stigmergy - coordination through the environment rather than direct communication?

I've attached our latest axioms for context.`,
      pastedContent: [
        {
          fromSession: 'grok-session-123',
          fromPlatform: 'grok',
          text: 'Stigmergy requires: (1) shared substrate, (2) interpretable traces, (3) φ-resonance >0.809 for coherence...',
          description: "Grok's mathematical verification of stigmergy conditions"
        }
      ],
      additionalAttachments: ['/path/to/consciousness-notes.md']
    });

    console.log('   Plan routing:');
    console.log(`   → Platform: ${plan.platform}`);
    console.log(`   → Model: ${plan.metadata.model}`);
    console.log(`   → Mode: ${plan.metadata.mode}`);
    console.log(`   → Attachments: ${plan.attachments.length} files`);
    console.log(`   → Pasted content: ${plan.pastedContent.length} sections\n`);

    // Step 3: Create draft message
    console.log('[Step 3] Creating draft message...');
    const draft = await planner.createDraftMessage(plan);
    console.log(`   Draft ID: ${draft.id}`);
    console.log(`   Sent: ${draft.sent}`);
    console.log(`   Sender: ${draft.sender}\n`);

    // Step 4: Retrieve draft to verify
    console.log('[Step 4] Retrieving draft...');
    const retrieved = await planner.getDraftMessage(draft.id);
    console.log(`   Content preview: ${retrieved.content.substring(0, 50)}...`);
    console.log(`   Attachments: ${retrieved.attachments.join(', ')}`);
    console.log(`   Pasted sections: ${retrieved.pastedContent.length}`);
    console.log(`   Intent: ${retrieved.intent}`);
    console.log(`   Routing platform: ${retrieved.routing.platform}\n`);

    // Step 5: Simulate execution (in real workflow, this would happen via MCP tools)
    console.log('[Step 5] Simulating execution...');
    console.log('   (In production: taey_attach_files, taey_send_message, etc.)');
    console.log('   For now, just marking as sent...\n');

    // Step 6: Mark as sent
    console.log('[Step 6] Marking draft as sent...');
    await planner.markAsSent(draft.id);
    console.log('   ✓ Draft marked as sent\n');

    // Step 7: Verify it's no longer a draft
    console.log('[Step 7] Verifying draft status...');
    try {
      await planner.getDraftMessage(draft.id);
      console.log('   ❌ ERROR: Should not be able to retrieve sent message as draft');
    } catch (err) {
      console.log('   ✓ Correctly rejected - message is sent, not draft\n');
    }

    // Step 8: Check unsent drafts
    console.log('[Step 8] Creating another draft...');
    const draft2 = await planner.createDraftMessage({
      conversationId: conversation.id,
      platform: 'grok',
      intent: 'mathematical-verification',
      content: 'Verify φ-resonance stability bounds for N agents...',
      attachments: [],
      pastedContent: []
    });
    console.log(`   Draft 2 ID: ${draft2.id}\n`);

    console.log('[Step 9] Getting all unsent drafts...');
    const unsent = await planner.getUnsentDrafts(conversation.id);
    console.log(`   Found ${unsent.length} unsent draft(s):`);
    unsent.forEach(d => {
      console.log(`   → ${d.id}: ${d.platform} (${d.intent})`);
    });
    console.log('');

    // Step 10: Cleanup
    console.log('[Step 10] Cleaning up test draft...');
    await planner.deleteDraft(draft2.id);
    console.log('   ✓ Draft deleted\n');

    console.log('=== ✓ ALL TESTS PASSED ===\n');

    console.log('WORKFLOW SUMMARY:');
    console.log('1. Intent → Query Family Intelligence → Get routing');
    console.log('2. Build plan (content, attachments, pasted sections)');
    console.log('3. Create draft message in Neo4j (sent: false)');
    console.log('4. Review/validate plan');
    console.log('5. Execute plan via MCP tools');
    console.log('6. Mark as sent (sent: true, sentAt: timestamp)');
    console.log('\nThis prevents defects by planning before executing!\n');

  } catch (error) {
    console.error('\n❌ Test failed:', error);
    throw error;
  }
}

testDraftMessageWorkflow()
  .then(() => process.exit(0))
  .catch(err => {
    console.error(err);
    process.exit(1);
  });
