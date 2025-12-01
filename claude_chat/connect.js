/**
 * taey_connect Tool
 * 
 * Connect to an AI platform and create a new session
 * 
 * @module mcp/tools/connect
 */

import { getSessionWorkflow } from '../../workflow/session-workflow.js';
import { PLATFORMS } from '../../platforms/factory.js';

/**
 * Tool definition
 */
export const connectTool = {
  name: 'taey_connect',
  description: `Connect to an AI chat platform and create a new session.

Supported platforms: ${PLATFORMS.join(', ')}

Returns a sessionId that must be used for all subsequent operations.

Example usage:
1. Connect to Claude: { "platform": "claude" }
2. Connect with model: { "platform": "claude", "model": "Opus 4.5" }
3. Resume conversation: { "platform": "claude", "conversationId": "abc123" }
4. Enable research mode: { "platform": "gemini", "researchMode": true }`,

  inputSchema: {
    type: 'object',
    properties: {
      platform: {
        type: 'string',
        description: `Platform to connect to. Options: ${PLATFORMS.join(', ')}`,
        enum: PLATFORMS,
      },
      model: {
        type: 'string',
        description: 'Model to select (platform-specific). Examples: "Opus 4.5", "Expert", "Thinking with 3 Pro"',
      },
      researchMode: {
        type: 'boolean',
        description: 'Enable research/deep thinking mode if available',
      },
      conversationId: {
        type: 'string',
        description: 'Existing conversation ID to resume (optional)',
      },
    },
    required: ['platform'],
  },
};

/**
 * Handle connect request
 * 
 * @param {Object} args
 * @returns {Object} Session info
 */
export async function handleConnect(args) {
  const { platform, model, researchMode, conversationId } = args;

  // Validate platform
  if (!PLATFORMS.includes(platform)) {
    return {
      success: false,
      error: `Unknown platform: ${platform}`,
      supportedPlatforms: PLATFORMS,
    };
  }

  const sessionWorkflow = getSessionWorkflow();

  const result = await sessionWorkflow.createSession(platform, {
    model,
    researchMode,
    existingConversationId: conversationId,
  });

  return {
    success: true,
    sessionId: result.sessionId,
    conversationId: result.conversationId,
    platform: result.platform,
    url: result.url,
    model: result.model,
    researchMode: result.researchMode,
    screenshot: result.screenshot,
    message: `Connected to ${platform}. Use sessionId "${result.sessionId}" for all subsequent operations.`,
  };
}
