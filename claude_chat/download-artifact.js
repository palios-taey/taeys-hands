/**
 * taey_download_artifact Tool
 * 
 * Download an artifact from the AI platform
 * 
 * @module mcp/tools/download-artifact
 */

import { getSessionWorkflow } from '../../workflow/session-workflow.js';

/**
 * Artifact support by platform
 */
const ARTIFACT_SUPPORT = {
  claude: { supported: true, formats: ['markdown'] },
  chatgpt: { supported: false },
  gemini: { supported: true, formats: ['markdown', 'html'] },
  grok: { supported: false },
  perplexity: { supported: true, formats: ['markdown', 'html'] },
};

/**
 * Tool definition
 */
export const downloadArtifactTool = {
  name: 'taey_download_artifact',
  description: `Download an artifact (code, document) from the AI platform.

Artifact support by platform:
- Claude: YES (Download button, markdown)
- ChatGPT: NO
- Gemini: YES (Export menu, markdown/html)
- Grok: NO
- Perplexity: YES (Export menu, markdown/html)

The artifact is saved to the specified download path.`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      downloadPath: {
        type: 'string',
        description: 'Directory to save the artifact (default: /tmp)',
        default: '/tmp',
      },
      format: {
        type: 'string',
        description: 'Export format (markdown or html, platform-specific)',
        enum: ['markdown', 'html'],
        default: 'markdown',
      },
    },
    required: ['sessionId'],
  },
};

/**
 * Handle download artifact request
 * 
 * @param {Object} args
 * @returns {Object} Result with file path
 */
export async function handleDownloadArtifact(args) {
  const { sessionId, downloadPath = '/tmp', format = 'markdown' } = args;

  const sessionWorkflow = getSessionWorkflow();
  const adapter = sessionWorkflow.getAdapter(sessionId);
  const session = sessionWorkflow.getSession(sessionId);
  const platform = session.metadata.platform;

  // Check if platform supports artifacts
  const support = ARTIFACT_SUPPORT[platform];
  if (!support || !support.supported) {
    return {
      success: false,
      error: `Artifact download not supported on ${platform}`,
    };
  }

  const result = await adapter.downloadArtifact({ downloadPath, format });

  if (!result.success) {
    return {
      success: false,
      error: result.error,
      screenshot: result.screenshot,
    };
  }

  return {
    success: true,
    filePath: result.filePath,
    filename: result.filename,
    format,
    screenshot: result.screenshot,
  };
}
