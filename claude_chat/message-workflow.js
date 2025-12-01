/**
 * Message Workflow
 * 
 * Purpose: Orchestrate message sending and response extraction
 * 
 * CRITICAL: This workflow integrates with ValidationStore to enforce
 * the validation chain. Messages cannot be sent without proper validation.
 * 
 * Flow:
 * 1. Plan step (with requirements)
 * 2. Attach files (if required)
 * 3. Type message
 * 4. Click send (BLOCKED if attachments missing)
 * 5. Wait for response
 * 6. Extract response
 * 
 * @module workflow/message-workflow
 */

import { getSessionWorkflow } from './session-workflow.js';
import { ValidationStore } from '../core/database/validation-store.js';
import { ConversationStore } from '../core/database/conversation-store.js';

/**
 * Message Workflow Manager
 */
class MessageWorkflow {
  constructor() {
    this.validationStore = null;
    this.conversationStore = null;
    this.initialized = false;
  }

  async initialize() {
    if (this.initialized) return;
    
    this.validationStore = new ValidationStore();
    await this.validationStore.initialize();
    
    this.conversationStore = new ConversationStore();
    await this.conversationStore.initialize();
    
    this.initialized = true;
  }

  /**
   * Start a new message plan
   * 
   * This creates the initial checkpoint that tracks requirements.
   * MUST be called before any message operations.
   * 
   * @param {string} sessionId - Active session
   * @param {Object} options
   * @param {string} options.message - The message to send
   * @param {Array<string>} [options.requiredAttachments] - Files that MUST be attached
   * @param {Object} [options.metadata] - Additional tracking metadata
   * @returns {Object} Plan checkpoint
   */
  async planMessage(sessionId, options = {}) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const session = sessionWorkflow.getSession(sessionId);
    
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }
    
    const conversationId = session.metadata.conversationId;
    
    // Create plan checkpoint
    const checkpoint = await this.validationStore.createCheckpoint({
      conversationId,
      sessionId,
      step: 'plan',
      status: 'pending',
      requirements: {
        message: options.message,
        requiredAttachments: options.requiredAttachments || [],
        attachmentsRequired: (options.requiredAttachments?.length || 0) > 0
      },
      metadata: options.metadata || {}
    });
    
    console.log(`[message-workflow] Plan created for ${conversationId}`);
    console.log(`  Message: ${options.message?.substring(0, 50)}...`);
    console.log(`  Required attachments: ${options.requiredAttachments?.length || 0}`);
    
    return checkpoint;
  }

  /**
   * Validate a workflow step
   * 
   * @param {string} sessionId
   * @param {string} step - Step to validate (plan, attach_files, type_message, click_send, etc.)
   * @param {Object} data - Step-specific validation data
   * @returns {Object} Validation result
   */
  async validateStep(sessionId, step, data = {}) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const session = sessionWorkflow.getSession(sessionId);
    
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }
    
    const conversationId = session.metadata.conversationId;
    
    // Get current checkpoint
    const currentCheckpoint = await this.validationStore.getLatestCheckpoint(conversationId);
    
    if (!currentCheckpoint) {
      throw new Error(`No checkpoint found for conversation ${conversationId}. Call planMessage first.`);
    }
    
    // Validate step prerequisites
    const prereqCheck = await this.validationStore.validatePrerequisites(conversationId, step);
    
    if (!prereqCheck.valid) {
      return {
        success: false,
        error: prereqCheck.error,
        requiredStep: prereqCheck.requiredStep,
        currentStep: currentCheckpoint.step
      };
    }
    
    // Create validated checkpoint
    // CRITICAL: Preserve actualAttachments when validating attach_files step
    const checkpointData = {
      conversationId,
      sessionId,
      step,
      status: 'validated',
      note: data.note || `Step ${step} validated`,
      metadata: data.metadata || {}
    };
    
    // Preserve attachment data
    if (step === 'attach_files' && data.actualAttachments) {
      checkpointData.actualAttachments = data.actualAttachments;
    } else if (currentCheckpoint.actualAttachments) {
      // Carry forward from previous checkpoint
      checkpointData.actualAttachments = currentCheckpoint.actualAttachments;
    }
    
    const checkpoint = await this.validationStore.createCheckpoint(checkpointData);
    
    console.log(`[message-workflow] Step '${step}' validated for ${conversationId}`);
    
    return {
      success: true,
      checkpoint,
      step
    };
  }

  /**
   * Type a message into the chat input
   * 
   * @param {string} sessionId
   * @param {string} message
   * @param {Object} options
   * @returns {Object} Result with screenshot
   */
  async typeMessage(sessionId, message, options = {}) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const adapter = sessionWorkflow.getAdapter(sessionId);
    const session = sessionWorkflow.getSession(sessionId);
    
    // Prepare input (focus, dismiss overlays if needed)
    await adapter.prepareInput();
    
    // Type message using human-like typing
    await adapter.typeMessage(message, options);
    
    // Take screenshot
    const screenshot = await adapter.screenshot('message-typed');
    
    // Create checkpoint
    await this.validationStore.createCheckpoint({
      conversationId: session.metadata.conversationId,
      sessionId,
      step: 'type_message',
      status: 'completed',
      note: `Typed ${message.length} characters`,
      metadata: { messageLength: message.length }
    });
    
    return {
      success: true,
      screenshot,
      messageLength: message.length
    };
  }

  /**
   * Click the send button
   * 
   * CRITICAL: This enforces validation before allowing send.
   * If attachments were required but not attached, this will FAIL.
   * 
   * @param {string} sessionId
   * @returns {Object} Result with screenshot
   */
  async clickSend(sessionId) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const adapter = sessionWorkflow.getAdapter(sessionId);
    const session = sessionWorkflow.getSession(sessionId);
    const conversationId = session.metadata.conversationId;
    
    // CRITICAL: ENFORCE VALIDATION BEFORE SEND
    const enforcement = await this.validationStore.enforceBeforeSend(conversationId);
    
    if (!enforcement.allowed) {
      console.error(`[message-workflow] SEND BLOCKED: ${enforcement.reason}`);
      
      // Take screenshot showing current state
      const screenshot = await adapter.screenshot('send-blocked');
      
      return {
        success: false,
        blocked: true,
        reason: enforcement.reason,
        requiredAction: enforcement.requiredAction,
        screenshot,
        // Include details for debugging
        requirements: enforcement.requirements,
        actualAttachments: enforcement.actualAttachments
      };
    }
    
    // Validation passed - click send
    await adapter.clickSend();
    
    const screenshot = await adapter.screenshot('send-clicked');
    
    // Create checkpoint
    await this.validationStore.createCheckpoint({
      conversationId,
      sessionId,
      step: 'click_send',
      status: 'completed',
      note: 'Message sent'
    });
    
    return {
      success: true,
      screenshot
    };
  }

  /**
   * Wait for the AI response to complete
   * 
   * @param {string} sessionId
   * @param {Object} options
   * @param {number} [options.timeout] - Max wait time in ms
   * @returns {Object} Response with content and detection metadata
   */
  async waitForResponse(sessionId, options = {}) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const adapter = sessionWorkflow.getAdapter(sessionId);
    const session = sessionWorkflow.getSession(sessionId);
    const conversationId = session.metadata.conversationId;
    
    console.log(`[message-workflow] Waiting for response on ${conversationId}...`);
    
    const startTime = Date.now();
    
    // Wait for response using Fibonacci polling
    const result = await adapter.waitForResponse(options.timeout, {
      sessionId,
      ...options
    });
    
    const duration = Date.now() - startTime;
    
    // Create checkpoint
    await this.validationStore.createCheckpoint({
      conversationId,
      sessionId,
      step: 'wait_response',
      status: 'completed',
      note: `Response received in ${duration}ms`,
      metadata: {
        detectionMethod: result.detectionMethod,
        confidence: result.confidence,
        detectionTime: result.detectionTime
      }
    });
    
    console.log(`[message-workflow] Response received in ${duration}ms`);
    console.log(`  Detection method: ${result.detectionMethod}`);
    console.log(`  Confidence: ${result.confidence}`);
    
    return {
      success: true,
      content: result.content,
      detectionMethod: result.detectionMethod,
      confidence: result.confidence,
      duration
    };
  }

  /**
   * Extract the latest response content
   * 
   * @param {string} sessionId
   * @returns {Object} Response content
   */
  async extractResponse(sessionId) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const adapter = sessionWorkflow.getAdapter(sessionId);
    const session = sessionWorkflow.getSession(sessionId);
    const conversationId = session.metadata.conversationId;
    
    // Get response text
    const content = await adapter.getLatestResponse();
    
    // Take screenshot
    const screenshot = await adapter.screenshot('response-extracted');
    
    // Create checkpoint
    await this.validationStore.createCheckpoint({
      conversationId,
      sessionId,
      step: 'extract_response',
      status: 'completed',
      note: `Extracted ${content.length} characters`
    });
    
    // Store message in Neo4j
    await this.conversationStore.addMessage({
      conversationId,
      role: 'assistant',
      content,
      metadata: {
        extractedAt: new Date().toISOString()
      }
    });
    
    return {
      success: true,
      content,
      contentLength: content.length,
      screenshot
    };
  }

  /**
   * Complete message workflow (plan → type → send → wait → extract)
   * 
   * This is a convenience method for simple messages without attachments.
   * For messages with attachments, use the individual methods.
   * 
   * @param {string} sessionId
   * @param {string} message
   * @param {Object} options
   * @returns {Object} Complete result with response
   */
  async sendAndWait(sessionId, message, options = {}) {
    // Plan (no attachments)
    await this.planMessage(sessionId, {
      message,
      requiredAttachments: []
    });
    
    // Validate plan
    await this.validateStep(sessionId, 'plan');
    
    // Type message
    await this.typeMessage(sessionId, message, options);
    
    // Validate type
    await this.validateStep(sessionId, 'type_message');
    
    // Click send
    const sendResult = await this.clickSend(sessionId);
    if (!sendResult.success) {
      return sendResult; // Return blocked result
    }
    
    // Wait for response
    await this.waitForResponse(sessionId, options);
    
    // Extract response
    const response = await this.extractResponse(sessionId);
    
    return {
      success: true,
      response: response.content,
      screenshots: {
        sent: sendResult.screenshot,
        extracted: response.screenshot
      }
    };
  }

  /**
   * Store user message in Neo4j
   * 
   * @param {string} sessionId
   * @param {string} content
   * @param {Object} options
   */
  async storeUserMessage(sessionId, content, options = {}) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const session = sessionWorkflow.getSession(sessionId);
    
    await this.conversationStore.addMessage({
      conversationId: session.metadata.conversationId,
      role: 'user',
      content,
      attachments: options.attachments || [],
      metadata: options.metadata || {}
    });
  }

  /**
   * Get validation status for a session
   * 
   * @param {string} sessionId
   * @returns {Object} Current validation state
   */
  async getValidationStatus(sessionId) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const session = sessionWorkflow.getSession(sessionId);
    
    if (!session) {
      return { error: 'Session not found' };
    }
    
    const conversationId = session.metadata.conversationId;
    const checkpoint = await this.validationStore.getLatestCheckpoint(conversationId);
    const chain = await this.validationStore.getValidationChain(conversationId);
    
    return {
      currentStep: checkpoint?.step,
      currentStatus: checkpoint?.status,
      requirements: checkpoint?.requirements,
      actualAttachments: checkpoint?.actualAttachments || [],
      chain: chain.map(c => ({ step: c.step, status: c.status }))
    };
  }
}

// Singleton instance
let instance = null;

/**
 * Get the message workflow instance
 * @returns {MessageWorkflow}
 */
export function getMessageWorkflow() {
  if (!instance) {
    instance = new MessageWorkflow();
  }
  return instance;
}

// Export class for testing
export { MessageWorkflow };
