/**
 * Test systematic screenshot verification at every checkpoint
 * Sends a simple message to ChatGPT and captures screenshots at:
 * 1. Initial state
 * 2. Input focused
 * 3. Message typed
 * 4. Message sent
 * 5. During response polling (Fibonacci intervals)
 * 6. Final complete response
 */

import { ChatGPTInterface } from '../src/interfaces/chat-interface.js';

async function test() {
  console.log('='.repeat(60));
  console.log('SYSTEMATIC SCREENSHOT VERIFICATION TEST');
  console.log('='.repeat(60));
  console.log('\nThis test will capture screenshots at every major checkpoint');
  console.log('Watch for screenshot paths in the output\n');

  const chatgpt = new ChatGPTInterface();

  try {
    // Connect to Chrome
    console.log('[1/4] Connecting to Chrome via CDP...');
    await chatgpt.connect();
    console.log('  ✓ Connected\n');

    // Navigate to new chat
    console.log('[2/4] Navigating to fresh conversation...');
    await chatgpt.page.goto('https://chatgpt.com/');
    await chatgpt.page.waitForTimeout(2000);
    console.log('  ✓ Ready\n');

    // Send message with full screenshot verification
    console.log('[3/4] Sending message with systematic verification...');
    console.log('  Message: "What is 2+2? (Give a very short answer)"\n');

    const result = await chatgpt.sendMessage(
      'What is 2+2? (Give a very short answer)',
      {
        humanLike: true,
        waitForResponse: true,
        timeout: 60000 // 1 min for this simple question
      }
    );

    console.log('\n' + '='.repeat(60));
    console.log('TEST COMPLETE');
    console.log('='.repeat(60));
    console.log(`\nResponse received (${result.response.length} chars):`);
    console.log(`  "${result.response.substring(0, 100)}..."\n`);

    console.log('Screenshots captured:');
    console.log(`  1. Initial:  ${result.screenshots.initial}`);
    console.log(`  2. Focused:  ${result.screenshots.focused}`);
    console.log(`  3. Typed:    ${result.screenshots.typed}`);
    console.log(`  4. Sent:     ${result.screenshots.sent}`);
    console.log('  5. Polling:  (Fibonacci intervals in /tmp/taey-ChatGPT-*-t*.png)');
    console.log('  6. Complete: (in /tmp/taey-ChatGPT-*-complete.png)\n');

    // Disconnect
    console.log('[4/4] Disconnecting...');
    await chatgpt.disconnect();
    console.log('  ✓ Done\n');

    console.log('You can now review all screenshots in /tmp/ to verify each step');

  } catch (error) {
    console.error('\n❌ Test failed:', error.message);
    console.error(error.stack);
    await chatgpt.disconnect();
    process.exit(1);
  }
}

test();
