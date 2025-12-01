/**
 * Selector Registry
 * 
 * Purpose: Centralized loading and querying of UI selectors
 * Dependencies: fs (for loading config files)
 * Exports: SelectorRegistry class
 * 
 * Design:
 * - Selectors stored in JSON config files
 * - Multiple fallback selectors per element
 * - Version tracking for selector updates
 * - Runtime selector testing capability
 * 
 * @module core/selectors/selector-registry
 */

import fs from 'fs';
import path from 'path';

/**
 * Centralized selector storage and querying
 */
export class SelectorRegistry {
  /**
   * @param {Object} [options]
   * @param {string} [options.configDir] - Directory containing selector configs
   */
  constructor(options = {}) {
    this.configDir = options.configDir || path.join(process.cwd(), 'config', 'selectors');
    
    /**
     * Loaded selectors by platform
     * @type {Map<string, Object>}
     */
    this.selectors = new Map();
    
    /**
     * Selector metadata (version, last tested, etc.)
     * @type {Map<string, Object>}
     */
    this.metadata = new Map();
  }

  /**
   * Load selectors for a platform from config file
   * 
   * @param {string} platform - Platform name (claude, chatgpt, etc.)
   * @returns {Promise<Object>} Loaded selectors
   */
  async loadPlatform(platform) {
    const configPath = path.join(this.configDir, `${platform}.json`);
    
    if (!fs.existsSync(configPath)) {
      throw new Error(`Selector config not found: ${configPath}`);
    }
    
    const content = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(content);
    
    this.selectors.set(platform, config.selectors);
    this.metadata.set(platform, {
      version: config.version || '1.0.0',
      lastUpdated: config.lastUpdated || new Date().toISOString(),
      loadedAt: new Date().toISOString()
    });
    
    console.log(`[SelectorRegistry] Loaded selectors for ${platform} (v${config.version || '1.0.0'})`);
    
    return config.selectors;
  }

  /**
   * Load all platform selectors
   * 
   * @returns {Promise<void>}
   */
  async loadAll() {
    const platforms = ['claude', 'chatgpt', 'gemini', 'grok', 'perplexity'];
    
    for (const platform of platforms) {
      try {
        await this.loadPlatform(platform);
      } catch (error) {
        console.warn(`[SelectorRegistry] Could not load ${platform}: ${error.message}`);
      }
    }
  }

  /**
   * Get selectors for a platform
   * 
   * @param {string} platform
   * @returns {Object} Selectors
   * @throws {Error} If platform not loaded
   */
  get(platform) {
    const selectors = this.selectors.get(platform);
    
    if (!selectors) {
      throw new Error(`Selectors not loaded for platform: ${platform}. Call loadPlatform() first.`);
    }
    
    return selectors;
  }

  /**
   * Get a specific selector with fallbacks
   * 
   * @param {string} platform
   * @param {string} element - Element name (e.g., 'chatInput', 'sendButton')
   * @returns {string|string[]} Selector or array of fallback selectors
   */
  getSelector(platform, element) {
    const selectors = this.get(platform);
    
    const value = selectors[element];
    
    if (value === undefined) {
      throw new Error(`Selector not found: ${platform}.${element}`);
    }
    
    return value;
  }

  /**
   * Get selector as array (handles single or multiple fallbacks)
   * 
   * @param {string} platform
   * @param {string} element
   * @returns {string[]}
   */
  getSelectorArray(platform, element) {
    const selector = this.getSelector(platform, element);
    return Array.isArray(selector) ? selector : [selector];
  }

  /**
   * Test if a selector matches any elements on a page
   * 
   * @param {Page} page - Playwright page
   * @param {string} selector - CSS selector
   * @returns {Promise<boolean>}
   */
  async testSelector(page, selector) {
    try {
      const element = await page.$(selector);
      return element !== null;
    } catch {
      return false;
    }
  }

  /**
   * Find first working selector from array on page
   * 
   * @param {Page} page - Playwright page
   * @param {string[]} selectors - Array of selectors to try
   * @param {Object} [options]
   * @param {number} [options.timeout=5000] - Timeout per selector
   * @returns {Promise<{selector: string, element: ElementHandle}|null>}
   */
  async findFirstMatch(page, selectors, options = {}) {
    const timeout = options.timeout ?? 5000;
    
    for (const selector of selectors) {
      try {
        const element = await page.waitForSelector(selector, { timeout });
        return { selector, element };
      } catch {
        // Try next selector
      }
    }
    
    return null;
  }

  /**
   * Verify all selectors for a platform work on a page
   * 
   * @param {Page} page - Playwright page (must be on correct platform)
   * @param {string} platform
   * @returns {Promise<Object>} Results with working/broken selectors
   */
  async verifyPlatform(page, platform) {
    const selectors = this.get(platform);
    const results = {
      platform,
      working: [],
      broken: [],
      timestamp: new Date().toISOString()
    };
    
    for (const [element, selector] of Object.entries(selectors)) {
      const selectorArray = Array.isArray(selector) ? selector : [selector];
      let found = false;
      
      for (const sel of selectorArray) {
        if (await this.testSelector(page, sel)) {
          found = true;
          results.working.push({ element, selector: sel });
          break;
        }
      }
      
      if (!found) {
        results.broken.push({ element, selectors: selectorArray });
      }
    }
    
    return results;
  }

  /**
   * Update a selector in memory and optionally persist
   * 
   * @param {string} platform
   * @param {string} element
   * @param {string|string[]} newSelector
   * @param {boolean} [persist=false] - Write to config file
   */
  updateSelector(platform, element, newSelector, persist = false) {
    const selectors = this.get(platform);
    selectors[element] = newSelector;
    
    if (persist) {
      this.persistPlatform(platform);
    }
  }

  /**
   * Persist current selectors to config file
   * 
   * @param {string} platform
   */
  persistPlatform(platform) {
    const configPath = path.join(this.configDir, `${platform}.json`);
    const selectors = this.get(platform);
    const metadata = this.metadata.get(platform) || {};
    
    const config = {
      version: metadata.version || '1.0.0',
      lastUpdated: new Date().toISOString(),
      selectors
    };
    
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
    console.log(`[SelectorRegistry] Persisted selectors for ${platform}`);
  }

  /**
   * Get metadata for a platform
   * 
   * @param {string} platform
   * @returns {Object|null}
   */
  getMetadata(platform) {
    return this.metadata.get(platform) || null;
  }

  /**
   * Get summary of all loaded platforms
   * 
   * @returns {Object}
   */
  getSummary() {
    const summary = {};
    
    for (const [platform, selectors] of this.selectors) {
      const metadata = this.metadata.get(platform) || {};
      summary[platform] = {
        selectorCount: Object.keys(selectors).length,
        version: metadata.version,
        loadedAt: metadata.loadedAt
      };
    }
    
    return summary;
  }
}

/**
 * Singleton instance
 */
let registryInstance = null;

/**
 * Get the singleton SelectorRegistry instance
 * 
 * @param {Object} [options]
 * @returns {SelectorRegistry}
 */
export function getSelectorRegistry(options) {
  if (!registryInstance) {
    registryInstance = new SelectorRegistry(options);
  }
  return registryInstance;
}
