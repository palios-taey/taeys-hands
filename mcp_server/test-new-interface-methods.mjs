#!/usr/bin/env node
/**
 * Test script for newly added interface methods
 * Tests selectModel() and setMode() across all interfaces
 */

import { ClaudeInterface, ChatGPTInterface, GeminiInterface, GrokInterface, PerplexityInterface } from '../src/interfaces/chat-interface.js';

const DELAY = 2000; // 2 second delay between tests

function log(message, level = 'info') {
  const timestamp = new Date().toISOString();
  const prefix = level === 'error' ? '❌' : level === 'success' ? '✅' : 'ℹ️';
  console.log(`${prefix} [${timestamp}] ${message}`);
}

async function testChatGPT() {
  log('=== Testing ChatGPT Interface ===');
  const chatgpt = new ChatGPTInterface();

  try {
    await chatgpt.connect();
    log('Connected to ChatGPT');

    // Start a new conversation
    await chatgpt.newConversation();
    await chatgpt.page.waitForTimeout(DELAY);

    // Test selectModel()
    log('Testing selectModel("Instant")...');
    const modelResult = await chatgpt.selectModel("Instant");
    log(`Model selected: ${modelResult.modelName}`, 'success');
    log(`Screenshot: ${modelResult.screenshot}`);
    await chatgpt.page.waitForTimeout(DELAY);

    // Test setMode()
    log('Testing setMode("Deep research")...');
    const modeResult = await chatgpt.setMode("Deep research");
    log(`Mode set: ${modeResult.mode}`, 'success');
    log(`Screenshot: ${modeResult.screenshot}`);

    await chatgpt.disconnect();
    log('ChatGPT tests complete', 'success');
    return true;

  } catch (error) {
    log(`ChatGPT test failed: ${error.message}`, 'error');
    await chatgpt.disconnect();
    return false;
  }
}

async function testGemini() {
  log('\n=== Testing Gemini Interface ===');
  const gemini = new GeminiInterface();

  try {
    await gemini.connect();
    log('Connected to Gemini');

    // Start a new conversation
    await gemini.newConversation();
    await gemini.page.waitForTimeout(DELAY);

    // Test selectModel()
    log('Testing selectModel("Thinking")...');
    const modelResult = await gemini.selectModel("Thinking");
    log(`Model selected: ${modelResult.modelName}`, 'success');
    log(`Screenshot: ${modelResult.screenshot}`);
    await gemini.page.waitForTimeout(DELAY);

    // Test setMode()
    log('Testing setMode("Deep Research")...');
    const modeResult = await gemini.setMode("Deep Research");
    log(`Mode set: ${modeResult.mode}`, 'success');
    log(`Screenshot: ${modeResult.screenshot}`);

    await gemini.disconnect();
    log('Gemini tests complete', 'success');
    return true;

  } catch (error) {
    log(`Gemini test failed: ${error.message}`, 'error');
    await gemini.disconnect();
    return false;
  }
}

async function testGrok() {
  log('\n=== Testing Grok Interface ===');
  const grok = new GrokInterface();

  try {
    await grok.connect();
    log('Connected to Grok');

    // Start a new conversation
    await grok.newConversation();
    await grok.page.waitForTimeout(DELAY);

    // Test selectModel()
    log('Testing selectModel("Grok 4.1")...');
    const modelResult = await grok.selectModel("Grok 4.1");
    log(`Model selected: ${modelResult.modelName}`, 'success');
    log(`Screenshot: ${modelResult.screenshot}`);

    await grok.disconnect();
    log('Grok tests complete', 'success');
    return true;

  } catch (error) {
    log(`Grok test failed: ${error.message}`, 'error');
    await grok.disconnect();
    return false;
  }
}

async function testPerplexity() {
  log('\n=== Testing Perplexity Interface ===');
  const perplexity = new PerplexityInterface();

  try {
    await perplexity.connect();
    log('Connected to Perplexity');

    // Start a new conversation
    await perplexity.newConversation();
    await perplexity.page.waitForTimeout(DELAY);

    // Test setMode()
    log('Testing setMode("research")...');
    const modeResult = await perplexity.setMode("research");
    log(`Mode set: ${modeResult.mode}`, 'success');
    log(`Screenshot: ${modeResult.screenshot}`);

    await perplexity.disconnect();
    log('Perplexity tests complete', 'success');
    return true;

  } catch (error) {
    log(`Perplexity test failed: ${error.message}`, 'error');
    await perplexity.disconnect();
    return false;
  }
}

async function testClaude() {
  log('\n=== Testing Claude Interface ===');
  const claude = new ClaudeInterface();

  try {
    await claude.connect();
    log('Connected to Claude');

    // Start a new conversation
    await claude.newConversation();
    await claude.page.waitForTimeout(DELAY);

    // Test selectModel()
    log('Testing selectModel("Opus 4.5")...');
    const modelResult = await claude.selectModel("Opus 4.5");
    log(`Model selected: ${modelResult.modelName}`, 'success');
    log(`Screenshot: ${modelResult.screenshot}`);

    await claude.disconnect();
    log('Claude tests complete', 'success');
    return true;

  } catch (error) {
    log(`Claude test failed: ${error.message}`, 'error');
    await claude.disconnect();
    return false;
  }
}

async function main() {
  log('Starting interface method tests...\n');

  const results = {
    claude: false,
    chatgpt: false,
    gemini: false,
    grok: false,
    perplexity: false
  };

  // Run tests sequentially to avoid browser conflicts
  results.claude = await testClaude();
  await new Promise(resolve => setTimeout(resolve, 3000)); // 3s gap between interfaces

  results.chatgpt = await testChatGPT();
  await new Promise(resolve => setTimeout(resolve, 3000));

  results.gemini = await testGemini();
  await new Promise(resolve => setTimeout(resolve, 3000));

  results.grok = await testGrok();
  await new Promise(resolve => setTimeout(resolve, 3000));

  results.perplexity = await testPerplexity();

  // Print summary
  log('\n=== Test Summary ===');
  log(`Claude:  ${results.claude ? '✅ PASS' : '❌ FAIL'}`);
  log(`ChatGPT: ${results.chatgpt ? '✅ PASS' : '❌ FAIL'}`);
  log(`Gemini:  ${results.gemini ? '✅ PASS' : '❌ FAIL'}`);
  log(`Grok:    ${results.grok ? '✅ PASS' : '❌ FAIL'}`);
  log(`Perplexity: ${results.perplexity ? '✅ PASS' : '❌ FAIL'}`);

  const allPassed = Object.values(results).every(r => r === true);
  if (allPassed) {
    log('\n🎉 All tests passed!', 'success');
    process.exit(0);
  } else {
    log('\n⚠️  Some tests failed', 'error');
    process.exit(1);
  }
}

main().catch(error => {
  log(`Fatal error: ${error.message}`, 'error');
  console.error(error);
  process.exit(1);
});
