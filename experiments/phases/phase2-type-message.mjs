/**
 * PHASE 2: Type Message
 * - Connect to existing CDP session
 * - Type message into focused input
 * - Capture screenshot
 * - Output JSON with screenshot path
 *
 * Usage: node phase2-type-message.mjs <ai-name> <session-id> <message>
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
  const message = process.argv[4];

  if (!aiMap[aiName]) {
    console.error(`Unknown AI: ${aiName}`);
    console.error(`Available: ${Object.keys(aiMap).join(', ')}`);
    process.exit(1);
  }

  if (!message) {
    console.error('Message required as 3rd argument');
    process.exit(1);
  }

  const InterfaceClass = aiMap[aiName];
  const ai = new InterfaceClass();

  try {
    // Connect to existing CDP session
    await ai.connect();

    // Run atomic action: type message
    const result = await ai.typeMessage(message, {
      sessionId,
      humanLike: true,
      mixedContent: true // Auto-detect and paste AI quotes
    });

    // Output JSON result
    console.log(JSON.stringify({
      phase: 2,
      action: 'typeMessage',
      success: true,
      messageLength: message.length,
      ...result
    }, null, 2));

    await ai.disconnect();
  } catch (error) {
    console.error(JSON.stringify({
      phase: 2,
      action: 'typeMessage',
      success: false,
      error: error.message
    }, null, 2));
    await ai.disconnect();
    process.exit(1);
  }
}

run();
