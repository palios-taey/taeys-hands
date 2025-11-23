import { ChatGPTInterface } from './src/interfaces/chat-interface.js';

async function test() {
  const chatgpt = new ChatGPTInterface();
  await chatgpt.connect();

  console.log('Going to new chat...');
  await chatgpt.page.goto('https://chatgpt.com/');
  await chatgpt.page.waitForTimeout(2000);

  console.log('Starting attachment...');
  await chatgpt.attachFileHumanLike('/Users/jesselarose/Downloads/THE_CHARTER.md');

  console.log('Done - check if file is attached');
  await chatgpt.disconnect();
}

test().catch(console.error);
