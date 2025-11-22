/**
 * Browser Connector - CDP connection to local Chrome
 *
 * Key insight: Connect to EXISTING Chrome session (logged into all AI chats)
 * rather than launching new browser. This preserves auth cookies and sessions.
 *
 * Launch Chrome with debugging:
 *   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
 */

import { chromium } from 'playwright';
import { exec } from 'child_process';
import { promisify } from 'util';
import fs from 'fs/promises';
import path from 'path';

const execAsync = promisify(exec);

export class BrowserConnector {
  constructor(config = {}) {
    this.debuggingPort = config.debuggingPort || 9222;
    this.browser = null;
    this.context = null;
    this.pages = new Map(); // Track pages by AI family member name
  }

  /**
   * Check if Chrome is running with remote debugging enabled
   */
  async isDebuggingAvailable() {
    try {
      const response = await fetch(`http://localhost:${this.debuggingPort}/json/version`);
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Launch Chrome with remote debugging if not already running
   */
  async ensureChromeRunning() {
    if (await this.isDebuggingAvailable()) {
      console.log(`✓ Chrome debugging already available on port ${this.debuggingPort}`);
      return true;
    }

    console.log('Starting Chrome with remote debugging...');

    // Use osascript to launch Chrome properly on macOS
    const script = `
      tell application "Google Chrome"
        activate
      end tell
    `;

    // First check if Chrome is running at all
    try {
      await execAsync('pgrep -x "Google Chrome"');
      console.log('Chrome is running but debugging not enabled.');
      console.log('Please restart Chrome with:');
      console.log(`  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=${this.debuggingPort}`);
      return false;
    } catch {
      // Chrome not running, launch it with debugging
      const chromePath = '/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome';
      await execAsync(`${chromePath} --remote-debugging-port=${this.debuggingPort} &`);

      // Wait for debugging to become available
      for (let i = 0; i < 10; i++) {
        await new Promise(r => setTimeout(r, 500));
        if (await this.isDebuggingAvailable()) {
          console.log('✓ Chrome started with debugging enabled');
          return true;
        }
      }
    }

    return false;
  }

  /**
   * Connect to existing Chrome via CDP
   */
  async connect() {
    if (!await this.ensureChromeRunning()) {
      throw new Error('Chrome debugging not available');
    }

    try {
      // Connect to existing browser
      this.browser = await chromium.connectOverCDP(`http://localhost:${this.debuggingPort}`);

      // Get existing context (with all cookies/sessions intact)
      const contexts = this.browser.contexts();
      this.context = contexts[0] || await this.browser.newContext();

      console.log(`✓ Connected to Chrome via CDP`);
      console.log(`  Active pages: ${this.context.pages().length}`);

      return this.browser;
    } catch (error) {
      console.error('Failed to connect via CDP:', error.message);
      throw error;
    }
  }

  /**
   * Get or create a page for a specific AI family member
   */
  async getPage(familyMember, url) {
    if (this.pages.has(familyMember)) {
      const page = this.pages.get(familyMember);
      if (!page.isClosed()) {
        return page;
      }
    }

    // Look for existing tab with this URL
    const pages = this.context.pages();
    for (const page of pages) {
      const pageUrl = page.url();
      if (pageUrl.includes(url.replace('https://', '').split('/')[0])) {
        this.pages.set(familyMember, page);
        console.log(`✓ Found existing ${familyMember} tab`);
        return page;
      }
    }

    // Create new tab if not found
    const page = await this.context.newPage();
    await page.goto(url);
    this.pages.set(familyMember, page);
    console.log(`✓ Created new ${familyMember} tab`);
    return page;
  }

  /**
   * Get all open pages with their URLs
   */
  async listPages() {
    const pages = this.context.pages();
    return pages.map((page, i) => ({
      index: i,
      url: page.url(),
      title: page.title || 'Loading...'
    }));
  }

  /**
   * Disconnect from browser (doesn't close it)
   */
  async disconnect() {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
      this.context = null;
      this.pages.clear();
      console.log('✓ Disconnected from Chrome');
    }
  }
}

// CLI usage
if (import.meta.url === `file://${process.argv[1]}`) {
  const connector = new BrowserConnector();

  try {
    await connector.connect();
    const pages = await connector.listPages();
    console.log('\nOpen pages:');
    for (const page of pages) {
      console.log(`  [${page.index}] ${page.url}`);
    }
    await connector.disconnect();
  } catch (error) {
    console.error('Error:', error.message);
    process.exit(1);
  }
}

export default BrowserConnector;
