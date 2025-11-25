/**
 * Manual test of taey_attach_files tool
 * Tests file attachment via MCP
 */

import { spawn } from 'child_process';
import { writeFileSync, mkdirSync } from 'fs';

async function testAttachFiles() {
  console.log('=== Testing taey_attach_files ===\n');

  // Create test file
  const testFilePath = '/tmp/test-attachment.txt';
  console.log('Creating test file:', testFilePath);
  writeFileSync(testFilePath, 'This is a test attachment file for MCP tool testing.\nCreated at: ' + new Date().toISOString());
  console.log('✓ Test file created\n');

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
    // Test 1: List tools to verify taey_attach_files is available
    console.log('Test 1: Listing available tools...');
    const listResponse = await sendRequest('tools/list', {});

    if (listResponse?.result?.tools) {
      const attachFilesTool = listResponse.result.tools.find(t => t.name === 'taey_attach_files');
      if (attachFilesTool) {
        console.log('✓ taey_attach_files tool found:');
        console.log(`  Description: ${attachFilesTool.description}`);
        console.log();
      } else {
        console.error('❌ taey_attach_files tool not found!');
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

    // Test 3: Start new conversation
    console.log('Test 3: Starting new conversation...');
    const newConvResponse = await sendRequest('tools/call', {
      name: 'taey_new_conversation',
      arguments: {
        sessionId
      }
    }, 3000);

    if (newConvResponse?.result) {
      const newConvResult = JSON.parse(newConvResponse.result.content[0].text);
      console.log('✓ New conversation started');
      console.log(`  Conversation URL: ${newConvResult.conversationUrl}`);
      console.log();
    }

    // Wait for new conversation to load
    console.log('Waiting 2s for new conversation to load...');
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Test 4: Attach file
    console.log('Test 4: Attaching file...');
    const attachResponse = await sendRequest('tools/call', {
      name: 'taey_attach_files',
      arguments: {
        sessionId,
        filePaths: [testFilePath]
      }
    }, 8000); // Give more time for file attachment (Finder navigation takes time)

    if (!attachResponse?.result) {
      console.error('❌ Failed to attach file:', attachResponse);
      if (attachResponse?.error) {
        console.error('Error:', attachResponse.error);
      }
    } else {
      const attachResult = JSON.parse(attachResponse.result.content[0].text);
      console.log('✓ File attachment result:');
      console.log(JSON.stringify(attachResult, null, 2));
      console.log();
      console.log(`Screenshot saved to: ${attachResult.screenshot}`);
      console.log();
    }

    // Keep browser open for verification
    console.log('Keeping browser open for 10 seconds for verification...');
    await new Promise(resolve => setTimeout(resolve, 10000));

    // Test 5: Disconnect
    console.log('Test 5: Disconnecting session...');
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
    console.log('  2. New conversation started');
    console.log('  3. File attachment dialog opened');
    console.log('  4. Test file was attached');
    console.log('  5. Screenshot saved showing attachment');
    console.log('  6. Browser closed after disconnect');

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

testAttachFiles().catch(console.error);
