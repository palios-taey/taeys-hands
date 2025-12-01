/**
 * Platform Bridge Factory
 *
 * Purpose: Detect OS and create appropriate automation bridge
 * Dependencies: os module, MacOSBridge, LinuxBridge
 * Exports: createBridge(), detectPlatform()
 *
 * @module core/platform/bridge-factory
 */

import os from 'os';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { MacOSBridge } from './macos-bridge.js';
import { LinuxBridge } from './linux-bridge.js';

// Load timing configuration from JSON
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const timingConfig = JSON.parse(
  readFileSync(join(__dirname, '..', 'timing.json'), 'utf-8')
);

/**
 * Detect the current operating system platform
 * @returns {'macos' | 'linux' | 'windows' | 'unknown'}
 */
export function detectPlatform() {
  const platform = os.platform();
  
  switch (platform) {
    case 'darwin':
      return 'macos';
    case 'linux':
      return 'linux';
    case 'win32':
      return 'windows';
    default:
      return 'unknown';
  }
}

/**
 * Create a platform-specific automation bridge
 * 
 * @param {Object} options - Bridge configuration options
 * @param {string} [options.browser='Google Chrome'] - Browser name for automation
 * @returns {MacOSBridge | LinuxBridge} Platform-appropriate bridge instance
 * @throws {Error} If platform is unsupported
 * 
 * @example
 * const bridge = createBridge({ browser: 'Google Chrome' });
 * await bridge.type('Hello, World!');
 */
export function createBridge(options = {}) {
  const platform = detectPlatform();
  const browserName = options.browser || 'Google Chrome';
  
  switch (platform) {
    case 'macos':
      return new MacOSBridge({ browser: browserName });
    
    case 'linux':
      return new LinuxBridge({ browser: browserName });
    
    case 'windows':
      throw new Error(
        'Windows is not yet supported. ' +
        'Use WSL2 with Linux bridge or switch to macOS.'
      );
    
    default:
      throw new Error(
        `Unknown platform: ${os.platform()}. ` +
        'Supported platforms: macOS (darwin), Linux'
      );
  }
}

/**
 * Get platform-specific timing multiplier
 * Slower systems get longer waits for reliability
 * 
 * @returns {number} Multiplier (1.0 = fast, 2.0 = slow)
 */
export function getTimingMultiplier() {
  const cpuCount = os.cpus().length;
  const totalMemGB = os.totalmem() / (1024 ** 3);
  
  // Fast system: 8+ cores, 16GB+ RAM
  if (cpuCount >= 8 && totalMemGB >= 16) {
    return 1.0;
  }
  
  // Medium system: 4+ cores, 8GB+ RAM
  if (cpuCount >= 4 && totalMemGB >= 8) {
    return 1.5;
  }
  
  // Slow system
  return 2.0;
}

/**
 * Standard timing constants (loaded from timing.json)
 * Multiply by getTimingMultiplier() for slower systems
 */
export const TIMING = timingConfig.base;

/**
 * Get adjusted timing value based on system performance
 *
 * @param {string} key - Timing constant key from TIMING
 * @returns {number} Adjusted timing in milliseconds
 */
export function getTiming(key) {
  const multiplier = getTimingMultiplier();
  const baseValue = TIMING[key];

  if (baseValue === undefined) {
    throw new Error(`Unknown timing key: ${key}. Available: ${Object.keys(TIMING).join(', ')}`);
  }

  return Math.round(baseValue * multiplier);
}

/**
 * Get platform-specific timeout
 *
 * @param {string} platform - Platform name (claude, chatgpt, gemini, grok, perplexity)
 * @param {string} mode - Mode name (default, extendedThinking, deepResearch, etc.)
 * @returns {number} Timeout in milliseconds
 */
export function getPlatformTimeout(platform, mode = 'default') {
  const platformConfig = timingConfig.platformTimeouts[platform];

  if (!platformConfig) {
    throw new Error(`Unknown platform: ${platform}. Available: ${Object.keys(timingConfig.platformTimeouts).join(', ')}`);
  }

  const timeout = platformConfig[mode] || platformConfig.default;

  if (timeout === undefined) {
    throw new Error(`Unknown mode "${mode}" for platform "${platform}". Available: ${Object.keys(platformConfig).join(', ')}`);
  }

  return timeout;
}

/**
 * Get Fibonacci polling configuration
 *
 * @returns {Object} { sequence, screenshotIntervals, stabilityRequired, fastPollSeconds }
 */
export function getFibonacciConfig() {
  return {
    sequence: timingConfig.responseDetection.fibonacci,
    screenshotIntervals: timingConfig.responseDetection.screenshotIntervals,
    stabilityRequired: timingConfig.responseDetection.stabilityRequired,
    fastPollSeconds: timingConfig.responseDetection.fastPollSeconds
  };
}

/**
 * Get typing configuration
 *
 * @returns {Object} Typing parameters from timing.json
 */
export function getTypingConfig() {
  return timingConfig.typing;
}

/**
 * Get retry configuration
 *
 * @returns {Object} { maxRetries, baseBackoff }
 */
export function getRetryConfig() {
  return timingConfig.retries;
}
