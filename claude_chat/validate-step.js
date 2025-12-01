/**
 * taey_validate_step Tool
 * 
 * Validate a workflow step (creates validated checkpoint)
 * 
 * @module mcp/tools/validate-step
 */

import { getMessageWorkflow } from '../../workflow/message-workflow.js';

/**
 * Valid workflow steps
 */
const VALID_STEPS = [
  'plan',
  'attach_files',
  'type_message',
  'click_send',
  'wait_response',
  'extract_response',
];

/**
 * Tool definition
 */
export const validateStepTool = {
  name: 'taey_validate_step',
  description: `Validate a workflow step.

Creates a validated checkpoint in the validation chain.
Required for proper validation enforcement.

Valid steps (in order):
1. plan - Initial message plan
2. attach_files - Files attached (if required)
3. type_message - Message typed into input
4. click_send - Send button clicked
5. wait_response - Response received
6. extract_response - Response extracted

CRITICAL: When validating attach_files, this preserves the actualAttachments
from the pending checkpoint, which is required for send enforcement.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      step: {
        type: 'string',
        description: `Step to validate. Options: ${VALID_STEPS.join(', ')}`,
        enum: VALID_STEPS,
      },
      note: {
        type: 'string',
        description: 'Optional note for the checkpoint',
      },
    },
    required: ['sessionId', 'step'],
  },
};

/**
 * Handle validate step request
 * 
 * @param {Object} args
 * @returns {Object} Validation result
 */
export async function handleValidateStep(args) {
  const { sessionId, step, note } = args;

  if (!VALID_STEPS.includes(step)) {
    return {
      success: false,
      error: `Invalid step: ${step}`,
      validSteps: VALID_STEPS,
    };
  }

  const messageWorkflow = getMessageWorkflow();

  const result = await messageWorkflow.validateStep(sessionId, step, { note });

  if (!result.success) {
    return {
      success: false,
      error: result.error,
      requiredStep: result.requiredStep,
      currentStep: result.currentStep,
      message: `Cannot validate "${step}". ${result.error}`,
    };
  }

  return {
    success: true,
    step,
    validated: true,
    checkpointId: result.checkpoint?.id,
    message: `Step "${step}" validated successfully`,
  };
}
