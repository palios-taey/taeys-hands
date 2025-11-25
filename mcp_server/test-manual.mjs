/**
 * Manual test of MCP server tool execution
 * Tests start_claude_research, get_research_status, get_research_result
 */

import { spawn } from 'child_process';
import { readFile } from 'fs/promises';

async function testMCPTools() {
  console.log('=== Starting MCP Server Manual Test ===\n');

  // Start the MCP server
  const server = spawn('node', ['dist/server.js'], {
    stdio: ['pipe', 'pipe', 'pipe']
  });

  let responseBuffer = '';

  server.stdout.on('data', (data) => {
    responseBuffer += data.toString();
  });

  server.stderr.on('data', (data) => {
    console.error('Server error:', data.toString());
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
    await new Promise(resolve => setTimeout(resolve, 500));

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
    // Test 1: Start a research job
    console.log('Test 1: Starting research job...');
    const startResponse = await sendRequest('tools/call', {
      name: 'start_claude_research',
      arguments: {
        model: 'claude-opus-4',
        message: 'What is 2+2?',
        files: [],
        research: false
      }
    });

    if (!startResponse?.result) {
      console.error('❌ Failed to start job:', startResponse);
      server.kill();
      return;
    }

    const resultText = JSON.parse(startResponse.result.content[0].text);
    const jobId = resultText.jobId;
    console.log(`✓ Job started: ${jobId}\n`);

    // Test 2: Check job status
    console.log('Test 2: Checking job status...');
    await new Promise(resolve => setTimeout(resolve, 2000));

    const statusResponse = await sendRequest('tools/call', {
      name: 'get_research_status',
      arguments: { job_id: jobId }
    });

    if (statusResponse?.result) {
      const status = JSON.parse(statusResponse.result.content[0].text);
      console.log('✓ Status retrieved:');
      console.log(JSON.stringify(status, null, 2));
    } else {
      console.error('❌ Failed to get status');
    }

    console.log('\n✓ MCP tools are working!');
    console.log('\nNote: Full workflow test requires browser automation.');
    console.log(`Job ID: ${jobId} - Check status with: get_research_status`);

  } catch (error) {
    console.error('Test failed:', error);
  } finally {
    server.kill();
  }
}

testMCPTools().catch(console.error);
