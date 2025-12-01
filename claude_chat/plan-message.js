/**
 * taey_plan_message Tool
 * 
 * Plan a message with requirements (MUST be called before sending)
 * 
 * This is the first step in the validation workflow.
 * It creates a checkpoint that tracks what's required for the message.
 * 
 * CRITICAL: If you specify requiredAttachments, you MUST attach those
 * files using taey_attach_files BEFORE calling taey_send_message.
 * The send will be BLOCKED if attachments are missing.
 * 
 * @module mcp/tools/plan-message
 */

import { getMessageWorkflow } from '../../workflow/message-workflow.js';

/**
 * Tool definition
 */
export const planMessageTool = {
  name: 'taey_plan_message',
  description: `Plan a message with requirements. MUST be called before sending.

This creates a validation checkpoint that tracks:
- The message to send
- Required attachments (if any)

CRITICAL WORKFLOW:
1. taey_plan_message (with requiredAttachments if needed)
2. taey_attach_files (if requiredAttachments specified)
3. taey_validate_step (validate attach_files)
4. taey_send_message (will be BLOCKED if attachments missing)

If you skip attachments when they're required, taey_send_message will fail with a clear error message telling you what to do.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      message: {
        type: 'string',
        description: 'The message to send',
      },
      requiredAttachments: {
        type: 'array',
        items: { type: 'string' },
        description: 'Array of file paths that MUST be attached before sending',
      },
    },
    required: ['sessionId', 'message'],
  },
};

/**
 * Handle plan message request
 * 
 * @param {Object} args
 * @returns {Object} Plan checkpoint
 */
export async function handlePlanMessage(args) {
  const { sessionId, message, requiredAttachments = [] } = args;

  const messageWorkflow = getMessageWorkflow();

  const checkpoint = await messageWorkflow.planMessage(sessionId, {
    message,
    requiredAttachments,
  });

  const hasAttachments = requiredAttachments.length > 0;

  return {
    success: true,
    sessionId,
    checkpointId: checkpoint.id,
    requirements: {
      message: message.substring(0, 100) + (message.length > 100 ? '...' : ''),
      attachmentsRequired: hasAttachments,
      requiredAttachments,
    },
    nextStep: hasAttachments
      ? 'Call taey_attach_files with the required files, then taey_validate_step, then taey_send_message'
      : 'Call taey_send_message to send (no attachments required)',
  };
}
