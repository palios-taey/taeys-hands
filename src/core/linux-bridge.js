/**
 * Linux Bridge - System-level mouse/keyboard control on Linux
 *
 * Uses xdotool and xclip for:
 * - Mouse movement with Bézier curves (human-like)
 * - Keyboard input with variable timing
 * - Application focus management
 * - Screen position queries
 * - Clipboard operations
 *
 * Mirrors OSABridge interface for cross-platform compatibility.
 */

import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export class LinuxBridge {
  constructor(config = {}) {
    this.typingBaseDelay = config.typingBaseDelay || 50;
    this.typingVariation = config.typingVariation || 30;
    this.bezierSteps = config.bezierSteps || 20;
  }

  /**
   * Execute shell command safely
   */
  async runCommand(command) {
    try {
      const { stdout, stderr } = await execAsync(command);
      if (stderr && !stderr.includes('Warning')) {
        console.warn('Command warning:', stderr);
      }
      return stdout.trim();
    } catch (error) {
      console.error(`Command failed: ${command}`);
      console.error('Error:', error.message);
      throw new Error(`Linux command failed: ${command} - ${error.message}`);
    }
  }

  /**
   * Get current mouse position
   * Returns { x, y }
   */
  async getMousePosition() {
    try {
      const output = await this.runCommand('xdotool getmouselocation --shell');
      const lines = output.split('\n');
      const coords = {};

      for (const line of lines) {
        const [key, value] = line.split('=');
        if (key === 'X') coords.x = parseInt(value, 10);
        if (key === 'Y') coords.y = parseInt(value, 10);
      }

      if (coords.x === undefined || coords.y === undefined) {
        throw new Error('Failed to parse mouse coordinates');
      }

      return coords;
    } catch (error) {
      throw new Error(`Failed to get mouse position: ${error.message}`);
    }
  }

  /**
   * Generate Bézier curve points for natural mouse movement
   * Same algorithm as Mac version for consistency
   */
  generateBezierPath(start, end, steps = this.bezierSteps) {
    const points = [];

    // Generate two control points with some randomness
    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;
    const dist = Math.sqrt(Math.pow(end.x - start.x, 2) + Math.pow(end.y - start.y, 2));

    const cp1 = {
      x: midX + (Math.random() - 0.5) * dist * 0.3,
      y: midY + (Math.random() - 0.5) * dist * 0.3
    };
    const cp2 = {
      x: midX + (Math.random() - 0.5) * dist * 0.3,
      y: midY + (Math.random() - 0.5) * dist * 0.3
    };

    // Cubic Bézier curve
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const t2 = t * t;
      const t3 = t2 * t;
      const mt = 1 - t;
      const mt2 = mt * mt;
      const mt3 = mt2 * mt;

      points.push({
        x: Math.round(mt3 * start.x + 3 * mt2 * t * cp1.x + 3 * mt * t2 * cp2.x + t3 * end.x),
        y: Math.round(mt3 * start.y + 3 * mt2 * t * cp1.y + 3 * mt * t2 * cp2.y + t3 * end.y)
      });
    }

    return points;
  }

  /**
   * Move mouse along Bézier curve (human-like)
   */
  async moveMouse(x, y) {
    const current = await this.getMousePosition();
    const path = this.generateBezierPath(current, { x, y });

    for (const point of path) {
      await this.runCommand(`xdotool mousemove ${point.x} ${point.y}`);

      // Variable delay between steps (5-15ms like Mac version)
      const delay = 5 + Math.random() * 10;
      await new Promise(r => setTimeout(r, delay));
    }
  }

  /**
   * Click at current position
   * Button 1 = left click
   */
  async click() {
    await this.runCommand('xdotool click 1');
  }

  /**
   * Move and click
   */
  async clickAt(x, y) {
    await this.moveMouse(x, y);
    await new Promise(r => setTimeout(r, 50 + Math.random() * 100));
    await this.click();
  }

  /**
   * Type text with human-like timing
   */
  async type(text, options = {}) {
    const baseDelay = options.baseDelay || this.typingBaseDelay;
    const variation = options.variation || this.typingVariation;

    for (const char of text) {
      // Handle special characters
      if (char === '\n') {
        // Shift+Return for line break (not submit) - matches Mac behavior
        await this.runCommand('xdotool key shift+Return');
      } else {
        // xdotool type handles most characters, but we'll type char-by-char for timing
        // Escape special shell characters
        const escaped = char
          .replace(/\\/g, '\\\\')
          .replace(/"/g, '\\"')
          .replace(/'/g, "'\\''")
          .replace(/\$/g, '\\$')
          .replace(/`/g, '\\`');

        await this.runCommand(`xdotool type --delay 0 -- "${escaped}"`);
      }

      // Variable delay with occasional "burst" typing (matches Mac behavior)
      let delay = baseDelay + (Math.random() - 0.5) * variation * 2;

      // Sometimes type faster (bursts)
      if (Math.random() < 0.1) {
        delay = delay * 0.3;
      }

      // Pause slightly longer after punctuation
      if (['.', '!', '?', ','].includes(char)) {
        delay += 50 + Math.random() * 100;
      }

      await new Promise(r => setTimeout(r, Math.max(10, delay)));
    }
  }

  /**
   * Press a special key
   */
  async pressKey(key) {
    const keyMap = {
      'return': 'Return',
      'enter': 'Return',
      'tab': 'Tab',
      'space': 'space',
      'delete': 'BackSpace',
      'escape': 'Escape',
      'command': 'Super_L',  // Linux Super key (Windows key)
      'shift': 'Shift_L',
      'option': 'Alt_L',     // Alt is Option equivalent
      'control': 'Control_L',
      'up': 'Up',
      'down': 'Down',
      'left': 'Left',
      'right': 'Right'
    };

    const xKey = keyMap[key.toLowerCase()];
    if (!xKey) {
      throw new Error(`Unknown key: ${key}`);
    }

    await this.runCommand(`xdotool key ${xKey}`);
  }

  /**
   * Press key with modifier
   */
  async pressKeyWithModifier(key, modifier) {
    const modifierMap = {
      'command': 'super',
      'shift': 'shift',
      'option': 'alt',
      'control': 'ctrl'
    };

    const xModifier = modifierMap[modifier.toLowerCase()];
    if (!xModifier) {
      throw new Error(`Unknown modifier: ${modifier}`);
    }

    // xdotool uses + to combine modifier and key
    await this.runCommand(`xdotool key ${xModifier}+${key}`);
  }

  /**
   * Focus an application by name
   * Searches for window by name and brings it to foreground
   * Uses windowraise + windowfocus for VNC/remote display compatibility
   */
  async focusApp(appName) {
    try {
      // Get window ID first
      const windowId = await this.runCommand(`xdotool search --name "${appName}" | head -1`);
      if (!windowId || windowId.trim() === '') {
        throw new Error(`No window found matching "${appName}"`);
      }

      // Use windowraise + windowfocus (works better on VNC than windowactivate)
      await this.runCommand(`xdotool windowraise ${windowId.trim()}`);
      await this.runCommand(`xdotool windowfocus --sync ${windowId.trim()}`);
      await new Promise(r => setTimeout(r, 300));
    } catch (error) {
      // If name match fails, try class match
      try {
        const windowId = await this.runCommand(`xdotool search --class "${appName}" | head -1`);
        if (!windowId || windowId.trim() === '') {
          throw new Error(`No window found matching class "${appName}"`);
        }
        await this.runCommand(`xdotool windowraise ${windowId.trim()}`);
        await this.runCommand(`xdotool windowfocus --sync ${windowId.trim()}`);
        await new Promise(r => setTimeout(r, 300));
      } catch (fallbackError) {
        throw new Error(`Failed to focus app "${appName}": ${error.message}`);
      }
    }
  }

  /**
   * Get frontmost (active) window name
   */
  async getFrontmostApp() {
    try {
      const windowId = await this.runCommand('xdotool getactivewindow');
      const windowName = await this.runCommand(`xdotool getwindowname ${windowId}`);
      return windowName;
    } catch (error) {
      throw new Error(`Failed to get frontmost app: ${error.message}`);
    }
  }

  /**
   * Validate that expected app is the frontmost window
   * Returns { valid: boolean, currentApp: string, error?: string }
   *
   * Handles VNC/remote displays where getactivewindow may not work.
   * Falls back to verifying the expected window exists and was recently focused.
   */
  async validateFocus(expectedApp = 'Chrome') {
    // Determine the search keyword
    let expectedKeyword = expectedApp.split(' ')[0].toLowerCase();
    if (expectedKeyword === 'chrome' || expectedKeyword === 'chromium') {
      expectedKeyword = 'chrom';  // Match both Chrome and Chromium
    }

    try {
      const currentApp = await this.getFrontmostApp();

      // Linux window titles often contain more info, so do partial match
      const isValid = currentApp.toLowerCase().includes(expectedKeyword);

      return {
        valid: isValid,
        currentApp,
        expectedApp,
        error: isValid ? null : `Expected ${expectedApp} to be frontmost, but found: ${currentApp}`
      };
    } catch (error) {
      // getactivewindow failed (common in VNC/remote displays without full WM support)
      // Fall back to checking if expected window exists and assume focusApp worked
      console.warn(`  [validateFocus] getactivewindow failed, using fallback: ${error.message}`);

      try {
        // Search for windows matching the expected app
        const result = await this.runCommand(`xdotool search --name "${expectedKeyword}"`);
        const windowIds = result.trim().split('\n').filter(id => id);

        if (windowIds.length > 0) {
          // Window exists - assume focus worked after focusApp was called
          const windowName = await this.runCommand(`xdotool getwindowname ${windowIds[0]}`);
          return {
            valid: true,
            currentApp: windowName,
            expectedApp,
            error: null,
            fallbackUsed: true
          };
        } else {
          return {
            valid: false,
            currentApp: 'unknown',
            expectedApp,
            error: `No windows found matching "${expectedKeyword}"`
          };
        }
      } catch (fallbackError) {
        return {
          valid: false,
          currentApp: 'unknown',
          expectedApp,
          error: `Focus validation error: ${error.message}, fallback also failed: ${fallbackError.message}`
        };
      }
    }
  }

  /**
   * Safe type - validates focus before typing, aborts if not focused
   * Prevents typing into wrong windows (like password dialogs)
   */
  async safeType(text, options = {}) {
    // First validate focus
    const focus = await this.validateFocus(options.expectedApp || 'Chrome');

    if (!focus.valid) {
      console.error(`  [ABORT] Focus validation failed: ${focus.error}`);
      throw new Error(`Focus validation failed: ${focus.error}. Refusing to type.`);
    }

    console.log(`  [Focus OK: ${focus.currentApp}]`);

    // Now safe to type
    return await this.type(text, options);
  }

  /**
   * Re-verify focus periodically during long typing sessions
   * For messages > 500 chars, check focus every 250 chars
   */
  async safeTypeLong(text, options = {}) {
    const chunkSize = 250;
    const expectedApp = options.expectedApp || 'Chrome';

    // Initial focus check
    const initialFocus = await this.validateFocus(expectedApp);
    if (!initialFocus.valid) {
      throw new Error(`Initial focus validation failed: ${initialFocus.error}`);
    }

    // Type in chunks, re-validating focus between chunks
    for (let i = 0; i < text.length; i += chunkSize) {
      const chunk = text.slice(i, i + chunkSize);

      // Re-check focus before each chunk (except first)
      if (i > 0) {
        const focus = await this.validateFocus(expectedApp);
        if (!focus.valid) {
          console.error(`  [ABORT at char ${i}] Focus lost: ${focus.error}`);
          throw new Error(`Focus lost during typing at char ${i}: ${focus.error}`);
        }
      }

      await this.type(chunk, options);
    }
  }

  /**
   * Type text quickly using xdotool (bypasses clipboard)
   * Use this instead of setClipboard + paste in VNC environments
   */
  async typeFast(text) {
    // Escape special characters for shell
    const escaped = text
      .replace(/\\/g, '\\\\')
      .replace(/"/g, '\\"')
      .replace(/\$/g, '\\$')
      .replace(/`/g, '\\`');

    // Use xdotool type with clearmodifiers to avoid modifier key issues
    // Split into chunks to avoid command line length limits
    const chunkSize = 500;
    for (let i = 0; i < text.length; i += chunkSize) {
      const chunk = text.slice(i, i + chunkSize);
      const escapedChunk = chunk
        .replace(/\\/g, '\\\\')
        .replace(/"/g, '\\"')
        .replace(/\$/g, '\\$')
        .replace(/`/g, '\\`');
      await this.runCommand(`xdotool type --clearmodifiers --delay 5 -- "${escapedChunk}"`);
    }
  }

  /**
   * Set clipboard content using xclip
   * Note: May not work in VNC environments - use typeFast() as alternative
   */
  async setClipboard(text) {
    const { exec: execCb } = await import('child_process');
    const display = process.env.DISPLAY || ':1';
    return new Promise((resolve, reject) => {
      // Set timeout to prevent hanging
      const timeout = setTimeout(() => {
        reject(new Error('xclip timeout after 5s - use typeFast() instead in VNC'));
      }, 5000);

      const proc = execCb(`DISPLAY=${display} xclip -selection clipboard`, (error) => {
        clearTimeout(timeout);
        if (error) reject(error);
      });
      proc.stdin.write(text);
      proc.stdin.end();
      proc.on('close', (code) => {
        clearTimeout(timeout);
        if (code === 0) resolve();
        else reject(new Error(`xclip failed with code ${code}`));
      });
    });
  }

  /**
   * Paste from clipboard (Ctrl+V)
   */
  async paste() {
    await this.runCommand('xdotool key ctrl+v');
    // Small delay to let paste complete
    await new Promise(r => setTimeout(r, 100));
  }

  /**
   * Safe paste - validates focus before pasting
   */
  async safePaste(options = {}) {
    const focus = await this.validateFocus(options.expectedApp || 'Chrome');
    if (!focus.valid) {
      throw new Error(`Focus validation failed for paste: ${focus.error}`);
    }
    return await this.paste();
  }

  /**
   * Type with mixed content - TYPE regular text, PASTE quoted content
   * Detects patterns like "Quote from AI: \"...\""
   *
   * @param text - Full message text
   * @param options.quotePattern - Regex to detect quoted content (default: content in quotes after colon)
   * @param options.pasteQuotes - If true, paste quoted content; if false, type everything
   */
  async typeWithMixedContent(text, options = {}) {
    const expectedApp = options.expectedApp || 'Chrome';
    const pasteQuotes = options.pasteQuotes !== false; // Default true

    // Pattern to match: AI_NAME: "quoted content" or similar patterns
    // Also matches content after "Previous responses:" or similar headers
    const quotePattern = options.quotePattern ||
      /(?:^|\n)([A-Z]+:?\s*[""]([^""]+)[""])|(?:Previous responses:\n)([\s\S]+?)(?=\n\n|$)/gm;

    // Validate initial focus
    const initialFocus = await this.validateFocus(expectedApp);
    if (!initialFocus.valid) {
      throw new Error(`Initial focus validation failed: ${initialFocus.error}`);
    }

    // Simple approach: if message contains other AI responses, use paste for those sections
    // For now, let's use a simpler heuristic: if text contains "\n\nPrevious" or "AI_NAME:" patterns

    // Check if this looks like it contains other AI content
    const hasAIContent = /\n(CLAUDE|CHATGPT|GROK|PERPLEXITY|GEMINI):/.test(text) ||
                         /Previous responses:/i.test(text);

    if (pasteQuotes && hasAIContent) {
      // Split into my content (type) and AI content (paste)
      const parts = text.split(/(\n(?:CLAUDE|CHATGPT|GROK|PERPLEXITY|GEMINI):[^\n]*(?:\n|$))/gi);

      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        if (!part) continue;

        // Check if this part is AI content (should be pasted)
        const isAIContent = /^[\n\s]*(CLAUDE|CHATGPT|GROK|PERPLEXITY|GEMINI):/i.test(part);

        if (isAIContent) {
          // PASTE this content
          console.log(`  [Pasting AI content: "${part.substring(0, 50)}..."]`);
          await this.setClipboard(part);
          await this.safePaste({ expectedApp });
        } else {
          // TYPE this content
          await this.safeTypeLong(part, { expectedApp, ...options });
        }
      }
    } else {
      // No AI content detected, just type normally
      await this.safeTypeLong(text, { expectedApp, ...options });
    }
  }
}

// CLI test
if (import.meta.url === `file://${process.argv[1]}`) {
  const bridge = new LinuxBridge();

  console.log('Testing Linux bridge...');

  try {
    const pos = await bridge.getMousePosition();
    console.log(`Current mouse position: ${pos.x}, ${pos.y}`);

    const app = await bridge.getFrontmostApp();
    console.log(`Frontmost app: ${app}`);

    console.log('✓ Linux bridge working');
  } catch (error) {
    console.error('✗ Linux bridge test failed:', error.message);
    console.error('\nMake sure xdotool and xclip are installed:');
    console.error('  Ubuntu/Debian: sudo apt install xdotool xclip');
    console.error('  Fedora/RHEL: sudo dnf install xdotool xclip');
    console.error('  Arch: sudo pacman -S xdotool xclip');
    process.exit(1);
  }
}

export default LinuxBridge;
