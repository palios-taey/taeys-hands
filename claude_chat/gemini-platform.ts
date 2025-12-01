/**
 * Gemini Platform Implementation
 * 
 * CRITICAL QUIRKS:
 * 1. Promotional overlays that block input clicks
 * 2. "Start research" button is programmatically disabled
 * 3. Two-step file attachment menu
 * 4. Quill editor for input
 * 
 * Solutions:
 * - dismissOverlays() before every input focus
 * - forceEnableStartButton() for Deep Research
 * - Screen coordinate clicking to bypass overlays
 */

import { Page } from 'playwright';
import { BasePlatform } from './base-platform.js';
import { TIMING, ScreenshotResult, DetectionResult } from '../types.js';

export class GeminiPlatform extends BasePlatform {
  constructor(page: Page) {
    super('gemini', page);
  }
  
  /**
   * Get latest Gemini response
   */
  async getLatestResponse(): Promise<string> {
    try {
      // Gemini uses message-content elements
      const messages = await this.page.$$('message-content');
      
      if (messages.length === 0) {
        // Fallback selector
        const fallback = await this.page.$$('.model-response-text');
        if (fallback.length === 0) return '';
        const lastMessage = fallback[fallback.length - 1];
        return (await lastMessage.textContent())?.trim() || '';
      }
      
      const lastMessage = messages[messages.length - 1];
      return (await lastMessage.textContent())?.trim() || '';
    } catch {
      return '';
    }
  }
  
  /**
   * CRITICAL: Dismiss promotional overlays before input focus
   */
  async dismissOverlays(): Promise<void> {
    const closeSelectors = this.selectors.getAll('closeOverlayButton');
    
    // Try each close button selector
    for (const selector of closeSelectors) {
      try {
        const btn = await this.page.$(selector);
        if (btn) {
          await btn.click();
          await this.sleep(TIMING.OVERLAY_DISMISS);
        }
      } catch {
        continue;
      }
    }
    
    // Also try Escape key
    try {
      await this.bridge.pressKey('escape');
      await this.sleep(TIMING.OVERLAY_DISMISS);
    } catch {
      // Ignore
    }
    
    // Click empty area as last resort
    try {
      await this.bridge.clickAt(50, 50);
      await this.sleep(TIMING.OVERLAY_DISMISS);
    } catch {
      // Ignore
    }
  }
  
  /**
   * Override prepareInput to dismiss overlays first
   */
  async prepareInput(): Promise<ScreenshotResult> {
    // CRITICAL: Dismiss overlays before any input interaction
    await this.dismissOverlays();
    
    // Bring tab to front
    await this.page.bringToFront();
    await this.sleep(TIMING.TAB_FOCUS);
    
    // Focus browser
    await this.bridge.focusApp(this.bridge.getBrowserName());
    await this.sleep(TIMING.APP_FOCUS);
    
    // Use screen coordinates to click input (bypasses invisible overlays)
    await this.clickInputWithScreenCoords();
    
    return this.screenshot('gemini-prepare-input');
  }
  
  /**
   * Two-step file attachment: menu button → upload files
   */
  async clickAttachmentEntryPoint(): Promise<void> {
    // Step 1: Click attach menu button (try multiple selectors)
    const attachSelectors = this.selectors.getAll('attachButton');
    let menuBtn = null;
    
    for (const selector of attachSelectors) {
      try {
        menuBtn = await this.page.waitForSelector(selector, { timeout: 3000 });
        if (menuBtn) break;
      } catch {
        continue;
      }
    }
    
    if (!menuBtn) {
      throw new Error('Could not find Gemini attach menu button');
    }
    
    await menuBtn.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Step 2: Click upload files option (try multiple selectors)
    const uploadSelectors = this.selectors.getAll('uploadMenuItem');
    let uploadBtn = null;
    
    for (const selector of uploadSelectors) {
      try {
        uploadBtn = await this.page.waitForSelector(selector, { timeout: 3000 });
        if (uploadBtn) break;
      } catch {
        continue;
      }
    }
    
    if (!uploadBtn) {
      throw new Error('Could not find Gemini upload files option');
    }
    
    await uploadBtn.click();
  }
  
  /**
   * CRITICAL: Force-enable the Start Research button if disabled
   */
  async forceEnableStartButton(): Promise<boolean> {
    const selector = this.selectors.getPrimary('startResearchButton');
    if (!selector) return false;
    
    try {
      const enabled = await this.page.evaluate((sel) => {
        const button = document.querySelector(sel) as HTMLButtonElement;
        if (button && button.disabled) {
          console.log('[Gemini] Force-enabling Start Research button');
          button.disabled = false;
          button.classList.remove('mat-mdc-button-disabled');
          button.style.pointerEvents = 'auto';
          return true;
        }
        return false;
      }, selector);
      
      if (enabled) {
        await this.sleep(500);
      }
      
      return enabled;
    } catch {
      return false;
    }
  }
  
  /**
   * Wait for Gemini response with Deep Research awareness
   */
  async waitForResponse(timeout: number = 3600000): Promise<DetectionResult> {
    const startTime = Date.now();
    
    // Check for and click Start Research button if present
    await this.checkAndClickStartResearch();
    
    let lastContent = '';
    let stableCount = 0;
    const stabilityRequired = 3; // Gemini needs more stability checks
    
    const initialContent = await this.getLatestResponse();
    await this.screenshot('gemini-wait-t0');
    
    while (Date.now() - startTime < timeout) {
      const content = await this.getLatestResponse();
      
      if (content && content !== initialContent && content.length > 0) {
        if (content === lastContent) {
          stableCount++;
          
          if (stableCount >= stabilityRequired) {
            await this.screenshot('gemini-complete');
            
            return {
              content,
              method: 'contentStability',
              confidence: 0.85,
              detectionTime: Date.now() - startTime,
              isComplete: true,
            };
          }
        } else {
          stableCount = 0;
          lastContent = content;
        }
      }
      
      // Slower polling for Deep Research
      await this.sleep(5000);
    }
    
    const finalContent = await this.getLatestResponse();
    await this.screenshot('gemini-timeout');
    
    return {
      content: finalContent || '',
      method: 'fallback',
      confidence: 0.5,
      detectionTime: Date.now() - startTime,
      isComplete: false,
    };
  }
  
  /**
   * Check for Start Research button and click if present
   */
  private async checkAndClickStartResearch(): Promise<void> {
    try {
      const selector = this.selectors.getPrimary('startResearchButton');
      if (!selector) return;
      
      const button = await this.page.$(selector);
      if (button) {
        // Force enable if disabled
        await this.forceEnableStartButton();
        
        // Click the button
        await button.click();
        await this.sleep(2000);
        
        console.log('[Gemini] Clicked Start Research button');
      }
    } catch {
      // Button not present, that's ok
    }
  }
  
  /**
   * Set Gemini mode (Deep Research, Deep Think)
   */
  async setMode(modeName: string): Promise<ScreenshotResult> {
    // Click toolbox drawer
    const drawerSelector = this.selectors.getCombined('modeSelector');
    const drawer = await this.waitForSelector(drawerSelector);
    await drawer.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Click mode option
    const modeSelector = this.selectors.getModeMenuItem(modeName);
    if (modeSelector) {
      const modeBtn = await this.waitForSelector(modeSelector);
      await modeBtn.click();
      await this.sleep(TIMING.MENU_RENDER);
    }
    
    return this.screenshot('gemini-mode-set');
  }
  
  /**
   * Download Gemini artifact (multi-step export)
   */
  async downloadArtifact(downloadPath: string = '/tmp'): Promise<{ success: boolean; filePath?: string; screenshot: string }> {
    try {
      // Click asset card
      const cardSelector = this.selectors.getCombined('downloadButton');
      const card = await this.waitForSelector(cardSelector);
      await card.click();
      await this.sleep(TIMING.MENU_RENDER);
      
      // Click Export button
      const exportSelector = this.selectors.getCombined('exportMenu');
      const exportBtn = await this.waitForSelector(exportSelector);
      await exportBtn.click();
      await this.sleep(TIMING.MENU_RENDER);
      
      // Set up download listener
      const downloadPromise = this.page.waitForEvent('download', { timeout: 10000 });
      
      // Click Download as Markdown
      const markdownSelector = this.selectors.getCombined('markdownOption');
      const markdownBtn = await this.waitForSelector(markdownSelector);
      await markdownBtn.click();
      
      // Wait for download
      const download = await downloadPromise;
      const filePath = `${downloadPath}/${download.suggestedFilename()}`;
      await download.saveAs(filePath);
      
      const screenshot = await this.screenshot('gemini-artifact-downloaded');
      
      return {
        success: true,
        filePath,
        screenshot: screenshot.path,
      };
    } catch (error) {
      const screenshot = await this.screenshot('gemini-download-failed');
      return {
        success: false,
        screenshot: screenshot.path,
      };
    }
  }
}

export function createGeminiPlatform(page: Page): GeminiPlatform {
  return new GeminiPlatform(page);
}
