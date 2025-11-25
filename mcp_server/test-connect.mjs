/**
 * Manual test of taey_connect and taey_disconnect tools
 * Tests the new function-based MCP architecture
 */

import { spawn } from 'child_process';

async function testConnectTools() {
  console.log('=== Testing taey_connect & taey_disconnect ===\n');

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
  const sendRequest = async (method, params) => {
    const request = {
      jsonrpc: '2.0',
      id: Date.now(),
      method,
      params
    };

    responseBuffer = '';
    server.stdin.write(JSON.stringify(request) + '\n');

    // Wait for response
    await new Promise(resolve => setTimeout(resolve, 2000));

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

  try {
    // Test 1: List tools
    console.log('Test 1: Listing available tools...');
    const listResponse = await sendRequest('tools/list', {});

    if (listResponse?.result?.tools) {
      console.log('✓ Available tools:');
      for (const tool of listResponse.result.tools) {
        console.log(`  - ${tool.name}: ${tool.description.substring(0, 60)}...`);
      }
      console.log();
    }

    // Test 2: Connect to Claude
    console.log('Test 2: Connecting to Claude interface...');
    const connectResponse = await sendRequest('tools/call', {
      name: 'taey_connect',
      arguments: {
        interface: 'claude'
      }
    });

    if (!connectResponse?.result) {
      console.error('❌ Failed to connect:', connectResponse);
      server.kill();
      return;
    }

    const connectResult = JSON.parse(connectResponse.result.content[0].text);
    const sessionId = connectResult.sessionId;
    console.log('✓ Connection result:');
    console.log(JSON.stringify(connectResult, null, 2));
    console.log();

    // Wait a bit to see browser open
    console.log('Waiting 5s to verify browser automation...');
    await new Promise(resolve => setTimeout(resolve, 5000));

    // Test 3: Disconnect
    console.log('Test 3: Disconnecting session...');
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
    } else {
      console.error('❌ Failed to disconnect');
    }

    console.log('\n✓ Test completed successfully!');
    console.log('\nVerify:');
    console.log('  1. Chrome browser opened');
    console.log('  2. Claude.ai page loaded');
    console.log('  3. Browser closed after disconnect');

  } catch (error) {
    console.error('Test failed:', error);
  } finally {
    server.kill();
  }
}

testConnectTools().catch(console.error);
