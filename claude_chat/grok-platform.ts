/**
 * Grok Platform Implementation
 * 
 * QUIRK: Model selector requires JavaScript click bypass
 * - Playwright's standard click() fails due to visibility tricks
 * - Solution: Use page.evaluate to click via JavaScript
 */

import { Page } from 'playwright';
import { BasePlatform } from './base-platform.js';
import { TIMING, ScreenshotResult } from '../types.js';

export class GrokPlatform extends BasePlatform {
  constructor(page: Page) {
    super('grok', page);
  }
  
  /**
   * Get latest Grok response
   */
  async getLatestResponse(): Promise<string> {
    try {
      // Try multiple selectors
      const selectors = [
        '[data-role="assistant"]',
        '.message-content',
        '[class*="response"]',
      ];
      
      for (const selector of selectors) {
        const messages = await this.page.$$(selector);
        if (messages.length > 0) {
          const lastMessage = messages[messages.length - 1];
          const content = await lastMessage.textContent();
          if (content?.trim()) return content.trim();
        }
      }
      
      return '';
    } catch {
      return '';
    }
  }
  
  /**
   * Click attachment entry point (Attach → Upload a file)
   */
  async clickAttachmentEntryPoint(): Promise<void> {
    // Click attach button
    const attachSelector = this.selectors.getCombined('attachButton');
    const attachBtn = await this.waitForSelector(attachSelector);
    await attachBtn.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Click upload menu item
    const uploadSelector = this.selectors.getCombined('uploadMenuItem');
    const uploadItem = await this.waitForSelector(uploadSelector);
    await uploadItem.click();
  }
  
  /**
   * QUIRK: Use JavaScript click for model selector
   */
  async selectModel(modelName: string): Promise<ScreenshotResult> {
    // Step 1: Click model selector via JavaScript (bypass visibility check)
    const selectorId = '#model-select-trigger';
    
    await this.page.waitForSelector(selectorId, { state: 'attached', timeout: 5000 });
    await this.page.evaluate((sel) => {
      const button = document.querySelector(sel) as HTMLButtonElement;
      if (button) button.click();
    }, selectorId);
    
    await this.sleep(TIMING.MENU_RENDER);
    
    // Step 2: Click model option
    const menuItemSelector = this.selectors.getModelMenuItem(modelName);
    if (menuItemSelector) {
      const menuItem = await this.waitForSelector(menuItemSelector);
      await menuItem.click();
      await this.sleep(TIMING.MENU_RENDER);
    }
    
    return this.screenshot('grok-model-selected');
  }
}

export function createGrokPlatform(page: Page): GrokPlatform {
  return new GrokPlatform(page);
}
