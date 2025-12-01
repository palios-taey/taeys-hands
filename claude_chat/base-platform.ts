/**
 * Base Platform - Abstract Class for AI Chat Interfaces
 * 
 * Provides:
 * - Common automation patterns
 * - Screenshot verification
 * - Response detection
 * - File attachment base
 * 
 * Platform-specific classes override methods as needed.
 */

import { Page } from 'playwright';
import path from 'path';
import fs from 'fs';
import { v4 as uuidv4 } from 'uuid';
import {
  PlatformType,
  PlatformConfig,
  SendMessageOptions,
  SendMessageResult,
  AttachmentResult,
  AttachFilesResult,
  DetectionResult,
  DetectionMethod,
  ScreenshotResult,
  TIMING,
  PLATFORM_CONFIGS,
  SelectorError,
  AttachmentError,
} from '../types.js';
import { PlatformBridge, createPlatformBridge } from './core/platform/bridge.js';
import { SelectorRegistry, createSelectorRegistry } from './core/selectors/registry.js';

// ============================================================================
// Base Platform Class
// ============================================================================

export abstract class BasePlatform {
  readonly platform: PlatformType;
  readonly config: PlatformConfig;
  protected readonly page: Page;
  protected readonly bridge: PlatformBridge;
  protected readonly selectors: SelectorRegistry;
  
  // Screenshot directory
  protected readonly screenshotDir: string;
  
  constructor(platform: PlatformType, page: Page) {
    this.platform = platform;
    this.config = PLATFORM_CONFIGS[platform];
    this.page = page;
    this.bridge = createPlatformBridge();
    this.selectors = createSelectorRegistry(platform);
    
    this.screenshotDir = process.env.SCREENSHOT_DIR || '/tmp/taey-screenshots';
    this.ensureScreenshotDir();
  }
  
  // ==========================================================================
  // Abstract Methods (must be implemented by subclasses)
  // ==========================================================================
  
  /**
   * Get the latest AI response from the page
   */
  abstract getLatestResponse(): Promise<string>;
  
  /**
   * Platform-specific entry point for file attachment
   */
  abstract clickAttachmentEntryPoint(): Promise<void>;
  
  // ==========================================================================
  // Input Preparation
  // ==========================================================================
  
  /**
   * Prepare input field for typing
   */
  async prepareInput(): Promise<ScreenshotResult> {
    // Bring tab to front
    await this.page.bringToFront();
    await this.sleep(TIMING.TAB_FOCUS);
    
    // Focus browser application
    await this.bridge.focusApp(this.bridge.getBrowserName());
    await this.sleep(TIMING.APP_FOCUS);
    
    // Click input field
    const inputSelector = this.selectors.getCombined('chatInput');
    const input = await this.waitForSelector(inputSelector);
    await input.click();
    await this.sleep(TIMING.TYPING_BUFFER);
    
    return this.screenshot('prepare-input');
  }
  
  /**
   * Type message into input field
   */
  async typeMessage(message: string, options: SendMessageOptions = {}): Promise<ScreenshotResult> {
    const { humanLike = true, mixedContent = true } = options;
    
    // Ensure focus
    await this.page.bringToFront();
    await this.bridge.focusApp(this.bridge.getBrowserName());
    
    // Click input with screen coordinates (more reliable)
    await this.clickInputWithScreenCoords();
    
    // Type message
    if (humanLike) {
      if (mixedContent && message.length > 100) {
        await this.bridge.typeWithMixedContent(message);
      } else {
        await this.bridge.safeTypeLong(message, { chunkSize: 100 });
      }
    } else {
      // Direct injection (faster but detectable)
      const input = await this.waitForSelector(this.selectors.getCombined('chatInput'));
      await input.fill(message);
    }
    
    await this.sleep(TIMING.TYPING_BUFFER);
    return this.screenshot('type-message');
  }
  
  /**
   * Click input using screen coordinates (bypasses overlays)
   */
  protected async clickInputWithScreenCoords(): Promise<void> {
    const inputSelector = this.selectors.getCombined('chatInput');
    const input = await this.waitForSelector(inputSelector);
    const box = await input.boundingBox();
    
    if (box) {
      const windowInfo = await this.page.evaluate(() => ({
        screenX: window.screenX,
        screenY: window.screenY,
        outerHeight: window.outerHeight,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        innerWidth: window.innerWidth,
      }));
      
      const chromeHeight = windowInfo.outerHeight - windowInfo.innerHeight;
      const chromeWidth = windowInfo.outerWidth - windowInfo.innerWidth;
      const screenX = windowInfo.screenX + (chromeWidth / 2) + box.x + (box.width / 2);
      const screenY = windowInfo.screenY + chromeHeight + box.y + (box.height / 2);
      
      await this.bridge.clickAt(Math.round(screenX), Math.round(screenY));
      await this.sleep(100);
    }
  }
  
  // ==========================================================================
  // Send Message
  // ==========================================================================
  
  /**
   * Click send (via Enter key - more reliable than button click)
   */
  async clickSend(): Promise<ScreenshotResult> {
    await this.sleep(TIMING.TYPING_BUFFER);
    await this.bridge.pressKey('return');
    await this.sleep(TIMING.NETWORK_SEND);
    return this.screenshot('click-send');
  }
  
  /**
   * Complete send message workflow
   */
  async sendMessage(message: string, options: SendMessageOptions = {}): Promise<SendMessageResult> {
    const { waitForResponse = false, timeout } = options;
    
    // Prepare, type, send
    await this.prepareInput();
    await this.typeMessage(message, options);
    const sendScreenshot = await this.clickSend();
    
    const result: SendMessageResult = {
      success: true,
      screenshot: sendScreenshot.path,
      sentText: message,
    };
    
    // Optionally wait for response
    if (waitForResponse) {
      const detection = await this.waitForResponse(timeout || this.config.defaultTimeout);
      result.responseText = detection.content;
      result.responseLength = detection.content.length;
      result.detectionMethod = detection.method;
      result.detectionConfidence = detection.confidence;
      result.detectionTime = detection.detectionTime;
    }
    
    return result;
  }
  
  // ==========================================================================
  // Response Detection
  // ==========================================================================
  
  /**
   * Wait for AI response with Fibonacci polling
   */
  async waitForResponse(timeout: number = 60000): Promise<DetectionResult> {
    const fibonacci = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55];
    const startTime = Date.now();
    
    let lastContent = '';
    let stableCount = 0;
    const stabilityRequired = 2;
    
    // Get initial content
    const initialContent = await this.getLatestResponse();
    
    // Screenshot at t=0
    await this.screenshot('wait-response-t0');
    
    let fibIndex = 0;
    
    while (Date.now() - startTime < timeout) {
      const content = await this.getLatestResponse();
      
      // Check if content is new and stable
      if (content && content !== initialContent && content.length > 0) {
        if (content === lastContent) {
          stableCount++;
          
          if (stableCount >= stabilityRequired) {
            await this.screenshot('wait-response-complete');
            
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
      
      // Calculate wait time
      let waitSeconds: number;
      if (stableCount > 0) {
        waitSeconds = 2; // Fast polling for confirmation
      } else if (fibIndex < 3) {
        waitSeconds = 1; // First 3 checks at 1s
      } else {
        waitSeconds = fibonacci[Math.min(fibIndex, fibonacci.length - 1)];
      }
      
      await this.sleep(waitSeconds * 1000);
      fibIndex++;
    }
    
    // Timeout - return partial content
    const finalContent = await this.getLatestResponse();
    await this.screenshot('wait-response-timeout');
    
    return {
      content: finalContent || '',
      method: 'fallback',
      confidence: 0.5,
      detectionTime: Date.now() - startTime,
      isComplete: false,
    };
  }
  
  // ==========================================================================
  // File Attachment
  // ==========================================================================
  
  /**
   * Attach a single file
   */
  async attachFile(filePath: string): Promise<AttachmentResult> {
    // Validate file exists
    if (!fs.existsSync(filePath)) {
      throw new AttachmentError(
        `File not found: ${filePath}`,
        'Verify the file path is correct and the file exists.'
      );
    }
    
    // Click attachment entry point (platform-specific)
    await this.clickAttachmentEntryPoint();
    
    // Wait for file dialog
    await this.sleep(TIMING.FILE_DIALOG_SPAWN);
    
    // Navigate file dialog
    await this.bridge.navigateFileDialog(filePath);
    
    // Wait for upload
    await this.sleep(TIMING.FILE_UPLOAD_PROCESS);
    
    const screenshot = await this.screenshot('attach-file');
    
    return {
      success: true,
      filePath,
      screenshot: screenshot.path,
      automationCompleted: true,
    };
  }
  
  /**
   * Attach multiple files
   */
  async attachFiles(filePaths: string[]): Promise<AttachFilesResult> {
    const attachments: AttachmentResult[] = [];
    
    for (const filePath of filePaths) {
      const result = await this.attachFile(filePath);
      attachments.push(result);
    }
    
    const screenshot = await this.screenshot('attach-files-complete');
    
    return {
      success: attachments.every(a => a.success),
      filesAttached: attachments.filter(a => a.success).length,
      attachments,
      screenshot: screenshot.path,
      message: `Automation completed for ${filePaths.length} file(s). VERIFY in screenshot that files appear in input area.`,
    };
  }
  
  // ==========================================================================
  // Model Selection (optional - override in subclasses)
  // ==========================================================================
  
  /**
   * Select AI model
   */
  async selectModel(modelName: string): Promise<ScreenshotResult> {
    if (!this.selectors.has('modelSelector')) {
      console.log(`[${this.platform}] Model selection not supported`);
      return this.screenshot('model-not-supported');
    }
    
    // Click model selector
    const selectorStr = this.selectors.getCombined('modelSelector');
    const selector = await this.waitForSelector(selectorStr);
    await selector.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Click model menu item
    const menuItemSelector = this.selectors.getModelMenuItem(modelName);
    if (!menuItemSelector) {
      throw new SelectorError(`No menu item selector for model: ${modelName}`, modelName);
    }
    
    const menuItem = await this.waitForSelector(menuItemSelector);
    await menuItem.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    return this.screenshot('model-selected');
  }
  
  // ==========================================================================
  // Mode Selection (optional - override in subclasses)
  // ==========================================================================
  
  /**
   * Enable research/thinking mode
   */
  async setMode(modeName: string): Promise<ScreenshotResult> {
    if (!this.selectors.has('modeSelector')) {
      console.log(`[${this.platform}] Mode selection not supported`);
      return this.screenshot('mode-not-supported');
    }
    
    // Click mode selector
    const selectorStr = this.selectors.getCombined('modeSelector');
    const selector = await this.waitForSelector(selectorStr);
    await selector.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    // Click mode menu item
    const menuItemSelector = this.selectors.getModeMenuItem(modeName);
    if (!menuItemSelector) {
      throw new SelectorError(`No menu item selector for mode: ${modeName}`, modeName);
    }
    
    const menuItem = await this.waitForSelector(menuItemSelector);
    await menuItem.click();
    await this.sleep(TIMING.MENU_RENDER);
    
    return this.screenshot('mode-set');
  }
  
  // ==========================================================================
  // Artifact Download (optional - override in subclasses)
  // ==========================================================================
  
  /**
   * Download artifact
   */
  async downloadArtifact(downloadPath: string = '/tmp'): Promise<{ success: boolean; filePath?: string; screenshot: string }> {
    if (!this.selectors.has('downloadButton')) {
      return {
        success: false,
        screenshot: (await this.screenshot('download-not-supported')).path,
      };
    }
    
    // Implementation varies by platform - override in subclasses
    return {
      success: false,
      screenshot: (await this.screenshot('download-not-implemented')).path,
    };
  }
  
  // ==========================================================================
  // Navigation
  // ==========================================================================
  
  /**
   * Navigate to specific conversation
   */
  async goToConversation(conversationId: string): Promise<void> {
    const url = this.buildConversationUrl(conversationId);
    await this.page.goto(url, { waitUntil: 'networkidle' });
  }
  
  /**
   * Start new conversation
   */
  async newConversation(): Promise<string | null> {
    const url = `${this.config.baseUrl}${this.config.newChatPath}`;
    await this.page.goto(url, { waitUntil: 'networkidle' });
    await this.sleep(2000);
    
    return this.extractConversationId(this.page.url());
  }
  
  /**
   * Get current conversation ID from URL
   */
  getCurrentConversationId(): string | null {
    return this.extractConversationId(this.page.url());
  }
  
  protected buildConversationUrl(conversationId: string): string {
    switch (this.platform) {
      case 'claude':
        return `${this.config.baseUrl}/chat/${conversationId}`;
      case 'chatgpt':
        return `${this.config.baseUrl}/c/${conversationId}`;
      case 'gemini':
        return `${this.config.baseUrl}/app/${conversationId}`;
      case 'grok':
        return `${this.config.baseUrl}/chat/${conversationId}`;
      case 'perplexity':
        return `${this.config.baseUrl}/search/${conversationId}`;
      default:
        return `${this.config.baseUrl}/${conversationId}`;
    }
  }
  
  protected extractConversationId(url: string): string | null {
    const match = url.match(this.config.conversationPattern);
    return match?.[1] || null;
  }
  
  // ==========================================================================
  // Screenshot Utilities
  // ==========================================================================
  
  /**
   * Take screenshot with standardized naming
   */
  async screenshot(label: string): Promise<ScreenshotResult> {
    const timestamp = Date.now();
    const filename = `taey-${this.platform}-${label}-${timestamp}.png`;
    const filepath = path.join(this.screenshotDir, filename);
    
    await this.page.screenshot({ path: filepath, fullPage: false });
    
    return {
      path: filepath,
      timestamp: new Date(),
    };
  }
  
  private ensureScreenshotDir(): void {
    if (!fs.existsSync(this.screenshotDir)) {
      fs.mkdirSync(this.screenshotDir, { recursive: true });
    }
  }
  
  // ==========================================================================
  // Selector Utilities
  // ==========================================================================
  
  /**
   * Wait for selector with timeout
   */
  protected async waitForSelector(selector: string, timeout: number = 10000) {
    try {
      return await this.page.waitForSelector(selector, { timeout });
    } catch {
      throw new SelectorError(
        `Selector not found within ${timeout}ms`,
        selector
      );
    }
  }
  
  /**
   * Try multiple selectors, return first match
   */
  protected async trySelectors(selectors: string[], timeout: number = 5000) {
    for (const selector of selectors) {
      try {
        return await this.page.waitForSelector(selector, { timeout });
      } catch {
        continue;
      }
    }
    throw new SelectorError(
      'None of the selectors matched',
      selectors.join(' | ')
    );
  }
  
  // ==========================================================================
  // Utility Functions
  // ==========================================================================
  
  protected sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
