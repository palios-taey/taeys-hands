/**
 * taey_disconnect Tool
 * 
 * Disconnect from an AI platform and cleanup session
 * 
 * @module mcp/tools/disconnect
 */

import { getSessionWorkflow } from '../../workflow/session-workflow.js';

/**
 * Tool definition
 */
export const disconnectTool = {
  name: 'taey_disconnect',
  description: `Disconnect from an AI platform and cleanup the session.

This closes the browser page and removes session tracking.
Optionally marks the conversation as closed in Neo4j.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      closeConversation: {
        type: 'boolean',
        description: 'Mark conversation as closed in Neo4j (default: false)',
        default: false,
      },
    },
    required: ['sessionId'],
  },
};

/**
 * Handle disconnect request
 * 
 * @param {Object} args
 * @returns {Object} Result
 */
export async function handleDisconnect(args) {
  const { sessionId, closeConversation = false } = args;

  const sessionWorkflow = getSessionWorkflow();

  // Check session exists
  const session = sessionWorkflow.getSession(sessionId);
  if (!session) {
    return {
      success: false,
      error: `Session not found: ${sessionId}`,
    };
  }

  const result = await sessionWorkflow.destroySession(sessionId, {
    closeConversation,
  });

  return {
    success: true,
    sessionId,
    conversationClosed: closeConversation,
    message: `Session ${sessionId} disconnected successfully`,
  };
}
