/**
 * taey_enable_research_mode Tool
 * 
 * Enable research/deep thinking mode on the AI platform
 * 
 * @module mcp/tools/enable-research
 */

import { getSessionWorkflow } from '../../workflow/session-workflow.js';

/**
 * Mode options by platform
 */
const MODE_OPTIONS = {
  claude: {
    modes: ['Extended Thinking', 'Research', 'Web Search'],
    description: 'Toggle via Tools menu',
  },
  chatgpt: {
    modes: ['Deep research', 'Agent mode', 'Web search', 'GitHub'],
    description: 'Modes accessed via + menu',
  },
  gemini: {
    modes: ['Deep Research', 'Deep Think'],
    description: 'Toggle via toolbox drawer',
  },
  grok: {
    modes: [],
    description: 'Use Expert or Heavy model for deeper thinking',
  },
  perplexity: {
    modes: ['search', 'research', 'studio'],
    description: 'Mode selection via radio buttons',
  },
};

/**
 * Tool definition
 */
export const enableResearchTool = {
  name: 'taey_enable_research_mode',
  description: `Enable research/deep thinking mode on the AI platform.

Modes by platform:
- Claude: Extended Thinking, Research, Web Search (via Tools menu)
- ChatGPT: Deep research, Agent mode, Web search (via + menu)
- Gemini: Deep Research, Deep Think (via toolbox drawer)
- Grok: Use Expert/Heavy model instead (no separate modes)
- Perplexity: search, research, studio (via radio buttons)

Set enabled=false to disable/switch back to default mode.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      enabled: {
        type: 'boolean',
        description: 'Enable (true) or disable (false) research mode',
        default: true,
      },
      mode: {
        type: 'string',
        description: 'Specific mode to enable (platform-specific)',
      },
    },
    required: ['sessionId'],
  },
};

/**
 * Handle enable research mode request
 * 
 * @param {Object} args
 * @returns {Object} Result
 */
export async function handleEnableResearch(args) {
  const { sessionId, enabled = true, mode } = args;

  const sessionWorkflow = getSessionWorkflow();
  const adapter = sessionWorkflow.getAdapter(sessionId);
  const session = sessionWorkflow.getSession(sessionId);
  const platform = session.metadata.platform;

  // Check if platform has modes
  const modeInfo = MODE_OPTIONS[platform];
  if (!modeInfo || modeInfo.modes.length === 0) {
    return {
      success: false,
      error: `Research mode not available on ${platform}`,
      suggestion: modeInfo?.description || 'Use model selection instead',
    };
  }

  const result = await adapter.setResearchMode(enabled, { mode });

  return {
    success: true,
    enabled,
    mode: result.mode || mode,
    platform,
    screenshot: result.screenshot,
    note: result.note,
    availableModes: modeInfo.modes,
  };
}
