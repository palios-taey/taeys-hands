/**
 * Browser Connector
 * 
 * Purpose: CDP connection and page management using Playwright
 * Dependencies: playwright
 * Exports: BrowserConnector class
 * 
 * Capabilities:
 * - Connect to existing Chrome instance via CDP
 * - Create and manage browser pages
 * - Screenshot capture with timestamps
 * - Health monitoring
 * 
 * @module core/browser/connector
 */

import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';

/**
 * Browser connection and page management
 */
export class BrowserConnector {
  /**
   * @param {Object} options
   * @param {string} [options.wsEndpoint] - WebSocket endpoint for CDP
   * @param {string} [options.cdpUrl='http://127.0.0.1:9222'] - CDP debugging URL
   * @param {string} [options.screenshotDir='/tmp/taey-screenshots'] - Screenshot directory
   */
  constructor(options = {}) {
    this.wsEndpoint = options.wsEndpoint;
    this.cdpUrl = options.cdpUrl || process.env.CDP_URL || 'http://127.0.0.1:9222';
    this.screenshotDir = options.screenshotDir || '/tmp/taey-screenshots';
    
    this.browser = null;
    this.connected = false;
    
    // Ensure screenshot directory exists
    if (!fs.existsSync(this.screenshotDir)) {
      fs.mkdirSync(this.screenshotDir, { recursive: true });
    }
  }

  /**
   * Connect to Chrome via CDP
   * 
   * @returns {Promise<void>}
   * @throws {Error} If connection fails
   */
  async connect() {
    if (this.connected) return;
    
    try {
      // Try WebSocket endpoint first
      if (this.wsEndpoint) {
        this.browser = await chromium.connectOverCDP(this.wsEndpoint);
      } else {
        // Discover WebSocket endpoint from CDP URL
        this.browser = await chromium.connectOverCDP(this.cdpUrl);
      }
      
      this.connected = true;
      console.log('[BrowserConnector] Connected to Chrome via CDP');
    } catch (error) {
      throw new Error(
        `Failed to connect to Chrome. ` +
        `Ensure Chrome is running with --remote-debugging-port=9222. ` +
        `Error: ${error.message}`
      );
    }
  }

  /**
   * Create a new browser page
   * 
   * @param {Object} [options]
   * @param {string} [options.url] - Initial URL to navigate to
   * @returns {Promise<Page>} Playwright page object
   */
  async createPage(options = {}) {
    if (!this.connected) {
      await this.connect();
    }
    
    // Get the default browser context
    const contexts = this.browser.contexts();
    let context;
    
    if (contexts.length > 0) {
      context = contexts[0];
    } else {
      context = await this.browser.newContext();
    }
    
    const page = await context.newPage();
    
    // Navigate to URL if provided
    if (options.url) {
      await page.goto(options.url, { waitUntil: 'domcontentloaded' });
    }
    
    return page;
  }

  /**
   * Get an existing page by URL pattern
   * 
   * @param {string|RegExp} urlPattern - URL to match
   * @returns {Promise<Page|null>}
   */
  async findPage(urlPattern) {
    if (!this.connected) {
      await this.connect();
    }
    
    for (const context of this.browser.contexts()) {
      for (const page of context.pages()) {
        const url = page.url();
        
        if (typeof urlPattern === 'string') {
          if (url.includes(urlPattern)) return page;
        } else {
          if (urlPattern.test(url)) return page;
        }
      }
    }
    
    return null;
  }

  /**
   * Get all open pages
   * 
   * @returns {Promise<Page[]>}
   */
  async getPages() {
    if (!this.connected) {
      await this.connect();
    }
    
    const pages = [];
    for (const context of this.browser.contexts()) {
      pages.push(...context.pages());
    }
    return pages;
  }

  /**
   * Capture a screenshot
   * 
   * @param {Page} page - Playwright page
   * @param {Object} [options]
   * @param {string} [options.name] - Screenshot name (default: timestamp)
   * @param {string} [options.prefix] - Filename prefix
   * @param {boolean} [options.fullPage=false] - Capture full page
   * @returns {Promise<string>} Screenshot file path
   */
  async screenshot(page, options = {}) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const prefix = options.prefix || 'taey';
    const name = options.name || timestamp;
    
    const filename = `${prefix}-${name}.png`;
    const filepath = path.join(this.screenshotDir, filename);
    
    await page.screenshot({
      path: filepath,
      fullPage: options.fullPage || false
    });
    
    return filepath;
  }

  /**
   * Check if a page is still connected
   * 
   * @param {Page} page
   * @returns {Promise<boolean>}
   */
  async isPageAlive(page) {
    try {
      // Try a simple operation
      await page.url();
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Close a page
   * 
   * @param {Page} page
   * @returns {Promise<void>}
   */
  async closePage(page) {
    try {
      await page.close();
    } catch (error) {
      console.warn('[BrowserConnector] Error closing page:', error.message);
    }
  }

  /**
   * Disconnect from browser
   * 
   * @returns {Promise<void>}
   */
  async disconnect() {
    if (this.browser) {
      // Don't close the browser, just disconnect
      // User's browser stays open
      this.connected = false;
      console.log('[BrowserConnector] Disconnected');
    }
  }

  /**
   * Check browser health
   * 
   * @returns {Promise<{healthy: boolean, pageCount: number}>}
   */
  async healthCheck() {
    try {
      if (!this.connected) {
        return { healthy: false, pageCount: 0 };
      }
      
      const pages = await this.getPages();
      return {
        healthy: true,
        pageCount: pages.length
      };
    } catch {
      return { healthy: false, pageCount: 0 };
    }
  }

  /**
   * Bring a page to front (focus)
   * 
   * @param {Page} page
   * @returns {Promise<void>}
   */
  async bringToFront(page) {
    await page.bringToFront();
  }

  /**
   * Get viewport info for a page
   * 
   * @param {Page} page
   * @returns {Promise<Object>}
   */
  async getViewportInfo(page) {
    return await page.evaluate(() => ({
      screenX: window.screenX,
      screenY: window.screenY,
      outerWidth: window.outerWidth,
      outerHeight: window.outerHeight,
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight
    }));
  }

  /**
   * Convert viewport coordinates to screen coordinates
   * 
   * @param {Page} page
   * @param {number} viewportX - X coordinate in viewport
   * @param {number} viewportY - Y coordinate in viewport
   * @returns {Promise<{x: number, y: number}>}
   */
  async viewportToScreen(page, viewportX, viewportY) {
    const info = await this.getViewportInfo(page);
    
    const chromeHeight = info.outerHeight - info.innerHeight;
    const chromeWidth = info.outerWidth - info.innerWidth;
    
    return {
      x: info.screenX + (chromeWidth / 2) + viewportX,
      y: info.screenY + chromeHeight + viewportY
    };
  }

  /**
   * Clean up old screenshots (older than retention days)
   * 
   * @param {number} [retentionDays=7] - Days to keep
   * @returns {Promise<number>} Number of files deleted
   */
  async cleanupScreenshots(retentionDays = 7) {
    const cutoff = Date.now() - (retentionDays * 24 * 60 * 60 * 1000);
    let deleted = 0;
    
    const files = fs.readdirSync(this.screenshotDir);
    
    for (const file of files) {
      const filepath = path.join(this.screenshotDir, file);
      const stats = fs.statSync(filepath);
      
      if (stats.mtimeMs < cutoff) {
        fs.unlinkSync(filepath);
        deleted++;
      }
    }
    
    return deleted;
  }
}

/**
 * Singleton instance
 */
let connectorInstance = null;

/**
 * Get the singleton BrowserConnector instance
 * 
 * @param {Object} [options]
 * @returns {BrowserConnector}
 */
export function getBrowserConnector(options) {
  if (!connectorInstance) {
    connectorInstance = new BrowserConnector(options);
  }
  return connectorInstance;
}
