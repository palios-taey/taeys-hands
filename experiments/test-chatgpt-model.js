/**
 * Test ChatGPT model selection
 */
import { ChatGPTInterface } from './src/interfaces/chat-interface.js';

async function testChatGPTModel() {
  console.log('=== ChatGPT Model Selection Test ===\n');

  const chatgpt = new ChatGPTInterface();

  try {
    // Connect using the interface's connect method
    await chatgpt.connect();
    console.log('Connected to ChatGPT\n');

    // Test 1: Select 5.1 Pro (should be default or in main list)
    console.log('--- Test 1: Select ChatGPT 5.1 Pro ---');
    const result1 = await chatgpt.setModel('ChatGPT');
    console.log(`Result: ${result1 ? 'SUCCESS' : 'FAILED'}\n`);

    await chatgpt.page.waitForTimeout(2000);

    // Test 2: Select 4o (Legacy model)
    console.log('--- Test 2: Select GPT-4o (Legacy) ---');
    const result2 = await chatgpt.setModel('GPT-4o', true);
    console.log(`Result: ${result2 ? 'SUCCESS' : 'FAILED'}\n`);

    await chatgpt.page.waitForTimeout(2000);

    // Test 3: Send a message with screenshots
    console.log('--- Test 3: Send message and capture response ---');
    const response = await chatgpt.sendMessage('Model selection test - what model are you?');
    console.log(`\nResponse received (${response?.length || 0} chars):`);
    console.log(response?.slice(0, 500) || 'No response');

    console.log('\n=== Test Complete ===');
    console.log('Check /tmp/taey-chatgpt-* for screenshots');

  } catch (error) {
    console.error('Test error:', error);
  } finally {
    await chatgpt.disconnect();
  }
}

testChatGPTModel();
