/**
 * PHASE 0a: Enable Research/Pro Mode
 * - Connect to existing CDP session
 * - Click Pro Search / Research mode button
 * - Capture screenshot
 * - Output JSON with screenshot path
 *
 * Usage: node phase0a-enable-research-mode.mjs <ai-name> <session-id> [selector]
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
  const selector = process.argv[4]; // Optional custom selector

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

    // Run atomic action: enable research mode
    const result = await ai.enableResearchMode({
      sessionId,
      selector // Will use default if not provided
    });

    // Output JSON result
    console.log(JSON.stringify({
      phase: '0a',
      action: 'enableResearchMode',
      success: true,
      ...result
    }, null, 2));

    await ai.disconnect();
  } catch (error) {
    console.error(JSON.stringify({
      phase: '0a',
      action: 'enableResearchMode',
      success: false,
      error: error.message
    }, null, 2));
    await ai.disconnect();
    process.exit(1);
  }
}

run();
