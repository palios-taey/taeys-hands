/**
 * Test disabling Extended Thinking on Claude
 */

import { spawn } from 'child_process';

async function testDisableResearchMode() {
  console.log('=== Testing Claude Extended Thinking Disable ===\n');

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
    // Connect to Claude
    console.log('Connecting to Claude...');
    const connectResponse = await sendRequest('tools/call', {
      name: 'taey_connect',
      arguments: {
        interface: 'claude'
      }
    }, 3000);

    const connectResult = JSON.parse(connectResponse.result.content[0].text);
    sessionId = connectResult.sessionId;
    console.log(`✓ Connected (Session: ${sessionId})`);
    console.log();

    await new Promise(resolve => setTimeout(resolve, 3000));

    // Enable Extended Thinking
    console.log('Test 1: Enabling Extended Thinking...');
    const enableResponse = await sendRequest('tools/call', {
      name: 'taey_enable_research_mode',
      arguments: {
        sessionId,
        enabled: true
      }
    }, 3000);

    const enableResult = JSON.parse(enableResponse.result.content[0].text);
    console.log('✓ Result:', enableResult.message);
    console.log(`  Screenshot: ${enableResult.screenshot}`);
    console.log();

    await new Promise(resolve => setTimeout(resolve, 2000));

    // Disable Extended Thinking
    console.log('Test 2: Disabling Extended Thinking...');
    const disableResponse = await sendRequest('tools/call', {
      name: 'taey_enable_research_mode',
      arguments: {
        sessionId,
        enabled: false
      }
    }, 3000);

    const disableResult = JSON.parse(disableResponse.result.content[0].text);
    console.log('✓ Result:', disableResult.message);
    console.log(`  Enabled: ${disableResult.enabled}`);
    console.log(`  Screenshot: ${disableResult.screenshot}`);
    console.log();

    console.log('Keeping browser open for 5 seconds to verify...');
    await new Promise(resolve => setTimeout(resolve, 5000));

    // Disconnect
    await sendRequest('tools/call', {
      name: 'taey_disconnect',
      arguments: { sessionId }
    });

    console.log('✓ Test completed successfully!');

  } catch (error) {
    console.error('Test failed:', error);
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

testDisableResearchMode().catch(console.error);
