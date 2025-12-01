/**
 * taey_extract_response Tool
 * 
 * Extract the latest AI response from the chat
 * 
 * @module mcp/tools/extract-response
 */

import { getMessageWorkflow } from '../../workflow/message-workflow.js';

/**
 * Tool definition
 */
export const extractResponseTool = {
  name: 'taey_extract_response',
  description: `Extract the latest AI response from the chat.

Use this after sending a message if you didn't use waitForResponse=true,
or if you want to re-extract the current response.

The response is also stored in Neo4j for conversation history.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
    },
    required: ['sessionId'],
  },
};

/**
 * Handle extract response request
 * 
 * @param {Object} args
 * @returns {Object} Response content
 */
export async function handleExtractResponse(args) {
  const { sessionId } = args;

  const messageWorkflow = getMessageWorkflow();

  const result = await messageWorkflow.extractResponse(sessionId);

  return {
    success: true,
    content: result.content,
    contentLength: result.contentLength,
    screenshot: result.screenshot,
  };
}
