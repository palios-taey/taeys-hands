/**
 * Grok Platform Adapter
 * 
 * Purpose: Grok-specific automation implementation
 * Platform: grok.com
 * 
 * QUIRKS:
 * - Model selector button requires JavaScript click (visibility trick)
 * - Standard Playwright click() fails due to element being "not visible"
 * 
 * Features:
 * - Model selection (Auto, Fast, Expert, Heavy, Grok 4.1)
 * - Standard file attachment
 * - No artifact download support
 * 
 * @module platforms/grok
 */

import { BasePlatformAdapter } from './base-adapter.js';
import { getTiming } from '../core/platform/bridge-factory.js';

/**
 * Grok platform adapter
 */
export class GrokAdapter extends BasePlatformAdapter {
  constructor(options) {
    super(options);
    this.name = 'grok';
    this.baseUrl = 'https://grok.com';
  }

  // ============================================
  // ABSTRACT IMPLEMENTATIONS
  // ============================================

  getPlatformName() {
    return 'grok';
  }

  async navigateToNew() {
    await this.page.goto(`${this.baseUrl}/`, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    const url = this.getCurrentUrl();
    const conversationId = await this.extractConversationId();
    
    return { conversationId, url };
  }

  async navigateToExisting(conversationId) {
    const url = `${this.baseUrl}/chat/${conversationId}`;
    await this.page.goto(url, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    return { url: this.getCurrentUrl() };
  }

  async extractConversationId() {
    const url = this.getCurrentUrl();
    // grok.com/chat/{conversationId}
    const match = url.match(/\/chat\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Select a model using JavaScript click bypass
   * QUIRK: Standard click fails due to Grok's visibility tricks
   * 
   * @param {string} modelName - 'Auto', 'Fast', 'Expert', 'Heavy', 'Grok 4.1'
   */
  async selectModel(modelName, options = {}) {
    try {
      // QUIRK: Use JavaScript click instead of Playwright click
      // The model selector button is "not visible" to Playwright
      await this.page.waitForSelector('#model-select-trigger', { 
        state: 'attached', 
        timeout: 5000 
      });
      
      await this.page.evaluate(() => {
        const button = document.querySelector('#model-select-trigger');
        if (button) button.click();
      });
      
      await this.sleep(getTiming('MENU_RENDER'));
      
      // Now find and click the model option
      // Grok uses text content for model names
      const modelItem = await this.page.waitForSelector(
        `[role="menuitem"]:has-text("${modelName}"), [role="option"]:has-text("${modelName}")`,
        { timeout: 5000 }
      );
      await modelItem.click();
      await this.sleep(500);
      
      const screenshot = await this.screenshot('select-model');
      return { success: true, screenshot, model: modelName };
    } catch (error) {
      const screenshot = await this.screenshot('select-model-failed');
      
      // Get available models for error message
      let availableModels = [];
      try {
        availableModels = await this.page.$$eval(
          '[role="menuitem"], [role="option"]',
          items => items.map(item => item.textContent.trim()).filter(t => t)
        );
      } catch {}
      
      throw new Error(
        `Failed to select model "${modelName}". ` +
        `Available: ${availableModels.join(', ') || 'unknown'}. ` +
        `Screenshot: ${screenshot}`
      );
    }
  }

  /**
   * Research mode - Grok doesn't have a separate research mode
   * Models like Expert and Heavy provide deeper thinking
   */
  async setResearchMode(enabled, options = {}) {
    if (enabled) {
      // Use Expert mode as the "research" equivalent
      console.log('[grok] No separate research mode - using Expert model for deeper thinking');
      return await this.selectModel('Expert', options);
    }
    
    // Disable = switch back to Auto
    return await this.selectModel('Auto', options);
  }

  /**
   * Click file attachment entry point
   */
  async clickAttachmentEntryPoint() {
    // Click attach button
    const attachBtn = await this.page.waitForSelector(
      'button[aria-label="Attach"]',
      { timeout: 5000 }
    );
    await attachBtn.click();
    await this.sleep(500);
    
    // Click "Upload a file" menu item
    const uploadItem = await this.page.waitForSelector(
      'div[role="menuitem"]:has-text("Upload a file")',
      { timeout: 5000 }
    );
    await uploadItem.click();
  }

  async getLatestResponse() {
    try {
      // Grok response containers
      const containers = await this.page.$$(
        '[data-testid="assistant-message"], .assistant-message, [class*="response"]'
      );
      
      if (containers.length === 0) return '';
      
      const lastContainer = containers[containers.length - 1];
      const text = await lastContainer.innerText();
      return text.trim();
    } catch (error) {
      console.warn(`[grok] Error extracting response: ${error.message}`);
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
      error: 'Grok does not support artifact downloads'
    };
  }

  // ============================================
  // OVERRIDES
  // ============================================

  /**
   * Override waitForResponse - Grok uses simple content stability
   */
  async waitForResponse(timeout = 60000, options = {}) {
    // Grok is typically fast, use shorter default timeout
    return await super.waitForResponse(timeout, options);
  }
}

export function createGrokAdapter(options) {
  return new GrokAdapter(options);
}
