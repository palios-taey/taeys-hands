/**
 * PHASE 0b: Attach File
 * - Connect to existing CDP session
 * - Click attach button
 * - Use Cmd+Shift+G to navigate to file
 * - Capture screenshot
 * - Output JSON with screenshot path
 *
 * Usage: node phase0b-attach-file.mjs <ai-name> <session-id> <file-path>
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
  const filePath = process.argv[4];

  if (!aiMap[aiName]) {
    console.error(`Unknown AI: ${aiName}`);
    console.error(`Available: ${Object.keys(aiMap).join(', ')}`);
    process.exit(1);
  }

  if (!filePath) {
    console.error('File path required as 3rd argument');
    process.exit(1);
  }

  const InterfaceClass = aiMap[aiName];
  const ai = new InterfaceClass();

  try {
    // Connect to existing CDP session
    await ai.connect();

    // Run atomic action: attach file
    const result = await ai.attachFile(filePath, { sessionId });

    // Output JSON result
    console.log(JSON.stringify({
      phase: '0b',
      action: 'attachFile',
      success: true,
      ...result
    }, null, 2));

    await ai.disconnect();
  } catch (error) {
    console.error(JSON.stringify({
      phase: '0b',
      action: 'attachFile',
      success: false,
      error: error.message
    }, null, 2));
    await ai.disconnect();
    process.exit(1);
  }
}

run();
