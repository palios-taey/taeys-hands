/**
 * PHASE 1: Prepare Input
 * - Connect to existing CDP session
 * - Bring tab to front
 * - Focus input field
 * - Capture screenshot
 * - Output JSON with screenshot path
 *
 * Usage: node phase1-prepare-input.mjs <ai-name> <session-id>
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

    // Run atomic action: prepare input
    const result = await ai.prepareInput({ sessionId });

    // Output JSON result
    console.log(JSON.stringify({
      phase: 1,
      action: 'prepareInput',
      success: true,
      ...result
    }, null, 2));

    await ai.disconnect();
  } catch (error) {
    console.error(JSON.stringify({
      phase: 1,
      action: 'prepareInput',
      success: false,
      error: error.message
    }, null, 2));
    await ai.disconnect();
    process.exit(1);
  }
}

run();
