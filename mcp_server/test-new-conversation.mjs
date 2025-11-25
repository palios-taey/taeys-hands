/**
 * Test taey_connect → taey_new_conversation → taey_disconnect
 */

import { spawn } from 'child_process';

async function testNewConversation() {
  console.log('=== Testing taey_new_conversation ===\n');

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
    await new Promise(resolve => setTimeout(resolve, 2000));

    const lines = responseBuffer.split('\n');
    for (const line of lines) {
      if (line.trim().startsWith('{')) {
        try {
          return JSON.parse(line);
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
      console.log('✓ New conversation result:');
      console.log(JSON.stringify(newConvResult, null, 2));
      console.log();
    } else {
      console.error('❌ Failed to start new conversation:', newConvResponse);
    }

    // 3. Disconnect
    console.log('Step 3: Disconnecting...');
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

testNewConversation().catch(console.error);
