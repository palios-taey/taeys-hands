/**
 * Claude Platform Adapter
 * 
 * Purpose: Claude-specific automation implementation
 * Platform: claude.ai
 * 
 * Features:
 * - Model selection (Opus 4.5, Sonnet 4, Haiku 4)
 * - Extended Thinking / Research mode
 * - Artifact download
 * - Standard file attachment
 * 
 * @module platforms/claude
 */

import { BasePlatformAdapter } from './base-adapter.js';
import { getTiming } from '../core/platform/bridge-factory.js';

/**
 * Claude platform adapter
 */
export class ClaudeAdapter extends BasePlatformAdapter {
  constructor(options) {
    super(options);
    this.name = 'claude';
    this.baseUrl = 'https://claude.ai';
  }

  // ============================================
  // ABSTRACT IMPLEMENTATIONS
  // ============================================

  /**
   * Get platform name
   * @returns {string}
   */
  getPlatformName() {
    return 'claude';
  }

  /**
   * Navigate to a new conversation
   * @returns {Promise<{conversationId: string, url: string}>}
   */
  async navigateToNew() {
    // Navigate to new chat URL
    await this.page.goto(`${this.baseUrl}/new`, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    // Extract conversation ID from URL (if redirected)
    const url = this.getCurrentUrl();
    const conversationId = await this.extractConversationId();
    
    return {
      conversationId: conversationId || null,
      url
    };
  }

  /**
   * Navigate to an existing conversation
   * @param {string} conversationId
   * @returns {Promise<{url: string}>}
   */
  async navigateToExisting(conversationId) {
    const url = `${this.baseUrl}/chat/${conversationId}`;
    await this.page.goto(url, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    return { url: this.getCurrentUrl() };
  }

  /**
   * Extract conversation ID from current URL
   * @returns {Promise<string|null>}
   */
  async extractConversationId() {
    const url = this.getCurrentUrl();
    
    // claude.ai/chat/{conversationId}
    const match = url.match(/\/chat\/([a-zA-Z0-9-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Select a model
   * @param {string} modelName - One of: "Opus 4.5", "Sonnet 4", "Haiku 4"
   * @param {Object} [options]
   * @returns {Promise<{success: boolean, screenshot: string}>}
   */
  async selectModel(modelName, options = {}) {
    try {
      // Click model selector dropdown
      const selectorBtn = await this.page.waitForSelector(
        this.selectors.modelSelector,
        { timeout: 5000 }
      );
      await selectorBtn.click();
      await this.sleep(getTiming('MENU_RENDER'));
      
      // Find and click the model menu item
      const menuItemSelector = `div[role="menuitem"]:has-text("${modelName}")`;
      const menuItem = await this.page.waitForSelector(menuItemSelector, { timeout: 5000 });
      await menuItem.click();
      await this.sleep(500);
      
      const screenshot = await this.screenshot('select-model');
      
      return {
        success: true,
        screenshot,
        model: modelName
      };
    } catch (error) {
      const screenshot = await this.screenshot('select-model-failed');
      
      // Try to get available models for better error message
      let availableModels = [];
      try {
        availableModels = await this.page.$$eval(
          'div[role="menuitem"]',
          items => items.map(item => item.textContent.trim())
        );
      } catch {}
      
      throw new Error(
        `Failed to select model "${modelName}". ` +
        `Available models: ${availableModels.join(', ') || 'unknown'}. ` +
        `Screenshot: ${screenshot}`
      );
    }
  }

  /**
   * Enable/disable Extended Thinking (Research) mode
   * @param {boolean} enabled
   * @param {Object} [options]
   * @returns {Promise<{success: boolean, screenshot: string}>}
   */
  async setResearchMode(enabled, options = {}) {
    try {
      // Click tools menu
      const toolsBtn = await this.page.waitForSelector(
        this.selectors.toolsMenu || '#input-tools-menu-trigger',
        { timeout: 5000 }
      );
      await toolsBtn.click();
      await this.sleep(getTiming('MENU_RENDER'));
      
      // Find the Research toggle
      const researchBtn = await this.page.waitForSelector(
        'button:has-text("Research")',
        { timeout: 5000 }
      );
      
      // Check current toggle state
      const toggle = await researchBtn.$('input[role="switch"]');
      const isCurrentlyEnabled = toggle ? await toggle.isChecked() : false;
      
      // Toggle if needed
      if (isCurrentlyEnabled !== enabled) {
        await researchBtn.click();
        await this.sleep(500);
      }
      
      // Close menu by pressing Escape
      await this.bridge.pressKey('escape');
      await this.sleep(300);
      
      const screenshot = await this.screenshot('set-research-mode');
      
      return {
        success: true,
        screenshot,
        enabled
      };
    } catch (error) {
      const screenshot = await this.screenshot('set-research-mode-failed');
      throw new Error(
        `Failed to ${enabled ? 'enable' : 'disable'} Extended Thinking. ` +
        `Screenshot: ${screenshot}`
      );
    }
  }

  /**
   * Click the file attachment entry point
   * @returns {Promise<void>}
   */
  async clickAttachmentEntryPoint() {
    // Click + menu
    const plusBtn = await this.page.waitForSelector(
      this.selectors.plusMenu || '[data-testid="input-menu-plus"]',
      { timeout: 5000 }
    );
    await plusBtn.click();
    await this.sleep(500);
    
    // Click "Upload a file" menu item
    const uploadItem = await this.page.waitForSelector(
      this.selectors.uploadMenuItem || 'text="Upload a file"',
      { timeout: 5000 }
    );
    await uploadItem.click();
  }

  /**
   * Extract the latest AI response
   * @returns {Promise<string>}
   */
  async getLatestResponse() {
    try {
      // Claude uses data-testid for assistant messages
      const containers = await this.page.$$(
        this.selectors.responseContainer || '[data-testid="assistant-message"]'
      );
      
      if (containers.length === 0) {
        return '';
      }
      
      // Get the last (most recent) response
      const lastContainer = containers[containers.length - 1];
      const text = await lastContainer.innerText();
      
      return text.trim();
    } catch (error) {
      console.warn(`[claude] Error extracting response: ${error.message}`);
      return '';
    }
  }

  /**
   * Download an artifact
   * @param {Object} options
   * @param {string} [options.downloadPath='/tmp'] - Directory to save
   * @param {string} [options.format='markdown'] - Format (markdown or html)
   * @returns {Promise<{success: boolean, filePath: string, screenshot: string}>}
   */
  async downloadArtifact(options = {}) {
    const downloadPath = options.downloadPath || '/tmp';
    const format = options.format || 'markdown';
    
    try {
      // Claude has a simple Download button for artifacts
      const downloadBtn = await this.page.waitForSelector(
        this.selectors.downloadButton || 'button[aria-label="Download"]',
        { timeout: 10000 }
      );
      
      // Setup download handler
      const [download] = await Promise.all([
        this.page.waitForEvent('download'),
        downloadBtn.click()
      ]);
      
      // Save to path
      const suggestedName = download.suggestedFilename();
      const filePath = `${downloadPath}/${suggestedName}`;
      await download.saveAs(filePath);
      
      const screenshot = await this.screenshot('download-artifact');
      
      return {
        success: true,
        filePath,
        screenshot,
        filename: suggestedName
      };
    } catch (error) {
      const screenshot = await this.screenshot('download-artifact-failed');
      return {
        success: false,
        filePath: null,
        screenshot,
        error: error.message
      };
    }
  }

  // ============================================
  // OPTIONAL OVERRIDES
  // ============================================

  /**
   * Wait for response with streaming detection
   * Claude's Extended Thinking shows a thinking indicator
   * 
   * @param {number} [timeout=300000]
   * @param {Object} [options]
   * @returns {Promise<{content: string, detectionMethod: string, confidence: number, detectionTime: number}>}
   */
  async waitForResponse(timeout = 300000, options = {}) {
    const startTime = Date.now();
    const sessionId = options.sessionId || 'unknown';
    
    try {
      // First, check for thinking indicator (Extended Thinking mode)
      const thinkingSelector = this.selectors.thinkingIndicator || '[data-testid="thinking-indicator"]';
      
      // Wait for thinking to start (if it will)
      await this.sleep(2000);
      
      // Check if thinking indicator is present
      const isThinking = await this.page.$(thinkingSelector);
      
      if (isThinking) {
        console.log('[claude] Extended Thinking detected, waiting for completion...');
        
        // Wait for thinking to complete (indicator disappears)
        await this.page.waitForSelector(thinkingSelector, {
          state: 'hidden',
          timeout
        });
        
        console.log('[claude] Extended Thinking completed');
      }
      
      // Now wait for response using streaming class detection
      // Claude adds a class while streaming
      await this.sleep(1000);
      
      // Fall back to content stability
      return await super.waitForResponse(timeout - (Date.now() - startTime), {
        ...options,
        sessionId
      });
      
    } catch (error) {
      // Timeout or error - try to get whatever content we have
      console.warn(`[claude] Response detection warning: ${error.message}`);
      
      const content = await this.getLatestResponse();
      
      return {
        content,
        detectionMethod: 'error_fallback',
        confidence: 0.5,
        detectionTime: Date.now() - startTime
      };
    }
  }
}

/**
 * Create a Claude adapter instance
 * 
 * @param {Object} options
 * @returns {ClaudeAdapter}
 */
export function createClaudeAdapter(options) {
  return new ClaudeAdapter(options);
}
