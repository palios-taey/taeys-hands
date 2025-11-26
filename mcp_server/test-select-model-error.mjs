/**
 * Test error handling for taey_select_model
 * Verifies that it only works with Claude sessions
 */

import { spawn } from 'child_process';

async function testSelectModelError() {
  console.log('=== Testing taey_select_model error handling ===\n');

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

  const sendRequest = async (method, params, waitTime = 2000) => {
    const request = {
      jsonrpc: '2.0',
      id: Date.now(),
      method,
      params
    };

    responseBuffer = '';
    server.stdin.write(JSON.stringify(request) + '\n');
    await new Promise(resolve => setTimeout(resolve, waitTime));

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

  let sessionId;

  try {
    // Test: Connect to ChatGPT (non-Claude interface)
    console.log('Test: Connecting to ChatGPT interface...');
    const connectResponse = await sendRequest('tools/call', {
      name: 'taey_connect',
      arguments: {
        interface: 'chatgpt'
      }
    }, 3000);

    if (!connectResponse?.result) {
      console.error('❌ Failed to connect:', connectResponse);
      server.kill();
      return;
    }

    const connectResult = JSON.parse(connectResponse.result.content[0].text);
    sessionId = connectResult.sessionId;
    console.log('✓ Connected to ChatGPT');
    console.log(`  Session ID: ${sessionId}`);
    console.log();

    await new Promise(resolve => setTimeout(resolve, 2000));

    // Try to select model (should fail)
    console.log('Attempting to select model on ChatGPT session (should fail)...');
    const selectResponse = await sendRequest('tools/call', {
      name: 'taey_select_model',
      arguments: {
        sessionId,
        modelName: 'Opus 4.5'
      }
    }, 2000);

    if (selectResponse?.error || selectResponse?.result?.isError) {
      console.log('✓ Correctly rejected non-Claude session:');
      if (selectResponse.error) {
        console.log(`  Error: ${selectResponse.error.message || selectResponse.error}`);
      } else if (selectResponse.result) {
        const errorResult = JSON.parse(selectResponse.result.content[0].text);
        console.log(`  Error: ${errorResult.error}`);
      }
      console.log();
      console.log('✓ Test PASSED: Error handling works correctly!');
    } else {
      console.error('❌ Test FAILED: Should have rejected non-Claude session');
      console.error('Response:', selectResponse);
    }

  } catch (error) {
    console.error('Test failed with exception:', error);
  } finally {
    if (sessionId) {
      try {
        await sendRequest('tools/call', {
          name: 'taey_disconnect',
          arguments: { sessionId }
        });
      } catch {}
    }
    server.kill();
  }
}

testSelectModelError().catch(console.error);
