#!/usr/bin/env node

/**
 * Test script for taey_extract_response tool
 *
 * Flow:
 * 1. Connect to Claude
 * 2. Send a simple math question
 * 3. Wait 5 seconds for response
 * 4. Extract response
 * 5. Verify response text is returned
 * 6. Disconnect
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

async function test() {
  console.log("Starting taey_extract_response test...\n");

  // Create MCP client
  const transport = new StdioClientTransport({
    command: "node",
    args: ["dist/server-v2.js"],
  });

  const client = new Client(
    {
      name: "test-extract-response",
      version: "1.0.0",
    },
    {
      capabilities: {},
    }
  );

  await client.connect(transport);
  console.log("✓ Connected to MCP server\n");

  let sessionId;

  try {
    // Step 1: Connect to Claude
    console.log("Step 1: Connecting to Claude...");
    const connectResult = await client.callTool({
      name: "taey_connect",
      arguments: {
        interface: "claude",
      },
    });

    const connectData = JSON.parse(connectResult.content[0].text);
    if (!connectData.success) {
      throw new Error(`Connect failed: ${connectData.error}`);
    }

    sessionId = connectData.sessionId;
    console.log(`✓ Connected (sessionId: ${sessionId})\n`);

    // Step 2: Send a simple math question
    console.log("Step 2: Sending message: 'What is 2 + 2?'");
    const sendResult = await client.callTool({
      name: "taey_send_message",
      arguments: {
        sessionId,
        message: "What is 2 + 2?",
      },
    });

    const sendData = JSON.parse(sendResult.content[0].text);
    if (!sendData.success) {
      throw new Error(`Send message failed: ${sendData.error}`);
    }

    console.log("✓ Message sent\n");

    // Step 3: Wait 5 seconds for response
    console.log("Step 3: Waiting 5 seconds for AI response...");
    await new Promise((resolve) => setTimeout(resolve, 5000));
    console.log("✓ Wait complete\n");

    // Step 4: Extract response
    console.log("Step 4: Extracting response...");
    const extractResult = await client.callTool({
      name: "taey_extract_response",
      arguments: {
        sessionId,
      },
    });

    const extractData = JSON.parse(extractResult.content[0].text);
    if (!extractData.success) {
      throw new Error(`Extract response failed: ${extractData.error}`);
    }

    console.log("✓ Response extracted\n");

    // Step 5: Verify response
    console.log("Step 5: Verifying response...");
    console.log("Response Data:");
    console.log(`  - Timestamp: ${extractData.timestamp}`);
    console.log(`  - Response Text: ${extractData.responseText.substring(0, 100)}${extractData.responseText.length > 100 ? '...' : ''}`);
    console.log(`  - Text Length: ${extractData.responseText.length} chars\n`);

    if (!extractData.responseText || extractData.responseText.length === 0) {
      throw new Error("Response text is empty");
    }

    console.log("✓ Response verified\n");

    console.log("Full Response Text:");
    console.log("─────────────────────────────────────────────────────");
    console.log(extractData.responseText);
    console.log("─────────────────────────────────────────────────────\n");

    // Step 6: Disconnect
    console.log("Step 6: Disconnecting...");
    const disconnectResult = await client.callTool({
      name: "taey_disconnect",
      arguments: {
        sessionId,
      },
    });

    const disconnectData = JSON.parse(disconnectResult.content[0].text);
    if (!disconnectData.success) {
      throw new Error(`Disconnect failed: ${disconnectData.error}`);
    }

    console.log("✓ Disconnected\n");

    console.log("═════════════════════════════════════════════════════");
    console.log("✓ ALL TESTS PASSED");
    console.log("═════════════════════════════════════════════════════\n");

  } catch (error) {
    console.error("\n✗ TEST FAILED");
    console.error(`Error: ${error.message}\n`);

    // Cleanup: disconnect if we have a session
    if (sessionId) {
      try {
        console.log("Attempting cleanup disconnect...");
        await client.callTool({
          name: "taey_disconnect",
          arguments: { sessionId },
        });
        console.log("✓ Cleanup disconnect successful\n");
      } catch (cleanupError) {
        console.error(`Cleanup failed: ${cleanupError.message}\n`);
      }
    }

    process.exit(1);
  } finally {
    await client.close();
  }
}

test().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
