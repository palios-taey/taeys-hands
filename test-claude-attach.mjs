/**
 * Test Claude human-like file attachment
 */

import { chromium } from 'playwright';
import { ClaudeInterface } from './src/interfaces/chat-interface.js';

async function testClaudeAttach() {
  console.log('Connecting to Chrome...');
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const contexts = browser.contexts();
  const context = contexts[0];
  const pages = await context.pages();

  // Find Claude tab
  const claudePage = pages.find(p => p.url().includes('claude.ai'));
  if (!claudePage) {
    console.log('ERROR: Claude tab not found - open https://claude.ai first');
    await browser.close();
    return;
  }

  console.log(`Found Claude at: ${claudePage.url()}`);

  // Initialize Claude interface
  const claude = new ClaudeInterface();
  await claude.initialize(claudePage);

  // Test file to attach
  const testFile = '/Users/REDACTED/taey-hands/THE_CHARTER.md';

  console.log('\n=== Testing Claude attachFileHumanLike ===');
  console.log(`File: ${testFile}`);

  const result = await claude.attachFileHumanLike(testFile);

  if (result) {
    console.log('SUCCESS: File attached!');
  } else {
    console.log('FAILED: File attachment failed');
  }

  await browser.close();
}

testClaudeAttach().catch(console.error);
