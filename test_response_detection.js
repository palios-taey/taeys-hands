#!/usr/bin/env node

/**
 * Test script for ResponseDetectionEngine integration in MCP server
 *
 * Tests:
 * 1. Connect to Claude
 * 2. Send message with waitForResponse: true
 * 3. Verify response is detected, extracted, and returned
 * 4. Verify response is saved to Neo4j
 */

import { getSessionManager } from './mcp_server/dist/session-manager.js';
import { getConversationStore } from './src/core/conversation-store.js';
import { ResponseDetectionEngine } from './src/core/response-detection.js';

async function testResponseDetection() {
  console.log('\n=== Testing ResponseDetectionEngine Integration ===\n');

  const sessionManager = getSessionManager();
  const conversationStore = getConversationStore();

  let sessionId;

  try {
    // Initialize schema
    console.log('1. Initializing ConversationStore schema...');
    await conversationStore.initSchema();
    console.log('   ✓ Schema initialized\n');

    // Create session
    console.log('2. Creating Claude session...');
    sessionId = await sessionManager.createSession('claude');
    console.log(`   ✓ Session created: ${sessionId}\n`);

    // Connect
    console.log('3. Connecting to Claude...');
    const chatInterface = sessionManager.getInterface(sessionId);
    await chatInterface.connect({ sessionId });
    console.log('   ✓ Connected\n');

    // Create conversation in Neo4j
    console.log('4. Creating conversation in Neo4j...');
    await conversationStore.createConversation({
      id: sessionId,
      title: 'Test Response Detection',
      purpose: 'Testing ResponseDetectionEngine integration',
      initiator: 'test_script',
      platforms: ['claude'],
      platform: 'claude',
      sessionId: sessionId,
      metadata: { test: true }
    });
    console.log('   ✓ Conversation created\n');

    // Send test message
    console.log('5. Sending test message...');
    const testMessage = 'What is 2+2? Please answer in one sentence.';

    // Log user message
    await conversationStore.addMessage(sessionId, {
      role: 'user',
      content: testMessage,
      platform: 'claude',
      timestamp: new Date().toISOString(),
      metadata: { source: 'test_script' }
    });

    // Send message
    await chatInterface.prepareInput();
    await chatInterface.typeMessage(testMessage);
    await chatInterface.clickSend();
    console.log('   ✓ Message sent\n');

    // Wait for response using ResponseDetectionEngine
    console.log('6. Waiting for response (using ResponseDetectionEngine)...');
    const session = sessionManager.getSession(sessionId);
    const detector = new ResponseDetectionEngine(
      chatInterface.page,
      session.interfaceType,
      { debug: true }
    );

    const detectionResult = await detector.detectCompletion();
    console.log(`   ✓ Response detected!`);
    console.log(`     Method: ${detectionResult.method}`);
    console.log(`     Confidence: ${detectionResult.confidence * 100}%`);
    console.log(`     Detection time: ${detectionResult.detectionTime}ms`);
    console.log(`     Response length: ${detectionResult.content.length} chars\n`);

    // Log assistant response
    console.log('7. Saving response to Neo4j...');
    await conversationStore.addMessage(sessionId, {
      role: 'assistant',
      content: detectionResult.content,
      platform: 'claude',
      timestamp: new Date().toISOString(),
      metadata: {
        source: 'test_script',
        detectionMethod: detectionResult.method,
        detectionConfidence: detectionResult.confidence,
        detectionTime: detectionResult.detectionTime
      }
    });
    console.log('   ✓ Response saved\n');

    // Verify in Neo4j
    console.log('8. Verifying messages in Neo4j...');
    const messages = await conversationStore.getMessages(sessionId);
    console.log(`   ✓ Found ${messages.length} messages:`);
    messages.forEach((msg, idx) => {
      console.log(`     ${idx + 1}. [${msg.role}] ${msg.content.substring(0, 60)}...`);
    });
    console.log();

    // Display response
    console.log('9. Response content:');
    console.log('   ─────────────────────────────────────────');
    console.log(`   ${detectionResult.content}`);
    console.log('   ─────────────────────────────────────────\n');

    console.log('✓ Test completed successfully!\n');

  } catch (error) {
    console.error('✗ Test failed:', error.message);
    console.error(error.stack);
  } finally {
    // Cleanup
    if (sessionId) {
      console.log('Cleaning up...');
      try {
        await sessionManager.destroySession(sessionId);
        console.log('✓ Session destroyed\n');
      } catch (err) {
        console.error('Warning: Failed to destroy session:', err.message);
      }
    }
  }
}

// Run test
testResponseDetection().catch(console.error);
