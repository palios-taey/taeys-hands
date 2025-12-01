/**
 * Platform Adapter Factory
 * 
 * Purpose: Create platform-specific adapters based on platform name
 * 
 * @module platforms/factory
 */

import { ClaudeAdapter } from './claude.js';
import { ChatGPTAdapter } from './chatgpt.js';
import { GeminiAdapter } from './gemini.js';
import { GrokAdapter } from './grok.js';
import { PerplexityAdapter } from './perplexity.js';

/**
 * Platform adapter classes by name
 */
const ADAPTERS = {
  claude: ClaudeAdapter,
  chatgpt: ChatGPTAdapter,
  gemini: GeminiAdapter,
  grok: GrokAdapter,
  perplexity: PerplexityAdapter
};

/**
 * Valid platform names
 */
export const PLATFORMS = Object.keys(ADAPTERS);

/**
 * Create a platform adapter
 * 
 * @param {string} platform - Platform name
 * @param {Object} options - Adapter options (page, bridge, selectors, config)
 * @returns {BasePlatformAdapter}
 * @throws {Error} If platform is unknown
 */
export function createAdapter(platform, options) {
  const AdapterClass = ADAPTERS[platform.toLowerCase()];
  
  if (!AdapterClass) {
    throw new Error(
      `Unknown platform: ${platform}. ` +
      `Valid platforms: ${PLATFORMS.join(', ')}`
    );
  }
  
  return new AdapterClass(options);
}

/**
 * Check if a platform is supported
 * 
 * @param {string} platform
 * @returns {boolean}
 */
export function isPlatformSupported(platform) {
  return platform.toLowerCase() in ADAPTERS;
}
