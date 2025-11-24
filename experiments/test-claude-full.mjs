/**
 * Full test of Claude interface with human-like file attachment
 */

import { ClaudeInterface } from './src/interfaces/chat-interface.js';

async function testClaudeFull() {
  console.log('=== Claude Full Test with File Attachment ===\n');

  const claude = new ClaudeInterface();

  try {
    // Connect
    console.log('1. Connecting to Claude...');
    await claude.connect();

    // Check login
    console.log('2. Checking login status...');
    const loggedIn = await claude.isLoggedIn();
    console.log(`   Logged in: ${loggedIn}`);

    if (!loggedIn) {
      console.log('ERROR: Not logged in to Claude');
      return;
    }

    // Test file to attach
    const testFile = '/Users/jesselarose/taey-hands/THE_CHARTER.md';

    // Attach file using human-like method
    console.log(`3. Attaching file (human-like): ${testFile}`);
    const attached = await claude.attachFileHumanLike(testFile);
    console.log(`   Attached: ${attached}`);

    if (!attached) {
      console.log('ERROR: Failed to attach file');
      return;
    }

    // Send message with the attachment
    console.log('4. Sending message...');
    const message = 'Hey Claude Chat, CCM here testing the file attachment. Can you confirm you received THE_CHARTER.md? Just respond with "File received: [filename]" and nothing else.';

    const response = await claude.sendMessage(message, { timeout: 60000 });

    console.log('\n=== Response ===');
    console.log(response);
    console.log('================\n');

    // Take final screenshot
    const screenshot = `/tmp/taey-claude-test-${Date.now()}.png`;
    await claude.screenshot(screenshot);
    console.log(`Screenshot: ${screenshot}`);

    console.log('\nSUCCESS: Full test completed!');

  } catch (e) {
    console.error('ERROR:', e.message);
    console.error(e.stack);
  } finally {
    await claude.disconnect();
  }
}

testClaudeFull().catch(console.error);
