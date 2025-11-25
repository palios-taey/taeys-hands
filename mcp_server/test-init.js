#!/usr/bin/env node

/**
 * Simple test to verify MCP server initializes correctly
 * Tests that the server can list tools and respond to basic requests
 */

import { spawn } from "child_process";

console.log("Testing MCP server initialization...\n");

// Spawn the server
const server = spawn("node", ["dist/server.js"], {
  cwd: "/Users/REDACTED/taey-hands/mcp_server",
  stdio: ["pipe", "pipe", "pipe"],
});

let stdoutData = "";
let stderrData = "";

server.stdout.on("data", (data) => {
  stdoutData += data.toString();
});

server.stderr.on("data", (data) => {
  stderrData += data.toString();
  console.log("Server output:", data.toString().trim());
});

// Wait for server to initialize
setTimeout(() => {
  console.log("\nSending initialize request...");

  // Send initialize request
  const initRequest = {
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: {
        name: "test-client",
        version: "1.0.0",
      },
    },
  };

  server.stdin.write(JSON.stringify(initRequest) + "\n");

  // Wait for response
  setTimeout(() => {
    console.log("\nSending list tools request...");

    // Send list tools request
    const listToolsRequest = {
      jsonrpc: "2.0",
      id: 2,
      method: "tools/list",
      params: {},
    };

    server.stdin.write(JSON.stringify(listToolsRequest) + "\n");

    // Wait for response
    setTimeout(() => {
      console.log("\n=== Test Results ===");

      if (stderrData.includes("Taey-Hands MCP server running on stdio")) {
        console.log("✓ Server initialized successfully");
      } else {
        console.log("✗ Server initialization message not found");
      }

      if (stdoutData.length > 0) {
        console.log("\n✓ Server responded to requests");
        console.log("\nServer responses:");

        // Try to parse JSON-RPC responses
        const lines = stdoutData.split("\n").filter((l) => l.trim());
        lines.forEach((line) => {
          try {
            const response = JSON.parse(line);
            console.log("\nResponse ID:", response.id);

            if (response.result?.tools) {
              console.log("Tools available:", response.result.tools.length);
              response.result.tools.forEach((tool) => {
                console.log("  -", tool.name);
              });
            } else if (response.result?.capabilities) {
              console.log("Server capabilities:", JSON.stringify(response.result.capabilities));
            }
          } catch (e) {
            console.log("Non-JSON output:", line.substring(0, 100));
          }
        });
      } else {
        console.log("\n✗ No responses received from server");
      }

      // Cleanup
      server.kill();
      process.exit(stdoutData.length > 0 ? 0 : 1);
    }, 1000);
  }, 1000);
}, 1000);

// Handle errors
server.on("error", (error) => {
  console.error("Server error:", error);
  process.exit(1);
});

server.on("exit", (code) => {
  if (code !== null && code !== 0 && code !== 143) {
    console.error("Server exited with code:", code);
  }
});
