/**
 * taey_list_sessions Tool
 * 
 * List all active sessions
 * 
 * @module mcp/tools/list-sessions
 */

import { getSessionWorkflow } from '../../workflow/session-workflow.js';

/**
 * Tool definition
 */
export const listSessionsTool = {
  name: 'taey_list_sessions',
  description: `List all active sessions.

Returns information about each active session including:
- Session ID
- Platform
- Conversation ID
- URL
- Status
- Last activity time`,

  inputSchema: {
    type: 'object',
    properties: {
      includeHealth: {
        type: 'boolean',
        description: 'Include health check for each session (slower)',
        default: false,
      },
    },
  },
};

/**
 * Handle list sessions request
 * 
 * @param {Object} args
 * @returns {Object} Session list
 */
export async function handleListSessions(args) {
  const { includeHealth = false } = args;

  const sessionWorkflow = getSessionWorkflow();
  const sessions = sessionWorkflow.listSessions();

  const result = [];

  for (const session of sessions) {
    const info = {
      sessionId: session.sessionId,
      platform: session.metadata?.platform,
      conversationId: session.metadata?.conversationId,
      url: session.metadata?.url,
      status: session.status,
      createdAt: session.createdAt,
      lastActivity: session.lastActivity,
    };

    if (includeHealth) {
      const health = await sessionWorkflow.checkSessionHealth(session.sessionId);
      info.healthy = health.healthy;
      info.healthReason = health.reason;
    }

    result.push(info);
  }

  return {
    success: true,
    count: result.length,
    sessions: result,
  };
}
