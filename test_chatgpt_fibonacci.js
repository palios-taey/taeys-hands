#!/usr/bin/env node

/**
 * Test ChatGPT E2E with Fibonacci polling
 * Tests: attach file → send message → response detection → extraction
 */

import { getSessionManager } from './mcp_server/dist/session-manager.js';
import { ResponseDetectionEngine } from './src/core/response-detection.js';
import { promises as fs } from 'fs';

async function testChatGPTFibonacci() {
  console.log('\n=== ChatGPT Fibonacci Polling Test ===\n');

  const sessionManager = getSessionManager();
  let sessionId;

  try {
    // 1. Create session
    console.log('1. Creating ChatGPT session...');
    sessionId = await sessionManager.createSession('chatgpt');
    console.log(`   ✓ Session created: ${sessionId}\n`);

    // 2. Connect
    console.log('2. Connecting to ChatGPT...');
    const chatInterface = sessionManager.getInterface(sessionId);
    await chatInterface.connect({ sessionId, newSession: true });
    console.log('   ✓ Connected\n');

    // 3. Attach test file
    console.log('3. Attaching test file...');
    const testFilePath = '/tmp/fibonacci-test.txt';
    await fs.writeFile(testFilePath, 'This is a test file for Fibonacci polling validation. Please read it and confirm what it says.');

    await chatInterface.attachFile([testFilePath]);
    console.log('   ✓ File attached\n');

    // 4. Send message
    console.log('4. Typing and sending message...');
    const testMessage = 'Please read the attached file and tell me what it says. Be brief - one sentence only.';

    await chatInterface.prepareInput();
    await chatInterface.typeMessage(testMessage);
    await chatInterface.clickSend();
    console.log('   ✓ Message sent\n');

    // 5. Wait for response using Fibonacci polling
    console.log('5. Waiting for response (Fibonacci polling)...');
    const session = sessionManager.getSession(sessionId);
    const detector = new ResponseDetectionEngine(
      chatInterface.page,
      session.interfaceType,
      { debug: true }
    );

    const startTime = Date.now();
    const detectionResult = await detector.detectCompletion();
    const detectionTime = Date.now() - startTime;

    console.log(`   ✓ Response detected!`);
    console.log(`     Method: ${detectionResult.method}`);
    console.log(`     Confidence: ${detectionResult.confidence * 100}%`);
    console.log(`     Detection time: ${detectionTime}ms`);
    console.log(`     Response length: ${detectionResult.content.length} chars`);
    if (detectionResult.fibonacciIndex !== undefined) {
      console.log(`     Fibonacci index: ${detectionResult.fibonacciIndex}`);
    }
    console.log(`\n     Response: ${detectionResult.content.substring(0, 200)}...\n`);

    // 6. Results
    if (detectionResult.content.length > 0) {
      console.log('✅ SUCCESS: Fibonacci polling working correctly!');
    } else {
      console.log('❌ FAILURE: Empty response extracted');
    }

  } catch (error) {
    console.error('\n❌ TEST FAILED:', error.message);
    console.error(error.stack);
  } finally {
    if (sessionId) {
      console.log('\n6. Cleaning up...');
      try {
        await sessionManager.destroySession(sessionId);
        console.log('   ✓ Session destroyed\n');
      } catch (err) {
        console.error('   ⚠ Cleanup error:', err.message);
      }
    }
  }
}

testChatGPTFibonacci();
