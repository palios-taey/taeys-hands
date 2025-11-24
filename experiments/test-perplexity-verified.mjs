/**
 * Perplexity test with manual verification gates
 * After each screenshot, the script pauses so Claude can verify before proceeding
 */

import { PerplexityInterface } from '../src/interfaces/chat-interface.js';
import readline from 'readline';

const sessionId = Date.now();

function prompt(question) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });
  return new Promise(resolve => {
    rl.question(question, answer => {
      rl.close();
      resolve(answer);
    });
  });
}

async function test() {
  console.log('='.repeat(70));
  console.log('PERPLEXITY VERIFIED TEST');
  console.log('Each phase will pause for Claude to verify screenshot');
  console.log('='.repeat(70));

  const perplexity = new PerplexityInterface();

  try {
    // PHASE 1: Connect and navigate
    console.log('\n[PHASE 1] Connecting and navigating...');
    await perplexity.connect();
    console.log('  ✓ Connected to Chrome\n');

    await perplexity.page.goto('https://www.perplexity.ai/search/perplexity-clarity-you-are-als-kyFxzJXbQJyH2ZB.BBcuFQ?sm=d');
    console.log('  ✓ Navigated to URL');

    // CRITICAL: Bring tab to front FIRST
    await perplexity.page.bringToFront();
    console.log('  ✓ Brought tab to front');
    await perplexity.page.waitForTimeout(2000);

    const ss1 = `/tmp/perp-${sessionId}-01-loaded.png`;
    await perplexity.screenshot(ss1);
    console.log(`\n  📸 Screenshot: ${ss1}`);
    console.log('  → Claude: Please READ this screenshot to verify Perplexity loaded correctly');
    await prompt('  Press Enter when Claude has verified... ');

    // PHASE 2: Enable Pro Search
    console.log('\n[PHASE 2] Attempting Pro Search...');
    try {
      const proBtn = await perplexity.page.waitForSelector('button[aria-label*="Pro"]', { timeout: 3000 }).catch(() => null);
      if (proBtn) {
        await proBtn.click();
        console.log('  ✓ Pro Search enabled');
        await perplexity.page.waitForTimeout(500);
      } else {
        console.log('  ⓘ Pro Search toggle not found');
      }
    } catch (e) {
      console.log(`  ⓘ Pro Search: ${e.message}`);
    }

    const ss2 = `/tmp/perp-${sessionId}-02-pro-mode.png`;
    await perplexity.screenshot(ss2);
    console.log(`\n  📸 Screenshot: ${ss2}`);
    console.log('  → Claude: Verify Pro Search state');
    await prompt('  Press Enter when Claude has verified... ');

    // PHASE 3: Focus input
    console.log('\n[PHASE 3] Focusing input...');
    const input = await perplexity.page.waitForSelector(perplexity.selectors.chatInput, { timeout: 10000 });
    await input.click();
    await perplexity.page.waitForTimeout(300);
    console.log('  ✓ Input focused');

    const ss3 = `/tmp/perp-${sessionId}-03-focused.png`;
    await perplexity.screenshot(ss3);
    console.log(`\n  📸 Screenshot: ${ss3}`);
    console.log('  → Claude: Verify input is focused (cursor visible)');
    await prompt('  Press Enter when Claude has verified... ');

    // PHASE 4: Type message
    console.log('\n[PHASE 4] Typing message...');
    const message = `I'm building browser automation for AI chat interfaces and facing a response detection challenge.

**The Problem:**
Sometimes AI responses complete server-side but the browser doesn't visually update until refreshed. This happens frequently with Gemini and occasionally with Grok.

**What I've Tried:**
From testing with Claude and ChatGPT:
CLAUDE: "DOM polling with Fibonacci backoff works well - responses appear in real-time as they stream"
CHATGPT: "Content stability detection (2 consecutive identical reads) reliably catches completion"

But Gemini shows a different pattern - the response exists in the server but the browser DOM doesn't reflect it.

**Question:**
What's the most robust approach to detect true response completion vs stale browser state? Should I:

1. Monitor browser notifications via CDP (if accessible)
2. Implement hybrid detection (DOM + visual screenshot analysis)
3. Add periodic page refresh cycles
4. Use MutationObserver for more granular DOM monitoring
5. Something else?

Context: Using Puppeteer CDP for automation, need to maintain human-like appearance.`;

    console.log(`  Message: ${message.length} chars`);
    console.log('  ⚠️  Keyboard will be locked during typing (~3-5 sec)\n');

    await perplexity.osa.focusApp('Google Chrome');
    await perplexity.page.waitForTimeout(300);
    await perplexity.osa.typeWithMixedContent(message);
    await perplexity.page.waitForTimeout(1000);
    console.log('  ✓ Message typed');

    const ss4 = `/tmp/perp-${sessionId}-04-typed.png`;
    await perplexity.screenshot(ss4);
    console.log(`\n  📸 Screenshot: ${ss4}`);
    console.log('  → Claude: Verify full message is visible in input');
    await prompt('  Press Enter when Claude has verified... ');

    // PHASE 5: Attach file
    console.log('\n[PHASE 5] Attaching file...');
    const filePath = '/Users/REDACTED/taey-hands/docs/AI_INTERFACES.md';

    try {
      const attachBtn = await perplexity.page.waitForSelector('button[data-testid="attach-files-button"]', { timeout: 5000 }).catch(() => null);
      if (attachBtn) {
        await attachBtn.click();
        await perplexity.page.waitForTimeout(500);

        const localFiles = await perplexity.page.waitForSelector('div[role="menuitem"]:has-text("Local files")', { timeout: 3000 }).catch(() => null);
        if (localFiles) {
          await localFiles.click();
          await perplexity.page.waitForTimeout(1000);

          const fileInput = await perplexity.page.waitForSelector('input[type="file"]', { timeout: 5000 });
          await fileInput.setInputFiles(filePath);
          console.log(`  ✓ File attached: ${filePath}`);
          await perplexity.page.waitForTimeout(1000);
        } else {
          console.log('  ⓘ Local files option not found');
        }
      } else {
        console.log('  ⓘ Attach button not found');
      }
    } catch (e) {
      console.log(`  ⓘ File attachment: ${e.message}`);
    }

    const ss5 = `/tmp/perp-${sessionId}-05-file-attached.png`;
    await perplexity.screenshot(ss5);
    console.log(`\n  📸 Screenshot: ${ss5}`);
    console.log('  → Claude: Verify file appears attached');
    await prompt('  Press Enter when Claude has verified... ');

    // PHASE 6: Send message
    console.log('\n[PHASE 6] Sending message...');
    await perplexity.osa.pressKey('return');
    await perplexity.page.waitForTimeout(1500);
    console.log('  ✓ Message sent');

    const ss6 = `/tmp/perp-${sessionId}-06-sent.png`;
    await perplexity.screenshot(ss6);
    console.log(`\n  📸 Screenshot: ${ss6}`);
    console.log('  → Claude: Verify message was sent (input cleared, "researching" shown)');
    await prompt('  Press Enter when Claude has verified... ');

    // PHASE 7: Wait for response
    console.log('\n[PHASE 7] Waiting for response...');
    console.log('  ⏳ Pro Search may take 30-60 seconds');
    console.log('  ⏳ Fibonacci polling with screenshots at each interval\n');

    const response = await perplexity.waitForResponse(180000, { sessionId });
    console.log('  ✓ Response received');

    const ss7 = `/tmp/perp-${sessionId}-07-complete.png`;
    await perplexity.screenshot(ss7);

    console.log('\n' + '='.repeat(70));
    console.log('TEST COMPLETE');
    console.log('='.repeat(70));
    console.log(`\nResponse (${response.length} chars):`);
    console.log(response.substring(0, 500) + '...\n');

    console.log('All screenshots:');
    console.log(`  1. ${ss1}`);
    console.log(`  2. ${ss2}`);
    console.log(`  3. ${ss3}`);
    console.log(`  4. ${ss4}`);
    console.log(`  5. ${ss5}`);
    console.log(`  6. ${ss6}`);
    console.log(`  7. ${ss7}`);
    console.log('  + Polling screenshots: /tmp/taey-Perplexity-*-t*.png\n');

    await perplexity.disconnect();
    console.log('✓ Disconnected\n');

  } catch (error) {
    console.error('\n❌ Error:', error.message);
    console.error(error.stack);
    await perplexity.disconnect();
    process.exit(1);
  }
}

test();
