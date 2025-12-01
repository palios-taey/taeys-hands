/**
 * Base Platform Adapter
 * 
 * Purpose: Abstract base class for platform-specific automation
 * Dependencies: browser connector, platform bridge, selector registry
 * Exports: BasePlatformAdapter class
 * 
 * Pattern:
 * - Shared implementations for common operations
 * - Abstract methods that subclasses MUST implement
 * - Override hooks for platform-specific quirks
 * 
 * @module platforms/base-adapter
 */

import path from 'path';
import { getTiming } from '../core/platform/bridge-factory.js';

/**
 * Fibonacci sequence for polling intervals
 */
const FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55];

/**
 * Screenshot intervals (Fibonacci indices)
 */
const SCREENSHOT_INTERVALS = new Set([0, 2, 5, 13, 34, 55]);

/**
 * Abstract base class for platform adapters
 */
export class BasePlatformAdapter {
  /**
   * @param {Object} options
   * @param {Page} options.page - Playwright page
   * @param {MacOSBridge|LinuxBridge} options.bridge - Platform automation bridge
   * @param {Object} options.selectors - Platform-specific selectors
   * @param {Object} options.config - Platform configuration
   */
  constructor(options) {
    this.page = options.page;
    this.bridge = options.bridge;
    this.selectors = options.selectors;
    this.config = options.config || {};
    
    this.name = 'base';
    this.screenshotDir = options.screenshotDir || '/tmp/taey-screenshots';
  }

  // ============================================
  // ABSTRACT METHODS (MUST implement in subclass)
  // ============================================

  /**
   * Get platform name
   * @returns {string}
   */
  getPlatformName() {
    throw new Error('Must implement getPlatformName() in subclass');
  }

  /**
   * Navigate to a new conversation
   * @returns {Promise<{conversationId: string, url: string}>}
   */
  async navigateToNew() {
    throw new Error('Must implement navigateToNew() in subclass');
  }

  /**
   * Navigate to an existing conversation
   * @param {string} conversationId
   * @returns {Promise<{url: string}>}
   */
  async navigateToExisting(conversationId) {
    throw new Error('Must implement navigateToExisting() in subclass');
  }

  /**
   * Extract conversation ID from current URL
   * @returns {Promise<string|null>}
   */
  async extractConversationId() {
    throw new Error('Must implement extractConversationId() in subclass');
  }

  /**
   * Select a model
   * @param {string} modelName
   * @param {Object} [options]
   * @returns {Promise<{success: boolean, screenshot: string}>}
   */
  async selectModel(modelName, options = {}) {
    throw new Error('Must implement selectModel() in subclass');
  }

  /**
   * Enable/disable research mode
   * @param {boolean} enabled
   * @param {Object} [options]
   * @returns {Promise<{success: boolean, screenshot: string}>}
   */
  async setResearchMode(enabled, options = {}) {
    throw new Error('Must implement setResearchMode() in subclass');
  }

  /**
   * Click the file attachment entry point (button/menu)
   * @returns {Promise<void>}
   */
  async clickAttachmentEntryPoint() {
    throw new Error('Must implement clickAttachmentEntryPoint() in subclass');
  }

  /**
   * Extract the latest AI response
   * @returns {Promise<string>}
   */
  async getLatestResponse() {
    throw new Error('Must implement getLatestResponse() in subclass');
  }

  /**
   * Download an artifact
   * @param {Object} options
   * @returns {Promise<{success: boolean, filePath: string, screenshot: string}>}
   */
  async downloadArtifact(options = {}) {
    throw new Error('Must implement downloadArtifact() in subclass');
  }

  // ============================================
  // SHARED IMPLEMENTATIONS (can override)
  // ============================================

  /**
   * Prepare input field for typing
   * Override to add platform-specific pre-input steps (e.g., dismiss overlays)
   * 
   * @param {Object} [options]
   * @returns {Promise<{screenshot: string, automationCompleted: boolean}>}
   */
  async prepareInput(options = {}) {
    const screenshotName = options.screenshotName || 'prepare-input';
    
    // Bring page to front
    await this.page.bringToFront();
    await this.sleep(getTiming('TAB_FOCUS'));
    
    // Focus browser window
    await this.bridge.focusApp();
    await this.sleep(getTiming('APP_FOCUS'));
    
    // Click input field
    const inputSelector = this.selectors.chatInput;
    const input = await this.page.waitForSelector(inputSelector, { timeout: 10000 });
    await input.click();
    await this.sleep(200);
    
    // Capture screenshot
    const screenshot = await this.screenshot(screenshotName);
    
    return {
      screenshot,
      automationCompleted: true
    };
  }

  /**
   * Type a message with human-like behavior
   * 
   * @param {string} message - Message to type
   * @param {Object} [options]
   * @param {boolean} [options.humanLike=true] - Use human-like typing
   * @param {boolean} [options.mixedContent=true] - Mix typing with pasting
   * @returns {Promise<{screenshot: string, automationCompleted: boolean}>}
   */
  async typeMessage(message, options = {}) {
    const humanLike = options.humanLike !== false;
    const mixedContent = options.mixedContent !== false;
    const screenshotName = options.screenshotName || 'type-message';
    
    if (humanLike) {
      // Bring to front and focus again
      await this.page.bringToFront();
      await this.sleep(200);
      await this.bridge.focusApp();
      
      // Click input with screen coordinates for reliable focus
      await this.clickInputWithScreenCoords();
      
      // Type message
      if (mixedContent && message.length > 50) {
        await this.bridge.typeWithMixedContent(message);
      } else {
        await this.bridge.safeTypeLong(message);
      }
    } else {
      // Direct injection (faster but may be detected)
      const input = await this.page.waitForSelector(this.selectors.chatInput);
      await input.fill(message);
    }
    
    await this.sleep(getTiming('TYPING_BUFFER'));
    
    const screenshot = await this.screenshot(screenshotName);
    
    return {
      screenshot,
      automationCompleted: true
    };
  }

  /**
   * Click the send button (Enter key)
   * 
   * @param {Object} [options]
   * @returns {Promise<{screenshot: string, automationCompleted: boolean}>}
   */
  async clickSend(options = {}) {
    const screenshotName = options.screenshotName || 'click-send';
    
    await this.sleep(300);
    await this.bridge.pressKey('return');
    
    // Wait for network activity
    await this.sleep(getTiming('NETWORK_SEND'));
    
    const screenshot = await this.screenshot(screenshotName);
    
    return {
      screenshot,
      automationCompleted: true
    };
  }

  /**
   * Wait for AI response using stability detection
   * Override for platform-specific response detection
   * 
   * @param {number} [timeout=300000] - Max wait time (ms)
   * @param {Object} [options]
   * @returns {Promise<{content: string, detectionMethod: string, confidence: number, detectionTime: number}>}
   */
  async waitForResponse(timeout = 300000, options = {}) {
    const sessionId = options.sessionId || 'unknown';
    const takeScreenshots = options.screenshots !== false;
    
    const startTime = Date.now();
    let lastContent = '';
    let stableCount = 0;
    const stabilityRequired = 2;
    let fibIndex = 0;
    
    // Get initial content
    const initialContent = await this.getLatestResponse();
    
    // Initial screenshot
    if (takeScreenshots) {
      await this.screenshot(`response-t0`);
    }
    
    while (Date.now() - startTime < timeout) {
      const content = await this.getLatestResponse();
      
      // Check for new, stable content
      if (content && content !== initialContent && content.length > 0) {
        if (content === lastContent) {
          stableCount++;
          
          if (stableCount >= stabilityRequired) {
            const detectionTime = Date.now() - startTime;
            
            // Final screenshot
            if (takeScreenshots) {
              await this.screenshot(`response-complete`);
            }
            
            return {
              content,
              detectionMethod: 'contentStability',
              confidence: 0.85,
              detectionTime
            };
          }
        } else {
          stableCount = 0;
          lastContent = content;
        }
      }
      
      // Calculate wait time
      let waitSeconds;
      if (stableCount > 0) {
        waitSeconds = 2; // Fast polling for confirmation
      } else if (fibIndex < 3) {
        waitSeconds = 1; // First few checks at 1s
      } else {
        waitSeconds = FIBONACCI[Math.min(fibIndex, FIBONACCI.length - 1)];
      }
      
      await this.sleep(waitSeconds * 1000);
      fibIndex++;
      
      // Take screenshots at intervals
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      if (takeScreenshots && SCREENSHOT_INTERVALS.has(elapsed)) {
        await this.screenshot(`response-t${elapsed}s`);
      }
    }
    
    // Timeout - return whatever we have
    return {
      content: lastContent || initialContent || '',
      detectionMethod: 'timeout',
      confidence: 0.5,
      detectionTime: Date.now() - startTime
    };
  }

  /**
   * Attach a file using native file picker
   * 
   * @param {string} filePath - Absolute path to file
   * @param {Object} [options]
   * @returns {Promise<{screenshot: string, automationCompleted: boolean, filePath: string}>}
   */
  async attachFile(filePath, options = {}) {
    const screenshotName = options.screenshotName || 'attach-file';
    
    // Verify file exists
    const fs = await import('fs');
    if (!fs.existsSync(filePath)) {
      throw new Error(`File not found: ${filePath}`);
    }
    
    // Click platform-specific entry point
    await this.clickAttachmentEntryPoint();
    
    // Wait for file picker to appear
    await this.sleep(getTiming('FILE_DIALOG_SPAWN'));
    
    // Navigate file picker
    await this.bridge.navigateFilePicker(filePath);
    
    // Wait for upload to process
    await this.sleep(getTiming('FILE_UPLOAD_PROCESS'));
    
    const screenshot = await this.screenshot(screenshotName);
    
    return {
      screenshot,
      automationCompleted: true,
      filePath
    };
  }

  // ============================================
  // UTILITY METHODS (never override)
  // ============================================

  /**
   * Take a screenshot
   * 
   * @param {string} name - Screenshot name
   * @returns {Promise<string>} Screenshot path
   */
  async screenshot(name) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `taey-${this.name}-${name}-${timestamp}.png`;
    const filepath = path.join(this.screenshotDir, filename);
    
    await this.page.screenshot({ path: filepath });
    
    return filepath;
  }

  /**
   * Click input with screen coordinates for reliable X11 focus
   * 
   * @returns {Promise<void>}
   */
  async clickInputWithScreenCoords() {
    const input = await this.page.waitForSelector(this.selectors.chatInput);
    const box = await input.boundingBox();
    
    if (!box) {
      // Fall back to Playwright click
      await input.click();
      return;
    }
    
    // Get window position
    const windowInfo = await this.page.evaluate(() => ({
      screenX: window.screenX,
      screenY: window.screenY,
      outerHeight: window.outerHeight,
      innerHeight: window.innerHeight,
      outerWidth: window.outerWidth,
      innerWidth: window.innerWidth
    }));
    
    // Calculate screen coordinates
    const chromeHeight = windowInfo.outerHeight - windowInfo.innerHeight;
    const chromeWidth = windowInfo.outerWidth - windowInfo.innerWidth;
    const screenX = windowInfo.screenX + (chromeWidth / 2) + box.x + (box.width / 2);
    const screenY = windowInfo.screenY + chromeHeight + box.y + (box.height / 2);
    
    await this.bridge.clickAt(Math.round(screenX), Math.round(screenY));
  }

  /**
   * Wait for an element with fallback selectors
   * 
   * @param {string|string[]} selectors
   * @param {Object} [options]
   * @returns {Promise<ElementHandle|null>}
   */
  async waitForSelector(selectors, options = {}) {
    const timeout = options.timeout ?? 5000;
    const selectorArray = Array.isArray(selectors) ? selectors : [selectors];
    
    for (const selector of selectorArray) {
      try {
        return await this.page.waitForSelector(selector, { timeout });
      } catch {
        // Try next selector
      }
    }
    
    return null;
  }

  /**
   * Click an element with retry logic
   * 
   * @param {string|string[]} selectors
   * @param {Object} [options]
   * @returns {Promise<boolean>}
   */
  async clickWithRetry(selectors, options = {}) {
    const maxRetries = options.maxRetries ?? 3;
    const selectorArray = Array.isArray(selectors) ? selectors : [selectors];
    
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      for (const selector of selectorArray) {
        try {
          const element = await this.page.waitForSelector(selector, { timeout: 5000 });
          await element.click();
          return true;
        } catch {
          // Try next selector
        }
      }
      
      if (attempt < maxRetries) {
        console.log(`[${this.name}] Click retry ${attempt}/${maxRetries}`);
        await this.sleep(1000 * attempt); // Exponential backoff
      }
    }
    
    return false;
  }

  /**
   * Sleep for specified milliseconds
   * 
   * @param {number} ms
   * @returns {Promise<void>}
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Get current page URL
   * 
   * @returns {string}
   */
  getCurrentUrl() {
    return this.page.url();
  }

  /**
   * Check if we're on the correct platform
   * 
   * @returns {boolean}
   */
  isOnPlatform() {
    const url = this.getCurrentUrl();
    const baseUrl = this.config.url || '';
    return url.includes(new URL(baseUrl).hostname);
  }
}
