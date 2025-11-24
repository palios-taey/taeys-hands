/**
 * Test ChatGPT mode selection
 */
import { ChatGPTInterface } from './src/interfaces/chat-interface.js';

async function testMode() {
  console.log('=== ChatGPT Mode Selection Test ===\n');
  const chatgpt = new ChatGPTInterface();

  try {
    await chatgpt.connect();
    console.log('Connected to ChatGPT\n');

    // Test mode selection - click the + button and select Deep research
    console.log('--- Testing Deep research mode ---');
    const result = await chatgpt.setMode('Deep research');
    console.log('Result:', result ? 'SUCCESS' : 'FAILED', '\n');

    await chatgpt.page.waitForTimeout(2000);

    console.log('Check /tmp/taey-chatgpt-mode-* for screenshots');

  } catch (error) {
    console.error('Test error:', error.message);
  } finally {
    await chatgpt.disconnect();
  }
}

testMode();
