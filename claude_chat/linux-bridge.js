/**
 * Linux Automation Bridge
 * 
 * Purpose: Provide human-like automation via xdotool
 * Dependencies: child_process, xdotool (system package)
 * Exports: LinuxBridge class
 * 
 * Key capabilities:
 * - Type text with human-like delays
 * - Click at screen coordinates
 * - Navigate file dialogs (Ctrl+L)
 * - Focus applications and windows
 * - Mixed content typing (type + paste for AI-generated text)
 * 
 * Prerequisites:
 * - xdotool installed: sudo apt install xdotool
 * - xclip installed: sudo apt install xclip
 * 
 * @module core/platform/linux-bridge
 */

import { exec, execSync } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * Linux automation bridge using xdotool
 */
export class LinuxBridge {
  /**
   * @param {Object} options
   * @param {string} [options.browser='google-chrome'] - Browser process name
   */
  constructor(options = {}) {
    this.browser = options.browser || 'google-chrome';
    this.platform = 'linux';
    this.windowId = null;
  }

  /**
   * Execute a shell command
   * 
   * @param {string} command - Command to execute
   * @returns {Promise<string>} Command output
   * @throws {Error} If command execution fails
   */
  async runCommand(command) {
    try {
      const { stdout, stderr } = await execAsync(command);
      if (stderr && !stderr.includes('Warning')) {
        console.warn('[LinuxBridge] Command warning:', stderr);
      }
      return stdout.trim();
    } catch (error) {
      throw new Error(`Command failed: ${command}\n${error.message}`);
    }
  }

  /**
   * Find the browser window ID
   * 
   * @returns {Promise<string>} Window ID
   */
  async findBrowserWindow() {
    if (this.windowId) {
      // Verify window still exists
      try {
        await this.runCommand(`xdotool getwindowname ${this.windowId}`);
        return this.windowId;
      } catch {
        this.windowId = null;
      }
    }
    
    // Find browser window
    const output = await this.runCommand(`xdotool search --name "${this.browser}" 2>/dev/null | head -1`);
    if (!output) {
      throw new Error(`Browser window not found: ${this.browser}`);
    }
    
    this.windowId = output;
    return this.windowId;
  }

  /**
   * Focus the browser window
   * 
   * @param {string} [appName] - Application name (defaults to browser)
   * @returns {Promise<void>}
   */
  async focusApp(appName = this.browser) {
    const windowId = await this.findBrowserWindow();
    await this.runCommand(`xdotool windowraise ${windowId}`);
    await this.runCommand(`xdotool windowfocus ${windowId}`);
    await this.sleep(200);
  }

  /**
   * Type a single character
   * 
   * @param {string} char - Character to type
   * @returns {Promise<void>}
   */
  async typeChar(char) {
    // Escape special characters for shell
    const escaped = char
      .replace(/'/g, "'\"'\"'")
      .replace(/"/g, '\\"')
      .replace(/\\/g, '\\\\')
      .replace(/`/g, '\\`')
      .replace(/\$/g, '\\$');
    
    await this.runCommand(`xdotool type --clearmodifiers -- '${escaped}'`);
  }

  /**
   * Type text with human-like timing variations
   * 
   * @param {string} text - Text to type
   * @param {Object} [options]
   * @param {number} [options.baseDelay=50] - Base delay between keystrokes (ms)
   * @param {number} [options.variation=25] - Random variation in delay (ms)
   * @returns {Promise<void>}
   */
  async type(text, options = {}) {
    const baseDelay = options.baseDelay ?? 50;
    const variation = options.variation ?? 25;
    
    // Use xdotool's built-in delay for efficiency
    const delay = Math.round((baseDelay + variation / 2) / 1000 * 1000) / 1000; // Convert to seconds
    
    // Escape for shell
    const escaped = text
      .replace(/'/g, "'\"'\"'")
      .replace(/"/g, '\\"')
      .replace(/\\/g, '\\\\');
    
    await this.runCommand(`xdotool type --delay ${Math.round(baseDelay)} -- '${escaped}'`);
  }

  /**
   * Type long text with safety checks for focus
   * 
   * @param {string} text - Text to type
   * @param {Object} [options]
   * @param {number} [options.chunkSize=50] - Characters before focus check
   * @returns {Promise<void>}
   */
  async safeTypeLong(text, options = {}) {
    const chunkSize = options.chunkSize ?? 50;
    
    for (let i = 0; i < text.length; i += chunkSize) {
      const chunk = text.substring(i, i + chunkSize);
      
      // Re-focus browser before each chunk
      await this.focusApp();
      await this.sleep(100);
      
      await this.type(chunk, options);
    }
  }

  /**
   * Type text using mixed method: type some, paste some
   * 
   * @param {string} text - Text to type/paste
   * @param {Object} [options]
   * @param {number} [options.typeRatio=0.3] - Fraction to type vs paste
   * @returns {Promise<void>}
   */
  async typeWithMixedContent(text, options = {}) {
    const typeRatio = options.typeRatio ?? 0.3;
    const segments = this.splitIntoSegments(text);
    
    for (const segment of segments) {
      const shouldType = Math.random() < typeRatio || segment.length < 10;
      
      if (shouldType) {
        await this.type(segment);
      } else {
        await this.paste(segment);
        await this.sleep(50);
      }
    }
  }

  /**
   * Split text into segments for mixed typing
   * 
   * @param {string} text
   * @returns {string[]}
   */
  splitIntoSegments(text) {
    const sentences = text.split(/(?<=[.!?])\s+/);
    const segments = [];
    let current = '';
    
    for (const sentence of sentences) {
      if (current.length + sentence.length > 100) {
        if (current) segments.push(current);
        current = sentence;
      } else {
        current += (current ? ' ' : '') + sentence;
      }
    }
    if (current) segments.push(current);
    
    return segments;
  }

  /**
   * Copy text to clipboard and paste
   * 
   * @param {string} text - Text to paste
   * @returns {Promise<void>}
   */
  async paste(text) {
    // Set clipboard using xclip
    const escaped = text.replace(/'/g, "'\"'\"'");
    await this.runCommand(`echo -n '${escaped}' | xclip -selection clipboard`);
    
    // Paste with Ctrl+V
    await this.pressKey('v', { control: true });
  }

  /**
   * Press a key with optional modifiers
   * 
   * @param {string} key - Key name
   * @param {Object} [modifiers]
   * @param {boolean} [modifiers.control] - Hold Ctrl
   * @param {boolean} [modifiers.shift] - Hold Shift
   * @param {boolean} [modifiers.alt] - Hold Alt
   * @param {boolean} [modifiers.super] - Hold Super (Windows key)
   * @returns {Promise<void>}
   */
  async pressKey(key, modifiers = {}) {
    // Build key combination
    const parts = [];
    if (modifiers.control) parts.push('ctrl');
    if (modifiers.shift) parts.push('shift');
    if (modifiers.alt) parts.push('alt');
    if (modifiers.super) parts.push('super');
    
    // Map key names
    let keyName;
    switch (key.toLowerCase()) {
      case 'return':
      case 'enter':
        keyName = 'Return';
        break;
      case 'escape':
      case 'esc':
        keyName = 'Escape';
        break;
      case 'tab':
        keyName = 'Tab';
        break;
      case 'delete':
      case 'backspace':
        keyName = 'BackSpace';
        break;
      case 'up':
        keyName = 'Up';
        break;
      case 'down':
        keyName = 'Down';
        break;
      case 'left':
        keyName = 'Left';
        break;
      case 'right':
        keyName = 'Right';
        break;
      default:
        keyName = key;
    }
    
    parts.push(keyName);
    const keyCombo = parts.join('+');
    
    await this.runCommand(`xdotool key --clearmodifiers ${keyCombo}`);
  }

  /**
   * Click at screen coordinates
   * 
   * @param {number} x - Screen X coordinate
   * @param {number} y - Screen Y coordinate
   * @returns {Promise<void>}
   */
  async clickAt(x, y) {
    await this.runCommand(`xdotool mousemove ${Math.round(x)} ${Math.round(y)}`);
    await this.sleep(50);
    await this.runCommand('xdotool click 1');
  }

  /**
   * Navigate Linux file picker using Ctrl+L
   * 
   * @param {string} filePath - Full path to file
   * @returns {Promise<void>}
   */
  async navigateFilePicker(filePath) {
    // Ctrl+L to focus location bar
    await this.pressKey('l', { control: true });
    await this.sleep(500);
    
    // Clear existing path
    await this.pressKey('a', { control: true });
    await this.sleep(100);
    
    // Type full file path
    await this.type(filePath, { baseDelay: 30, variation: 15 });
    await this.sleep(300);
    
    // Press Enter to confirm
    await this.pressKey('return');
    await this.sleep(1000);
  }

  /**
   * Get the browser process name
   * 
   * @returns {string}
   */
  getBrowserName() {
    return this.browser;
  }

  /**
   * Sleep for specified milliseconds
   * 
   * @param {number} ms - Milliseconds to sleep
   * @returns {Promise<void>}
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Check if xdotool is available
   * 
   * @returns {Promise<boolean>}
   */
  async hasXdotool() {
    try {
      await this.runCommand('which xdotool');
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Check if xclip is available
   * 
   * @returns {Promise<boolean>}
   */
  async hasXclip() {
    try {
      await this.runCommand('which xclip');
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Verify all dependencies are available
   * 
   * @returns {Promise<{ok: boolean, missing: string[]}>}
   */
  async checkDependencies() {
    const missing = [];
    
    if (!(await this.hasXdotool())) {
      missing.push('xdotool (install with: sudo apt install xdotool)');
    }
    
    if (!(await this.hasXclip())) {
      missing.push('xclip (install with: sudo apt install xclip)');
    }
    
    return {
      ok: missing.length === 0,
      missing
    };
  }
}
