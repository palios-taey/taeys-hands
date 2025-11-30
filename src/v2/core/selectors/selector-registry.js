/**
 * SelectorRegistry - Centralized selector management for taey-hands v2
 *
 * Loads per-platform selector JSON files from config/selectors/*.json
 * and provides a simple getSelector(platform, key) API with
 * descriptive errors and fallback support.
 *
 * @class SelectorRegistry
 */

import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class SelectorRegistry {
  /**
   * @param {string} baseDir - Base directory for selector configs
   */
  constructor(baseDir = path.join(process.cwd(), 'config', 'selectors')) {
    this.baseDir = baseDir;
    this.platformCache = new Map();
  }

  /**
   * Load platform selector configuration from JSON file
   * @private
   * @param {string} platform - Platform name (chatgpt, claude, gemini, grok, perplexity)
   * @returns {Promise<Object>} Platform selector config
   */
  async loadPlatform(platform) {
    const cached = this.platformCache.get(platform);
    if (cached) return cached;

    const filePath = path.join(this.baseDir, `${platform}.json`);

    try {
      const raw = await fs.readFile(filePath, 'utf8');
      const parsed = JSON.parse(raw);

      if (!parsed.selectors) {
        throw new Error(
          `Selector config for platform '${platform}' is missing 'selectors' map (${filePath}).`
        );
      }

      this.platformCache.set(platform, parsed);
      return parsed;
    } catch (error) {
      if (error.code === 'ENOENT') {
        throw new Error(
          `Selector config file not found for platform '${platform}' at ${filePath}. ` +
          `Available platforms: chatgpt, claude, gemini, grok, perplexity`
        );
      }
      throw error;
    }
  }

  /**
   * Returns the best selector string for a given (platform, key).
   * Uses primary selector, falling back if necessary.
   *
   * @param {string} platform - Platform name
   * @param {string} key - Selector key (e.g., 'attach_button', 'send_button')
   * @returns {Promise<string>} Selector string
   */
  async getSelector(platform, key) {
    const cfg = await this.loadPlatform(platform);
    const def = cfg.selectors[key];

    if (!def) {
      const available = Object.keys(cfg.selectors).sort();
      throw new Error(
        `Selector key '${key}' not found for platform '${platform}'. ` +
        `Available keys: ${available.join(', ')}`
      );
    }

    if (def.primary) return def.primary;
    if (def.fallback) return def.fallback;

    throw new Error(
      `Selector '${key}' for platform '${platform}' has neither primary nor fallback defined.`
    );
  }

  /**
   * Returns the full selector definition (primary + fallback + description).
   *
   * @param {string} platform - Platform name
   * @param {string} key - Selector key
   * @returns {Promise<Object>} Selector definition with primary, fallback, description
   */
  async getDefinition(platform, key) {
    const cfg = await this.loadPlatform(platform);
    const def = cfg.selectors[key];

    if (!def) {
      const available = Object.keys(cfg.selectors).sort();
      throw new Error(
        `Selector key '${key}' not found for platform '${platform}'. ` +
        `Available keys: ${available.join(', ')}`
      );
    }

    return def;
  }

  /**
   * Get all selector keys for a platform
   *
   * @param {string} platform - Platform name
   * @returns {Promise<string[]>} Array of selector keys
   */
  async getAvailableKeys(platform) {
    const cfg = await this.loadPlatform(platform);
    return Object.keys(cfg.selectors).sort();
  }

  /**
   * Get platform configuration including version and URL
   *
   * @param {string} platform - Platform name
   * @returns {Promise<Object>} Platform config
   */
  async getPlatformConfig(platform) {
    const cfg = await this.loadPlatform(platform);
    return {
      version: cfg.version,
      platform: cfg.platform,
      url: cfg.url
    };
  }

  /**
   * Clear the cache for a specific platform or all platforms
   *
   * @param {string} [platform] - Platform to clear, or undefined for all
   */
  clearCache(platform) {
    if (platform) {
      this.platformCache.delete(platform);
    } else {
      this.platformCache.clear();
    }
  }
}

export { SelectorRegistry };
