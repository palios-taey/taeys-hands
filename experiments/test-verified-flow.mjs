/**
 * Multi-phase test with manual verification gates
 * Each phase returns screenshots for human (or Claude Code) to verify
 * before proceeding to next phase
 */

import { ClaudeInterface } from '../src/interfaces/chat-interface.js';
import { readFileSync } from 'fs';

const sessionId = Date.now();
const phase = process.argv[2] || 'init';

async function runPhase() {
  const claude = new ClaudeInterface();

  try {
    await claude.connect();
    console.log(`✓ Connected to Claude\n`);

    // Navigate to existing conversation
    if (phase === 'init') {
      console.log('PHASE: INIT - Navigate to existing conversation');
      await claude.page.goto('https://claude.ai/chat/');
      await claude.page.waitForTimeout(2000);

      const ss = `/tmp/verify-${sessionId}-00-init.png`;
      await claude.screenshot(ss);
      console.log(`Screenshot: ${ss}`);
      console.log('\nNext: node experiments/test-verified-flow.mjs focus');
      return;
    }

    if (phase === 'focus') {
      console.log('PHASE: FOCUS - Click input and verify ready');
      const input = await claude.page.waitForSelector(claude.selectors.chatInput);
      await input.click();
      await claude.page.waitForTimeout(500);

      const ss = `/tmp/verify-${sessionId}-01-focused.png`;
      await claude.screenshot(ss);
      console.log(`Screenshot: ${ss}`);
      console.log('\nNext: node experiments/test-verified-flow.mjs type');
      return;
    }

    if (phase === 'type') {
      console.log('PHASE: TYPE - Send message with mixed content');

      const message = `I'm working on browser automation for AI chat interfaces. Current challenge:

Response detection - Sometimes responses complete but the browser doesn't update. This happens with Grok and Gemini especially. Browser notifications exist for this.

Question: What's the best approach to detect when a response is truly complete vs when the browser just hasn't updated yet? Should I:
1. Monitor browser notifications (if accessible via CDP)
2. Use multiple verification strategies (DOM + visual changes)
3. Implement periodic page refreshes
4. Something else?

Context from testing:
CHATGPT: "The DOM polling works well, responses appear in real-time"
GEMINI: "Sometimes the response completes server-side but browser doesn't show it until refresh"`;

      // Focus and type
      await claude.osa.focusApp('Google Chrome');
      await claude.page.waitForTimeout(300);

      console.log('Typing message...');
      await claude.osa.typeWithMixedContent(message);
      await claude.page.waitForTimeout(1000);

      const ss = `/tmp/verify-${sessionId}-02-typed.png`;
      await claude.screenshot(ss);
      console.log(`Screenshot: ${ss}`);
      console.log('\nNext: node experiments/test-verified-flow.mjs send');
      return;
    }

    if (phase === 'send') {
      console.log('PHASE: SEND - Submit message');
      await claude.osa.pressKey('return');
      await claude.page.waitForTimeout(1500);

      const ss = `/tmp/verify-${sessionId}-03-sent.png`;
      await claude.screenshot(ss);
      console.log(`Screenshot: ${ss}`);
      console.log('\nNext: node experiments/test-verified-flow.mjs poll');
      return;
    }

    if (phase === 'poll') {
      console.log('PHASE: POLL - Wait for response');
      console.log('Starting Fibonacci polling...\n');

      const response = await claude.waitForResponse(300000, { sessionId });

      const ss = `/tmp/verify-${sessionId}-04-complete.png`;
      await claude.screenshot(ss);

      console.log(`\nResponse received (${response.length} chars):`);
      console.log(response.substring(0, 500) + '...\n');
      console.log(`Final screenshot: ${ss}`);
      return;
    }

    console.log('Unknown phase. Use: init, focus, type, send, or poll');

  } catch (error) {
    console.error('Error:', error.message);
  } finally {
    await claude.disconnect();
  }
}

runPhase();
