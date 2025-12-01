/**
 * Validation Checkpoint Store
 * 
 * CRITICAL: Proactive validation enforcement system
 * 
 * This is the core safety mechanism that prevents workflow failures.
 * Key innovation: Requirement-based enforcement (not just step ordering)
 * 
 * - Stores requiredAttachments in 'plan' step
 * - Enforces attachments MUST be present before send_message
 * - Makes skipping steps mathematically impossible
 */

import { v4 as uuidv4 } from 'uuid';
import os from 'os';
import { Neo4jClient, getNeo4jClient } from './neo4j-client.js';
import {
  ValidationCheckpoint,
  ValidationStep,
  ValidationRequirements,
  CanProceedResult,
  ValidationError,
} from '../../types.js';

// ============================================================================
// Step Prerequisites
// ============================================================================

const STEP_PREREQUISITES: Record<ValidationStep, ValidationStep[]> = {
  'plan': [],
  'attach_files': ['plan'],
  'type_message': ['plan', 'attach_files'],  // Can skip attach_files if no attachments required
  'click_send': ['type_message'],
  'wait_response': ['click_send'],
  'extract_response': ['click_send', 'wait_response'],  // Can skip wait_response
};

// ============================================================================
// Validation Checkpoint Store
// ============================================================================

export class ValidationCheckpointStore {
  private readonly client: Neo4jClient;
  private readonly validator: string;
  private initialized = false;
  
  constructor(client?: Neo4jClient) {
    this.client = client || getNeo4jClient();
    this.validator = `${os.hostname()}-claude`;
  }
  
  /**
   * Initialize schema
   */
  async initSchema(): Promise<void> {
    if (this.initialized) return;
    
    await this.client.connect();
    
    const constraints = [
      'CREATE CONSTRAINT validation_checkpoint_id IF NOT EXISTS FOR (v:ValidationCheckpoint) REQUIRE v.id IS UNIQUE',
    ];
    
    const indexes = [
      'CREATE INDEX validation_conversation IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.conversationId)',
      'CREATE INDEX validation_step IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.step)',
      'CREATE INDEX validation_timestamp IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.timestamp)',
      'CREATE INDEX validation_validated IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.validated)',
    ];
    
    for (const query of [...constraints, ...indexes]) {
      try {
        await this.client.run(query);
      } catch (error) {
        const msg = String(error);
        if (!msg.includes('already exists')) {
          console.error(`[ValidationStore] Schema error: ${msg}`);
        }
      }
    }
    
    this.initialized = true;
    console.log('[ValidationCheckpointStore] Schema initialized');
  }
  
  // ==========================================================================
  // Core CRUD Operations
  // ==========================================================================
  
  /**
   * Create a validation checkpoint
   */
  async createCheckpoint(options: {
    conversationId: string;
    step: ValidationStep;
    validated: boolean;
    notes: string;
    screenshot?: string;
    requiredAttachments?: string[];
    actualAttachments?: string[];
  }): Promise<ValidationCheckpoint> {
    const id = uuidv4();
    const now = new Date().toISOString();
    
    const result = await this.client.runSingle<{ v: ValidationCheckpoint }>(`
      MATCH (c:Conversation { id: $conversationId })
      CREATE (v:ValidationCheckpoint {
        id: $id,
        conversationId: $conversationId,
        step: $step,
        validated: $validated,
        notes: $notes,
        screenshot: $screenshot,
        validator: $validator,
        timestamp: datetime($now),
        requiredAttachments: $requiredAttachments,
        actualAttachments: $actualAttachments
      })
      CREATE (v)-[:IN_CONVERSATION]->(c)
      RETURN v
    `, {
      id,
      conversationId: options.conversationId,
      step: options.step,
      validated: options.validated,
      notes: options.notes,
      screenshot: options.screenshot || null,
      validator: this.validator,
      requiredAttachments: options.requiredAttachments || [],
      actualAttachments: options.actualAttachments || [],
      now,
    });
    
    return result?.v || {
      id,
      conversationId: options.conversationId,
      step: options.step,
      validated: options.validated,
      notes: options.notes,
      screenshot: options.screenshot,
      validator: this.validator,
      timestamp: new Date(now),
      requiredAttachments: options.requiredAttachments || [],
      actualAttachments: options.actualAttachments || [],
    };
  }
  
  /**
   * Get last validation for conversation
   */
  async getLastValidation(conversationId: string): Promise<ValidationCheckpoint | null> {
    const result = await this.client.runSingle<{ v: ValidationCheckpoint }>(`
      MATCH (v:ValidationCheckpoint { conversationId: $conversationId })
      RETURN v
      ORDER BY v.timestamp DESC
      LIMIT 1
    `, { conversationId });
    
    return result?.v || null;
  }
  
  /**
   * Get last VALIDATED checkpoint (validated=true)
   */
  async getLastValidatedStep(conversationId: string): Promise<ValidationCheckpoint | null> {
    const result = await this.client.runSingle<{ v: ValidationCheckpoint }>(`
      MATCH (v:ValidationCheckpoint { conversationId: $conversationId, validated: true })
      RETURN v
      ORDER BY v.timestamp DESC
      LIMIT 1
    `, { conversationId });
    
    return result?.v || null;
  }
  
  /**
   * Check if a specific step is validated
   */
  async isStepValidated(conversationId: string, step: ValidationStep): Promise<boolean> {
    const result = await this.client.runSingle<{ v: ValidationCheckpoint }>(`
      MATCH (v:ValidationCheckpoint { conversationId: $conversationId, step: $step, validated: true })
      RETURN v
      ORDER BY v.timestamp DESC
      LIMIT 1
    `, { conversationId, step });
    
    return result !== null;
  }
  
  /**
   * Get entire validation chain for conversation
   */
  async getValidationChain(conversationId: string): Promise<ValidationCheckpoint[]> {
    const results = await this.client.run<{ v: ValidationCheckpoint }>(`
      MATCH (v:ValidationCheckpoint { conversationId: $conversationId })
      RETURN v
      ORDER BY v.timestamp ASC
    `, { conversationId });
    
    return results.map(r => r.v);
  }
  
  // ==========================================================================
  // CRITICAL: Requirement-Based Enforcement
  // ==========================================================================
  
  /**
   * Check if conversation requires attachments (from plan step)
   * 
   * This is the KEY method for attachment enforcement.
   * Returns requirements from the validated 'plan' checkpoint.
   */
  async requiresAttachments(conversationId: string): Promise<ValidationRequirements> {
    // Find the validated 'plan' checkpoint
    const result = await this.client.runSingle<{ v: ValidationCheckpoint }>(`
      MATCH (v:ValidationCheckpoint { conversationId: $conversationId, step: 'plan', validated: true })
      RETURN v
      ORDER BY v.timestamp DESC
      LIMIT 1
    `, { conversationId });
    
    if (!result?.v) {
      return { required: false, files: [], count: 0 };
    }
    
    const files = result.v.requiredAttachments || [];
    return {
      required: files.length > 0,
      files,
      count: files.length,
    };
  }
  
  /**
   * Check if can proceed to next step (with requirement enforcement)
   * 
   * This method implements the PROACTIVE validation:
   * - Not just "did previous step happen"
   * - But "are all REQUIREMENTS met"
   */
  async canProceedToStep(conversationId: string, nextStep: ValidationStep): Promise<CanProceedResult> {
    // Get last validated step
    const lastValidated = await this.getLastValidatedStep(conversationId);
    
    // Check prerequisites
    const prerequisites = STEP_PREREQUISITES[nextStep];
    
    // Special case: 'plan' has no prerequisites
    if (prerequisites.length === 0) {
      return {
        canProceed: true,
        reason: 'No prerequisites required',
        lastValidated: lastValidated?.step || null,
      };
    }
    
    // Check if ANY prerequisite is satisfied
    let hasPrerequisite = false;
    for (const prereq of prerequisites) {
      const isValidated = await this.isStepValidated(conversationId, prereq);
      if (isValidated) {
        hasPrerequisite = true;
        break;
      }
    }
    
    if (!hasPrerequisite) {
      return {
        canProceed: false,
        reason: `Missing prerequisite: need one of [${prerequisites.join(', ')}] validated`,
        lastValidated: lastValidated?.step || null,
      };
    }
    
    // CRITICAL: For type_message and click_send, check attachment requirements
    if (nextStep === 'type_message' || nextStep === 'click_send') {
      const requirements = await this.requiresAttachments(conversationId);
      
      if (requirements.required) {
        // MUST have attach_files validated
        const attachValidated = await this.isStepValidated(conversationId, 'attach_files');
        
        if (!attachValidated) {
          return {
            canProceed: false,
            reason: `Draft plan requires ${requirements.count} attachment(s): ${requirements.files.join(', ')}. ` +
                    `You MUST call taey_attach_files and validate before sending.`,
            lastValidated: lastValidated?.step || null,
          };
        }
        
        // Get the attach_files checkpoint and verify count
        const attachCheckpoint = await this.client.runSingle<{ v: ValidationCheckpoint }>(`
          MATCH (v:ValidationCheckpoint { conversationId: $conversationId, step: 'attach_files', validated: true })
          RETURN v
          ORDER BY v.timestamp DESC
          LIMIT 1
        `, { conversationId });
        
        const actualCount = attachCheckpoint?.v?.actualAttachments?.length || 0;
        
        if (actualCount < requirements.count) {
          return {
            canProceed: false,
            reason: `Required ${requirements.count} attachment(s) but only ${actualCount} validated. ` +
                    `Missing: ${requirements.files.slice(actualCount).join(', ')}`,
            lastValidated: lastValidated?.step || null,
          };
        }
      }
    }
    
    return {
      canProceed: true,
      reason: 'All prerequisites and requirements satisfied',
      lastValidated: lastValidated?.step || null,
    };
  }
  
  // ==========================================================================
  // Enforcement Helpers
  // ==========================================================================
  
  /**
   * Enforce prerequisites before action (throws if cannot proceed)
   */
  async enforcePrerequisites(conversationId: string, step: ValidationStep): Promise<void> {
    const result = await this.canProceedToStep(conversationId, step);
    
    if (!result.canProceed) {
      throw new ValidationError(
        `Validation checkpoint failed: ${result.reason}`,
        this.getSuggestion(step, result)
      );
    }
  }
  
  /**
   * Get suggestion for how to proceed
   */
  private getSuggestion(step: ValidationStep, result: CanProceedResult): string {
    switch (step) {
      case 'attach_files':
        return 'Call taey_validate_step with step="plan", validated=true, and requiredAttachments list first.';
      
      case 'type_message':
      case 'click_send':
        if (result.reason.includes('attachment')) {
          return 'Call taey_attach_files with the required files, then taey_validate_step with step="attach_files", validated=true.';
        }
        return `Validate the ${result.lastValidated || 'plan'} step first.`;
      
      default:
        return `Complete the prerequisite step(s) before ${step}.`;
    }
  }
  
  /**
   * Create pending checkpoint (validated=false) for actions that need verification
   */
  async createPendingCheckpoint(options: {
    conversationId: string;
    step: ValidationStep;
    notes: string;
    screenshot?: string;
    requiredAttachments?: string[];
    actualAttachments?: string[];
  }): Promise<ValidationCheckpoint> {
    return this.createCheckpoint({
      ...options,
      validated: false,
    });
  }
  
  /**
   * Validate a pending checkpoint
   */
  async validatePendingCheckpoint(
    conversationId: string,
    step: ValidationStep,
    notes: string
  ): Promise<ValidationCheckpoint | null> {
    // Find the pending checkpoint
    const result = await this.client.runSingle<{ v: ValidationCheckpoint }>(`
      MATCH (v:ValidationCheckpoint { conversationId: $conversationId, step: $step, validated: false })
      SET v.validated = true, v.notes = v.notes + ' | VALIDATED: ' + $notes
      RETURN v
    `, { conversationId, step, notes });
    
    return result?.v || null;
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let storeInstance: ValidationCheckpointStore | null = null;

export function getValidationStore(): ValidationCheckpointStore {
  if (!storeInstance) {
    storeInstance = new ValidationCheckpointStore();
  }
  return storeInstance;
}
