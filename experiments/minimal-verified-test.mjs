/**
 * Minimal Verified Test - One step at a time with verification
 * STOP if any step fails
 */
import { ChatGPTInterface } from '../src/interfaces/chat-interface.js';
import { exec } from 'child_process';
import { promisify } from 'util';
const execAsync = promisify(exec);

const SCREENSHOT_DIR = '/tmp/minimal-test';
let stepNum = 0;

async function screenshot(description) {
  stepNum++;
  const filename = `${SCREENSHOT_DIR}/${String(stepNum).padStart(2, '0')}-${description.replace(/\s+/g, '-').substring(0, 30)}.png`;
  await execAsync(`screencapture -x "${filename}"`);
  console.log(`[${stepNum}] ${description}`);
  console.log(`    -> ${filename}`);
  return filename;
}

async function test() {
  await execAsync(`rm -rf ${SCREENSHOT_DIR} && mkdir -p ${SCREENSHOT_DIR}`);
  console.log('=== MINIMAL VERIFIED TEST ===\n');
  console.log(`Screenshots: ${SCREENSHOT_DIR}\n`);

  // STEP 1: Connect to Chrome
  console.log('\n--- STEP 1: Connect to Chrome ---');
  const chatgpt = new ChatGPTInterface();
  await chatgpt.connect();
  console.log('Connected to Chrome CDP');

  // STEP 2: Screenshot initial state
  await screenshot('01-initial-state');

  // STEP 3: Navigate to ChatGPT
  console.log('\n--- STEP 2: Navigate to chatgpt.com ---');
  await chatgpt.page.goto('https://chatgpt.com/', { waitUntil: 'networkidle0', timeout: 30000 });
  await chatgpt.page.waitForTimeout(2000);
  await screenshot('02-after-navigation');

  // STEP 4: Bring tab to front
  console.log('\n--- STEP 3: Bring tab to front ---');
  await chatgpt.page.bringToFront();
  await chatgpt.page.waitForTimeout(500);
  await screenshot('03-after-bringToFront');

  // STEP 5: Focus Chrome app via osascript
  console.log('\n--- STEP 4: Focus Chrome app ---');
  await chatgpt.osa.focusApp('Google Chrome');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('04-after-focusApp');

  // STEP 6: Find input and click it
  console.log('\n--- STEP 5: Click input field ---');
  const input = await chatgpt.page.waitForSelector(chatgpt.selectors.chatInput, { timeout: 10000 });
  await input.click();
  await chatgpt.page.waitForTimeout(500);
  await screenshot('05-after-click-input');

  // STEP 7: Type a SHORT test string
  console.log('\n--- STEP 6: Type "TEST123" ---');
  await chatgpt.osa.type('TEST123');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('06-after-type-TEST123');

  // STEP 8: Set clipboard and paste
  console.log('\n--- STEP 7: Set clipboard to "[PASTED]" ---');
  await chatgpt.osa.setClipboard('[PASTED]');
  console.log('Clipboard set');

  console.log('\n--- STEP 8: Paste (Cmd+V) ---');
  await chatgpt.osa.paste();
  await chatgpt.page.waitForTimeout(500);
  await screenshot('07-after-paste');

  // STEP 9: Type more
  console.log('\n--- STEP 9: Type "END" ---');
  await chatgpt.osa.type('END');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('08-final-state');

  console.log('\n=== TEST COMPLETE ===');
  console.log(`\nExpected input: "TEST123[PASTED]END"`);
  console.log(`Review: open ${SCREENSHOT_DIR}`);

  await chatgpt.disconnect();
}

test().catch(err => {
  console.error('TEST FAILED:', err.message);
  process.exit(1);
});
