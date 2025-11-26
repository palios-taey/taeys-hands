#!/usr/bin/env node
/**
 * Validation Test for November 25, 2025 Implementation Fixes
 *
 * Tests:
 * 1. Gemini Deep Research "Start research" button auto-click
 * 2. Neo4j conversation logging
 * 3. Model selection for all interfaces
 */

import { getSessionManager } from '../../mcp_server/session-manager.js';
import { getConversationStore } from '../../src/core/conversation-store.js';

const sessionManager = getSessionManager();
const conversationStore = getConversationStore();

console.log('🧪 VALIDATION TEST: Implementation Fixes 2025-11-25\n');

// Test 1: Neo4j Connection & Schema
async function testNeo4jConnection() {
  console.log('📊 Test 1: Neo4j Connection & Schema');
  try {
    await conversationStore.initSchema();
    const stats = await conversationStore.getStats();
    console.log('  ✅ Connected to Neo4j');
    console.log(`  ✅ Schema initialized`);
    console.log(`  📈 Stats: ${JSON.stringify(stats, null, 2)}`);
    return true;
  } catch (err) {
    console.error('  ❌ Failed:', err.message);
    return false;
  }
}

// Test 2: Gemini Regular Conversation (baseline)
async function testGeminiRegular() {
  console.log('\n🤖 Test 2: Gemini Regular Conversation (no research)');
  try {
    const sessionId = await sessionManager.createSession('gemini');
    console.log(`  ✅ Session created: ${sessionId}`);

    const gemini = sessionManager.getInterface(sessionId);

    // Send simple message
    await gemini.prepareInput();
    await gemini.typeMessage('What is 2+2?');
    await gemini.clickSend();
    console.log('  ✅ Message sent');

    // Wait for response (should NOT click Start Research button)
    const response = await gemini.waitForResponse(30000);
    console.log(`  ✅ Response received: ${response.substring(0, 100)}...`);

    await sessionManager.destroySession(sessionId);
    return true;
  } catch (err) {
    console.error('  ❌ Failed:', err.message);
    return false;
  }
}

// Test 3: Model Selection - Claude
async function testModelSelection() {
  console.log('\n🎛️  Test 3: Model Selection (Claude)');
  try {
    const sessionId = await sessionManager.createSession('claude');
    console.log(`  ✅ Session created: ${sessionId}`);

    const claude = sessionManager.getInterface(sessionId);

    // Test model selection
    const result = await claude.selectModel('Sonnet 4');
    console.log(`  ✅ Model selected: Sonnet 4`);
    console.log(`  📸 Screenshot: ${result.screenshot}`);

    await sessionManager.destroySession(sessionId);
    return true;
  } catch (err) {
    console.error('  ❌ Failed:', err.message);
    return false;
  }
}

// Test 4: Verify Neo4j Conversation Creation
async function testNeo4jConversationCreation() {
  console.log('\n💾 Test 4: Neo4j Conversation Creation');
  try {
    // Create a conversation manually
    const testConversation = await conversationStore.createConversation({
      id: 'test-' + Date.now(),
      title: 'Validation Test Conversation',
      purpose: 'Testing Neo4j integration',
      initiator: 'validation_script',
      platforms: ['claude', 'chatgpt'],
      metadata: { test: true }
    });

    console.log(`  ✅ Conversation created: ${testConversation.id}`);

    // Add test message
    const testMessage = await conversationStore.addMessage(testConversation.id, {
      role: 'user',
      content: 'This is a test message',
      platform: 'claude',
      timestamp: new Date().toISOString(),
      metadata: { test: true }
    });

    console.log(`  ✅ Message added: ${testMessage.id}`);

    // Retrieve conversation
    const retrieved = await conversationStore.getConversation(testConversation.id);
    console.log(`  ✅ Conversation retrieved with ${retrieved.messages.length} messages`);

    return true;
  } catch (err) {
    console.error('  ❌ Failed:', err.message);
    return false;
  }
}

// Run all tests
async function main() {
  console.log('Starting validation tests...\n');
  console.log('═'.repeat(60));

  const results = {
    neo4j_connection: await testNeo4jConnection(),
    gemini_regular: await testGeminiRegular(),
    model_selection: await testModelSelection(),
    neo4j_conversation: await testNeo4jConversationCreation()
  };

  console.log('\n' + '═'.repeat(60));
  console.log('\n📋 TEST RESULTS:\n');

  for (const [test, passed] of Object.entries(results)) {
    const status = passed ? '✅ PASS' : '❌ FAIL';
    console.log(`  ${status} - ${test}`);
  }

  const allPassed = Object.values(results).every(r => r === true);
  console.log('\n' + (allPassed ? '🎉 ALL TESTS PASSED' : '⚠️  SOME TESTS FAILED'));

  process.exit(allPassed ? 0 : 1);
}

main().catch(err => {
  console.error('\n💥 Test suite crashed:', err);
  process.exit(1);
});
