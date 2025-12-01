/**
 * ChatGPT Platform Adapter
 * 
 * Purpose: ChatGPT-specific automation implementation
 * Platform: chatgpt.com
 * 
 * QUIRKS:
 * - Model selection is DISABLED (UI changed, use modes instead)
 * - Use setMode() for Deep research, Agent mode, etc.
 * - No artifact download support
 * 
 * Features:
 * - Mode selection (Deep research, Agent mode, Web search)
 * - Standard file attachment via + menu
 * 
 * @module platforms/chatgpt
 */

import { BasePlatformAdapter } from './base-adapter.js';
import { getTiming } from '../core/platform/bridge-factory.js';

/**
 * ChatGPT platform adapter
 */
export class ChatGPTAdapter extends BasePlatformAdapter {
  constructor(options) {
    super(options);
    this.name = 'chatgpt';
    this.baseUrl = 'https://chatgpt.com';
  }

  // ============================================
  // ABSTRACT IMPLEMENTATIONS
  // ============================================

  getPlatformName() {
    return 'chatgpt';
  }

  async navigateToNew() {
    await this.page.goto(`${this.baseUrl}/`, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    // ChatGPT may auto-redirect to a conversation
    const url = this.getCurrentUrl();
    const conversationId = await this.extractConversationId();
    
    return { conversationId, url };
  }

  async navigateToExisting(conversationId) {
    const url = `${this.baseUrl}/c/${conversationId}`;
    await this.page.goto(url, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    return { url: this.getCurrentUrl() };
  }

  async extractConversationId() {
    const url = this.getCurrentUrl();
    // chatgpt.com/c/{conversationId}
    const match = url.match(/\/c\/([a-zA-Z0-9-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Model selection - DISABLED
   * ChatGPT UI changed to use Auto mode by default
   * Use setMode() for deep research/thinking capabilities
   */
  async selectModel(modelName, options = {}) {
    console.log(`[chatgpt] selectModel(${modelName}) - DISABLED`);
    console.log(`  ChatGPT model selection disabled - using Auto mode`);
    console.log(`  For thinking: use setMode('Deep research') instead`);
    
    const screenshot = await this.screenshot('select-model-disabled');
    
    return {
      success: true,
      screenshot,
      model: 'Auto',
      note: 'Model selection disabled - ChatGPT uses Auto mode. Use setMode() for capabilities.'
    };
  }

  /**
   * Set a mode (Deep research, Agent mode, Web search, etc.)
   * This is the preferred way to get thinking/research on ChatGPT
   * 
   * @param {string} modeName - 'Deep research', 'Agent mode', 'Web search', 'GitHub'
   */
  async setResearchMode(enabled, options = {}) {
    const modeName = options.mode || 'Deep research';
    
    if (!enabled) {
      console.log(`[chatgpt] Disabling modes not supported - modes auto-deactivate after use`);
      const screenshot = await this.screenshot('mode-disable-skipped');
      return { success: true, screenshot, note: 'Mode disable skipped - auto-deactivates' };
    }
    
    try {
      // Click + button to open mode menu
      const plusBtn = await this.page.waitForSelector(
        this.selectors.plusButton || '[data-testid="composer-plus-btn"]',
        { timeout: 5000 }
      );
      await plusBtn.click();
      await this.sleep(getTiming('MENU_RENDER'));
      
      // Click the mode
      const modeItem = await this.page.waitForSelector(
        `text="${modeName}"`,
        { timeout: 5000 }
      );
      await modeItem.click();
      await this.sleep(500);
      
      const screenshot = await this.screenshot('set-mode');
      return { success: true, screenshot, mode: modeName, enabled: true };
    } catch (error) {
      const screenshot = await this.screenshot('set-mode-failed');
      throw new Error(`Failed to set mode "${modeName}". Screenshot: ${screenshot}`);
    }
  }

  /**
   * ChatGPT-specific file attachment
   * CRITICAL: ChatGPT's file picker UI is broken - must use direct injection
   *
   * @param {string|string[]} filePaths - File path(s) to attach
   * @returns {Promise<{success: boolean, screenshot: string}>}
   */
  async attachFile(filePaths) {
    const paths = Array.isArray(filePaths) ? filePaths : [filePaths];

    console.log(`[chatgpt] Attaching ${paths.length} file(s) via direct injection`);

    try {
      // Verify files exist
      const fs = await import('fs/promises');
      for (const filePath of paths) {
        try {
          await fs.access(filePath);
        } catch {
          throw new Error(`File not found: ${filePath}`);
        }
      }

      // Click + button to open menu
      const plusBtn = await this.page.waitForSelector(
        this.selectors.plusButton || '[data-testid="composer-plus-btn"]',
        { timeout: 5000 }
      );
      await plusBtn.click();
      await this.sleep(800);

      // Click "Add photos & files" menu item
      const addPhotosItem = await this.page.waitForSelector(
        'text="Add photos & files"',
        { timeout: 5000 }
      );
      await addPhotosItem.click();
      await this.sleep(500);

      // CRITICAL WORKAROUND: Direct file injection into hidden input
      // ChatGPT's file picker dialog is broken - bypass it entirely
      console.log(`[chatgpt] Injecting files into hidden input element`);
      const fileInput = this.page.locator('input[type="file"]').first();
      await fileInput.setInputFiles(paths);
      await this.sleep(1000);

      const screenshot = await this.screenshot('file-attached');
      console.log(`[chatgpt] Successfully attached ${paths.length} file(s)`);

      return {
        success: true,
        screenshot,
        filesAttached: paths.length
      };

    } catch (error) {
      const screenshot = await this.screenshot('attach-failed');
      throw new Error(`ChatGPT file attachment failed: ${error.message}. Screenshot: ${screenshot}`);
    }
  }

  async getLatestResponse() {
    try {
      // ChatGPT uses data-message-author-role for messages
      const containers = await this.page.$$(
        '[data-message-author-role="assistant"]'
      );
      
      if (containers.length === 0) return '';
      
      const lastContainer = containers[containers.length - 1];
      const text = await lastContainer.innerText();
      return text.trim();
    } catch (error) {
      console.warn(`[chatgpt] Error extracting response: ${error.message}`);
      return '';
    }
  }

  /**
   * Download artifact - NOT SUPPORTED
   */
  async downloadArtifact(options = {}) {
    const screenshot = await this.screenshot('download-not-supported');
    return {
      success: false,
      filePath: null,
      screenshot,
      error: 'ChatGPT does not support artifact downloads'
    };
  }

  // ============================================
  // OVERRIDES
  // ============================================

  /**
   * Override waitForResponse to detect Regenerate button
   */
  async waitForResponse(timeout = 180000, options = {}) {
    const startTime = Date.now();
    const sessionId = options.sessionId || 'unknown';
    
    try {
      // ChatGPT shows a Regenerate button when response is complete
      // Wait for it to appear (with fallback to stability)
      await this.page.waitForSelector(
        'button:has-text("Regenerate"), button[aria-label="Regenerate"]',
        { timeout: Math.min(timeout, 60000) }
      );
      
      const content = await this.getLatestResponse();
      const detectionTime = Date.now() - startTime;
      
      await this.screenshot('response-complete');
      
      return {
        content,
        detectionMethod: 'regenerateButton',
        confidence: 0.95,
        detectionTime
      };
    } catch {
      // Fall back to content stability
      console.log('[chatgpt] Regenerate button not found, using stability detection');
      return await super.waitForResponse(timeout - (Date.now() - startTime), options);
    }
  }
}

export function createChatGPTAdapter(options) {
  return new ChatGPTAdapter(options);
}
