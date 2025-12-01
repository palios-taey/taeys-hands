#!/usr/bin/env node

/**
 * Taey's Hands MCP Server
 * 
 * Purpose: Model Context Protocol server for AI chat automation
 * 
 * This server exposes tools for:
 * - Connecting to AI platforms (Claude, ChatGPT, Gemini, Grok, Perplexity)
 * - Sending messages with validation enforcement
 * - Attaching files with requirement tracking
 * - Extracting responses
 * - Cross-pollination between platforms
 * 
 * @module mcp/server
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';

// Import tool definitions
import { connectTool, handleConnect } from './tools/connect.js';
import { disconnectTool, handleDisconnect } from './tools/disconnect.js';
import { sendMessageTool, handleSendMessage } from './tools/send-message.js';
import { attachFilesTool, handleAttachFiles } from './tools/attach-files.js';
import { validateStepTool, handleValidateStep } from './tools/validate-step.js';
import { extractResponseTool, handleExtractResponse } from './tools/extract-response.js';
import { selectModelTool, handleSelectModel } from './tools/select-model.js';
import { enableResearchTool, handleEnableResearch } from './tools/enable-research.js';
import { downloadArtifactTool, handleDownloadArtifact } from './tools/download-artifact.js';
import { pasteResponseTool, handlePasteResponse } from './tools/paste-response.js';
import { listSessionsTool, handleListSessions } from './tools/list-sessions.js';
import { planMessageTool, handlePlanMessage } from './tools/plan-message.js';

// Import workflows for shutdown
import { getSessionWorkflow } from '../workflow/session-workflow.js';

/**
 * All available tools
 */
const TOOLS = [
  connectTool,
  disconnectTool,
  planMessageTool,
  sendMessageTool,
  attachFilesTool,
  validateStepTool,
  extractResponseTool,
  selectModelTool,
  enableResearchTool,
  downloadArtifactTool,
  pasteResponseTool,
  listSessionsTool,
];

/**
 * Tool handlers by name
 */
const HANDLERS = {
  taey_connect: handleConnect,
  taey_disconnect: handleDisconnect,
  taey_plan_message: handlePlanMessage,
  taey_send_message: handleSendMessage,
  taey_attach_files: handleAttachFiles,
  taey_validate_step: handleValidateStep,
  taey_extract_response: handleExtractResponse,
  taey_select_model: handleSelectModel,
  taey_enable_research_mode: handleEnableResearch,
  taey_download_artifact: handleDownloadArtifact,
  taey_paste_response: handlePasteResponse,
  taey_list_sessions: handleListSessions,
};

/**
 * Create and configure the MCP server
 */
function createServer() {
  const server = new Server(
    {
      name: 'taey-hands',
      version: '2.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // Handle tool listing
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools: TOOLS };
  });

  // Handle tool calls
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

    const handler = HANDLERS[name];
    if (!handler) {
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: false,
              error: `Unknown tool: ${name}`,
              availableTools: Object.keys(HANDLERS),
            }),
          },
        ],
        isError: true,
      };
    }

    try {
      console.error(`[mcp] Calling tool: ${name}`);
      console.error(`[mcp] Arguments: ${JSON.stringify(args)}`);

      const result = await handler(args);

      console.error(`[mcp] Result: ${JSON.stringify(result).substring(0, 200)}...`);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    } catch (error) {
      console.error(`[mcp] Error in ${name}: ${error.message}`);
      console.error(error.stack);

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              success: false,
              error: error.message,
              tool: name,
            }),
          },
        ],
        isError: true,
      };
    }
  });

  return server;
}

/**
 * Main entry point
 */
async function main() {
  console.error('[mcp] Starting Taey\'s Hands MCP Server v2.0.0');

  const server = createServer();
  const transport = new StdioServerTransport();

  // Handle shutdown
  process.on('SIGINT', async () => {
    console.error('[mcp] Received SIGINT, shutting down...');
    await shutdown();
    process.exit(0);
  });

  process.on('SIGTERM', async () => {
    console.error('[mcp] Received SIGTERM, shutting down...');
    await shutdown();
    process.exit(0);
  });

  // Connect and run
  await server.connect(transport);
  console.error('[mcp] Server running on stdio');
}

/**
 * Graceful shutdown
 */
async function shutdown() {
  try {
    const sessionWorkflow = getSessionWorkflow();
    await sessionWorkflow.shutdown();
    console.error('[mcp] Shutdown complete');
  } catch (error) {
    console.error(`[mcp] Error during shutdown: ${error.message}`);
  }
}

// Run
main().catch((error) => {
  console.error(`[mcp] Fatal error: ${error.message}`);
  console.error(error.stack);
  process.exit(1);
});
