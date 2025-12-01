/**
 * taey_attach_files Tool
 * 
 * Attach files to the chat input
 * 
 * CRITICAL: This tool properly tracks actualAttachments in checkpoints,
 * which is required for validation enforcement to work.
 * 
 * @module mcp/tools/attach-files
 */

import { getAttachmentWorkflow } from '../../workflow/attachment-workflow.js';

/**
 * Tool definition
 */
export const attachFilesTool = {
  name: 'taey_attach_files',
  description: `Attach files to the chat input.

Files must be specified as absolute paths.
Each file is attached sequentially with verification.

After attaching, call taey_validate_step with step="attach_files" to validate,
then proceed to taey_send_message.

WORKFLOW:
1. taey_plan_message with requiredAttachments=["/path/to/file1.md", "/path/to/file2.md"]
2. taey_attach_files with files=["/path/to/file1.md", "/path/to/file2.md"]
3. taey_validate_step step="attach_files"
4. taey_send_message`,

  inputSchema: {
    type: 'object',
    properties: {
      sessionId: {
        type: 'string',
        description: 'Session ID from taey_connect',
      },
      files: {
        type: 'array',
        items: { type: 'string' },
        description: 'Array of absolute file paths to attach',
      },
    },
    required: ['sessionId', 'files'],
  },
};

/**
 * Handle attach files request
 * 
 * @param {Object} args
 * @returns {Object} Attachment results
 */
export async function handleAttachFiles(args) {
  const { sessionId, files } = args;

  if (!files || files.length === 0) {
    return {
      success: false,
      error: 'No files specified',
    };
  }

  const attachmentWorkflow = getAttachmentWorkflow();

  const result = await attachmentWorkflow.attachFiles(sessionId, files);

  if (!result.success) {
    return {
      success: false,
      error: `Failed to attach all files. ${result.successful}/${result.total} succeeded.`,
      results: result.results,
      actualAttachments: result.actualAttachments,
    };
  }

  return {
    success: true,
    attached: result.successful,
    total: result.total,
    actualAttachments: result.actualAttachments,
    results: result.results.map(r => ({
      file: r.fileName,
      success: r.success,
      verified: r.verified,
      error: r.error,
    })),
    nextStep: 'Call taey_validate_step with step="attach_files", then taey_send_message',
  };
}
