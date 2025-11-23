/**
 * osascript Bridge - System-level mouse/keyboard control on macOS
 *
 * Uses AppleScript via osascript for:
 * - Mouse movement with Bézier curves (human-like)
 * - Keyboard input with variable timing
 * - Application focus management
 * - Screen position queries
 */

import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export class OSABridge {
  constructor(config = {}) {
    this.typingBaseDelay = config.typingBaseDelay || 50;
    this.typingVariation = config.typingVariation || 30;
    this.bezierSteps = config.bezierSteps || 20;
  }

  /**
   * Execute AppleScript
   */
  async runScript(script) {
    try {
      const { stdout } = await execAsync(`osascript -e '${script.replace(/'/g, "'\"'\"'")}'`);
      return stdout.trim();
    } catch (error) {
      console.error('osascript error:', error.message);
      throw error;
    }
  }

  /**
   * Get current mouse position
   */
  async getMousePosition() {
    // Use cliclick for reliable mouse position
    try {
      const { stdout } = await execAsync('cliclick p:.');
      const [x, y] = stdout.trim().split(',').map(Number);
      return { x, y };
    } catch {
      // Fallback: use Python if cliclick not available
      const script = `
import Quartz
loc = Quartz.NSEvent.mouseLocation()
print(f"{int(loc.x)},{int(Quartz.NSScreen.mainScreen().frame().size.height - loc.y)}")
      `;
      const { stdout } = await execAsync(`python3 -c "${script}"`);
      const [x, y] = stdout.trim().split(',').map(Number);
      return { x, y };
    }
  }

  /**
   * Generate Bézier curve points for natural mouse movement
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
      // Use cliclick for reliable mouse movement
      try {
        await execAsync(`cliclick m:${point.x},${point.y}`);
      } catch {
        // Fallback to Python
        const script = `
import Quartz
Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (${point.x}, ${point.y}), 0))
        `;
        await execAsync(`python3 -c "${script}"`);
      }

      // Variable delay between steps
      const delay = 5 + Math.random() * 10;
      await new Promise(r => setTimeout(r, delay));
    }
  }

  /**
   * Click at current position
   */
  async click() {
    try {
      await execAsync('cliclick c:.');
    } catch {
      const pos = await this.getMousePosition();
      const script = `
import Quartz
import time
pos = (${pos.x}, ${pos.y})
Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, pos, 0))
time.sleep(0.05)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, pos, 0))
      `;
      await execAsync(`python3 -c "${script}"`);
    }
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
      // Escape special characters for osascript
      let keystroke;
      if (char === '"') {
        keystroke = 'keystroke "\\"" ';
      } else if (char === '\\') {
        keystroke = 'keystroke "\\\\" ';
      } else if (char === '\n') {
        keystroke = 'key code 36 using {shift down}'; // Shift+Return for line break (not submit)
      } else {
        keystroke = `keystroke "${char}"`;
      }

      await this.runScript(`tell application "System Events" to ${keystroke}`);

      // Variable delay with occasional "burst" typing
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
    const keyCodes = {
      'return': 36,
      'enter': 36,
      'tab': 48,
      'space': 49,
      'delete': 51,
      'escape': 53,
      'command': 55,
      'shift': 56,
      'option': 58,
      'control': 59,
      'up': 126,
      'down': 125,
      'left': 123,
      'right': 124
    };

    const code = keyCodes[key.toLowerCase()];
    if (code) {
      await this.runScript(`tell application "System Events" to key code ${code}`);
    } else {
      throw new Error(`Unknown key: ${key}`);
    }
  }

  /**
   * Press key with modifier
   */
  async pressKeyWithModifier(key, modifier) {
    const modifiers = {
      'command': 'command down',
      'shift': 'shift down',
      'option': 'option down',
      'control': 'control down'
    };

    const mod = modifiers[modifier.toLowerCase()];
    if (!mod) throw new Error(`Unknown modifier: ${modifier}`);

    await this.runScript(`tell application "System Events" to keystroke "${key}" using {${mod}}`);
  }

  /**
   * Focus an application
   */
  async focusApp(appName) {
    await this.runScript(`tell application "${appName}" to activate`);
    await new Promise(r => setTimeout(r, 200));
  }

  /**
   * Get frontmost application name
   */
  async getFrontmostApp() {
    return await this.runScript(`
      tell application "System Events"
        name of first application process whose frontmost is true
      end tell
    `);
  }

  /**
   * Validate that Chrome (or specified browser) is the frontmost app
   * Returns { valid: boolean, currentApp: string, error?: string }
   */
  async validateFocus(expectedApp = 'Google Chrome') {
    const currentApp = await this.getFrontmostApp();
    const isValid = currentApp.toLowerCase().includes(expectedApp.toLowerCase().split(' ')[0]);

    return {
      valid: isValid,
      currentApp,
      expectedApp,
      error: isValid ? null : `Expected ${expectedApp} to be frontmost, but found: ${currentApp}`
    };
  }

  /**
   * Safe type - validates Chrome focus before typing, aborts if not focused
   * Prevents typing into wrong windows (like password dialogs)
   */
  async safeType(text, options = {}) {
    // First validate focus
    const focus = await this.validateFocus(options.expectedApp || 'Google Chrome');

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
    const expectedApp = options.expectedApp || 'Google Chrome';

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
}

// CLI test
if (import.meta.url === `file://${process.argv[1]}`) {
  const bridge = new OSABridge();

  console.log('Testing osascript bridge...');

  const pos = await bridge.getMousePosition();
  console.log(`Current mouse position: ${pos.x}, ${pos.y}`);

  const app = await bridge.getFrontmostApp();
  console.log(`Frontmost app: ${app}`);

  console.log('✓ osascript bridge working');
}

export default OSABridge;
