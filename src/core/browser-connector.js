/**
 * Browser Connector - CDP connection to local Chrome/Firefox
 *
 * Cross-platform support:
 * - macOS: Chrome/Chromium via CDP
 * - Linux: Chrome/Chromium/Firefox via CDP
 *
 * Key insight: Connect to EXISTING browser session (logged into all AI chats)
 * rather than launching new browser. This preserves auth cookies and sessions.
 *
 * Launch browser with debugging:
 *   macOS: /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
 *   Linux Chrome: google-chrome --remote-debugging-port=9222
 *   Linux Firefox: firefox --remote-debugging-port=9222
 */

import { chromium, firefox } from 'playwright';
import { exec } from 'child_process';
import { promisify } from 'util';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

const execAsync = promisify(exec);

export class BrowserConnector {
  constructor(config = {}) {
    this.debuggingPort = config.debuggingPort || 9222;
    this.browser = null;
    this.context = null;
    this.pages = new Map(); // Track pages by AI family member name
    this.browserWindowName = null; // Cached window name for xdotool/osascript
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
   * Launch browser with remote debugging if not already running
   * Cross-platform: supports Chrome/Chromium/Firefox on macOS and Linux
   */
  async ensureBrowserRunning() {
    if (await this.isDebuggingAvailable()) {
      console.log(`✓ Browser debugging already available on port ${this.debuggingPort}`);
      return true;
    }

    console.log('Starting browser with remote debugging...');

    const platform = os.platform();

    if (platform === 'darwin') {
      // macOS: Try Chrome/Chromium
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
    } else if (platform === 'linux') {
      // Linux: Try to find and launch browser
      // Priority: google-chrome > chromium > firefox

      let browserCmd = null;
      let browserName = null;

      // Check for Chrome
      try {
        await execAsync('which google-chrome');
        browserCmd = 'google-chrome';
        browserName = 'Chrome';
      } catch {
        // Check for Chromium
        try {
          await execAsync('which chromium-browser');
          browserCmd = 'chromium-browser';
          browserName = 'Chromium';
        } catch {
          try {
            await execAsync('which chromium');
            browserCmd = 'chromium';
            browserName = 'Chromium';
          } catch {
            // Check for Firefox
            try {
              await execAsync('which firefox');
              browserCmd = 'firefox';
              browserName = 'Firefox';
            } catch {
              console.log('ERROR: No supported browser found');
              console.log('Please install: google-chrome, chromium-browser, chromium, or firefox');
              return false;
            }
          }
        }
      }

      console.log(`Found ${browserName}, launching with debugging...`);

      // Check if already running
      try {
        await execAsync(`pgrep -x "${browserCmd}"`);
        console.log(`${browserName} is running but debugging not enabled.`);
        console.log(`Please restart ${browserName} with:`);
        console.log(`  ${browserCmd} --remote-debugging-port=${this.debuggingPort}`);
        return false;
      } catch {
        // Not running, launch with debugging
        await execAsync(`${browserCmd} --remote-debugging-port=${this.debuggingPort} >/dev/null 2>&1 &`);

        // Wait for debugging to become available
        for (let i = 0; i < 10; i++) {
          await new Promise(r => setTimeout(r, 500));
          if (await this.isDebuggingAvailable()) {
            console.log(`✓ ${browserName} started with debugging enabled`);
            return true;
          }
        }
      }
    } else {
      console.log(`ERROR: Unsupported platform: ${platform}`);
      return false;
    }

    return false;
  }

  /**
   * Connect to existing browser via CDP
   * Auto-detects Firefox vs Chrome/Chromium
   */
  async connect() {
    if (!await this.ensureBrowserRunning()) {
      throw new Error('Browser debugging not available');
    }

    try {
      // Try Chromium first (Chrome, Chromium, Edge)
      try {
        this.browser = await chromium.connectOverCDP(`http://localhost:${this.debuggingPort}`);
        console.log(`✓ Connected to Chromium-based browser via CDP`);

        // Detect actual browser name for window management
        await this._detectBrowserWindowName();
      } catch (chromeError) {
        // If Chromium fails, try Firefox
        try {
          this.browser = await firefox.connectOverCDP(`http://localhost:${this.debuggingPort}`);
          console.log(`✓ Connected to Firefox via CDP`);
          this.browserWindowName = 'Firefox';
        } catch (firefoxError) {
          throw new Error(`Failed to connect to browser: ${chromeError.message}`);
        }
      }

      // Get existing context (with all cookies/sessions intact)
      const contexts = this.browser.contexts();
      this.context = contexts[0] || await this.browser.newContext();

      // Apply stealth measures to hide automation detection
      // ChatGPT and other sites check navigator.webdriver
      await this._applyStealthMeasures();

      console.log(`  Active pages: ${this.context.pages().length}`);

      return this.browser;
    } catch (error) {
      console.error('Failed to connect via CDP:', error.message);
      throw error;
    }
  }

  /**
   * Detect browser window name for window management (xdotool/osascript)
   * This is the name used by the window manager, not the CDP version
   */
  async _detectBrowserWindowName() {
    const platform = os.platform();

    if (platform === 'darwin') {
      // macOS: Always "Google Chrome" or "Chromium"
      try {
        await execAsync('pgrep -x "Google Chrome"');
        this.browserWindowName = 'Google Chrome';
      } catch {
        this.browserWindowName = 'Chromium';
      }
    } else if (platform === 'linux') {
      // Linux: Check which browser process is actually running
      // Note: Snap Chromium creates processes named "chrome" but windows titled "Chromium"
      // Priority: google-chrome > chromium-browser > chromium > chrome (snap)
      try {
        await execAsync('pgrep -x "google-chrome"');
        this.browserWindowName = 'Google Chrome';
        return;
      } catch {}

      try {
        await execAsync('pgrep -x "chromium-browser"');
        this.browserWindowName = 'Chromium';
        return;
      } catch {}

      try {
        await execAsync('pgrep -x "chromium"');
        this.browserWindowName = 'Chromium';
        return;
      } catch {}

      try {
        // Snap Chromium creates processes named "chrome" but windows are "- Chromium"
        await execAsync('pgrep -x "chrome"');
        this.browserWindowName = 'Chromium';
        return;
      } catch {}

      // Fallback to Chromium (most common)
      this.browserWindowName = 'Chromium';
    } else {
      // Fallback
      this.browserWindowName = 'Google Chrome';
    }
  }

  /**
   * Get browser window name for window management
   * Returns the name used by xdotool/osascript, not the CDP version
   */
  getBrowserName() {
    return this.browserWindowName || 'Chromium';
  }

  /**
   * Apply stealth measures to hide automation detection
   * ChatGPT and other sites check navigator.webdriver and other signals
   */
  async _applyStealthMeasures() {
    console.log('  Applying stealth measures...');

    // Add init script to all pages (existing and new)
    await this.context.addInitScript(() => {
      // Hide webdriver property - most important detection vector
      Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
      });

      // Mask automation indicators
      delete navigator.__proto__.webdriver;

      // Add realistic chrome object if missing
      if (!window.chrome) {
        window.chrome = {
          runtime: {},
          loadTimes: function() {},
          csi: function() {},
          app: {},
        };
      }

      // Mask Playwright-specific properties
      const originalQuery = window.navigator.permissions.query;
      window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
          Promise.resolve({ state: Notification.permission }) :
          originalQuery(parameters)
      );

      // Add realistic plugins (headless browsers often have none)
      Object.defineProperty(navigator, 'plugins', {
        get: () => {
          const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
          ];
          plugins.item = (i) => plugins[i];
          plugins.namedItem = (n) => plugins.find(p => p.name === n);
          plugins.refresh = () => {};
          return plugins;
        },
      });

      // Add realistic languages
      Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
      });

      // Console log to verify (only in debug)
      // console.log('[Stealth] Applied automation masking');
    });

    console.log('  ✓ Stealth measures applied');
  }

  /**
   * Get or create a page for a specific AI family member
   */
  async getPage(familyMember, url) {
    if (this.pages.has(familyMember)) {
      const page = this.pages.get(familyMember);
      if (!page.isClosed()) {
        await page.bringToFront();  // Bring cached tab to front
        console.log(`✓ Using cached ${familyMember} tab: ${page.url()}`);
        return page;
      }
    }

    // Look for existing tab with this URL
    const pages = this.context.pages();
    const urlPattern = url.replace('https://', '').split('/')[0];
    console.log(`  Searching for tab matching: ${urlPattern}`);
    for (const page of pages) {
      const pageUrl = page.url();
      if (pageUrl.includes(urlPattern)) {
        this.pages.set(familyMember, page);
        await page.bringToFront();  // Bring found tab to front
        console.log(`✓ Found existing ${familyMember} tab: ${pageUrl}`);
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
