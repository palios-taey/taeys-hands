/**
 * PHASE 4: Wait for Response
 * - Connect to existing CDP session
 * - Wait for AI response with Fibonacci polling
 * - Capture screenshots at intervals
 * - Output JSON with response text and screenshots
 *
 * Usage: node phase4-wait-response.mjs <ai-name> <session-id> [timeout-seconds]
 */

import {
  ClaudeInterface,
  ChatGPTInterface,
  GeminiInterface,
  GrokInterface,
  PerplexityInterface
} from '../../src/interfaces/chat-interface.js';

const aiMap = {
  claude: ClaudeInterface,
  chatgpt: ChatGPTInterface,
  gemini: GeminiInterface,
  grok: GrokInterface,
  perplexity: PerplexityInterface
};

async function run() {
  const aiName = process.argv[2] || 'perplexity';
  const sessionId = process.argv[3] || Date.now();
  const timeoutSeconds = parseInt(process.argv[4]) || 180; // 3 min default

  if (!aiMap[aiName]) {
    console.error(`Unknown AI: ${aiName}`);
    console.error(`Available: ${Object.keys(aiMap).join(', ')}`);
    process.exit(1);
  }

  const InterfaceClass = aiMap[aiName];
  const ai = new InterfaceClass();

  try {
    // Connect to existing CDP session
    await ai.connect();

    console.log(`Waiting for ${aiName} response (timeout: ${timeoutSeconds}s)...`);

    // Run atomic action: wait for response
    const response = await ai.waitForResponse(timeoutSeconds * 1000, {
      sessionId,
      screenshots: true
    });

    // Output JSON result
    console.log(JSON.stringify({
      phase: 4,
      action: 'waitForResponse',
      success: true,
      responseLength: response.length,
      response: response.substring(0, 500) + '...', // First 500 chars
      fullResponse: response,
      screenshotsPattern: `/tmp/taey-${aiName}-${sessionId}-*.png`
    }, null, 2));

    await ai.disconnect();
  } catch (error) {
    console.error(JSON.stringify({
      phase: 4,
      action: 'waitForResponse',
      success: false,
      error: error.message
    }, null, 2));
    await ai.disconnect();
    process.exit(1);
  }
}

run();
