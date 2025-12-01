/**
 * Perplexity Platform Adapter
 * 
 * Purpose: Perplexity-specific automation implementation
 * Platform: perplexity.ai
 * 
 * QUIRKS:
 * - No model selection (uses single model)
 * - Mode selection via radio buttons (Search, Research, Labs)
 * - Response extraction requires SPECIFIC parent container selector
 *   (base selector matches child elements, extracting only last paragraph)
 * 
 * Features:
 * - Mode selection (Search, Research/Pro, Labs)
 * - Multi-step artifact export
 * - File attachment via menu
 * 
 * @module platforms/perplexity
 */

import { BasePlatformAdapter } from './base-adapter.js';
import { getTiming } from '../core/platform/bridge-factory.js';

/**
 * Perplexity platform adapter
 */
export class PerplexityAdapter extends BasePlatformAdapter {
  constructor(options) {
    super(options);
    this.name = 'perplexity';
    this.baseUrl = 'https://perplexity.ai';
  }

  // ============================================
  // ABSTRACT IMPLEMENTATIONS
  // ============================================

  getPlatformName() {
    return 'perplexity';
  }

  async navigateToNew() {
    await this.page.goto(`${this.baseUrl}/`, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    const url = this.getCurrentUrl();
    const conversationId = await this.extractConversationId();
    
    return { conversationId, url };
  }

  async navigateToExisting(conversationId) {
    const url = `${this.baseUrl}/search/${conversationId}`;
    await this.page.goto(url, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    return { url: this.getCurrentUrl() };
  }

  async extractConversationId() {
    const url = this.getCurrentUrl();
    // perplexity.ai/search/{conversationId}
    const match = url.match(/\/search\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Model selection - NOT SUPPORTED
   * Perplexity uses a single model, use mode selection instead
   */
  async selectModel(modelName, options = {}) {
    console.log(`[perplexity] selectModel() - Not supported, Perplexity uses single model`);
    console.log(`  Use setResearchMode() to switch between Search/Research/Labs`);
    
    const screenshot = await this.screenshot('select-model-not-supported');
    return {
      success: true,
      screenshot,
      note: 'Perplexity does not support model selection. Use setResearchMode() for mode switching.'
    };
  }

  /**
   * Set mode via radio buttons
   * 
   * @param {boolean} enabled - true to enable Pro/Research mode
   * @param {Object} options
   * @param {string} [options.mode='research'] - 'search', 'research', or 'studio' (Labs)
   */
  async setResearchMode(enabled, options = {}) {
    // Map mode names to values
    const modeMap = {
      'search': 'search',
      'research': 'research',
      'pro': 'research',
      'labs': 'studio',
      'studio': 'studio'
    };
    
    const modeName = options.mode || (enabled ? 'research' : 'search');
    const modeValue = modeMap[modeName.toLowerCase()] || 'search';
    
    try {
      // Find and click the radio button
      const radioSelector = `button[role="radio"][value="${modeValue}"]`;
      const radioBtn = await this.page.waitForSelector(radioSelector, { timeout: 5000 });
      await radioBtn.click();
      await this.sleep(500);
      
      const screenshot = await this.screenshot('set-mode');
      return { success: true, screenshot, mode: modeValue, enabled };
    } catch (error) {
      const screenshot = await this.screenshot('set-mode-failed');
      throw new Error(`Failed to set mode "${modeName}". Screenshot: ${screenshot}`);
    }
  }

  /**
   * Click file attachment entry point
   */
  async clickAttachmentEntryPoint() {
    // Click attach button
    const attachBtn = await this.page.waitForSelector(
      'button[data-testid="attach-files-button"]',
      { timeout: 5000 }
    );
    await attachBtn.click();
    await this.sleep(500);
    
    // Click "Local files" menu item
    const localFilesItem = await this.page.waitForSelector(
      'div[role="menuitem"]:has-text("Local files")',
      { timeout: 5000 }
    );
    await localFilesItem.click();
  }

  /**
   * Extract latest response - QUIRK: Must use specific parent selector
   * 
   * The base selector [class*="prose"] matches ALL child elements (p, h1, ul, etc.)
   * which results in only getting the last paragraph.
   * 
   * FIX: Use the specific parent container selector to get full response.
   */
  async getLatestResponse() {
    try {
      // QUIRK FIX: Use specific parent selector, not generic prose class
      const answerSelector = 'div.prose.dark\\:prose-invert.inline.leading-relaxed';

      const containers = await this.page.$$(answerSelector);

      let mainResponseText = '';

      if (containers.length === 0) {
        // Fallback to alternative selectors
        const fallbackContainers = await this.page.$$('[class*="answer-content"], [class*="response-text"]');
        if (fallbackContainers.length > 0) {
          const last = fallbackContainers[fallbackContainers.length - 1];
          mainResponseText = (await last.innerText()).trim();
        }
      } else {
        const lastContainer = containers[containers.length - 1];
        mainResponseText = (await lastContainer.innerText()).trim();
      }

      // Check for artifacts/attachments (created during Pro Research/Labs modes)
      const artifactButton = await this.page.$('[data-testid="asset-card-open-button"]');

      if (artifactButton) {
        try {
          // Click artifact card to reveal content
          await artifactButton.click();
          await this.sleep(1000);

          // Extract artifact content (usually in a modal or expanded view)
          // Try common artifact content selectors
          const artifactSelectors = [
            '[data-testid="artifact-content"]',
            '[class*="artifact"]',
            'pre code',
            '[class*="modal"] [class*="prose"]'
          ];

          let artifactText = '';
          for (const selector of artifactSelectors) {
            const artifactElem = await this.page.$(selector);
            if (artifactElem) {
              artifactText = await artifactElem.innerText();
              break;
            }
          }

          if (artifactText) {
            return `${mainResponseText}\n\n---ARTIFACT---\n${artifactText.trim()}`;
          }
        } catch (artifactErr) {
          console.warn(`[perplexity] Error extracting artifact: ${artifactErr.message}`);
        }
      }

      return mainResponseText;
    } catch (error) {
      console.warn(`[perplexity] Error extracting response: ${error.message}`);
      return '';
    }
  }

  /**
   * Download artifact (3-step flow: banner → Export button → Download)
   */
  async downloadArtifact(options = {}) {
    const downloadPath = options.downloadPath || '/tmp';

    try {
      // Step 1: Click artifact banner button to open side panel
      const assetCardButton = await this.page.waitForSelector(
        '[data-testid="asset-card-open-button"]',
        { timeout: 10000 }
      );
      await assetCardButton.click();
      await this.sleep(1000); // Wait for side panel to open

      // Step 2: Click Export button in side panel header
      const exportBtn = await this.page.waitForSelector(
        'button:has-text("Export")',
        { timeout: 5000 }
      );
      await exportBtn.click();
      await this.sleep(500); // Wait for dropdown menu

      // Step 3: Click "Download as File" from dropdown
      const downloadMenuItem = await this.page.waitForSelector(
        'div[role="menuitem"]:has-text("Download as File")',
        { timeout: 5000 }
      );

      // Handle download
      const [download] = await Promise.all([
        this.page.waitForEvent('download', { timeout: 10000 }),
        downloadMenuItem.click()
      ]);

      const suggestedName = download.suggestedFilename();
      const filePath = `${downloadPath}/${suggestedName}`;
      await download.saveAs(filePath);

      const screenshot = await this.screenshot('download-artifact');
      return { success: true, filePath, screenshot, filename: suggestedName };
    } catch (error) {
      const screenshot = await this.screenshot('download-artifact-failed');
      return { success: false, filePath: null, screenshot, error: error.message };
    }
  }

  // ============================================
  // OVERRIDES
  // ============================================

  /**
   * Override waitForResponse - Perplexity Labs can take very long
   */
  async waitForResponse(timeout = 1800000, options = {}) {
    // Default 30 min timeout for Labs mode
    return await super.waitForResponse(timeout, options);
  }
}

export function createPerplexityAdapter(options) {
  return new PerplexityAdapter(options);
}
