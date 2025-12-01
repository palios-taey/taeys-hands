/**
 * Validation Checkpoint Store
 * 
 * Purpose: Neo4j persistence for workflow validation checkpoints
 * Critical: This is the enforcement layer that prevents attachment skipping
 * 
 * Dependencies: neo4j-client
 * Exports: ValidationStore class
 * 
 * Key concepts:
 * - Checkpoints record workflow step validation
 * - Requirements (requiredAttachments) are set at plan step
 * - Enforcement checks requirements before allowing send
 * - Audit trail persists all validation decisions
 * 
 * @module core/database/validation-store
 */

import { getNeo4jClient } from './neo4j-client.js';
import { v4 as uuidv4 } from 'uuid';
import os from 'os';

/**
 * Valid workflow steps in order
 */
export const WORKFLOW_STEPS = [
  'plan',           // Create execution plan (set requirements)
  'attach_files',   // Attach files to conversation
  'type_message',   // Type prompt into input
  'click_send',     // Submit the message
  'wait_response',  // Wait for AI response
  'extract_response' // Extract response text
];

/**
 * Step prerequisites - what must be validated before each step
 */
const STEP_PREREQUISITES = {
  plan: [],
  attach_files: ['plan'],
  type_message: ['plan'], // OR attach_files - handled in logic
  click_send: ['type_message'],
  wait_response: ['click_send'],
  extract_response: ['click_send'] // OR wait_response - handled in logic
};

/**
 * Validation checkpoint store for workflow enforcement
 */
export class ValidationStore {
  constructor() {
    this.client = getNeo4jClient();
    this.validator = this.getValidatorName();
  }

  /**
   * Get the validator name (machine hostname + user)
   * 
   * @returns {string}
   */
  getValidatorName() {
    return `${os.hostname()}-claude`;
  }

  /**
   * Initialize the Neo4j schema
   * 
   * @returns {Promise<void>}
   */
  async initSchema() {
    await this.client.connect();
    
    // Create constraint for unique checkpoint IDs
    await this.client.run(`
      CREATE CONSTRAINT validation_checkpoint_id IF NOT EXISTS
      FOR (v:ValidationCheckpoint) REQUIRE v.id IS UNIQUE
    `);
    
    // Create indexes for efficient queries
    await this.client.run(`
      CREATE INDEX validation_conversation IF NOT EXISTS
      FOR (v:ValidationCheckpoint) ON (v.conversationId)
    `);
    
    await this.client.run(`
      CREATE INDEX validation_step IF NOT EXISTS
      FOR (v:ValidationCheckpoint) ON (v.step)
    `);
    
    await this.client.run(`
      CREATE INDEX validation_timestamp IF NOT EXISTS
      FOR (v:ValidationCheckpoint) ON (v.timestamp)
    `);
    
    // Compound index for common queries
    await this.client.run(`
      CREATE INDEX validation_conversation_step IF NOT EXISTS
      FOR (v:ValidationCheckpoint) ON (v.conversationId, v.step)
    `);
    
    console.log('[ValidationStore] Schema initialized');
  }

  /**
   * Create a validation checkpoint
   * 
   * @param {Object} options
   * @param {string} options.conversationId - Session/conversation ID
   * @param {string} options.step - Workflow step name
   * @param {boolean} options.validated - Whether step succeeded
   * @param {string} options.notes - What was observed (REQUIRED)
   * @param {string} [options.screenshot] - Screenshot path
   * @param {string[]} [options.requiredAttachments] - Files required by plan
   * @param {string[]} [options.actualAttachments] - Files actually attached
   * @returns {Promise<Object>} Created checkpoint
   */
  async createCheckpoint(options) {
    const {
      conversationId,
      step,
      validated,
      notes,
      screenshot,
      requiredAttachments = [],
      actualAttachments = []
    } = options;
    
    // Validate step name
    if (!WORKFLOW_STEPS.includes(step)) {
      throw new Error(`Invalid step: ${step}. Must be one of: ${WORKFLOW_STEPS.join(', ')}`);
    }
    
    // Notes are required for audit trail
    if (!notes || notes.trim().length === 0) {
      throw new Error('Notes are required for validation checkpoints');
    }
    
    const id = uuidv4();
    const timestamp = new Date().toISOString();
    
    const result = await this.client.write(`
      CREATE (v:ValidationCheckpoint {
        id: $id,
        conversationId: $conversationId,
        step: $step,
        validated: $validated,
        notes: $notes,
        screenshot: $screenshot,
        validator: $validator,
        timestamp: datetime($timestamp),
        requiredAttachments: $requiredAttachments,
        actualAttachments: $actualAttachments
      })
      RETURN v
    `, {
      id,
      conversationId,
      step,
      validated,
      notes,
      screenshot: screenshot || null,
      validator: this.validator,
      timestamp,
      requiredAttachments,
      actualAttachments
    });
    
    if (result.length === 0) {
      throw new Error('Failed to create validation checkpoint');
    }
    
    return {
      id,
      conversationId,
      step,
      validated,
      notes,
      screenshot,
      validator: this.validator,
      timestamp,
      requiredAttachments,
      actualAttachments
    };
  }

  /**
   * Get the last validation for a conversation
   * 
   * @param {string} conversationId
   * @returns {Promise<Object|null>}
   */
  async getLastValidation(conversationId) {
    const result = await this.client.read(`
      MATCH (v:ValidationCheckpoint {conversationId: $conversationId})
      RETURN v
      ORDER BY v.timestamp DESC
      LIMIT 1
    `, { conversationId });
    
    if (result.length === 0) return null;
    
    const checkpoint = result[0].v;
    return this.normalizeCheckpoint(checkpoint);
  }

  /**
   * Get a specific step's validation
   * 
   * @param {string} conversationId
   * @param {string} step
   * @returns {Promise<Object|null>}
   */
  async getStep(conversationId, step) {
    const result = await this.client.read(`
      MATCH (v:ValidationCheckpoint {conversationId: $conversationId, step: $step})
      RETURN v
      ORDER BY v.timestamp DESC
      LIMIT 1
    `, { conversationId, step });
    
    if (result.length === 0) return null;
    
    return this.normalizeCheckpoint(result[0].v);
  }

  /**
   * Check if a step is validated
   * 
   * @param {string} conversationId
   * @param {string} step
   * @returns {Promise<boolean>}
   */
  async isStepValidated(conversationId, step) {
    const validation = await this.getStep(conversationId, step);
    return validation?.validated === true;
  }

  /**
   * Get the complete validation chain for a conversation
   * 
   * @param {string} conversationId
   * @returns {Promise<Object[]>}
   */
  async getValidationChain(conversationId) {
    const result = await this.client.read(`
      MATCH (v:ValidationCheckpoint {conversationId: $conversationId})
      RETURN v
      ORDER BY v.timestamp ASC
    `, { conversationId });
    
    return result.map(r => this.normalizeCheckpoint(r.v));
  }

  /**
   * Check if conversation requires attachments
   * 
   * @param {string} conversationId
   * @returns {Promise<{required: boolean, files: string[], count: number}>}
   */
  async getRequirements(conversationId) {
    const planStep = await this.getStep(conversationId, 'plan');
    
    if (!planStep || !planStep.validated) {
      return { required: false, files: [], count: 0 };
    }
    
    const files = planStep.requiredAttachments || [];
    
    return {
      required: files.length > 0,
      files,
      count: files.length
    };
  }

  /**
   * Check if prerequisites are met for a step
   * 
   * @param {string} conversationId
   * @param {string} nextStep
   * @returns {Promise<{canProceed: boolean, reason: string, lastValidated: string|null}>}
   */
  async canProceedToStep(conversationId, nextStep) {
    const prerequisites = STEP_PREREQUISITES[nextStep];
    
    if (!prerequisites) {
      return {
        canProceed: false,
        reason: `Unknown step: ${nextStep}`,
        lastValidated: null
      };
    }
    
    // No prerequisites - can always proceed
    if (prerequisites.length === 0) {
      return {
        canProceed: true,
        reason: 'No prerequisites required',
        lastValidated: null
      };
    }
    
    // Check if any prerequisite is validated
    for (const prereq of prerequisites) {
      const isValidated = await this.isStepValidated(conversationId, prereq);
      if (isValidated) {
        return {
          canProceed: true,
          reason: `Prerequisite '${prereq}' is validated`,
          lastValidated: prereq
        };
      }
    }
    
    // Special handling for steps with OR prerequisites
    if (nextStep === 'type_message') {
      const attachValidated = await this.isStepValidated(conversationId, 'attach_files');
      if (attachValidated) {
        return {
          canProceed: true,
          reason: "Prerequisite 'attach_files' is validated",
          lastValidated: 'attach_files'
        };
      }
    }
    
    if (nextStep === 'extract_response') {
      const waitValidated = await this.isStepValidated(conversationId, 'wait_response');
      if (waitValidated) {
        return {
          canProceed: true,
          reason: "Prerequisite 'wait_response' is validated",
          lastValidated: 'wait_response'
        };
      }
    }
    
    // Prerequisites not met
    const last = await this.getLastValidation(conversationId);
    return {
      canProceed: false,
      reason: `Step '${nextStep}' requires one of [${prerequisites.join(', ')}] to be validated first`,
      lastValidated: last?.step || null
    };
  }

  /**
   * CRITICAL: Enforce validation before send_message
   * This is the proactive enforcement that prevents attachment skipping
   * 
   * @param {string} conversationId
   * @returns {Promise<{allowed: boolean, error?: string}>}
   */
  async enforceBeforeSend(conversationId) {
    // Get requirements from plan step
    const requirements = await this.getRequirements(conversationId);
    
    if (requirements.required) {
      // MUST have attach_files step validated
      const attachStep = await this.getStep(conversationId, 'attach_files');
      
      if (!attachStep) {
        return {
          allowed: false,
          error: `Cannot send: Plan requires ${requirements.count} attachment(s). ` +
                 `Use taey_attach_files() first, then taey_validate_step(step='attach_files', validated=true).`
        };
      }
      
      if (!attachStep.validated) {
        return {
          allowed: false,
          error: `Cannot send: Attachment step not validated. ` +
                 `Review screenshot and call taey_validate_step(step='attach_files', validated=true).`
        };
      }
      
      // Check attachment count matches
      const actualCount = attachStep.actualAttachments?.length || 0;
      if (actualCount !== requirements.count) {
        return {
          allowed: false,
          error: `Cannot send: Plan requires ${requirements.count} attachment(s) ` +
                 `but only ${actualCount} were attached. ` +
                 `Attach missing files with taey_attach_files().`
        };
      }
      
      // All requirements met
      return { allowed: true };
    }
    
    // No attachments required - just need plan validated
    const planStep = await this.getStep(conversationId, 'plan');
    
    if (!planStep || !planStep.validated) {
      return {
        allowed: false,
        error: `Cannot send: Plan step not validated. ` +
               `Use taey_validate_step(step='plan', validated=true) first.`
      };
    }
    
    return { allowed: true };
  }

  /**
   * Clear all validations for a conversation (for testing/reset)
   * 
   * @param {string} conversationId
   * @returns {Promise<number>} Number of deleted checkpoints
   */
  async clearValidations(conversationId) {
    const result = await this.client.write(`
      MATCH (v:ValidationCheckpoint {conversationId: $conversationId})
      WITH v, v.id AS id
      DELETE v
      RETURN count(id) AS deleted
    `, { conversationId });
    
    return result[0]?.deleted || 0;
  }

  /**
   * Normalize a checkpoint from Neo4j format
   * 
   * @param {Object} checkpoint
   * @returns {Object}
   */
  normalizeCheckpoint(checkpoint) {
    return {
      id: checkpoint.id,
      conversationId: checkpoint.conversationId,
      step: checkpoint.step,
      validated: checkpoint.validated,
      notes: checkpoint.notes,
      screenshot: checkpoint.screenshot || null,
      validator: checkpoint.validator,
      timestamp: checkpoint.timestamp,
      requiredAttachments: checkpoint.requiredAttachments || [],
      actualAttachments: checkpoint.actualAttachments || []
    };
  }
}

/**
 * Singleton instance
 */
let storeInstance = null;

/**
 * Get the singleton ValidationStore instance
 * 
 * @returns {ValidationStore}
 */
export function getValidationStore() {
  if (!storeInstance) {
    storeInstance = new ValidationStore();
  }
  return storeInstance;
}
