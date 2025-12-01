/**
 * Gemini Platform Adapter
 * 
 * Purpose: Gemini-specific automation implementation
 * Platform: gemini.google.com
 * 
 * CRITICAL QUIRKS:
 * - Promotional overlays block input clicks (must dismiss)
 * - "Start research" button is programmatically disabled (must force-enable)
 * - Two-step file attachment menu
 * - Multi-step artifact export
 * 
 * Features:
 * - Model selection (Thinking with 3 Pro, Thinking)
 * - Deep Research / Deep Think modes
 * - Artifact export (Markdown/HTML)
 * 
 * @module platforms/gemini
 */

import { BasePlatformAdapter } from './base-adapter.js';
import { getTiming } from '../core/platform/bridge-factory.js';

/**
 * Gemini platform adapter
 */
export class GeminiAdapter extends BasePlatformAdapter {
  constructor(options) {
    super(options);
    this.name = 'gemini';
    this.baseUrl = 'https://gemini.google.com';
  }

  // ============================================
  // ABSTRACT IMPLEMENTATIONS
  // ============================================

  getPlatformName() {
    return 'gemini';
  }

  async navigateToNew() {
    await this.page.goto(`${this.baseUrl}/app`, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    
    // Dismiss any overlays that appear on load
    await this.dismissOverlays();
    
    const url = this.getCurrentUrl();
    const conversationId = await this.extractConversationId();
    
    return { conversationId, url };
  }

  async navigateToExisting(conversationId) {
    // Gemini uses /app/conversation/{id} pattern
    const url = `${this.baseUrl}/app/conversation/${conversationId}`;
    await this.page.goto(url, { waitUntil: 'domcontentloaded' });
    await this.sleep(2000);
    await this.dismissOverlays();
    
    return { url: this.getCurrentUrl() };
  }

  async extractConversationId() {
    const url = this.getCurrentUrl();
    // gemini.google.com/app/conversation/{conversationId}
    const match = url.match(/\/conversation\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Select a model
   * @param {string} modelName - "Thinking with 3 Pro" or "Thinking"
   */
  async selectModel(modelName, options = {}) {
    try {
      // Click model selector
      const selectorBtn = await this.page.waitForSelector(
        this.selectors.modelSelector || '[data-test-id="bard-mode-menu-button"]',
        { timeout: 5000 }
      );
      await selectorBtn.click();
      await this.sleep(getTiming('MENU_RENDER'));
      
      // Find and click model
      const menuItem = await this.page.waitForSelector(
        `button[mat-menu-item]:has-text("${modelName}")`,
        { timeout: 5000 }
      );
      await menuItem.click();
      await this.sleep(500);
      
      const screenshot = await this.screenshot('select-model');
      return { success: true, screenshot, model: modelName };
    } catch (error) {
      const screenshot = await this.screenshot('select-model-failed');
      throw new Error(`Failed to select model "${modelName}". Screenshot: ${screenshot}`);
    }
  }

  /**
   * Enable Deep Research or Deep Think mode
   * @param {boolean} enabled
   * @param {Object} options
   * @param {string} [options.mode='Deep Research'] - 'Deep Research' or 'Deep Think'
   */
  async setResearchMode(enabled, options = {}) {
    const modeName = options.mode || 'Deep Research';
    
    try {
      // Click toolbox drawer button
      const toolboxBtn = await this.page.waitForSelector(
        'button.toolbox-drawer-button',
        { timeout: 5000 }
      );
      await toolboxBtn.click();
      await this.sleep(getTiming('MENU_RENDER'));
      
      // Find mode button
      const modeBtn = await this.page.waitForSelector(
        `button[mat-list-item]:has-text("${modeName}")`,
        { timeout: 5000 }
      );
      await modeBtn.click();
      await this.sleep(500);
      
      const screenshot = await this.screenshot('set-research-mode');
      return { success: true, screenshot, mode: modeName, enabled };
    } catch (error) {
      const screenshot = await this.screenshot('set-research-mode-failed');
      throw new Error(`Failed to set ${modeName} mode. Screenshot: ${screenshot}`);
    }
  }

  /**
   * Click file attachment entry point (two-step menu)
   */
  async clickAttachmentEntryPoint() {
    // Step 1: Click upload menu button (try multiple selectors)
    const menuSelectors = [
      'button[aria-label="Open upload file menu"]',
      'button[aria-label="Add files"]',
      'button mat-icon[fonticon="add_2"]',
      '[data-test-id="upload-menu-button"]'
    ];
    
    let menuBtn = null;
    for (const selector of menuSelectors) {
      try {
        menuBtn = await this.page.waitForSelector(selector, { timeout: 2000 });
        if (menuBtn) break;
      } catch {}
    }
    
    if (!menuBtn) {
      throw new Error('Could not find Gemini upload menu button');
    }
    
    await menuBtn.click();
    await this.sleep(500);
    
    // Step 2: Click "Upload files" menu item
    const uploadSelectors = [
      'button[data-test-id="local-images-files-uploader-button"]',
      'button:has-text("Upload files")',
      '[data-test-id="hidden-local-file-upload-button"]'
    ];
    
    let uploadBtn = null;
    for (const selector of uploadSelectors) {
      try {
        uploadBtn = await this.page.waitForSelector(selector, { timeout: 2000 });
        if (uploadBtn) break;
      } catch {}
    }
    
    if (!uploadBtn) {
      throw new Error('Could not find Gemini upload files button');
    }
    
    await uploadBtn.click();
  }

  async getLatestResponse() {
    try {
      // Gemini response containers
      const containers = await this.page.$$('.response-content, .model-response-text');
      
      if (containers.length === 0) return '';
      
      const lastContainer = containers[containers.length - 1];
      const text = await lastContainer.innerText();
      return text.trim();
    } catch (error) {
      console.warn(`[gemini] Error extracting response: ${error.message}`);
      return '';
    }
  }

  /**
   * Download artifact (multi-step export)
   */
  async downloadArtifact(options = {}) {
    const downloadPath = options.downloadPath || '/tmp';
    const format = options.format || 'markdown';
    
    try {
      // Click asset card
      const assetCard = await this.page.waitForSelector(
        '[data-testid="asset-card-open-button"]',
        { timeout: 10000 }
      );
      await assetCard.click();
      await this.sleep(500);
      
      // Click Export button
      const exportBtn = await this.page.waitForSelector(
        'button:has-text("Export")',
        { timeout: 5000 }
      );
      await exportBtn.click();
      await this.sleep(500);
      
      // Select format
      const formatText = format === 'markdown' ? 'Download as Markdown' : 'Download as HTML';
      const formatBtn = await this.page.waitForSelector(
        `button:has-text("${formatText}")`,
        { timeout: 5000 }
      );
      
      // Setup download handler
      const [download] = await Promise.all([
        this.page.waitForEvent('download'),
        formatBtn.click()
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
  // GEMINI-SPECIFIC QUIRK HANDLERS
  // ============================================

  /**
   * Dismiss promotional overlays that block input
   * CRITICAL: Must call before any input interaction
   */
  async dismissOverlays() {
    const closeSelectors = [
      'button[aria-label="Close"]',
      'button[aria-label="Dismiss"]',
      '.cdk-overlay-container button mat-icon[fonticon="close"]',
      '.cdk-overlay-backdrop',
      '[aria-label="Close promotional banner"]'
    ];
    
    // Try clicking close buttons
    for (const selector of closeSelectors) {
      try {
        const btn = await this.page.$(selector);
        if (btn) {
          await btn.click();
          await this.sleep(200);
        }
      } catch {}
    }
    
    // Fallback: Press Escape
    try {
      await this.bridge.pressKey('escape');
      await this.sleep(200);
    } catch {}
    
    // Fallback: Click empty area
    try {
      await this.bridge.clickAt(50, 50);
      await this.sleep(200);
    } catch {}
  }

  /**
   * Force-enable the "Start research" button
   * CRITICAL: Gemini's Deep Research button is often programmatically disabled
   */
  async forceEnableStartButton() {
    await this.page.evaluate(() => {
      const button = document.querySelector('button[data-test-id="confirm-button"]');
      if (button && button.disabled) {
        console.log('[Gemini] Force-enabling Start research button');
        button.disabled = false;
        button.classList.remove('mat-mdc-button-disabled');
        button.style.pointerEvents = 'auto';
      }
    });
    await this.sleep(500);
  }

  /**
   * Click Start research button (with force-enable)
   */
  async clickStartResearch() {
    await this.forceEnableStartButton();
    
    const startBtn = await this.page.waitForSelector(
      'button[data-test-id="confirm-button"][aria-label="Start research"]',
      { timeout: 5000 }
    );
    await startBtn.click();
  }

  // ============================================
  // OVERRIDES
  // ============================================

  /**
   * Override prepareInput to dismiss overlays first
   */
  async prepareInput(options = {}) {
    // CRITICAL: Dismiss overlays before trying to focus input
    await this.dismissOverlays();
    
    // Use screen coordinates click to bypass any remaining overlay issues
    await this.page.bringToFront();
    await this.sleep(getTiming('TAB_FOCUS'));
    await this.bridge.focusApp();
    await this.sleep(getTiming('APP_FOCUS'));
    
    // Click input with screen coordinates
    await this.clickInputWithScreenCoords();
    await this.sleep(200);
    
    const screenshot = await this.screenshot('prepare-input');
    return { screenshot, automationCompleted: true };
  }

  /**
   * Override waitForResponse to handle Deep Research button
   */
  async waitForResponse(timeout = 300000, options = {}) {
    const startTime = Date.now();
    
    // Check if Deep Research mode - need to click Start button
    try {
      const startBtn = await this.page.$('button[data-test-id="confirm-button"]');
      if (startBtn) {
        console.log('[gemini] Deep Research detected, clicking Start button...');
        await this.clickStartResearch();
      }
    } catch {}
    
    // Now wait for response using content stability
    return await super.waitForResponse(timeout - (Date.now() - startTime), options);
  }
}

export function createGeminiAdapter(options) {
  return new GeminiAdapter(options);
}
