/**
 * Test ChatGPT file attachment - clean method (no Finder dialog)
 */
import { ChatGPTInterface } from './src/interfaces/chat-interface.js';
import { writeFileSync } from 'fs';

async function testCleanFileAttach() {
  console.log('=== ChatGPT Clean File Attachment Test ===\n');

  // Create a simple test file
  const testFilePath = '/tmp/taey-clean-test-file.txt';
  writeFileSync(testFilePath, 'Clean file attachment test for Taey Hands.\nNo Finder dialog should appear.\n');
  console.log(`Created test file: ${testFilePath}\n`);

  const chatgpt = new ChatGPTInterface();

  try {
    await chatgpt.connect();
    console.log('Connected to ChatGPT\n');

    // Navigate to fresh chat
    console.log('--- Navigating to fresh chat ---');
    await chatgpt.page.goto('https://chatgpt.com/', { waitUntil: 'networkidle', timeout: 30000 });
    await chatgpt.page.waitForTimeout(2000);

    // Use the clean attachFile method
    console.log('--- Attaching file (clean method) ---');
    const result = await chatgpt.attachFile(testFilePath);
    console.log(`Attach result: ${result ? 'SUCCESS' : 'FAILED'}\n`);

    // Try typing a message
    console.log('--- Typing message ---');
    await chatgpt.page.fill('#prompt-textarea', 'Describe the file I just uploaded');
    await chatgpt.page.waitForTimeout(500);

    // Screenshot before send
    const beforeSendScreenshot = `/tmp/taey-chatgpt-clean-before-send-${Date.now()}.png`;
    await chatgpt.screenshot(beforeSendScreenshot);
    console.log(`Screenshot before send: ${beforeSendScreenshot}`);

    console.log('\n=== Test Complete ===');
    console.log('If no Finder dialog appeared and the file is shown in the chat input,');
    console.log('the clean attachment method works!');

  } catch (error) {
    console.error('Test error:', error.message);
  } finally {
    await chatgpt.disconnect();
  }
}

testCleanFileAttach();
