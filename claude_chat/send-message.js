/**
 * taey_send_message Tool
 * 
 * Send a message to the AI platform
 * 
 * CRITICAL: This tool enforces validation. If the plan requires attachments
 * that haven't been attached, the send will be BLOCKED.
 * 
 * @module mcp/tools/send-message
 */

import { getMessageWorkflow } from '../../workflow/message-workflow.js';

/**
 * Tool definition
 */
export const sendMessageTool = {
  name: 'taey_send_message',
  description: `Send a message to the AI platform.

VALIDATION ENFORCEMENT:
If you called taey_plan_message with requiredAttachments, this tool will BLOCK
the send until those attachments are actually attached. You'll get a clear
error message telling you exactly what's missing.

WORKFLOW OPTIONS:
A) Simple message (no attachments):
   1. taey_plan_message (or skip if no validation needed)
   2. taey_send_message

B) Message with attachments:
   1. taey_plan_message with requiredAttachments
   2. taey_attach_files
   3. taey_validate_step step="attach_files"
   4. taey_send_message

C) Quick send (skipValidation=true):
   - Bypasses all validation checks
   - Use only when you're sure no attachments are needed
   - NOT RECOMMENDED for production workflows`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      message: {
        type: 'string',
        description: 'Message to send (if not already typed)',
      },
      waitForResponse: {
        type: 'boolean',
        description: 'Wait for AI response after sending (default: true)',
        default: true,
      },
      timeout: {
        type: 'number',
        description: 'Max time to wait for response in ms (default: 300000 = 5 min)',
        default: 300000,
      },
      skipValidation: {
        type: 'boolean',
        description: 'Skip validation enforcement (NOT RECOMMENDED)',
        default: false,
      },
    },
    required: ['sessionId'],
  },
};

/**
 * Handle send message request
 * 
 * @param {Object} args
 * @returns {Object} Result with response
 */
export async function handleSendMessage(args) {
  const {
    sessionId,
    message,
    waitForResponse = true,
    timeout = 300000,
    skipValidation = false,
  } = args;

  const messageWorkflow = getMessageWorkflow();

  // If message provided, type it first
  if (message) {
    // Validate plan step if not skipping validation
    if (!skipValidation) {
      await messageWorkflow.validateStep(sessionId, 'plan');
    }

    // Type the message
    await messageWorkflow.typeMessage(sessionId, message);

    // Validate type step
    if (!skipValidation) {
      await messageWorkflow.validateStep(sessionId, 'type_message');
    }

    // Store user message
    await messageWorkflow.storeUserMessage(sessionId, message);
  }

  // Click send (this enforces validation)
  const sendResult = await messageWorkflow.clickSend(sessionId);

  if (!sendResult.success) {
    // Send was blocked by validation
    return {
      success: false,
      blocked: true,
      reason: sendResult.reason,
      requiredAction: sendResult.requiredAction,
      screenshot: sendResult.screenshot,
      requirements: sendResult.requirements,
      actualAttachments: sendResult.actualAttachments,
      message: `SEND BLOCKED: ${sendResult.reason}. ${sendResult.requiredAction}`,
    };
  }

  // Wait for response if requested
  if (waitForResponse) {
    const responseResult = await messageWorkflow.waitForResponse(sessionId, { timeout });
    const extracted = await messageWorkflow.extractResponse(sessionId);

    return {
      success: true,
      sent: true,
      response: extracted.content,
      responseLength: extracted.contentLength,
      detectionMethod: responseResult.detectionMethod,
      confidence: responseResult.confidence,
      duration: responseResult.duration,
      screenshots: {
        sent: sendResult.screenshot,
        response: extracted.screenshot,
      },
    };
  }

  return {
    success: true,
    sent: true,
    waitingForResponse: false,
    screenshot: sendResult.screenshot,
    message: 'Message sent. Call taey_extract_response to get the response when ready.',
  };
}
