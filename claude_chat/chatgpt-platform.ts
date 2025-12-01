/**
 * ChatGPT Platform Implementation
 * 
 * QUIRK: Model selection is disabled
 * - ChatGPT now uses Auto mode by default
 * - Use setMode() for Deep Research instead
 */

import { Page } from 'playwright';
import { BasePlatform } from './base-platform.js';
import { TIMING, ScreenshotResult } from '../types.js';

export class ChatGPTPlatform extends BasePlatform {
  constructor(page: Page) {
    super('chatgpt', page);
  }
  
  /**
   * Get latest ChatGPT response
   */
  async getLatestResponse(): Promise<string> {
    try {
      const selectors = [
        '[data-message-author-role="assistant"]',
        '.markdown.prose',
        '[class*="agent-turn"]',
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
   * Click attachment entry point (+ menu → Add photos & files)
   */
  async clickAttachmentEntryPoint(): Promise<void> {
    // Click + button
    const plusSelector = this.selectors.getCombined('attachButton');
    const plusBtn = await this.waitForSelector(plusSelector);
    await plusBtn.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Click "Add photos & files"
    const uploadSelector = this.selectors.getCombined('uploadMenuItem');
    const uploadItem = await this.waitForSelector(uploadSelector);
    await uploadItem.click();
  }
  
  /**
   * Model selection is DISABLED for ChatGPT
   */
  async selectModel(modelName: string): Promise<ScreenshotResult> {
    console.log(`[ChatGPT] selectModel(${modelName}) - DISABLED`);
    console.log('  ChatGPT model selection disabled - using Auto mode');
    console.log('  For thinking: use setMode("Deep research") instead');
    
    return this.screenshot('chatgpt-model-disabled');
  }
  
  /**
   * Set ChatGPT mode (Deep research, Agent mode, etc.)
   */
  async setMode(modeName: string): Promise<ScreenshotResult> {
    // Click + button
    const plusSelector = this.selectors.getCombined('modeSelector');
    const plusBtn = await this.waitForSelector(plusSelector);
    await plusBtn.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Click mode
    const modeSelector = `text="${modeName}"`;
    const modeBtn = await this.waitForSelector(modeSelector);
    await modeBtn.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    return this.screenshot('chatgpt-mode-set');
  }
}

export function createChatGPTPlatform(page: Page): ChatGPTPlatform {
  return new ChatGPTPlatform(page);
}
