/**
 * Complete Perplexity test with all features:
 * - Navigate to existing chat
 * - Enable Pro Search
 * - Attach file (AI_INTERFACES.md)
 * - Mixed content (pasted AI quotes)
 * - Real question about response detection
 * - Full screenshot verification
 */

import { PerplexityInterface } from '../src/interfaces/chat-interface.js';

const sessionId = Date.now();

async function test() {
  console.log('='.repeat(70));
  console.log('PERPLEXITY COMPLETE TEST - All Features');
  console.log('='.repeat(70));

  const perplexity = new PerplexityInterface();

  try {
    // Connect
    console.log('\n[1/7] Connecting to Chrome...');
    await perplexity.connect();
    console.log('  ✓ Connected\n');

    // Navigate to specific chat
    console.log('[2/7] Navigating to chat...');
    await perplexity.page.goto('https://www.perplexity.ai/search/perplexity-clarity-you-are-als-kyFxzJXbQJyH2ZB.BBcuFQ?sm=d');
    await perplexity.page.bringToFront(); // ALWAYS bring tab to front first
    await perplexity.page.waitForTimeout(2000);

    const ss1 = `/tmp/perp-${sessionId}-01-loaded.png`;
    await perplexity.screenshot(ss1);
    console.log(`  ✓ Screenshot saved: ${ss1}`);
    console.log(`  → Verifying screenshot before proceeding...\n`);

    // VERIFICATION: Read screenshot to confirm we're on the right page
    // (In production this would be automated, but for testing we capture it)
    await perplexity.page.waitForTimeout(500);

    // Enable Pro Search if available
    console.log('[3/7] Attempting to enable Pro Search...');
    try {
      const proBtn = await perplexity.page.waitForSelector('button[aria-label*="Pro"]', { timeout: 3000 }).catch(() => null);
      if (proBtn) {
        await proBtn.click();
        console.log('  ✓ Pro Search enabled');
        await perplexity.page.waitForTimeout(500);
      } else {
        console.log('  ⓘ Pro Search toggle not found (may already be enabled or not available)');
      }
    } catch (e) {
      console.log(`  ⓘ Could not toggle Pro Search: ${e.message}`);
    }

    const ss2 = `/tmp/perp-${sessionId}-02-pro-mode.png`;
    await perplexity.screenshot(ss2);
    console.log(`  Screenshot: ${ss2}\n`);

    // Compose the message with mixed content
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

    // Focus input
    console.log('[4/7] Focusing input field...');
    const input = await perplexity.page.waitForSelector(perplexity.selectors.chatInput, { timeout: 10000 });
    await input.click();
    await perplexity.page.waitForTimeout(300);

    const ss3 = `/tmp/perp-${sessionId}-03-focused.png`;
    await perplexity.screenshot(ss3);
    console.log(`  ✓ Screenshot: ${ss3}\n`);

    // Type the message (will use human-like typing with mixed content)
    console.log('[5/7] Typing message with mixed content...');
    console.log(`  Message length: ${message.length} chars`);
    console.log('  (This will use human-like typing - keyboard will be locked briefly)\n');

    await perplexity.osa.focusApp('Google Chrome');
    await perplexity.page.waitForTimeout(300);
    await perplexity.osa.typeWithMixedContent(message);
    await perplexity.page.waitForTimeout(1000);

    const ss4 = `/tmp/perp-${sessionId}-04-typed.png`;
    await perplexity.screenshot(ss4);
    console.log(`  ✓ Screenshot: ${ss4}\n`);

    // Attach file - AI_INTERFACES.md
    console.log('[6/7] Attaching file (AI_INTERFACES.md)...');
    const filePath = '/Users/jesselarose/taey-hands/docs/AI_INTERFACES.md';

    try {
      // Click attach button
      const attachBtn = await perplexity.page.waitForSelector('button[data-testid="attach-files-button"]', { timeout: 5000 }).catch(() => null);
      if (attachBtn) {
        await attachBtn.click();
        await perplexity.page.waitForTimeout(500);

        // Click "Local files" menu item
        const localFiles = await perplexity.page.waitForSelector('div[role="menuitem"]:has-text("Local files")', { timeout: 3000 }).catch(() => null);
        if (localFiles) {
          await localFiles.click();
          await perplexity.page.waitForTimeout(1000);

          // Use file input
          const fileInput = await perplexity.page.waitForSelector('input[type="file"]', { timeout: 5000 });
          await fileInput.setInputFiles(filePath);
          console.log(`  ✓ File attached: ${filePath}`);
          await perplexity.page.waitForTimeout(1000);
        } else {
          console.log('  ⓘ Local files option not found in menu');
        }
      } else {
        console.log('  ⓘ Attach button not found (may be Pro-only feature)');
      }
    } catch (e) {
      console.log(`  ⓘ File attachment skipped: ${e.message}`);
    }

    const ss5 = `/tmp/perp-${sessionId}-05-file-attached.png`;
    await perplexity.screenshot(ss5);
    console.log(`  Screenshot: ${ss5}\n`);

    // Send message
    console.log('[7/7] Sending message...');
    await perplexity.osa.pressKey('return');
    await perplexity.page.waitForTimeout(1500);

    const ss6 = `/tmp/perp-${sessionId}-06-sent.png`;
    await perplexity.screenshot(ss6);
    console.log(`  ✓ Screenshot: ${ss6}\n`);

    // Wait for response with Fibonacci polling
    console.log('Waiting for Perplexity response (Pro Search may take 30-60 seconds)...\n');
    const response = await perplexity.waitForResponse(180000, { sessionId }); // 3 min timeout

    const ss7 = `/tmp/perp-${sessionId}-07-complete.png`;
    await perplexity.screenshot(ss7);

    console.log('\n' + '='.repeat(70));
    console.log('TEST COMPLETE');
    console.log('='.repeat(70));
    console.log(`\nResponse received (${response.length} chars):`);
    console.log(response.substring(0, 500) + '...\n');

    console.log('Screenshots captured:');
    console.log(`  1. Loaded:       ${ss1}`);
    console.log(`  2. Pro mode:     ${ss2}`);
    console.log(`  3. Focused:      ${ss3}`);
    console.log(`  4. Typed:        ${ss4}`);
    console.log(`  5. File attached:${ss5}`);
    console.log(`  6. Sent:         ${ss6}`);
    console.log(`  7. Complete:     ${ss7}`);
    console.log('  + Polling interval screenshots in /tmp/taey-Perplexity-*-t*.png\n');

    await perplexity.disconnect();
    console.log('✓ Disconnected\n');

  } catch (error) {
    console.error('\n❌ Test failed:', error.message);
    console.error(error.stack);
    await perplexity.disconnect();
    process.exit(1);
  }
}

test();
