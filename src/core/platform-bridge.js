/**
 * Platform Bridge - Cross-platform factory for OS-specific automation
 *
 * Detects the operating system and returns the appropriate bridge:
 * - macOS → OSABridge (AppleScript via osascript)
 * - Linux → LinuxBridge (xdotool + xclip)
 *
 * Provides 100% API compatibility across platforms for:
 * - Mouse movement with Bézier curves
 * - Keyboard input with human-like timing
 * - Application focus management
 * - Screen position queries
 * - Clipboard operations
 */

import os from 'os';

/**
 * Create platform-specific bridge instance
 * @param {Object} config - Configuration object passed to bridge constructor
 * @returns {OSABridge|LinuxBridge} Platform-specific bridge instance
 * @throws {Error} If platform is not supported (not macOS or Linux)
 */
export async function createPlatformBridge(config = {}) {
  const platform = os.platform();

  if (platform === 'darwin') {
    // macOS - use AppleScript bridge
    const { OSABridge } = await import('./osascript-bridge.js');
    return new OSABridge(config);
  } else if (platform === 'linux') {
    // Linux - use xdotool bridge
    const { LinuxBridge } = await import('./linux-bridge.js');
    return new LinuxBridge(config);
  } else {
    throw new Error(`Unsupported platform: ${platform}. Only macOS (darwin) and Linux are supported.`);
  }
}

/**
 * Get current platform name
 * @returns {string} 'macOS', 'Linux', or platform name
 */
export function getPlatformName() {
  const platform = os.platform();

  if (platform === 'darwin') return 'macOS';
  if (platform === 'linux') return 'Linux';

  return platform;
}

/**
 * Check if current platform is supported
 * @returns {boolean} True if macOS or Linux
 */
export function isPlatformSupported() {
  const platform = os.platform();
  return platform === 'darwin' || platform === 'linux';
}

export default createPlatformBridge;
