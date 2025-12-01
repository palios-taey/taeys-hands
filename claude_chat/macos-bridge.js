/**
 * macOS Automation Bridge
 * 
 * Purpose: Provide human-like automation via AppleScript/osascript
 * Dependencies: child_process
 * Exports: MacOSBridge class
 * 
 * Key capabilities:
 * - Type text with human-like delays
 * - Click at screen coordinates
 * - Navigate file dialogs (Cmd+Shift+G)
 * - Focus applications and windows
 * - Mixed content typing (type + paste for AI-generated text)
 * 
 * @module core/platform/macos-bridge
 */

import { exec, execSync } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * macOS automation bridge using AppleScript
 */
export class MacOSBridge {
  /**
   * @param {Object} options
   * @param {string} [options.browser='Google Chrome'] - Browser process name
   */
  constructor(options = {}) {
    this.browser = options.browser || 'Google Chrome';
    this.platform = 'macos';
  }

  /**
   * Execute an AppleScript command
   * 
   * @param {string} script - AppleScript to execute
   * @returns {Promise<string>} Script output
   * @throws {Error} If script execution fails
   */
  async runScript(script) {
    try {
      const { stdout, stderr } = await execAsync(`osascript -e '${script.replace(/'/g, "'\"'\"'")}'`);
      if (stderr) console.warn('[MacOSBridge] Script warning:', stderr);
      return stdout.trim();
    } catch (error) {
      throw new Error(`AppleScript failed: ${error.message}`);
    }
  }

  /**
   * Focus an application window
   * 
   * @param {string} [appName] - Application name (defaults to browser)
   * @returns {Promise<void>}
   */
  async focusApp(appName = this.browser) {
    const script = `
      tell application "${appName}"
        activate
      end tell
    `;
    await this.runScript(script);
    // Wait for focus to settle
    await this.sleep(200);
  }

  /**
   * Type a single character with natural delay
   * 
   * @param {string} char - Character to type
   * @returns {Promise<void>}
   */
  async typeChar(char) {
    // Escape special characters for AppleScript
    const escaped = char
      .replace(/\\/g, '\\\\')
      .replace(/"/g, '\\"')
      .replace(/\n/g, '\\n')
      .replace(/\r/g, '\\r')
      .replace(/\t/g, '\\t');
    
    const script = `
      tell application "System Events"
        tell process "${this.browser}"
          keystroke "${escaped}"
        end tell
      end tell
    `;
    await this.runScript(script);
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
    
    for (const char of text) {
      await this.typeChar(char);
      
      // Human-like timing: base + random variation
      const delay = baseDelay + Math.random() * variation;
      await this.sleep(delay);
      
      // Occasional longer pause (as if thinking)
      if (Math.random() < 0.05) {
        await this.sleep(100 + Math.random() * 150);
      }
    }
  }

  /**
   * Type long text with safety checks for focus
   * Re-focuses browser periodically to prevent typing to wrong window
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
   * Better for AI-generated text with special characters
   * 
   * @param {string} text - Text to type/paste
   * @param {Object} [options]
   * @param {number} [options.typeRatio=0.3] - Fraction to type vs paste (0-1)
   * @returns {Promise<void>}
   */
  async typeWithMixedContent(text, options = {}) {
    const typeRatio = options.typeRatio ?? 0.3;
    
    // Split text into segments
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
   * Splits on sentence boundaries, paragraphs, or length
   * 
   * @param {string} text
   * @returns {string[]}
   */
  splitIntoSegments(text) {
    // Split on sentence boundaries or every ~100 characters
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
    // Set clipboard content
    const escaped = text.replace(/"/g, '\\"').replace(/\\/g, '\\\\');
    const setClipboard = `set the clipboard to "${escaped}"`;
    await this.runScript(setClipboard);
    
    // Paste with Cmd+V
    await this.pressKey('v', { command: true });
  }

  /**
   * Press a key with optional modifiers
   * 
   * @param {string} key - Key name (return, escape, v, g, etc.)
   * @param {Object} [modifiers]
   * @param {boolean} [modifiers.command] - Hold Cmd
   * @param {boolean} [modifiers.shift] - Hold Shift
   * @param {boolean} [modifiers.option] - Hold Option
   * @param {boolean} [modifiers.control] - Hold Control
   * @returns {Promise<void>}
   */
  async pressKey(key, modifiers = {}) {
    // Build modifier string
    const mods = [];
    if (modifiers.command) mods.push('command down');
    if (modifiers.shift) mods.push('shift down');
    if (modifiers.option) mods.push('option down');
    if (modifiers.control) mods.push('control down');
    
    const usingClause = mods.length > 0 ? ` using {${mods.join(', ')}}` : '';
    
    // Handle special key names
    let keyCode;
    switch (key.toLowerCase()) {
      case 'return':
      case 'enter':
        keyCode = 'key code 36';
        break;
      case 'escape':
      case 'esc':
        keyCode = 'key code 53';
        break;
      case 'tab':
        keyCode = 'key code 48';
        break;
      case 'delete':
      case 'backspace':
        keyCode = 'key code 51';
        break;
      case 'up':
        keyCode = 'key code 126';
        break;
      case 'down':
        keyCode = 'key code 125';
        break;
      case 'left':
        keyCode = 'key code 123';
        break;
      case 'right':
        keyCode = 'key code 124';
        break;
      default:
        // Regular character
        keyCode = `keystroke "${key}"`;
    }
    
    const script = `
      tell application "System Events"
        tell process "${this.browser}"
          ${keyCode}${usingClause}
        end tell
      end tell
    `;
    
    await this.runScript(script);
  }

  /**
   * Click at screen coordinates
   * 
   * @param {number} x - Screen X coordinate
   * @param {number} y - Screen Y coordinate
   * @returns {Promise<void>}
   */
  async clickAt(x, y) {
    const script = `
      tell application "System Events"
        click at {${Math.round(x)}, ${Math.round(y)}}
      end tell
    `;
    await this.runScript(script);
  }

  /**
   * Navigate macOS file picker using Cmd+Shift+G
   * 
   * @param {string} filePath - Full path to file
   * @returns {Promise<void>}
   */
  async navigateFilePicker(filePath) {
    // Extract directory and filename
    const lastSlash = filePath.lastIndexOf('/');
    const directory = filePath.substring(0, lastSlash);
    const filename = filePath.substring(lastSlash + 1);
    
    // Cmd+Shift+G to open "Go to folder" dialog
    await this.pressKey('g', { command: true, shift: true });
    await this.sleep(800);
    
    // Type directory path
    await this.type(directory, { baseDelay: 30, variation: 15 });
    await this.sleep(300);
    
    // Press Enter to navigate
    await this.pressKey('return');
    await this.sleep(1000);
    
    // Type filename to select
    await this.type(filename, { baseDelay: 30, variation: 15 });
    await this.sleep(300);
    
    // Press Enter to confirm selection
    await this.pressKey('return');
    await this.sleep(1000);
  }

  /**
   * Get the browser process name for targeting
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
   * Check if we have accessibility permissions
   * 
   * @returns {Promise<boolean>}
   */
  async hasAccessibilityPermission() {
    try {
      const script = `
        tell application "System Events"
          return true
        end tell
      `;
      await this.runScript(script);
      return true;
    } catch {
      return false;
    }
  }
}
