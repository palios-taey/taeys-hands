/**
 * Verified Paste Test - Screenshots before and after EVERY action
 * No assumptions - verify each step visually
 */
import { ChatGPTInterface } from '../src/interfaces/chat-interface.js';
import { exec } from 'child_process';
import { promisify } from 'util';
const execAsync = promisify(exec);

const SCREENSHOT_DIR = '/tmp/verified-paste-test';
let stepNum = 0;

async function screenshot(description) {
  stepNum++;
  const filename = `${SCREENSHOT_DIR}/${String(stepNum).padStart(2, '0')}-${description.replace(/\s+/g, '-')}.png`;
  await execAsync(`screencapture -x "${filename}"`);
  console.log(`[SCREENSHOT ${stepNum}] ${description}: ${filename}`);
  return filename;
}

async function test() {
  // Clean and create screenshot dir
  await execAsync(`rm -rf ${SCREENSHOT_DIR} && mkdir -p ${SCREENSHOT_DIR}`);

  console.log('=== VERIFIED PASTE TEST ===');
  console.log(`Screenshots will be saved to: ${SCREENSHOT_DIR}\n`);

  const chatgpt = new ChatGPTInterface();
  await chatgpt.connect();

  // Step 1: Go to ChatGPT new chat
  console.log('\n--- STEP: Navigate to ChatGPT ---');
  await screenshot('before-navigation');
  await chatgpt.page.goto('https://chatgpt.com/');
  await chatgpt.page.waitForTimeout(2000);
  await screenshot('after-navigation');

  // Step 2: Focus Chrome app
  console.log('\n--- STEP: Focus Chrome ---');
  await screenshot('before-focus-chrome');
  await chatgpt.osa.focusApp('Google Chrome');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('after-focus-chrome');

  // Step 3: Find and click input
  console.log('\n--- STEP: Click input field ---');
  await screenshot('before-click-input');
  const input = await chatgpt.page.waitForSelector(chatgpt.selectors.chatInput, { timeout: 10000 });
  await input.click();
  await chatgpt.page.waitForTimeout(300);
  await screenshot('after-click-input');

  // Step 4: Type first part
  console.log('\n--- STEP: Type "Hello from CCM. " ---');
  await screenshot('before-type-1');
  await chatgpt.osa.safeTypeLong('Hello from CCM. ');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('after-type-1');

  // Step 5: Set clipboard
  console.log('\n--- STEP: Set clipboard content ---');
  const clipboardContent = '[PASTED CONTENT FROM GROK]';
  console.log(`  Setting clipboard to: "${clipboardContent}"`);
  await chatgpt.osa.setClipboard(clipboardContent);
  // Can't screenshot clipboard, but log it
  console.log('  Clipboard set (no visual change expected)');

  // Step 6: Paste
  console.log('\n--- STEP: Paste (Cmd+V) ---');
  await screenshot('before-paste');
  await chatgpt.osa.safePaste();
  await chatgpt.page.waitForTimeout(500);
  await screenshot('after-paste');

  // Step 7: Type second part
  console.log('\n--- STEP: Type " And more typed text." ---');
  await screenshot('before-type-2');
  await chatgpt.osa.safeTypeLong(' And more typed text.');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('after-type-2');

  // Final screenshot
  await screenshot('final-state');

  console.log('\n=== TEST COMPLETE ===');
  console.log(`\nReview screenshots in: ${SCREENSHOT_DIR}`);
  console.log('Run: open ' + SCREENSHOT_DIR);

  await chatgpt.disconnect();
}

test().catch(console.error);
