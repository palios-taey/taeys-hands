/**
 * Verify Paste Actually Works
 * Use distinctive content that would be obvious if typed vs pasted
 */
import { ChatGPTInterface } from '../src/interfaces/chat-interface.js';
import { exec } from 'child_process';
import { promisify } from 'util';
const execAsync = promisify(exec);

const SCREENSHOT_DIR = '/tmp/verify-paste';
let stepNum = 0;

async function screenshot(description) {
  stepNum++;
  const filename = `${SCREENSHOT_DIR}/${String(stepNum).padStart(2, '0')}-${description}.png`;
  await execAsync(`screencapture -x "${filename}"`);
  console.log(`[${stepNum}] ${description}: ${filename}`);
  return filename;
}

async function test() {
  await execAsync(`rm -rf ${SCREENSHOT_DIR} && mkdir -p ${SCREENSHOT_DIR}`);
  console.log('=== VERIFY PASTE ACTUALLY WORKS ===\n');

  const chatgpt = new ChatGPTInterface();
  await chatgpt.connect();

  // Navigate to fresh ChatGPT
  console.log('Navigating to ChatGPT...');
  await chatgpt.page.goto('https://chatgpt.com/', { waitUntil: 'networkidle0', timeout: 30000 });
  await chatgpt.page.waitForTimeout(2000);
  await screenshot('01-loaded');

  // Bring to front and focus
  await chatgpt.page.bringToFront();
  await chatgpt.osa.focusApp('Google Chrome');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('02-focused');

  // Click input
  console.log('Clicking input...');
  const input = await chatgpt.page.waitForSelector(chatgpt.selectors.chatInput, { timeout: 10000 });
  await input.click();
  await chatgpt.page.waitForTimeout(500);
  await screenshot('03-input-clicked');

  // TYPE a marker
  console.log('Typing "START>"...');
  await chatgpt.osa.type('START>');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('04-after-type-start');

  // Set clipboard to DISTINCTIVE content - long, has special chars
  // If this gets TYPED it would take a while and look different
  const pasteContent = '<<<THIS_WAS_PASTED_NOT_TYPED_12345>>>';
  console.log(`Setting clipboard to: "${pasteContent}"`);
  await chatgpt.osa.setClipboard(pasteContent);

  // Verify clipboard was set by reading it back
  const { stdout: clipboardCheck } = await execAsync('pbpaste');
  console.log(`Clipboard verify: "${clipboardCheck.trim()}"`);
  if (clipboardCheck.trim() !== pasteContent) {
    console.error('ERROR: Clipboard was not set correctly!');
    return;
  }

  // PASTE
  console.log('Pasting (Cmd+V)...');
  await screenshot('05-before-paste');
  await chatgpt.osa.paste();
  await chatgpt.page.waitForTimeout(1000);
  await screenshot('06-after-paste');

  // TYPE end marker
  console.log('Typing "<END"...');
  await chatgpt.osa.type('<END');
  await chatgpt.page.waitForTimeout(500);
  await screenshot('07-final');

  // Get input value via page evaluation
  console.log('\n--- VERIFICATION ---');
  try {
    const inputValue = await chatgpt.page.evaluate(() => {
      const textarea = document.querySelector('#prompt-textarea');
      return textarea ? textarea.innerText || textarea.value : 'NOT FOUND';
    });
    console.log(`Input content: "${inputValue}"`);

    if (inputValue.includes('THIS_WAS_PASTED')) {
      console.log('✅ PASTE WORKED - distinctive content found in input');
    } else {
      console.log('❌ PASTE FAILED - distinctive content NOT in input');
    }
  } catch (e) {
    console.log('Could not read input value:', e.message);
  }

  console.log(`\nScreenshots: ${SCREENSHOT_DIR}`);
  await chatgpt.disconnect();
}

test().catch(console.error);
