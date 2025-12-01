/**
 * taey_select_model Tool
 * 
 * Select a model on the AI platform
 * 
 * @module mcp/tools/select-model
 */

import { getSessionWorkflow } from '../../workflow/session-workflow.js';

/**
 * Model options by platform
 */
const MODEL_OPTIONS = {
  claude: ['Opus 4.5', 'Sonnet 4', 'Haiku 4'],
  chatgpt: [], // Model selection disabled - use modes instead
  gemini: ['Thinking with 3 Pro', 'Thinking'],
  grok: ['Auto', 'Fast', 'Expert', 'Heavy', 'Grok 4.1'],
  perplexity: [], // No model selection - use modes instead
};

/**
 * Tool definition
 */
export const selectModelTool = {
  name: 'taey_select_model',
  description: `Select a model on the AI platform.

Model options by platform:
- Claude: Opus 4.5, Sonnet 4, Haiku 4
- ChatGPT: Model selection DISABLED (use taey_enable_research_mode for Deep research)
- Gemini: Thinking with 3 Pro, Thinking
- Grok: Auto, Fast, Expert, Heavy, Grok 4.1
- Perplexity: No model selection (use taey_enable_research_mode for modes)

NOTE: This can be called after connecting to switch models mid-session.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      model: {
        type: 'string',
        description: 'Model name to select',
      },
    },
    required: ['sessionId', 'model'],
  },
};

/**
 * Handle select model request
 * 
 * @param {Object} args
 * @returns {Object} Result
 */
export async function handleSelectModel(args) {
  const { sessionId, model } = args;

  const sessionWorkflow = getSessionWorkflow();
  const adapter = sessionWorkflow.getAdapter(sessionId);
  const session = sessionWorkflow.getSession(sessionId);
  const platform = session.metadata.platform;

  // Check if platform supports model selection
  const supportedModels = MODEL_OPTIONS[platform] || [];
  if (supportedModels.length === 0) {
    return {
      success: false,
      error: `Model selection not supported on ${platform}`,
      suggestion: platform === 'chatgpt' || platform === 'perplexity'
        ? 'Use taey_enable_research_mode instead'
        : 'This platform does not support model selection',
    };
  }

  const result = await adapter.selectModel(model);

  return {
    success: true,
    model: result.model,
    platform,
    screenshot: result.screenshot,
    note: result.note,
  };
}
