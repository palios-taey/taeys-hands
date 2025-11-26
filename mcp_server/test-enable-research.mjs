/**
 * Manual test of taey_enable_research_mode tool
 * Tests research mode enablement for Claude and Perplexity
 */

import { spawn } from 'child_process';

async function testEnableResearchMode() {
  console.log('=== Testing taey_enable_research_mode ===\n');

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

  let claudeSessionId;
  let perplexitySessionId;

  try {
    // Test 1: List tools to verify taey_enable_research_mode is available
    console.log('Test 1: Listing available tools...');
    const listResponse = await sendRequest('tools/list', {});

    if (listResponse?.result?.tools) {
      const researchTool = listResponse.result.tools.find(t => t.name === 'taey_enable_research_mode');
      if (researchTool) {
        console.log('✓ taey_enable_research_mode tool found:');
        console.log(`  Description: ${researchTool.description}`);
        console.log();
      } else {
        console.error('❌ taey_enable_research_mode tool not found!');
        server.kill();
        return;
      }
    }

    // Test 2: Connect to Claude
    console.log('Test 2: Connecting to Claude interface...');
    const claudeConnectResponse = await sendRequest('tools/call', {
      name: 'taey_connect',
      arguments: {
        interface: 'claude'
      }
    }, 3000);

    if (!claudeConnectResponse?.result) {
      console.error('❌ Failed to connect to Claude:', claudeConnectResponse);
      server.kill();
      return;
    }

    const claudeConnectResult = JSON.parse(claudeConnectResponse.result.content[0].text);
    claudeSessionId = claudeConnectResult.sessionId;
    console.log('✓ Connected to Claude');
    console.log(`  Session ID: ${claudeSessionId}`);
    console.log();

    // Wait for page to fully load
    console.log('Waiting 3s for Claude page to load...');
    await new Promise(resolve => setTimeout(resolve, 3000));

    // Test 3: Enable research mode on Claude (Extended Thinking)
    console.log('Test 3: Enabling Extended Thinking on Claude...');
    const claudeResearchResponse = await sendRequest('tools/call', {
      name: 'taey_enable_research_mode',
      arguments: {
        sessionId: claudeSessionId,
        enabled: true
      }
    }, 3000);

    if (!claudeResearchResponse?.result) {
      console.error('❌ Failed to enable research mode on Claude:', claudeResearchResponse);
      if (claudeResearchResponse?.error) {
        console.error('Error:', claudeResearchResponse.error);
      }
    } else {
      const claudeResearchResult = JSON.parse(claudeResearchResponse.result.content[0].text);
      console.log('✓ Claude research mode result:');
      console.log(JSON.stringify(claudeResearchResult, null, 2));
      console.log();
      console.log(`Screenshot saved to: ${claudeResearchResult.screenshot}`);
      console.log();
    }

    // Keep browser open for verification
    console.log('Keeping Claude browser open for 5 seconds...');
    await new Promise(resolve => setTimeout(resolve, 5000));

    // Test 4: Connect to Perplexity
    console.log('Test 4: Connecting to Perplexity interface...');
    const perplexityConnectResponse = await sendRequest('tools/call', {
      name: 'taey_connect',
      arguments: {
        interface: 'perplexity'
      }
    }, 3000);

    if (!perplexityConnectResponse?.result) {
      console.error('❌ Failed to connect to Perplexity:', perplexityConnectResponse);
    } else {
      const perplexityConnectResult = JSON.parse(perplexityConnectResponse.result.content[0].text);
      perplexitySessionId = perplexityConnectResult.sessionId;
      console.log('✓ Connected to Perplexity');
      console.log(`  Session ID: ${perplexitySessionId}`);
      console.log();

      // Wait for page to fully load
      console.log('Waiting 3s for Perplexity page to load...');
      await new Promise(resolve => setTimeout(resolve, 3000));

      // Test 5: Enable research mode on Perplexity (Pro Search)
      console.log('Test 5: Enabling Pro Search on Perplexity...');
      const perplexityResearchResponse = await sendRequest('tools/call', {
        name: 'taey_enable_research_mode',
        arguments: {
          sessionId: perplexitySessionId
        }
      }, 3000);

      if (!perplexityResearchResponse?.result) {
        console.error('❌ Failed to enable research mode on Perplexity:', perplexityResearchResponse);
        if (perplexityResearchResponse?.error) {
          console.error('Error:', perplexityResearchResponse.error);
        }
      } else {
        const perplexityResearchResult = JSON.parse(perplexityResearchResponse.result.content[0].text);
        console.log('✓ Perplexity research mode result:');
        console.log(JSON.stringify(perplexityResearchResult, null, 2));
        console.log();
        console.log(`Screenshot saved to: ${perplexityResearchResult.screenshot}`);
        console.log();
      }

      // Keep browser open for verification
      console.log('Keeping Perplexity browser open for 5 seconds...');
      await new Promise(resolve => setTimeout(resolve, 5000));
    }

    // Test 6: Disconnect both sessions
    console.log('Test 6: Disconnecting sessions...');

    if (claudeSessionId) {
      const claudeDisconnectResponse = await sendRequest('tools/call', {
        name: 'taey_disconnect',
        arguments: {
          sessionId: claudeSessionId
        }
      });

      if (claudeDisconnectResponse?.result) {
        console.log('✓ Claude disconnected');
      }
    }

    if (perplexitySessionId) {
      const perplexityDisconnectResponse = await sendRequest('tools/call', {
        name: 'taey_disconnect',
        arguments: {
          sessionId: perplexitySessionId
        }
      });

      if (perplexityDisconnectResponse?.result) {
        console.log('✓ Perplexity disconnected');
      }
    }

    console.log('\n✓ Test completed successfully!');
    console.log('\nVerify:');
    console.log('  CLAUDE:');
    console.log('    1. Chrome browser opened to Claude.ai');
    console.log('    2. Extended Thinking mode was enabled');
    console.log('    3. Screenshot saved showing enabled state');
    console.log('  PERPLEXITY:');
    console.log('    1. Chrome browser opened to Perplexity.ai');
    console.log('    2. Pro Search mode was enabled');
    console.log('    3. Screenshot saved showing enabled state');
    console.log('  BOTH:');
    console.log('    4. Browsers closed after disconnect');

  } catch (error) {
    console.error('Test failed:', error);
  } finally {
    // Clean up
    if (claudeSessionId) {
      try {
        await sendRequest('tools/call', {
          name: 'taey_disconnect',
          arguments: { sessionId: claudeSessionId }
        });
      } catch {}
    }
    if (perplexitySessionId) {
      try {
        await sendRequest('tools/call', {
          name: 'taey_disconnect',
          arguments: { sessionId: perplexitySessionId }
        });
      } catch {}
    }
    server.kill();
  }
}

testEnableResearchMode().catch(console.error);
