/**
 * Test ChatGPT file attachment
 */
import { ChatGPTInterface } from './src/interfaces/chat-interface.js';
import { writeFileSync } from 'fs';

async function testFileAttach() {
  console.log('=== ChatGPT File Attachment Test ===\n');

  // Create a simple test file
  const testFilePath = '/tmp/taey-test-file.txt';
  writeFileSync(testFilePath, 'This is a test file for Taey Hands file attachment testing.\nLine 2: Testing file upload to ChatGPT.\n');
  console.log(`Created test file: ${testFilePath}\n`);

  const chatgpt = new ChatGPTInterface();

  try {
    await chatgpt.connect();
    console.log('Connected to ChatGPT\n');

    // Click the + button to open menu
    console.log('--- Opening + menu ---');
    const plusButton = '[data-testid="composer-plus-btn"]';
    await chatgpt.page.click(plusButton);
    await chatgpt.page.waitForTimeout(500);

    // Take screenshot of menu
    const menuScreenshot = `/tmp/taey-chatgpt-attach-menu-${Date.now()}.png`;
    await chatgpt.screenshot(menuScreenshot);
    console.log(`Screenshot: ${menuScreenshot}`);

    // Look for file input element (hidden input that gets triggered)
    const fileInputExists = await chatgpt.page.evaluate(() => {
      const inputs = document.querySelectorAll('input[type="file"]');
      return inputs.length;
    });
    console.log(`File inputs found: ${fileInputExists}`);

    // Try to find and interact with the file attachment option
    // First, let's click "Add photos & files"
    console.log('\n--- Clicking "Add photos & files" ---');
    try {
      await chatgpt.page.click('text="Add photos & files"');
      await chatgpt.page.waitForTimeout(1000);

      // After clicking, there should be a file input we can use
      const fileInput = await chatgpt.page.$('input[type="file"]');
      if (fileInput) {
        console.log('Found file input element');
        // Set the file
        await fileInput.setInputFiles(testFilePath);
        console.log('File set on input');
        await chatgpt.page.waitForTimeout(1000);

        // Screenshot after file selected
        const afterScreenshot = `/tmp/taey-chatgpt-attach-after-${Date.now()}.png`;
        await chatgpt.screenshot(afterScreenshot);
        console.log(`Screenshot after: ${afterScreenshot}`);
      } else {
        console.log('No file input found after clicking');
      }
    } catch (e) {
      console.log(`Click error: ${e.message}`);
    }

    // Take final screenshot
    const finalScreenshot = `/tmp/taey-chatgpt-attach-final-${Date.now()}.png`;
    await chatgpt.screenshot(finalScreenshot);
    console.log(`Final screenshot: ${finalScreenshot}`);

    console.log('\n=== Test Complete ===');

  } catch (error) {
    console.error('Test error:', error.message);
  } finally {
    await chatgpt.disconnect();
  }
}

testFileAttach();
