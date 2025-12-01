/**
 * Attachment Workflow
 * 
 * Purpose: Orchestrate file attachment with validation enforcement
 * 
 * CRITICAL: This was the main source of failures in v1.
 * Key fixes incorporated:
 * 1. Dynamic browser name (not hardcoded)
 * 2. Split directory/filename navigation
 * 3. Explicit attachFile() calls per platform
 * 4. Preserve actualAttachments in checkpoints
 * 
 * @module workflow/attachment-workflow
 */

import path from 'path';
import fs from 'fs';
import { getSessionWorkflow } from './session-workflow.js';
import { ValidationStore } from '../core/database/validation-store.js';
import { getTiming } from '../core/platform/bridge-factory.js';

/**
 * Attachment Workflow Manager
 */
class AttachmentWorkflow {
  constructor() {
    this.validationStore = null;
    this.initialized = false;
  }

  async initialize() {
    if (this.initialized) return;
    
    this.validationStore = new ValidationStore();
    await this.validationStore.initialize();
    
    this.initialized = true;
  }

  /**
   * Attach a single file to the chat
   * 
   * @param {string} sessionId
   * @param {string} filePath - Absolute path to file
   * @param {Object} options
   * @returns {Object} Result with screenshot
   */
  async attachFile(sessionId, filePath, options = {}) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const adapter = sessionWorkflow.getAdapter(sessionId);
    const session = sessionWorkflow.getSession(sessionId);
    
    // Validate file exists
    if (!fs.existsSync(filePath)) {
      throw new Error(`File not found: ${filePath}`);
    }
    
    const fileName = path.basename(filePath);
    const dirPath = path.dirname(filePath);
    
    console.log(`[attachment-workflow] Attaching file: ${fileName}`);
    console.log(`  Directory: ${dirPath}`);
    
    try {
      // 1. Click attachment entry point (platform-specific menu)
      await adapter.clickAttachmentEntryPoint();
      
      // Wait for file dialog to spawn
      await this.sleep(getTiming('FILE_DIALOG_SPAWN'));
      
      // 2. Navigate file picker using platform bridge
      // CRITICAL FIX: Split directory and filename navigation
      await adapter.bridge.navigateFilePicker(dirPath, fileName);
      
      // Wait for upload to process
      await this.sleep(getTiming('FILE_UPLOAD_PROCESS'));
      
      // 3. Take screenshot to verify attachment
      const screenshot = await adapter.screenshot(`attach-${fileName}`);
      
      // 4. Verify attachment pill is visible (platform-specific)
      const verified = await this.verifyAttachmentVisible(adapter, fileName);
      
      if (!verified) {
        console.warn(`[attachment-workflow] Could not verify attachment pill for ${fileName}`);
      }
      
      console.log(`[attachment-workflow] File attached: ${fileName}`);
      
      return {
        success: true,
        filePath,
        fileName,
        screenshot,
        verified
      };
      
    } catch (error) {
      const screenshot = await adapter.screenshot(`attach-failed-${fileName}`);
      console.error(`[attachment-workflow] Failed to attach ${fileName}: ${error.message}`);
      
      return {
        success: false,
        filePath,
        fileName,
        screenshot,
        error: error.message
      };
    }
  }

  /**
   * Attach multiple files with validation tracking
   * 
   * @param {string} sessionId
   * @param {Array<string>} filePaths - Array of absolute file paths
   * @param {Object} options
   * @returns {Object} Results for all attachments
   */
  async attachFiles(sessionId, filePaths, options = {}) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const session = sessionWorkflow.getSession(sessionId);
    const conversationId = session.metadata.conversationId;
    
    console.log(`[attachment-workflow] Attaching ${filePaths.length} files`);
    
    const results = [];
    const successfulAttachments = [];
    
    for (const filePath of filePaths) {
      const result = await this.attachFile(sessionId, filePath, options);
      results.push(result);
      
      if (result.success) {
        successfulAttachments.push({
          path: filePath,
          name: result.fileName
        });
      }
      
      // Small delay between attachments
      await this.sleep(500);
    }
    
    // CRITICAL: Create checkpoint with actualAttachments
    // This preserves the attachment data for validation enforcement
    await this.validationStore.createCheckpoint({
      conversationId,
      sessionId,
      step: 'attach_files',
      status: 'completed',
      actualAttachments: successfulAttachments,
      note: `Attached ${successfulAttachments.length}/${filePaths.length} files`,
      metadata: {
        requested: filePaths.length,
        successful: successfulAttachments.length,
        failed: filePaths.length - successfulAttachments.length
      }
    });
    
    const allSuccess = results.every(r => r.success);
    
    return {
      success: allSuccess,
      total: filePaths.length,
      successful: successfulAttachments.length,
      failed: filePaths.length - successfulAttachments.length,
      results,
      actualAttachments: successfulAttachments
    };
  }

  /**
   * Verify an attachment pill is visible in the UI
   * 
   * @param {BasePlatformAdapter} adapter
   * @param {string} fileName
   * @returns {boolean}
   */
  async verifyAttachmentVisible(adapter, fileName) {
    try {
      // Try to find attachment pill containing filename
      const pillSelectors = [
        `[data-testid*="attachment"]:has-text("${fileName}")`,
        `[class*="attachment"]:has-text("${fileName}")`,
        `[class*="pill"]:has-text("${fileName}")`,
        `[class*="file"]:has-text("${fileName}")`,
        // Partial match for truncated filenames
        `[data-testid*="attachment"]`,
        `[class*="attachment-pill"]`
      ];
      
      for (const selector of pillSelectors) {
        try {
          const pill = await adapter.page.$(selector);
          if (pill) {
            return true;
          }
        } catch {}
      }
      
      return false;
    } catch {
      return false;
    }
  }

  /**
   * Validate that attachments match requirements
   * 
   * @param {string} sessionId
   * @param {Array<string>} requiredFiles - Required file paths
   * @returns {Object} Validation result
   */
  async validateAttachments(sessionId, requiredFiles) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const session = sessionWorkflow.getSession(sessionId);
    const conversationId = session.metadata.conversationId;
    
    // Get latest checkpoint
    const checkpoint = await this.validationStore.getLatestCheckpoint(conversationId);
    
    if (!checkpoint) {
      return {
        valid: false,
        error: 'No checkpoint found',
        required: requiredFiles.length,
        actual: 0
      };
    }
    
    const actualAttachments = checkpoint.actualAttachments || [];
    const actualPaths = actualAttachments.map(a => a.path);
    
    // Check all required files are attached
    const missing = requiredFiles.filter(f => !actualPaths.includes(f));
    
    if (missing.length > 0) {
      return {
        valid: false,
        error: `Missing attachments: ${missing.join(', ')}`,
        required: requiredFiles.length,
        actual: actualAttachments.length,
        missing
      };
    }
    
    return {
      valid: true,
      required: requiredFiles.length,
      actual: actualAttachments.length,
      attachments: actualAttachments
    };
  }

  /**
   * Get current attachment status
   * 
   * @param {string} sessionId
   * @returns {Object} Attachment status
   */
  async getAttachmentStatus(sessionId) {
    await this.initialize();
    
    const sessionWorkflow = getSessionWorkflow();
    const session = sessionWorkflow.getSession(sessionId);
    const conversationId = session.metadata.conversationId;
    
    const checkpoint = await this.validationStore.getLatestCheckpoint(conversationId);
    
    if (!checkpoint) {
      return {
        hasAttachments: false,
        count: 0,
        attachments: []
      };
    }
    
    // Get requirements from plan step
    const planCheckpoint = await this.validationStore.getCheckpointByStep(conversationId, 'plan');
    const requirements = planCheckpoint?.requirements || {};
    
    return {
      hasAttachments: (checkpoint.actualAttachments?.length || 0) > 0,
      count: checkpoint.actualAttachments?.length || 0,
      attachments: checkpoint.actualAttachments || [],
      required: requirements.requiredAttachments || [],
      requirementsMet: this.checkRequirementsMet(
        checkpoint.actualAttachments || [],
        requirements.requiredAttachments || []
      )
    };
  }

  /**
   * Check if attachment requirements are met
   * 
   * @param {Array} actual - Actual attachments
   * @param {Array} required - Required attachments
   * @returns {boolean}
   */
  checkRequirementsMet(actual, required) {
    if (required.length === 0) return true;
    if (actual.length < required.length) return false;
    
    const actualPaths = actual.map(a => a.path);
    return required.every(r => actualPaths.includes(r));
  }

  /**
   * Remove all attachments (if platform supports)
   * 
   * @param {string} sessionId
   */
  async clearAttachments(sessionId) {
    const sessionWorkflow = getSessionWorkflow();
    const adapter = sessionWorkflow.getAdapter(sessionId);
    const session = sessionWorkflow.getSession(sessionId);
    
    // Try to find and click remove buttons on attachment pills
    try {
      const removeButtons = await adapter.page.$$(
        '[data-testid*="remove"], [aria-label*="Remove"], button[class*="close"]'
      );
      
      for (const btn of removeButtons) {
        await btn.click();
        await this.sleep(200);
      }
      
      // Update checkpoint
      await this.validationStore.createCheckpoint({
        conversationId: session.metadata.conversationId,
        sessionId,
        step: 'attach_files',
        status: 'cleared',
        actualAttachments: [],
        note: 'Attachments cleared'
      });
      
      return { success: true, cleared: removeButtons.length };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  /**
   * Sleep helper
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// Singleton instance
let instance = null;

/**
 * Get the attachment workflow instance
 * @returns {AttachmentWorkflow}
 */
export function getAttachmentWorkflow() {
  if (!instance) {
    instance = new AttachmentWorkflow();
  }
  return instance;
}

// Export class for testing
export { AttachmentWorkflow };
