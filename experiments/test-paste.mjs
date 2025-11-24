/**
 * Quick test of clipboard/paste functionality
 */
import { ChatGPTInterface } from '../src/interfaces/chat-interface.js';
import { exec } from 'child_process';
import { promisify } from 'util';
const execAsync = promisify(exec);

async function test() {
  console.log('Testing clipboard/paste...\n');
  
  const chatgpt = new ChatGPTInterface();
  await chatgpt.connect();
  
  // Go to new chat
  await chatgpt.page.goto('https://chatgpt.com/');
  await chatgpt.page.waitForTimeout(2000);
  
  // Focus input
  const input = await chatgpt.page.waitForSelector(chatgpt.selectors.chatInput, { timeout: 10000 });
  await input.click();
  await chatgpt.page.waitForTimeout(200);
  
  // Focus Chrome
  await chatgpt.osa.focusApp('Google Chrome');
  await chatgpt.page.waitForTimeout(200);
  
  // TEST 1: Type some text
  console.log('TEST 1: Typing intro text...');
  await chatgpt.osa.safeTypeLong('This is typed by CCM. ');
  await chatgpt.page.waitForTimeout(500);
  
  // TEST 2: Paste some text
  console.log('TEST 2: Pasting AI quote...');
  await chatgpt.osa.setClipboard('[PASTED: "This quote from Grok was copy-pasted, not typed"]');
  await chatgpt.osa.safePaste();
  await chatgpt.page.waitForTimeout(500);
  
  // TEST 3: Type more
  console.log('TEST 3: Typing followup...');
  await chatgpt.osa.safeTypeLong(' And this is typed again.');
  
  // Screenshot
  await execAsync('screencapture -x /tmp/paste-test-result.png');
  console.log('\nScreenshot saved to /tmp/paste-test-result.png');
  console.log('Check if input shows: typed + [PASTED:...] + typed');
  
  await chatgpt.disconnect();
  console.log('\nDone!');
}

test().catch(console.error);
