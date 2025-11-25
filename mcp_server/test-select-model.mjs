/**
 * Manual test of taey_select_model tool
 * Tests Claude model selection via MCP
 */

import { spawn } from 'child_process';

async function testSelectModel() {
  console.log('=== Testing taey_select_model ===\n');

  // Start the MCP server (v2)
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

  // Wait for server to start
  await new Promise(resolve => setTimeout(resolve, 1000));

  // Helper to send JSON-RPC request
  const sendRequest = async (method, params, waitTime = 2000) => {
    const request = {
      jsonrpc: '2.0',
      id: Date.now(),
      method,
      params
    };

    responseBuffer = '';
    server.stdin.write(JSON.stringify(request) + '\n');

    // Wait for response
    await new Promise(resolve => setTimeout(resolve, waitTime));

    // Find the JSON response in buffer
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
    // Test 1: List tools to verify taey_select_model is available
    console.log('Test 1: Listing available tools...');
    const listResponse = await sendRequest('tools/list', {});

    if (listResponse?.result?.tools) {
      const selectModelTool = listResponse.result.tools.find(t => t.name === 'taey_select_model');
      if (selectModelTool) {
        console.log('✓ taey_select_model tool found:');
        console.log(`  Description: ${selectModelTool.description}`);
        console.log(`  Model options: ${selectModelTool.inputSchema.properties.modelName.enum.join(', ')}`);
        console.log();
      } else {
        console.error('❌ taey_select_model tool not found!');
        server.kill();
        return;
      }
    }

    // Test 2: Connect to Claude
    console.log('Test 2: Connecting to Claude interface...');
    const connectResponse = await sendRequest('tools/call', {
      name: 'taey_connect',
      arguments: {
        interface: 'claude'
      }
    }, 3000);

    if (!connectResponse?.result) {
      console.error('❌ Failed to connect:', connectResponse);
      server.kill();
      return;
    }

    const connectResult = JSON.parse(connectResponse.result.content[0].text);
    sessionId = connectResult.sessionId;
    console.log('✓ Connected to Claude');
    console.log(`  Session ID: ${sessionId}`);
    console.log();

    // Wait for page to fully load
    console.log('Waiting 3s for Claude page to load...');
    await new Promise(resolve => setTimeout(resolve, 3000));

    // Test 3: Select Opus 4.5 model
    console.log('Test 3: Selecting Opus 4.5 model...');
    const selectResponse = await sendRequest('tools/call', {
      name: 'taey_select_model',
      arguments: {
        sessionId,
        modelName: 'Opus 4.5'
      }
    }, 3000);

    if (!selectResponse?.result) {
      console.error('❌ Failed to select model:', selectResponse);
      if (selectResponse?.error) {
        console.error('Error:', selectResponse.error);
      }
    } else {
      const selectResult = JSON.parse(selectResponse.result.content[0].text);
      console.log('✓ Model selection result:');
      console.log(JSON.stringify(selectResult, null, 2));
      console.log();
      console.log(`Screenshot saved to: ${selectResult.screenshot}`);
      console.log();
    }

    // Keep browser open for verification
    console.log('Keeping browser open for 10 seconds for verification...');
    await new Promise(resolve => setTimeout(resolve, 10000));

    // Test 4: Disconnect
    console.log('Test 4: Disconnecting session...');
    const disconnectResponse = await sendRequest('tools/call', {
      name: 'taey_disconnect',
      arguments: {
        sessionId
      }
    });

    if (disconnectResponse?.result) {
      const disconnectResult = JSON.parse(disconnectResponse.result.content[0].text);
      console.log('✓ Disconnect result:');
      console.log(JSON.stringify(disconnectResult, null, 2));
    }

    console.log('\n✓ Test completed successfully!');
    console.log('\nVerify:');
    console.log('  1. Chrome browser opened to Claude.ai');
    console.log('  2. Model selector dropdown opened');
    console.log('  3. Opus 4.5 was selected');
    console.log('  4. Screenshot saved showing selected model');
    console.log('  5. Browser closed after disconnect');

  } catch (error) {
    console.error('Test failed:', error);
  } finally {
    // Clean up
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

testSelectModel().catch(console.error);
