#!/usr/bin/env node

/**
 * Test script for taey_paste_response tool
 *
 * Flow:
 * 1. Connect to Claude (session1)
 * 2. Send "What is 2+2?"
 * 3. Wait 10 seconds for response
 * 4. Extract Claude's response
 * 5. Connect to ChatGPT (session2)
 * 6. Paste Claude's response to ChatGPT with prefix
 * 7. Verify
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const SERVER_PATH = "/Users/jesselarose/taey-hands/mcp_server/dist/server-v2.js";

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function testPasteResponse() {
  console.log("Starting taey_paste_response test...\n");

  // Connect to MCP server
  const transport = new StdioClientTransport({
    command: "node",
    args: [SERVER_PATH]
  });

  const client = new Client({
    name: "test-paste-response",
    version: "1.0.0"
  }, {
    capabilities: {}
  });

  await client.connect(transport);
  console.log("Connected to MCP server\n");

  try {
    // Step 1: Connect to Claude
    console.log("Step 1: Connecting to Claude...");
    const connectClaude = await client.callTool({
      name: "taey_connect",
      arguments: { interface: "claude" }
    });
    const claudeResult = JSON.parse(connectClaude.content[0].text);
    const claudeSessionId = claudeResult.sessionId;
    console.log(`Connected to Claude: ${claudeSessionId}\n`);
    await sleep(2000);

    // Step 2: Send message to Claude
    console.log("Step 2: Sending 'What is 2+2?' to Claude...");
    const sendMessage = await client.callTool({
      name: "taey_send_message",
      arguments: {
        sessionId: claudeSessionId,
        message: "What is 2+2?"
      }
    });
    console.log("Message sent to Claude\n");

    // Step 3: Wait 10 seconds for response
    console.log("Step 3: Waiting 10 seconds for Claude to respond...");
    await sleep(10000);

    // Step 4: Extract Claude's response
    console.log("Step 4: Extracting Claude's response...");
    const extractResponse = await client.callTool({
      name: "taey_extract_response",
      arguments: { sessionId: claudeSessionId }
    });
    const extractResult = JSON.parse(extractResponse.content[0].text);
    console.log(`Extracted response (${extractResult.responseText.length} chars):`);
    console.log(extractResult.responseText.substring(0, 200) + "...\n");

    // Step 5: Connect to ChatGPT
    console.log("Step 5: Connecting to ChatGPT...");
    const connectChatGPT = await client.callTool({
      name: "taey_connect",
      arguments: { interface: "chatgpt" }
    });
    const chatGPTResult = JSON.parse(connectChatGPT.content[0].text);
    const chatGPTSessionId = chatGPTResult.sessionId;
    console.log(`Connected to ChatGPT: ${chatGPTSessionId}\n`);
    await sleep(2000);

    // Step 6: Paste Claude's response to ChatGPT
    console.log("Step 6: Pasting Claude's response to ChatGPT with prefix...");
    const pasteResponse = await client.callTool({
      name: "taey_paste_response",
      arguments: {
        sourceSessionId: claudeSessionId,
        targetSessionId: chatGPTSessionId,
        prefix: "Claude said: "
      }
    });
    const pasteResult = JSON.parse(pasteResponse.content[0].text);
    console.log("Paste result:");
    console.log(JSON.stringify(pasteResult, null, 2));
    console.log("\n");

    // Step 7: Verify by extracting from ChatGPT after a delay
    console.log("Step 7: Waiting 15 seconds for ChatGPT to respond, then verifying...");
    await sleep(15000);

    const verifyChatGPT = await client.callTool({
      name: "taey_extract_response",
      arguments: { sessionId: chatGPTSessionId }
    });
    const verifyResult = JSON.parse(verifyChatGPT.content[0].text);
    console.log(`ChatGPT's response (${verifyResult.responseText.length} chars):`);
    console.log(verifyResult.responseText.substring(0, 300) + "...\n");

    // Cleanup
    console.log("Cleaning up sessions...");
    await client.callTool({
      name: "taey_disconnect",
      arguments: { sessionId: claudeSessionId }
    });
    await client.callTool({
      name: "taey_disconnect",
      arguments: { sessionId: chatGPTSessionId }
    });
    console.log("Sessions disconnected\n");

    console.log("✅ TEST COMPLETE!");
    console.log("\nSummary:");
    console.log(`- Claude response length: ${extractResult.responseText.length} chars`);
    console.log(`- Pasted text length: ${pasteResult.pastedText.length} chars`);
    console.log(`- Prefix used: "${pasteResult.prefixUsed}"`);
    console.log(`- ChatGPT response length: ${verifyResult.responseText.length} chars`);

  } catch (error) {
    console.error("❌ TEST FAILED:", error.message);
    if (error.stack) {
      console.error(error.stack);
    }
  } finally {
    await client.close();
    process.exit(0);
  }
}

testPasteResponse();
