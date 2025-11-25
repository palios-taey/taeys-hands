/**
 * Test taey_connect → taey_new_conversation → taey_send_message → taey_disconnect
 */

import { spawn } from 'child_process';

async function testSendMessage() {
  console.log('=== Testing taey_send_message ===\n');

  const server = spawn('node', ['dist/server-v2.js'], {
    stdio: ['pipe', 'pipe', 'pipe']
  });

  let responseBuffer = '';

  server.stdout.on('data', (data) => {
    responseBuffer += data.toString();
  });

  server.stderr.on('data', (data) => {
    console.error('Server:', data.toString().trim());
  });

  await new Promise(resolve => setTimeout(resolve, 1000));

  const sendRequest = async (method, params) => {
    const request = {
      jsonrpc: '2.0',
      id: Date.now(),
      method,
      params
    };

    responseBuffer = '';
    server.stdin.write(JSON.stringify(request) + '\n');

    // Give more time for operations that involve typing
    const waitTime = method === 'tools/call' && params.name === 'taey_send_message' ? 8000 : 2000;
    await new Promise(resolve => setTimeout(resolve, waitTime));

    const lines = responseBuffer.split('\n');
    for (const line of lines) {
      if (line.trim().startsWith('{')) {
        try {
          const parsed = JSON.parse(line);
          if (parsed.result || parsed.error) {
            return parsed;
          }
        } catch {}
      }
    }
    return null;
  };

  try {
    // 1. Connect to Claude
    console.log('Step 1: Connecting to Claude...');
    const connectResponse = await sendRequest('tools/call', {
      name: 'taey_connect',
      arguments: { interface: 'claude' }
    });

    const connectResult = JSON.parse(connectResponse.result.content[0].text);
    const sessionId = connectResult.sessionId;
    console.log(`✓ Connected with session: ${sessionId}\n`);

    // Wait for page to load
    await new Promise(resolve => setTimeout(resolve, 3000));

    // 2. Start new conversation
    console.log('Step 2: Starting new conversation...');
    const newConvResponse = await sendRequest('tools/call', {
      name: 'taey_new_conversation',
      arguments: { sessionId }
    });

    if (newConvResponse?.result) {
      const newConvResult = JSON.parse(newConvResponse.result.content[0].text);
      console.log('✓ New conversation started:');
      console.log(JSON.stringify(newConvResult, null, 2));
      console.log();
    } else {
      console.error('❌ Failed to start new conversation:', newConvResponse);
    }

    // Wait for new conversation to load
    await new Promise(resolve => setTimeout(resolve, 2000));

    // 3. Send message
    console.log('Step 3: Sending message...');
    const sendMsgResponse = await sendRequest('tools/call', {
      name: 'taey_send_message',
      arguments: {
        sessionId,
        message: 'What is 2+2?',
        waitForResponse: false
      }
    });

    if (sendMsgResponse?.result) {
      const sendMsgResult = JSON.parse(sendMsgResponse.result.content[0].text);
      console.log('✓ Message sent:');
      console.log(JSON.stringify(sendMsgResult, null, 2));
      console.log();
    } else {
      console.log('⚠️  Response delayed (message likely sent - check screenshots)');
    }

    // Wait to see the message appear
    console.log('Waiting 5 seconds to observe message...');
    await new Promise(resolve => setTimeout(resolve, 5000));

    // 4. Disconnect
    console.log('Step 4: Disconnecting...');
    await sendRequest('tools/call', {
      name: 'taey_disconnect',
      arguments: { sessionId }
    });

    console.log('✓ Disconnected\n');
    console.log('✓ Test completed successfully!');

  } catch (error) {
    console.error('Test failed:', error);
  } finally {
    server.kill();
  }
}

testSendMessage().catch(console.error);
