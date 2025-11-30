/**
 * Validation Checkpoints for Chat Workflow Steps
 *
 * Enforces manual validation after each workflow step to prevent runaway execution.
 * Each step must be explicitly validated before the next step can proceed.
 */

import { v4 as uuidv4 } from 'uuid';
import { getNeo4jClient } from './neo4j-client.js';
import os from 'os';

export class ValidationCheckpointStore {
  constructor(neo4jClient = null) {
    this.client = neo4jClient || getNeo4jClient();
  }

  /**
   * Get validator identity (which Claude instance is validating)
   */
  getValidatorIdentity() {
    const hostname = os.hostname();
    const machinePrefix = hostname.split('.')[0].toLowerCase();
    return `${machinePrefix}-claude`;
  }

  /**
   * Initialize validation checkpoint schema
   */
  async initSchema() {
    const queries = [
      // Constraint for uniqueness
      'CREATE CONSTRAINT validation_checkpoint_id IF NOT EXISTS FOR (v:ValidationCheckpoint) REQUIRE v.id IS UNIQUE',

      // Indexes for common queries
      'CREATE INDEX validation_conversation IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.conversationId)',
      'CREATE INDEX validation_step IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.step)',
      'CREATE INDEX validation_timestamp IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.timestamp)'
    ];

    for (const cypher of queries) {
      try {
        await this.client.write(cypher);
      } catch (err) {
        if (!err.message.includes('already exists')) {
          console.warn(`[ValidationCheckpoints] Schema warning: ${err.message}`);
        }
      }
    }

    console.log('[ValidationCheckpoints] Schema initialized');
  }

  /**
   * Create a validation checkpoint
   *
   * @param {Object} options
   * @param {string} options.conversationId
   * @param {string} options.step - 'plan' | 'attach_files' | 'type_message' | 'click_send' | etc.
   * @param {boolean} options.validated - true if step succeeded, false if failed
   * @param {string} options.notes - What the validator observed
   * @param {string} options.screenshot - Path to screenshot (optional)
   * @param {string} options.validator - Who validated (optional, auto-detected)
   * @returns {Object} Checkpoint record
   */
  async createCheckpoint(options) {
    const checkpoint = {
      id: uuidv4(),
      conversationId: options.conversationId,
      step: options.step,
      validated: options.validated,
      notes: options.notes,
      screenshot: options.screenshot || null,
      validator: options.validator || this.getValidatorIdentity(),
      timestamp: new Date().toISOString()
    };

    await this.client.write(
      `MATCH (c:Conversation {id: $conversationId})
       CREATE (v:ValidationCheckpoint {
         id: $id,
         conversationId: $conversationId,
         step: $step,
         validated: $validated,
         notes: $notes,
         screenshot: $screenshot,
         validator: $validator,
         timestamp: datetime($timestamp)
       })
       CREATE (v)-[:IN_CONVERSATION]->(c)
       RETURN v`,
      checkpoint
    );

    console.log(`[ValidationCheckpoints] Created: ${checkpoint.step} (${checkpoint.validated ? 'validated' : 'failed'})`);
    return checkpoint;
  }

  /**
   * Get the most recent validation for a conversation
   *
   * @param {string} conversationId
   * @returns {Object|null} {step, validated, timestamp, notes} or null if none
   */
  async getLastValidation(conversationId) {
    const result = await this.client.read(
      `MATCH (v:ValidationCheckpoint {conversationId: $conversationId})
       RETURN v
       ORDER BY v.timestamp DESC
       LIMIT 1`,
      { conversationId }
    );

    if (!result || result.length === 0) {
      return null;
    }

    const checkpoint = result[0].v.properties || result[0].v;
    return {
      id: checkpoint.id,
      step: checkpoint.step,
      validated: checkpoint.validated,
      timestamp: checkpoint.timestamp,
      notes: checkpoint.notes,
      screenshot: checkpoint.screenshot,
      validator: checkpoint.validator
    };
  }

  /**
   * Check if a specific step is validated
   *
   * @param {string} conversationId
   * @param {string} step
   * @returns {boolean} True if step exists and is validated
   */
  async isStepValidated(conversationId, step) {
    const result = await this.client.read(
      `MATCH (v:ValidationCheckpoint {conversationId: $conversationId, step: $step})
       RETURN v
       ORDER BY v.timestamp DESC
       LIMIT 1`,
      { conversationId, step }
    );

    if (!result || result.length === 0) {
      return false;
    }

    const checkpoint = result[0].v.properties || result[0].v;
    return checkpoint.validated === true;
  }

  /**
   * Get all validations for a conversation in chronological order
   *
   * @param {string} conversationId
   * @returns {Array<Object>} Array of checkpoints
   */
  async getValidationChain(conversationId) {
    const result = await this.client.read(
      `MATCH (v:ValidationCheckpoint {conversationId: $conversationId})
       RETURN v
       ORDER BY v.timestamp ASC`,
      { conversationId }
    );

    return result.map(row => {
      const checkpoint = row.v.properties || row.v;
      return {
        id: checkpoint.id,
        step: checkpoint.step,
        validated: checkpoint.validated,
        timestamp: checkpoint.timestamp,
        notes: checkpoint.notes,
        screenshot: checkpoint.screenshot,
        validator: checkpoint.validator
      };
    });
  }

  /**
   * Check if we can proceed to a given step
   * Verifies that required previous step(s) are validated
   *
   * @param {string} conversationId
   * @param {string} nextStep - The step we want to proceed to
   * @returns {Object} {canProceed: boolean, reason: string, lastValidated: string|null}
   */
  async canProceedToStep(conversationId, nextStep) {
    const stepOrder = {
      'plan': [],  // No prerequisites
      'attach_files': ['plan'],
      'type_message': ['plan', 'attach_files'],  // Can skip attach if no files
      'click_send': ['type_message'],
      'wait_response': ['click_send'],
      'extract_response': ['click_send', 'wait_response']  // Either one
    };

    const requiredSteps = stepOrder[nextStep];
    if (!requiredSteps || requiredSteps.length === 0) {
      return {
        canProceed: true,
        reason: 'No prerequisites required',
        lastValidated: null
      };
    }

    const lastValidation = await this.getLastValidation(conversationId);

    if (!lastValidation) {
      return {
        canProceed: false,
        reason: `No validation checkpoints found. Must validate one of: ${requiredSteps.join(', ')}`,
        lastValidated: null
      };
    }

    if (!requiredSteps.includes(lastValidation.step)) {
      return {
        canProceed: false,
        reason: `Last validated step was '${lastValidation.step}'. Must validate one of: ${requiredSteps.join(', ')}`,
        lastValidated: lastValidation.step
      };
    }

    if (!lastValidation.validated) {
      return {
        canProceed: false,
        reason: `Last step '${lastValidation.step}' was marked as failed. Fix and re-validate before proceeding.`,
        lastValidated: lastValidation.step
      };
    }

    return {
      canProceed: true,
      reason: `Step '${lastValidation.step}' validated successfully`,
      lastValidated: lastValidation.step
    };
  }
}
