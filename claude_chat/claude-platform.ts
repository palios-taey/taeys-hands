/**
 * Claude Platform Implementation
 * 
 * Specific behaviors:
 * - Extended Thinking toggle
 * - Model selector (Opus, Sonnet, Haiku)
 * - + menu for file attachment
 * - Simple artifact download (direct button)
 * - Thinking indicator for response detection
 */

import { Page } from 'playwright';
import { BasePlatform } from './base-platform.js';
import { TIMING, ScreenshotResult, DetectionResult } from '../types.js';

export class ClaudePlatform extends BasePlatform {
  constructor(page: Page) {
    super('claude', page);
  }
  
  /**
   * Get latest Claude response
   */
  async getLatestResponse(): Promise<string> {
    const selector = this.selectors.getCombined('responseContainer');
    
    try {
      // Get all assistant messages
      const messages = await this.page.$$(selector);
      
      if (messages.length === 0) {
        return '';
      }
      
      // Get the last message's text content
      const lastMessage = messages[messages.length - 1];
      const content = await lastMessage.textContent();
      
      return content?.trim() || '';
    } catch {
      return '';
    }
  }
  
  /**
   * Click attachment entry point (+ menu → Upload a file)
   */
  async clickAttachmentEntryPoint(): Promise<void> {
    // Click + menu button
    const plusSelector = this.selectors.getCombined('attachButton');
    const plusBtn = await this.waitForSelector(plusSelector);
    await plusBtn.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Click "Upload a file" menu item
    const uploadSelector = this.selectors.getCombined('uploadMenuItem');
    const uploadItem = await this.waitForSelector(uploadSelector);
    await uploadItem.click();
  }
  
  /**
   * Wait for Claude response with Extended Thinking awareness
   */
  async waitForResponse(timeout: number = 300000): Promise<DetectionResult> {
    const startTime = Date.now();
    
    // First, check if Extended Thinking is active
    const thinkingSelector = this.selectors.getPrimary('thinkingIndicator');
    const streamingClass = this.selectors.getStreamingClass();
    
    let lastContent = '';
    let stableCount = 0;
    const stabilityRequired = 2;
    
    const initialContent = await this.getLatestResponse();
    await this.screenshot('claude-wait-t0');
    
    while (Date.now() - startTime < timeout) {
      // Check for streaming indicator
      const isStreaming = await this.checkIsStreaming(streamingClass);
      
      if (isStreaming) {
        // Still streaming, reset stability counter
        stableCount = 0;
        await this.sleep(1000);
        continue;
      }
      
      // Check content stability
      const content = await this.getLatestResponse();
      
      if (content && content !== initialContent && content.length > 0) {
        if (content === lastContent) {
          stableCount++;
          
          if (stableCount >= stabilityRequired) {
            await this.screenshot('claude-complete');
            
            return {
              content,
              method: 'streamingClass',
              confidence: 0.95,
              detectionTime: Date.now() - startTime,
              isComplete: true,
            };
          }
        } else {
          stableCount = 0;
          lastContent = content;
        }
      }
      
      // Fibonacci polling
      await this.sleep(2000);
    }
    
    // Timeout fallback
    const finalContent = await this.getLatestResponse();
    await this.screenshot('claude-timeout');
    
    return {
      content: finalContent || '',
      method: 'fallback',
      confidence: 0.5,
      detectionTime: Date.now() - startTime,
      isComplete: false,
    };
  }
  
  /**
   * Check if response is still streaming
   */
  private async checkIsStreaming(streamingClass?: string): Promise<boolean> {
    if (!streamingClass) return false;
    
    try {
      const element = await this.page.$(`[${streamingClass}="true"]`);
      return element !== null;
    } catch {
      return false;
    }
  }
  
  /**
   * Enable/disable Extended Thinking (Research mode)
   */
  async setResearchMode(enabled: boolean): Promise<ScreenshotResult> {
    // Click tools menu
    const toolsSelector = this.selectors.getCombined('modeSelector');
    const toolsBtn = await this.waitForSelector(toolsSelector);
    await toolsBtn.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Find Research toggle
    const researchBtn = await this.waitForSelector('button:has-text("Research")');
    
    // Check current state
    const toggleInput = await researchBtn.$('input[role="switch"]');
    const isCurrentlyEnabled = toggleInput 
      ? await toggleInput.isChecked() 
      : false;
    
    // Toggle if needed
    if (enabled !== isCurrentlyEnabled) {
      await researchBtn.click();
      await this.sleep(TIMING.MENU_RENDER);
    }
    
    // Close menu by clicking elsewhere
    await this.page.keyboard.press('Escape');
    
    return this.screenshot('claude-research-mode');
  }
  
  /**
   * Download artifact (simple button click)
   */
  async downloadArtifact(downloadPath: string = '/tmp'): Promise<{ success: boolean; filePath?: string; screenshot: string }> {
    try {
      // Set up download listener
      const downloadPromise = this.page.waitForEvent('download', { timeout: 10000 });
      
      // Click download button
      const downloadSelector = this.selectors.getCombined('downloadButton');
      const downloadBtn = await this.waitForSelector(downloadSelector);
      await downloadBtn.click();
      
      // Wait for download
      const download = await downloadPromise;
      const filePath = `${downloadPath}/${download.suggestedFilename()}`;
      await download.saveAs(filePath);
      
      const screenshot = await this.screenshot('claude-artifact-downloaded');
      
      return {
        success: true,
        filePath,
        screenshot: screenshot.path,
      };
    } catch (error) {
      const screenshot = await this.screenshot('claude-download-failed');
      return {
        success: false,
        screenshot: screenshot.path,
      };
    }
  }
  
  /**
   * Select Claude model (Opus 4.5, Sonnet 4, Haiku 4)
   */
  async selectModel(modelName: string): Promise<ScreenshotResult> {
    // Click model selector
    const selectorStr = this.selectors.getCombined('modelSelector');
    const selector = await this.waitForSelector(selectorStr);
    await selector.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Find and click model
    const menuItemSelector = this.selectors.getModelMenuItem(modelName);
    if (menuItemSelector) {
      const menuItem = await this.waitForSelector(menuItemSelector);
      await menuItem.click();
      await this.sleep(TIMING.MENU_RENDER);
    }
    
    return this.screenshot('claude-model-selected');
  }
}

export function createClaudePlatform(page: Page): ClaudePlatform {
  return new ClaudePlatform(page);
}
