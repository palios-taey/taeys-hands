/**
 * Platform Bridge - OS Abstraction Layer
 * 
 * Provides unified interface for OS-specific operations:
 * - Keyboard input (typing, key presses)
 * - Mouse control (clicking, movement)
 * - Clipboard operations
 * - Application focus
 * - File dialog navigation
 * 
 * Implementations:
 * - macOS: AppleScript via osascript
 * - Linux: xdotool
 */

import { exec } from 'child_process';
import { promisify } from 'util';
import os from 'os';
import { OSType, TIMING } from '../../types.js';

const execAsync = promisify(exec);

// ============================================================================
// Bridge Interface
// ============================================================================

export interface PlatformBridge {
  readonly osType: OSType;
  
  // Typing operations
  type(text: string, options?: TypeOptions): Promise<void>;
  typeWithMixedContent(text: string): Promise<void>;
  safeTypeLong(text: string, options?: SafeTypeOptions): Promise<void>;
  
  // Key operations
  pressKey(key: string): Promise<void>;
  pressKeyCombo(keys: string[]): Promise<void>;
  
  // Mouse operations
  clickAt(x: number, y: number): Promise<void>;
  
  // Clipboard operations
  setClipboard(text: string): Promise<void>;
  getClipboard(): Promise<string>;
  paste(): Promise<void>;
  
  // Application control
  focusApp(appName: string): Promise<void>;
  getBrowserName(): string;
  
  // File dialog navigation (macOS: Cmd+Shift+G, Linux: Ctrl+L)
  navigateFileDialog(filePath: string): Promise<void>;
  
  // Script execution
  runScript(script: string): Promise<string>;
  runCommand(command: string): Promise<string>;
}

export interface TypeOptions {
  baseDelay?: number;
  variation?: number;
}

export interface SafeTypeOptions extends TypeOptions {
  chunkSize?: number;
  focusCheckInterval?: number;
}

// ============================================================================
// macOS Bridge (AppleScript)
// ============================================================================

export class MacOSBridge implements PlatformBridge {
  readonly osType: OSType = 'darwin';
  
  private readonly browserName: string;
  
  constructor(browserName: string = 'Google Chrome') {
    this.browserName = browserName;
  }
  
  async type(text: string, options: TypeOptions = {}): Promise<void> {
    const { baseDelay = 30, variation = 15 } = options;
    
    // Escape special characters for AppleScript
    const escaped = this.escapeForAppleScript(text);
    
    // Use keystroke for short text, or type character by character with delays
    if (text.length < 50) {
      await this.runScript(`
        tell application "System Events"
          keystroke "${escaped}"
        end tell
      `);
    } else {
      // Character-by-character typing with mimesis delays
      for (const char of text) {
        const escapedChar = this.escapeForAppleScript(char);
        await this.runScript(`
          tell application "System Events"
            keystroke "${escapedChar}"
          end tell
        `);
        const delay = baseDelay + Math.random() * variation;
        await this.sleep(delay);
      }
    }
  }
  
  async typeWithMixedContent(text: string): Promise<void> {
    // Split text into chunks, type some, paste others
    // This makes AI-generated text look more natural
    const chunks = this.splitIntoMixedChunks(text);
    
    for (const chunk of chunks) {
      if (chunk.paste) {
        await this.setClipboard(chunk.text);
        await this.paste();
        await this.sleep(100);
      } else {
        await this.type(chunk.text, { baseDelay: 25, variation: 10 });
      }
    }
  }
  
  async safeTypeLong(text: string, options: SafeTypeOptions = {}): Promise<void> {
    const { chunkSize = 100, focusCheckInterval = 500 } = options;
    
    // Break into chunks and verify focus between each
    for (let i = 0; i < text.length; i += chunkSize) {
      const chunk = text.slice(i, i + chunkSize);
      
      // Re-verify browser focus before each chunk
      await this.focusApp(this.browserName);
      await this.sleep(50);
      
      await this.type(chunk, options);
      
      if (i + chunkSize < text.length) {
        await this.sleep(focusCheckInterval);
      }
    }
  }
  
  async pressKey(key: string): Promise<void> {
    const keyMap: Record<string, string> = {
      'return': 'return',
      'enter': 'return',
      'tab': 'tab',
      'escape': 'escape',
      'space': 'space',
      'delete': 'delete',
      'backspace': 'delete',
      'up': 'up arrow',
      'down': 'down arrow',
      'left': 'left arrow',
      'right': 'right arrow',
    };
    
    const mappedKey = keyMap[key.toLowerCase()] || key;
    
    await this.runScript(`
      tell application "System Events"
        key code ${this.getKeyCode(mappedKey)}
      end tell
    `);
  }
  
  async pressKeyCombo(keys: string[]): Promise<void> {
    // Parse keys like ['command', 'shift', 'g']
    const modifiers: string[] = [];
    let mainKey = '';
    
    for (const key of keys) {
      const lower = key.toLowerCase();
      if (['command', 'cmd', 'control', 'ctrl', 'option', 'alt', 'shift'].includes(lower)) {
        modifiers.push(lower.replace('cmd', 'command').replace('ctrl', 'control').replace('alt', 'option'));
      } else {
        mainKey = key;
      }
    }
    
    const modifierString = modifiers.length > 0 
      ? `using {${modifiers.map(m => m + ' down').join(', ')}}` 
      : '';
    
    await this.runScript(`
      tell application "System Events"
        keystroke "${mainKey}" ${modifierString}
      end tell
    `);
  }
  
  async clickAt(x: number, y: number): Promise<void> {
    // Use cliclick if available, otherwise fall back to AppleScript
    try {
      await this.runCommand(`cliclick c:${Math.round(x)},${Math.round(y)}`);
    } catch {
      // Fallback to AppleScript mouse click
      await this.runScript(`
        do shell script "
          osascript -e 'tell application \\"System Events\\" to click at {${Math.round(x)}, ${Math.round(y)}}'
        "
      `);
    }
  }
  
  async setClipboard(text: string): Promise<void> {
    const escaped = text.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    await this.runScript(`set the clipboard to "${escaped}"`);
  }
  
  async getClipboard(): Promise<string> {
    const result = await this.runScript('the clipboard');
    return result.trim();
  }
  
  async paste(): Promise<void> {
    await this.pressKeyCombo(['command', 'v']);
  }
  
  async focusApp(appName: string): Promise<void> {
    await this.runScript(`
      tell application "${appName}"
        activate
      end tell
    `);
    await this.sleep(TIMING.APP_FOCUS);
  }
  
  getBrowserName(): string {
    return this.browserName;
  }
  
  async navigateFileDialog(filePath: string): Promise<void> {
    // Parse path into directory and filename
    const lastSlash = filePath.lastIndexOf('/');
    const directory = filePath.substring(0, lastSlash);
    const filename = filePath.substring(lastSlash + 1);
    
    // Step 1: Open Go To Folder dialog (Cmd+Shift+G)
    await this.runScript(`
      tell application "System Events"
        tell process "${this.browserName}"
          keystroke "g" using {command down, shift down}
        end tell
      end tell
    `);
    await this.sleep(TIMING.MENU_RENDER);
    
    // Step 2: Type directory path
    await this.type(directory, { baseDelay: 30, variation: 15 });
    await this.sleep(TIMING.TYPING_BUFFER);
    
    // Step 3: Press Enter to navigate to directory
    await this.pressKey('return');
    await this.sleep(TIMING.FINDER_NAVIGATE);
    
    // Step 4: Type filename to select it
    await this.type(filename, { baseDelay: 30, variation: 15 });
    await this.sleep(TIMING.TYPING_BUFFER);
    
    // Step 5: Press Enter to select/open file
    await this.pressKey('return');
    await this.sleep(TIMING.FINDER_NAVIGATE);
  }
  
  async runScript(script: string): Promise<string> {
    const { stdout } = await execAsync(`osascript -e '${script.replace(/'/g, "'\\''")}'`);
    return stdout;
  }
  
  async runCommand(command: string): Promise<string> {
    const { stdout } = await execAsync(command);
    return stdout;
  }
  
  // Private helpers
  
  private escapeForAppleScript(text: string): string {
    return text
      .replace(/\\/g, '\\\\')
      .replace(/"/g, '\\"')
      .replace(/\n/g, '\\n')
      .replace(/\r/g, '\\r')
      .replace(/\t/g, '\\t');
  }
  
  private splitIntoMixedChunks(text: string): Array<{ text: string; paste: boolean }> {
    const chunks: Array<{ text: string; paste: boolean }> = [];
    let remaining = text;
    
    while (remaining.length > 0) {
      // Randomly decide whether to type or paste
      const shouldPaste = remaining.length > 50 && Math.random() > 0.6;
      const chunkSize = shouldPaste 
        ? Math.floor(Math.random() * 200) + 50  // 50-250 chars for paste
        : Math.floor(Math.random() * 30) + 10;  // 10-40 chars for typing
      
      const chunk = remaining.slice(0, chunkSize);
      remaining = remaining.slice(chunkSize);
      
      chunks.push({ text: chunk, paste: shouldPaste });
    }
    
    return chunks;
  }
  
  private getKeyCode(key: string): number {
    const keyCodes: Record<string, number> = {
      'return': 36,
      'tab': 48,
      'space': 49,
      'delete': 51,
      'escape': 53,
      'up arrow': 126,
      'down arrow': 125,
      'left arrow': 123,
      'right arrow': 124,
    };
    return keyCodes[key] || 0;
  }
  
  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// ============================================================================
// Linux Bridge (xdotool)
// ============================================================================

export class LinuxBridge implements PlatformBridge {
  readonly osType: OSType = 'linux';
  
  private readonly browserName: string;
  
  constructor(browserName: string = 'google-chrome') {
    this.browserName = browserName;
  }
  
  async type(text: string, options: TypeOptions = {}): Promise<void> {
    const { baseDelay = 30 } = options;
    
    // xdotool type with delay
    const escaped = text.replace(/'/g, "'\\''");
    await this.runCommand(`xdotool type --delay ${baseDelay} '${escaped}'`);
  }
  
  async typeWithMixedContent(text: string): Promise<void> {
    const chunks = this.splitIntoMixedChunks(text);
    
    for (const chunk of chunks) {
      if (chunk.paste) {
        await this.setClipboard(chunk.text);
        await this.paste();
        await this.sleep(100);
      } else {
        await this.type(chunk.text, { baseDelay: 25 });
      }
    }
  }
  
  async safeTypeLong(text: string, options: SafeTypeOptions = {}): Promise<void> {
    const { chunkSize = 100, focusCheckInterval = 500 } = options;
    
    for (let i = 0; i < text.length; i += chunkSize) {
      const chunk = text.slice(i, i + chunkSize);
      
      await this.focusApp(this.browserName);
      await this.sleep(50);
      
      await this.type(chunk, options);
      
      if (i + chunkSize < text.length) {
        await this.sleep(focusCheckInterval);
      }
    }
  }
  
  async pressKey(key: string): Promise<void> {
    const keyMap: Record<string, string> = {
      'return': 'Return',
      'enter': 'Return',
      'tab': 'Tab',
      'escape': 'Escape',
      'space': 'space',
      'delete': 'Delete',
      'backspace': 'BackSpace',
      'up': 'Up',
      'down': 'Down',
      'left': 'Left',
      'right': 'Right',
    };
    
    const mappedKey = keyMap[key.toLowerCase()] || key;
    await this.runCommand(`xdotool key ${mappedKey}`);
  }
  
  async pressKeyCombo(keys: string[]): Promise<void> {
    const keyMap: Record<string, string> = {
      'command': 'super',
      'cmd': 'super',
      'control': 'ctrl',
      'ctrl': 'ctrl',
      'option': 'alt',
      'alt': 'alt',
      'shift': 'shift',
    };
    
    const mappedKeys = keys.map(k => keyMap[k.toLowerCase()] || k);
    await this.runCommand(`xdotool key ${mappedKeys.join('+')}`);
  }
  
  async clickAt(x: number, y: number): Promise<void> {
    await this.runCommand(`xdotool mousemove ${Math.round(x)} ${Math.round(y)} click 1`);
  }
  
  async setClipboard(text: string): Promise<void> {
    const escaped = text.replace(/'/g, "'\\''");
    await this.runCommand(`echo -n '${escaped}' | xclip -selection clipboard`);
  }
  
  async getClipboard(): Promise<string> {
    const result = await this.runCommand('xclip -selection clipboard -o');
    return result.trim();
  }
  
  async paste(): Promise<void> {
    await this.pressKeyCombo(['ctrl', 'v']);
  }
  
  async focusApp(appName: string): Promise<void> {
    // Try to find and focus the window
    try {
      const windowId = await this.runCommand(`xdotool search --name "${appName}" | head -1`);
      if (windowId.trim()) {
        await this.runCommand(`xdotool windowactivate ${windowId.trim()}`);
        await this.runCommand(`xdotool windowraise ${windowId.trim()}`);
      }
    } catch {
      // Window might not be found, continue anyway
    }
    await this.sleep(TIMING.APP_FOCUS);
  }
  
  getBrowserName(): string {
    return this.browserName;
  }
  
  async navigateFileDialog(filePath: string): Promise<void> {
    // Linux file dialogs: Ctrl+L opens location bar
    await this.pressKeyCombo(['ctrl', 'l']);
    await this.sleep(TIMING.MENU_RENDER);
    
    // Type full path
    await this.type(filePath, { baseDelay: 30 });
    await this.sleep(TIMING.TYPING_BUFFER);
    
    // Press Enter to navigate and select
    await this.pressKey('return');
    await this.sleep(TIMING.FINDER_NAVIGATE);
  }
  
  async runScript(script: string): Promise<string> {
    // Linux doesn't have osascript, so we just run the command
    return this.runCommand(script);
  }
  
  async runCommand(command: string): Promise<string> {
    const { stdout } = await execAsync(command);
    return stdout;
  }
  
  // Private helpers
  
  private splitIntoMixedChunks(text: string): Array<{ text: string; paste: boolean }> {
    const chunks: Array<{ text: string; paste: boolean }> = [];
    let remaining = text;
    
    while (remaining.length > 0) {
      const shouldPaste = remaining.length > 50 && Math.random() > 0.6;
      const chunkSize = shouldPaste 
        ? Math.floor(Math.random() * 200) + 50
        : Math.floor(Math.random() * 30) + 10;
      
      const chunk = remaining.slice(0, chunkSize);
      remaining = remaining.slice(chunkSize);
      
      chunks.push({ text: chunk, paste: shouldPaste });
    }
    
    return chunks;
  }
  
  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// ============================================================================
// Bridge Factory
// ============================================================================

export function createPlatformBridge(browserName?: string): PlatformBridge {
  const platform = os.platform() as OSType;
  
  switch (platform) {
    case 'darwin':
      return new MacOSBridge(browserName || 'Google Chrome');
    case 'linux':
      return new LinuxBridge(browserName || 'google-chrome');
    default:
      throw new Error(`Unsupported platform: ${platform}. Only macOS and Linux are supported.`);
  }
}

export function getPlatform(): OSType {
  return os.platform() as OSType;
}
