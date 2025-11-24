/**
 * Test the new ResponseDetectionEngine from Perplexity Labs
 */
import { ClaudeInterface } from './src/interfaces/chat-interface.js';
import { ResponseDetectionEngine } from './src/core/response-detection.js';

async function testClaudeDetection() {
  const claude = new ClaudeInterface();
  await claude.connect();

  console.log('Going to Claude Chat...');
  await claude.page.goto('https://claude.ai/new');
  await claude.page.waitForTimeout(2000);

  // Focus Chrome
  await claude.osa.focusApp('Google Chrome');
  await claude.page.waitForTimeout(500);

  // Type a simple message
  console.log('Typing test message...');
  const input = await claude.page.waitForSelector('[contenteditable="true"]', { timeout: 10000 });
  await input.click();
  await claude.page.waitForTimeout(200);

  await claude.osa.safeTypeLong('What is 2+2? Reply with just the number.');
  await claude.page.waitForTimeout(300);

  // Send
  console.log('Sending message...');
  await claude.osa.pressKey('return');

  // Create detection engine
  console.log('Starting response detection...');
  const detector = new ResponseDetectionEngine(claude.page, 'claude', {
    stabilityWindow: 2000,
    pollInterval: 500,
    debug: true
  });

  try {
    const result = await detector.detectCompletion();
    console.log('\n=== DETECTION RESULT ===');
    console.log(`Method: ${result.method}`);
    console.log(`Confidence: ${(result.confidence * 100).toFixed(0)}%`);
    console.log(`Detection Time: ${result.detectionTime}ms`);
    console.log(`Content Preview: ${result.content?.substring(0, 200)}...`);
    console.log('========================\n');
  } catch (err) {
    console.error('Detection failed:', err.message);
  }

  await claude.page.screenshot({ path: '/tmp/detection-test-result.png' });
  console.log('Screenshot: /tmp/detection-test-result.png');

  await claude.disconnect();
}

testClaudeDetection().catch(console.error);
