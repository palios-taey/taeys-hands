/**
 * taey_paste_response Tool
 * 
 * Paste a response from one platform to another (cross-pollination)
 * 
 * This is a key capability for The AI Family coordination.
 * It allows Claude to share responses between platforms.
 * 
 * @module mcp/tools/paste-response
 */

import { getSessionWorkflow } from '../../workflow/session-workflow.js';
import { getMessageWorkflow } from '../../workflow/message-workflow.js';

/**
 * Tool definition
 */
export const pasteResponseTool = {
  name: 'taey_paste_response',
  description: `Paste content into a session's chat input.

This is designed for cross-pollination - sharing responses between AI platforms.

Example workflow:
1. Connect to Grok: taey_connect platform="grok"
2. Send message and get response from Grok
3. Connect to Claude: taey_connect platform="claude"
4. Paste Grok's response to Claude: taey_paste_response sessionId=claude_session content=grok_response
5. Send to Claude to get their perspective

The content is typed using human-like typing patterns to avoid detection.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID to paste into (from taey_connect)',
      },
      content: {
        type: 'string',
        description: 'Content to paste into the chat input',
      },
      prefix: {
        type: 'string',
        description: 'Optional prefix to add before the content (e.g., "Grok said:")',
      },
      suffix: {
        type: 'string',
        description: 'Optional suffix to add after the content',
      },
    },
    required: ['sessionId', 'content'],
  },
};

/**
 * Handle paste response request
 * 
 * @param {Object} args
 * @returns {Object} Result
 */
export async function handlePasteResponse(args) {
  const { sessionId, content, prefix = '', suffix = '' } = args;

  const sessionWorkflow = getSessionWorkflow();
  const adapter = sessionWorkflow.getAdapter(sessionId);

  // Build full content
  let fullContent = content;
  if (prefix) fullContent = prefix + '\n\n' + fullContent;
  if (suffix) fullContent = fullContent + '\n\n' + suffix;

  // Prepare input (focus, dismiss overlays)
  await adapter.prepareInput();

  // Type content using human-like typing
  await adapter.typeMessage(fullContent, {
    humanLike: true,
  });

  const screenshot = await adapter.screenshot('paste-response');

  return {
    success: true,
    pasted: true,
    contentLength: fullContent.length,
    screenshot,
    message: 'Content pasted. Call taey_send_message to send (or add more content first).',
  };
}
