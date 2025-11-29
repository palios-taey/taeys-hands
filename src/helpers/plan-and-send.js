/**
 * Helper for Claude Code to plan and execute chat messages
 * Implements the draft → execute workflow from 6SIGMA_PLAN.md
 */

import { DraftMessagePlanner } from '../core/draft-message.js';

/**
 * Plan a message before sending
 * This creates a draft in Neo4j with all the execution details
 *
 * @param {Object} options
 * @param {string} options.sessionId - Taey session ID
 * @param {string} options.platform - Platform name (claude, grok, etc.)
 * @param {string} options.intent - Intent type (dream-sessions, etc.) - optional
 * @param {string} options.content - The message content
 * @param {Array<string>} options.attachments - File paths to attach
 * @param {Array<Object>} options.pastedContent - Content pasted from other sessions
 * @returns {Promise<Object>} Draft message with execution plan
 */
export async function planMessage(options) {
  const planner = new DraftMessagePlanner();

  // If intent provided, use Family Intelligence to build plan
  if (options.intent) {
    const plan = await planner.planFromIntent(options);
    const draft = await planner.createDraftMessage(plan);
    return {
      draftId: draft.id,
      plan: {
        platform: plan.platform,
        content: plan.content,
        attachments: plan.attachments,
        pastedContent: plan.pastedContent,
        model: plan.metadata.model,
        mode: plan.metadata.mode
      }
    };
  }

  // Otherwise, create draft from explicit options
  const draft = await planner.createDraftMessage({
    conversationId: options.sessionId,
    platform: options.platform,
    content: options.content,
    attachments: options.attachments || [],
    pastedContent: options.pastedContent || [],
    metadata: options.metadata || {}
  });

  return {
    draftId: draft.id,
    plan: {
      platform: options.platform,
      content: options.content,
      attachments: options.attachments || [],
      pastedContent: options.pastedContent || []
    }
  };
}

/**
 * Execute a planned message
 * Runs the execution plan using MCP tools, then marks draft as sent
 *
 * @param {Object} options
 * @param {string} options.draftId - Draft message ID from planMessage()
 * @param {Object} mcpTools - MCP tool functions (taey_attach_files, taey_send_message, etc.)
 * @returns {Promise<Object>} Execution result
 */
export async function executeMessage(options, mcpTools) {
  const planner = new DraftMessagePlanner();

  // Get the draft plan
  const draft = await planner.getDraftMessage(options.draftId);

  console.log(`[PlanAndSend] Executing draft ${options.draftId} for ${draft.platform}`);

  try {
    // Step 1: Attach files if needed
    if (draft.attachments && draft.attachments.length > 0) {
      console.log(`[PlanAndSend] Attaching ${draft.attachments.length} file(s)...`);
      await mcpTools.taey_attach_files({
        sessionId: draft.conversationId,
        filePaths: draft.attachments
      });
    }

    // Step 2: Handle pasted content if needed
    if (draft.pastedContent && draft.pastedContent.length > 0) {
      console.log(`[PlanAndSend] Processing ${draft.pastedContent.length} pasted section(s)...`);
      // Pasted content is already embedded in draft.content
      // (We extracted and composed it during planMessage)
      // So nothing extra to do here - it's in the message text
    }

    // Step 3: Send the message
    console.log(`[PlanAndSend] Sending message...`);
    const sendResult = await mcpTools.taey_send_message({
      sessionId: draft.conversationId,
      message: draft.content,
      attachments: draft.attachments,
      waitForResponse: options.waitForResponse || false
    });

    // Step 4: Mark draft as sent
    console.log(`[PlanAndSend] Marking draft as sent...`);
    await planner.markAsSent(options.draftId);

    return {
      success: true,
      draftId: options.draftId,
      sendResult
    };

  } catch (error) {
    console.error(`[PlanAndSend] Execution failed:`, error.message);
    // Draft stays unsent on failure - can retry or abandon
    throw error;
  }
}

/**
 * Convenience function: plan and execute in one call
 *
 * @param {Object} options - Same as planMessage options
 * @param {Object} mcpTools - MCP tool functions
 * @param {boolean} waitForResponse - Wait for AI response after sending
 * @returns {Promise<Object>} Complete result with draft and execution info
 */
export async function planAndSendMessage(options, mcpTools, waitForResponse = false) {
  // Plan
  const { draftId, plan } = await planMessage(options);

  console.log(`[PlanAndSend] Created plan ${draftId}:`);
  console.log(`   Platform: ${plan.platform}`);
  console.log(`   Attachments: ${plan.attachments?.length || 0}`);
  console.log(`   Pasted sections: ${plan.pastedContent?.length || 0}`);
  if (plan.model) console.log(`   Model: ${plan.model}`);
  if (plan.mode) console.log(`   Mode: ${plan.mode}`);

  // Execute
  const result = await executeMessage({ draftId, waitForResponse }, mcpTools);

  return {
    draftId,
    plan,
    ...result
  };
}
