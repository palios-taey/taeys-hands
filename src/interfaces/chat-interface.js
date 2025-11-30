/**
 * Chat Interface Abstraction - Unified API for AI Family chat UIs
 *
 * Abstracts the differences between Claude, ChatGPT, Gemini, and Grok
 * so Taey can orchestrate conversations across all of them.
 */

import BrowserConnector from '../core/browser-connector.js';
import { createPlatformBridge } from '../core/platform-bridge.js';
import { SelectorRegistry } from '../v2/core/selectors/selector-registry.js';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

export class ChatInterface {
  constructor(config = {}) {
    this.browser = new BrowserConnector(config.browser);
    this.bridge = null; // Will be initialized in connect()
    this.page = null;
    this.name = config.name || 'unknown';
    this.url = config.url;
    this.selectors = config.selectors || {};
    this.connected = false;
    this.mimesisConfig = config.mimesis || {};
    this.registry = new SelectorRegistry(); // Initialize SelectorRegistry
  }

  /**
   * Get browser window name for focusApp calls
   * Handles Chrome, Chromium, and Firefox on both macOS and Linux
   */
  _getBrowserName() {
    return this.browser.getBrowserName ? this.browser.getBrowserName() : 'Chromium';
  }

  /**
   * Get selector from registry with fallback to hardcoded selectors
   * @param {string} key - Selector key (e.g., 'attach_button', 'send_button', 'message_input')
   * @param {string} fallback - Fallback selector if registry fails
   * @returns {Promise<string>} Selector string
   */
  async _getSelector(key, fallback) {
    try {
      const selector = await this.registry.getSelector(this.name, key);
      console.log(`  → Using registry selector for '${key}': ${selector}`);
      return selector;
    } catch (err) {
      if (fallback) {
        console.log(`  → Using fallback selector for '${key}': ${fallback}`);
        return fallback;
      }
      throw new Error(`Selector '${key}' not found in registry and no fallback provided: ${err.message}`);
    }
  }

  /**
   * Connect to this chat interface
   * @param {Object} options - { sessionId, screenshotPath, newConversation, conversationId }
   * @returns {Object} { screenshot: string, sessionId: string, conversationId: string|null }
   */
  async connect(options = {}) {
    // Session ID is required - either provided or generated
    const sessionId = options.sessionId || Date.now().toString();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-connected.png`;

    await this.browser.connect();

    // Determine target URL based on session type
    let targetUrl;
    if (options.newConversation) {
      // Fresh session - navigate to new chat URL (will click new chat button after)
      targetUrl = this._getNewChatUrl();
      console.log(`  [${this.name}: Creating new conversation → ${targetUrl}]`);
    } else if (options.conversationId) {
      // Resume existing conversation - navigate directly to it
      targetUrl = this.buildConversationUrl(options.conversationId);
      console.log(`  [${this.name}: Resuming conversation → ${targetUrl}]`);
    } else {
      // No explicit session type - navigate to base URL (may load cached conversation)
      targetUrl = this.url;
      console.log(`  [${this.name}: Navigating to base URL → ${targetUrl}]`);
    }

    this.page = await this.browser.getPage(this.name, targetUrl);

    // Wait for chat input to be ready
    try {
      const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
      await this.page.waitForSelector(chatInputSelector, { timeout: 15000 });
    } catch (err) {
      console.error(`  [${this.name}: Chat input not found after navigation]`);
      throw new Error(`Chat input not found for ${this.name} at ${targetUrl}`);
    }

    // Initialize platform-specific bridge
    this.bridge = await createPlatformBridge(this.mimesisConfig);

    // Bring browser to front, then bring this tab to front
    await this.bridge.focusApp(this._getBrowserName());
    await this.page.bringToFront();
    await this.page.waitForTimeout(500); // Wait for tab to be fully visible

    // Extract actual conversationId from URL (for new conversations)
    const currentUrl = await this.getCurrentConversationUrl();
    const actualConversationId = this._extractConversationId(currentUrl);

    // Capture screenshot to verify tab is visible
    await this.screenshot(screenshotPath);

    this.connected = true;
    console.log(`✓ Connected to ${this.name}`);
    console.log(`  Screenshot → ${screenshotPath}`);
    if (actualConversationId) {
      console.log(`  Conversation ID → ${actualConversationId}`);
    }

    return {
      screenshot: screenshotPath,
      sessionId: sessionId,
      conversationId: actualConversationId
    };
  }

  /**
   * Get the new chat URL for this platform
   * Override in subclasses for platform-specific URLs
   * @returns {string} URL to navigate to for creating a new chat
   */
  _getNewChatUrl() {
    // Default: most platforms create new chat at base URL
    return this.url;
  }

  /**
   * Extract conversation ID from URL
   * Override in subclasses for platform-specific URL patterns
   * @param {string} url - Current page URL
   * @returns {string|null} Conversation ID or null if not found
   */
  _extractConversationId(url) {
    // Default: no extraction (override in subclasses)
    return null;
  }

  /**
   * Check if logged in (by looking for chat input)
   */
  async isLoggedIn() {
    try {
      const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
      await this.page.waitForSelector(chatInputSelector, { timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Start a new chat conversation
   * Either clicks the new chat button or navigates to the base URL
   */
  async startNewChat() {
    // Try to click new chat button if available
    try {
      const newChatBtnSelector = await this._getSelector('new_chat_button', this.selectors.newChatButton);
      if (newChatBtnSelector) {
        const newChatBtn = await this.page.$(newChatBtnSelector);
        if (newChatBtn) {
          await newChatBtn.click();
          await this.page.waitForTimeout(1000);
          console.log(`  [${this.name}: Started new chat via button]`);
          return true;
        }
      }
    } catch (e) {
      // Fall through to URL navigation
    }

    // Fall back to navigating to base URL
    if (this.url) {
      await this.page.goto(this.url);
      await this.page.waitForTimeout(2000);
      console.log(`  [${this.name}: Started new chat via URL navigation]`);
      return true;
    }

    throw new Error(`Cannot start new chat for ${this.name} - no button selector or URL`);
  }

  /**
   * Take a screenshot of the current page
   * @param {string} filename - Optional filename (default: /tmp/taey-screenshot.png)
   * @returns {string} Path to the saved screenshot
   */
  async screenshot(filename = '/tmp/taey-screenshot.png') {
    await this.page.screenshot({ path: filename, fullPage: false });
    console.log(`  [Screenshot saved to ${filename}]`);
    return filename;
  }

  /**
   * Attach a file to the current conversation
   * @param {string|string[]} filePaths - Path(s) to file(s) to attach
   */
  async attachFile(filePaths) {
    const paths = Array.isArray(filePaths) ? filePaths : [filePaths];

    // Verify files exist
    for (const filePath of paths) {
      try {
        await fs.access(filePath);
      } catch {
        throw new Error(`File not found: ${filePath}`);
      }
    }

    // Get file input selector from registry with fallback
    const fileInputSelector = await this._getSelector('file_input', this.selectors.fileInput);
    if (!fileInputSelector) {
      throw new Error(`File attachments not supported for ${this.name}`);
    }

    // Try to find an existing file input, or click the attachment button to reveal one
    let fileInput = await this.page.$(fileInputSelector);

    if (!fileInput) {
      // Get attach button selector from registry with fallback
      const attachBtnSelector = await this._getSelector('attach_button', this.selectors.attachmentButton);
      if (attachBtnSelector) {
        const attachBtn = await this.page.$(attachBtnSelector);
        if (attachBtn) {
          await attachBtn.click();
          await this.page.waitForTimeout(500);
          fileInput = await this.page.$(fileInputSelector);
        }
      }
    }

    if (!fileInput) {
      throw new Error(`Could not find file input for ${this.name}`);
    }

    // Use Playwright's setInputFiles to inject files directly
    await fileInput.setInputFiles(paths);

    // Wait for upload to process
    await this.page.waitForTimeout(1000);

    console.log(`  [Attached ${paths.length} file(s) to ${this.name}]`);
    return true;
  }

  /**
   * Send a message with file attachment(s)
   * @param {string} message - The message to send
   * @param {string|string[]} filePaths - Path(s) to file(s) to attach
   * @param {Object} options - Same options as sendMessage
   */
  async sendMessageWithAttachment(message, filePaths, options = {}) {
    // Attach files first
    await this.attachFile(filePaths);

    // Wait a moment for the attachment to register
    await this.page.waitForTimeout(500);

    // Then send the message
    return await this.sendMessage(message, options);
  }

  /**
   * Shared: Navigate file dialog to select a file
   * Cross-platform: Cmd+Shift+G on macOS, Ctrl+L on Linux
   * Call this after the native file dialog is open
   * @param {string} filePath - Absolute path to the file
   */
  async _navigateFinderDialog(filePath) {
    const platform = os.platform();

    if (platform === 'darwin') {
      // macOS: Use Cmd+Shift+G (Go to folder)
      // Split path into directory and filename
      const dir = filePath.substring(0, filePath.lastIndexOf('/'));
      const filename = filePath.substring(filePath.lastIndexOf('/') + 1);

      console.log(`  [${this.name}: macOS - Pressing Cmd+Shift+G]`);
      const browserName = this._getBrowserName();
      await this.bridge.runScript(`
        tell application "System Events"
          tell process "${browserName}"
            keystroke "g" using {command down, shift down}
          end tell
        end tell
      `);
      await this.page.waitForTimeout(800);

      // Type the directory path only
      console.log(`  [${this.name}: Typing directory "${dir}"]`);
      await this.bridge.type(dir, { baseDelay: 30, variation: 15 });
      await this.page.waitForTimeout(300);

      // Press Enter to navigate to directory
      console.log(`  [${this.name}: Pressing Enter to navigate to directory]`);
      await this.bridge.pressKey('return');
      await this.page.waitForTimeout(1000);

      // Type filename to select it
      console.log(`  [${this.name}: Typing filename "${filename}"]`);
      await this.bridge.type(filename, { baseDelay: 30, variation: 15 });
      await this.page.waitForTimeout(300);

      // Press Enter to open/select file
      console.log(`  [${this.name}: Pressing Enter to select file]`);
      await this.bridge.pressKey('return');
      await this.page.waitForTimeout(1000);
    } else if (platform === 'linux') {
      // Linux: Use Ctrl+L (location bar in file dialogs)
      console.log(`  [${this.name}: Linux - Pressing Ctrl+L]`);
      await this.bridge.pressKeyWithModifier('l', 'control');
      await this.page.waitForTimeout(800);

      // Type the file path
      console.log(`  [${this.name}: Typing path "${filePath}"]`);
      await this.bridge.type(filePath, { baseDelay: 30, variation: 15 });
      await this.page.waitForTimeout(300);

      // Press Enter to navigate/select
      console.log(`  [${this.name}: Pressing Enter to select file]`);
      await this.bridge.pressKey('return');
      await this.page.waitForTimeout(1000);
    } else {
      throw new Error(`File dialog navigation not supported on platform: ${platform}`);
    }
  }

  /**
   * ATOMIC ACTION: Enable research/pro mode
   * Interface-specific implementation (e.g., Pro Search on Perplexity)
   *
   * ⚠️ UNVERIFIED ACTION - UI state change MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify the UI actually changed state (button toggled, mode enabled).
   * ALWAYS check the returned screenshot to verify the intended effect occurred.
   *
   * @param {Object} options - { sessionId, screenshotPath, selector }
   * @returns {Object} { screenshot: string, automationCompleted: boolean }
   * @throws {Error} If research mode button not found or click fails
   */
  async enableResearchMode(options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-research-mode.png`;
    const selector = options.selector || 'button[aria-label*="Pro"]'; // Default for Perplexity

    console.log(`[${this.name}] enableResearchMode()`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // STRICT: No graceful failure - throw if button not found
    const button = await this.page.waitForSelector(selector, { timeout: 5000 });
    await button.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  /**
   * ATOMIC ACTION: Attach file
   * Uses native file picker with osascript Cmd+Shift+G navigation
   *
   * ⚠️ UNVERIFIED ACTION - File attachment MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify the file actually appeared in the UI attachment area.
   * ALWAYS check the returned screenshot to verify file is visible in input.
   *
   * @param {string} filePath - Absolute path to file
   * @param {Object} options - { sessionId, screenshotPath, attachButtonSelector }
   * @returns {Object} { screenshot: string, automationCompleted: boolean, filePath: string }
   * @throws {Error} If attach button not found or file attachment fails
   */
  async attachFile(filePath, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-file-attached.png`;

    // Platform-specific attach button selectors
    // NOTE: Claude, ChatGPT, and Perplexity have override methods with menu navigation
    const platformSelectors = {
      'grok': 'button[aria-label="Attach"]',
      'claude': '[data-testid="input-menu-plus"]',  // Claude uses + menu (but has override)
      'chatgpt': '[data-testid="composer-plus-btn"]',  // ChatGPT uses + menu (but has override)
      'gemini': 'button[aria-label="Open upload file menu"]',
      'perplexity': 'button[data-testid="attach-files-button"]'  // Perplexity has override
    };

    const attachButtonSelector = options.attachButtonSelector || platformSelectors[this.name];

    if (!attachButtonSelector) {
      throw new Error(`No attach button selector defined for platform: ${this.name}`);
    }

    console.log(`[${this.name}] attachFile(${filePath})`);
    console.log(`  → Using selector: ${attachButtonSelector}`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Try to find attach button with multiple fallback strategies
    let attachBtn = null;
    try {
      attachBtn = await this.page.waitForSelector(attachButtonSelector, { timeout: 5000 });
      console.log(`  ✓ Found attach button with primary selector`);
    } catch (firstError) {
      console.log(`  ⚠ Primary selector timed out: ${attachButtonSelector}`);

      // Fallback: Try generic attachment button selectors
      const fallbackSelectors = [
        'button[aria-label*="Attach"]',
        'button[aria-label*="Upload"]',
        'button[aria-label*="attach" i]',
        'button[data-testid*="attach"]',
        'button[aria-label*="file" i]',
        '[data-testid="input-menu-plus"]',  // Claude fallback
        '[data-testid="composer-plus-btn"]'  // ChatGPT fallback
      ];

      for (const fallbackSelector of fallbackSelectors) {
        try {
          console.log(`  → Trying fallback: ${fallbackSelector}`);
          attachBtn = await this.page.waitForSelector(fallbackSelector, { timeout: 2000 });
          if (attachBtn) {
            console.log(`  ✓ Found attach button with fallback: ${fallbackSelector}`);
            break;
          }
        } catch {
          // Continue to next fallback
        }
      }

      if (!attachBtn) {
        throw new Error(`Attach button not found after trying primary and fallback selectors for ${this.name}`);
      }
    }

    await attachBtn.click();
    console.log(`  ✓ Clicked attach button`);
    await this.page.waitForTimeout(1500); // Wait for file picker or menu

    // Use osascript to navigate file picker with Cmd+Shift+G
    const dir = filePath.substring(0, filePath.lastIndexOf('/'));
    const filename = filePath.substring(filePath.lastIndexOf('/') + 1);

    // Cmd+Shift+G to open "Go to folder"
    const browserName = this._getBrowserName();
    const cmdShiftG = `tell application "System Events" to tell process "${browserName}" to keystroke "g" using {command down, shift down}`;
    await this.bridge.runScript(cmdShiftG);
    await this.page.waitForTimeout(500);

    // Type directory path
    await this.bridge.type(dir);
    await this.page.waitForTimeout(300);

    // Press Enter to navigate
    await this.bridge.pressKey('return');
    await this.page.waitForTimeout(1000);

    // Type filename to select it
    await this.bridge.type(filename);
    await this.page.waitForTimeout(300);

    // Press Enter to open/attach
    await this.bridge.pressKey('return');
    console.log(`  ✓ Automation completed - VERIFY FILE IN SCREENSHOT`);

    // Capture screenshot
    await this.page.waitForTimeout(1500); // Wait for file to appear
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      filePath
    };
  }

  /**
   * ATOMIC ACTION: Prepare input for typing
   * Brings tab to front, focuses input, captures screenshot
   *
   * ⚠️ UNVERIFIED ACTION - Input focus MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify focus actually moved to the input (cursor visible).
   * ALWAYS check the returned screenshot to verify input has focus indicator.
   *
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot: string, automationCompleted: boolean }
   */
  async prepareInput(options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-focused.png`;

    console.log(`[${this.name}] prepareInput()`);

    // Bring tab to front (CRITICAL for osascript typing)
    await this.page.bringToFront();
    await this.page.waitForTimeout(100);

    // Focus the input
    const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
    const input = await this.page.waitForSelector(chatInputSelector, { timeout: 10000 });
    await input.click();
    await this.page.waitForTimeout(200);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Automation completed - VERIFY FOCUS IN SCREENSHOT`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  /**
   * ATOMIC ACTION: Type message into focused input
   * Assumes input is already focused (call prepareInput first)
   *
   * ⚠️ UNVERIFIED ACTION - Text in input MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify text actually appeared in the input box.
   * ALWAYS check the returned screenshot to verify message is visible in input.
   *
   * @param {string} message - The message to type
   * @param {Object} options - { humanLike: boolean, mixedContent: boolean, sessionId, screenshotPath }
   * @returns {Object} { screenshot: string, automationCompleted: boolean }
   */
  async typeMessage(message, options = {}) {
    const useHumanInput = options.humanLike !== false;
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-typed.png`;

    console.log(`[${this.name}] typeMessage(${message.length} chars)`);

    if (useHumanInput) {
      // CRITICAL: Bring tab to front again before typing
      await this.page.bringToFront();
      await this.page.waitForTimeout(200);

      // Focus the browser window (using xdotool windowraise + windowfocus)
      await this.bridge.focusApp(this._getBrowserName());

      // CRITICAL: Get input element coordinates and click with xdotool (not Playwright)
      // This ensures X11 focus is set correctly for xdotool typing
      const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
      const input = await this.page.waitForSelector(chatInputSelector, { timeout: 10000 });
      const box = await input.boundingBox();
      if (box) {
        // Get browser window position and chrome height to convert viewport coords to screen coords
        // boundingBox() returns viewport-relative coordinates, but xdotool needs screen coordinates
        const windowInfo = await this.page.evaluate(() => ({
          screenX: window.screenX,
          screenY: window.screenY,
          outerHeight: window.outerHeight,
          innerHeight: window.innerHeight,
          outerWidth: window.outerWidth,
          innerWidth: window.innerWidth
        }));

        // Calculate offsets: window position + browser chrome (toolbar, etc.)
        const chromeHeight = windowInfo.outerHeight - windowInfo.innerHeight;
        const chromeWidth = windowInfo.outerWidth - windowInfo.innerWidth;

        // Convert viewport coordinates to screen coordinates
        const screenX = windowInfo.screenX + (chromeWidth / 2) + box.x + (box.width / 2);
        const screenY = windowInfo.screenY + chromeHeight + box.y + (box.height / 2);

        const clickX = Math.round(screenX);
        const clickY = Math.round(screenY);

        console.log(`  [DEBUG] Window: (${windowInfo.screenX}, ${windowInfo.screenY}), Chrome: ${chromeHeight}px`);
        console.log(`  [DEBUG] Box: (${box.x}, ${box.y}) -> Screen: (${clickX}, ${clickY})`);

        await this.bridge.clickAt(clickX, clickY);
        await this.page.waitForTimeout(300);
      } else {
        // Fallback to Playwright click if boundingBox fails
        await input.click();
        await this.page.waitForTimeout(200);
      }

      // Use mixed content typing (type + paste) for AI quotes
      if (options.mixedContent !== false) {
        await this.bridge.typeWithMixedContent(message);
      } else {
        await this.bridge.safeTypeLong(message);
      }
    } else {
      // Direct injection (faster but detectable)
      const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
      const input = await this.page.waitForSelector(chatInputSelector, { timeout: 10000 });
      await input.fill(message);
    }

    // Capture screenshot
    await this.page.waitForTimeout(500);
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Automation completed - VERIFY TEXT IN SCREENSHOT`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  /**
   * ATOMIC ACTION: Paste message into focused input
   * Assumes input is already focused (call prepareInput first)
   * Uses clipboard paste instead of typing for maximum speed
   *
   * ⚠️ UNVERIFIED ACTION - Text in input MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify text actually appeared in the input box.
   * ALWAYS check the returned screenshot to verify message is visible in input.
   *
   * @param {string} message - The message to paste
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot: string, automationCompleted: boolean }
   */
  async pasteMessage(message, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-pasted.png`;

    console.log(`[${this.name}] pasteMessage(${message.length} chars)`);

    // CRITICAL: Bring tab to front before typing
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Focus the browser window (required for xdotool on Linux)
    await this.bridge.focusApp(this._getBrowserName());

    // Click on input to ensure focus using screen coordinates
    const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
    const input = await this.page.waitForSelector(chatInputSelector, { timeout: 10000 });
    const box = await input.boundingBox();
    if (box) {
      const windowInfo = await this.page.evaluate(() => ({
        screenX: window.screenX,
        screenY: window.screenY,
        outerHeight: window.outerHeight,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        innerWidth: window.innerWidth
      }));
      const chromeHeight = windowInfo.outerHeight - windowInfo.innerHeight;
      const chromeWidth = windowInfo.outerWidth - windowInfo.innerWidth;
      const screenX = windowInfo.screenX + (chromeWidth / 2) + box.x + (box.width / 2);
      const screenY = windowInfo.screenY + chromeHeight + box.y + (box.height / 2);
      await this.bridge.clickAt(screenX, screenY);
      await this.page.waitForTimeout(100);
    }

    // Use typeFast to bypass clipboard (xclip doesn't work in VNC)
    await this.bridge.typeFast(message);

    // Capture screenshot
    await this.page.waitForTimeout(500);
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Automation completed - VERIFY TEXT IN SCREENSHOT`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  /**
   * ATOMIC ACTION: Send the message
   * Assumes message is already typed in input
   *
   * ⚠️ UNVERIFIED ACTION - Message submission MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify the message actually sent (input cleared, message appears).
   * ALWAYS check the returned screenshot to verify input is empty and sending.
   *
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot: string, automationCompleted: boolean }
   */
  async clickSend(options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-sent.png`;

    console.log(`[${this.name}] clickSend()`);

    // Send via Enter key
    await this.page.waitForTimeout(300);
    await this.bridge.pressKey('return');

    // Capture screenshot after send
    await this.page.waitForTimeout(1000);
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Automation completed - VERIFY SEND IN SCREENSHOT`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  /**
   * Send a message and wait for response
   * NOTE: This is now a convenience wrapper around atomic actions
   * For step-by-step control, use: prepareInput() → typeMessage() → clickSend() → waitForResponse()
   */
  async sendMessage(message, options = {}) {
    const useHumanInput = options.humanLike !== false;
    const waitForResponse = options.waitForResponse !== false;
    const timeout = options.timeout || 120000; // 2 min default for long responses
    const sessionId = Date.now();

    console.log(`\n[${this.name}] Starting sendMessage with systematic verification`);

    // CHECKPOINT 1: Initial state before any action
    const ss1 = `/tmp/taey-${this.name}-${sessionId}-01-initial.png`;
    await this.screenshot(ss1);
    console.log(`  ✓ Screenshot 1: Initial state → ${ss1}`);

    // Bring this tab to foreground (critical for osascript typing)
    await this.page.bringToFront();
    await this.page.waitForTimeout(100);

    // Focus the input
    const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
    const input = await this.page.waitForSelector(chatInputSelector, { timeout: 10000 });
    await input.click();
    await this.page.waitForTimeout(200);

    // CHECKPOINT 2: After focusing input, before typing
    const ss2 = `/tmp/taey-${this.name}-${sessionId}-02-focused.png`;
    await this.screenshot(ss2);
    console.log(`  ✓ Screenshot 2: Input focused → ${ss2}`);

    // Type the message
    if (useHumanInput) {
      // CRITICAL: Bring this tab to front before focusing Chrome
      // Without this, typing goes to whatever tab Chrome was showing
      await this.page.bringToFront();
      await this.page.waitForTimeout(200);

      // Use osascript for human-like typing with focus validation
      await this.bridge.focusApp(this._getBrowserName());

      // Use safe typing that validates Chrome focus and re-checks during long messages
      // If message contains AI content (cross-pollination), use mixed typing (type + paste)
      console.log(`  [Typing message: ${message.length} chars...]`);
      if (options.mixedContent !== false) {
        await this.bridge.typeWithMixedContent(message);
      } else {
        await this.bridge.safeTypeLong(message);
      }
    } else {
      // Direct injection (faster but detectable)
      await input.fill(message);
    }

    // CHECKPOINT 3: After typing, before sending
    await this.page.waitForTimeout(500);
    const ss3 = `/tmp/taey-${this.name}-${sessionId}-03-typed.png`;
    await this.screenshot(ss3);
    console.log(`  ✓ Screenshot 3: Message typed → ${ss3}`);

    // Send the message
    await this.page.waitForTimeout(300);
    await this.bridge.pressKey('return');

    // CHECKPOINT 4: After clicking send
    await this.page.waitForTimeout(1000);
    const ss4 = `/tmp/taey-${this.name}-${sessionId}-04-sent.png`;
    await this.screenshot(ss4);
    console.log(`  ✓ Screenshot 4: Message sent → ${ss4}`);

    if (!waitForResponse) {
      return { sent: true, response: null, screenshots: [ss1, ss2, ss3, ss4] };
    }

    // Wait for response (includes periodic screenshots during polling)
    console.log(`  [Waiting for response, timeout: ${timeout/1000}s...]`);
    const response = await this.waitForResponse(timeout, { sessionId });

    return {
      sent: true,
      response,
      screenshots: {
        initial: ss1,
        focused: ss2,
        typed: ss3,
        sent: ss4,
        // waitForResponse adds its own screenshots
      }
    };
  }

  /**
   * Wait for AI response using Fibonacci polling with content stability
   * Now includes screenshot capture at intervals for visibility
   * @param {number} timeout - Max wait time in ms (default 10 min)
   * @param {Object} options - { screenshots: boolean, screenshotDir: string }
   */
  async waitForResponse(timeout = 600000, options = {}) {
    const startTime = Date.now();
    const takeScreenshots = options.screenshots !== false; // Default: enabled
    const screenshotDir = options.screenshotDir || '/tmp';
    const sessionId = options.sessionId || Date.now();

    // Fibonacci sequence (seconds): 1, 1, 2, 3, 5, 8, 13, 21, 34, 55
    const fibonacci = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55];
    // Take screenshots at these Fibonacci intervals (seconds)
    const screenshotIntervals = new Set([0, 2, 5, 13, 34, 55]);
    let fibIndex = 0;
    let totalElapsed = 0;

    let lastContent = '';
    let stableCount = 0;
    const stabilityRequired = 2; // 2 identical content reads = done

    console.log(`  [${this.name}: Fibonacci polling with visual monitoring]`);

    // Get initial content to detect when new response appears
    const initialContent = await this.getLatestResponse();

    // Initial screenshot (t=0)
    if (takeScreenshots) {
      const filename = `${screenshotDir}/taey-${this.name}-${sessionId}-t0.png`;
      await this.screenshot(filename);
    }

    while (Date.now() - startTime < timeout) {
      const elapsed = Math.round((Date.now() - startTime) / 1000);
      const content = await this.getLatestResponse();

      // Check if content is new (different from before we sent) and stable
      if (content && content !== initialContent && content.length > 0) {
        if (content === lastContent) {
          stableCount++;
          console.log(`  [${this.name}: stable ${stableCount}/${stabilityRequired} at ${elapsed}s]`);

          if (stableCount >= stabilityRequired) {
            console.log(`  [${this.name} complete in ${elapsed}s, ${content.length} chars]`);

            // Final screenshot on completion
            if (takeScreenshots) {
              const filename = `${screenshotDir}/taey-${this.name}-${sessionId}-complete.png`;
              await this.screenshot(filename);
            }

            this.logTimingData(elapsed, content.length);
            return content;
          }
        } else {
          stableCount = 0;
          lastContent = content;
          console.log(`  [${this.name}: streaming at ${elapsed}s, ${content.length} chars]`);
        }
      }

      // Fibonacci wait - but use short delay (2s) once stability starts
      let waitSeconds;
      if (stableCount > 0) {
        // After first stable detection, use fast polling for confirmation
        waitSeconds = 2;
      } else if (fibIndex < 3) {
        // First 3 checks at 1s for fast responses
        waitSeconds = 1;
      } else {
        // Then use Fibonacci sequence
        waitSeconds = fibonacci[Math.min(fibIndex, fibonacci.length - 1)];
      }
      await this.page.waitForTimeout(waitSeconds * 1000);
      fibIndex++;
      totalElapsed += waitSeconds;

      // Take screenshot at Fibonacci intervals for visibility
      if (takeScreenshots && screenshotIntervals.has(totalElapsed)) {
        const filename = `${screenshotDir}/taey-${this.name}-${sessionId}-t${totalElapsed}s.png`;
        await this.screenshot(filename);
      }
    }

    const elapsed = Math.round((Date.now() - startTime) / 1000);
    const content = await this.getLatestResponse();
    console.log(`  [${this.name} timeout after ${elapsed}s]`);

    // Timeout screenshot for debugging
    if (takeScreenshots) {
      const filename = `${screenshotDir}/taey-${this.name}-${sessionId}-timeout.png`;
      await this.screenshot(filename);
    }

    return content;
  }

  /**
   * Log timing data for learning response patterns
   */
  logTimingData(elapsedSeconds, responseLength) {
    const now = new Date();
    const data = {
      ai: this.name,
      timestamp: now.toISOString(),
      dayOfWeek: now.getDay(),
      hourOfDay: now.getHours(),
      responseTime: elapsedSeconds,
      responseLength: responseLength
    };
    // Log for future pattern analysis
    console.log(`  [TIMING: ${JSON.stringify(data)}]`);
  }

  /**
   * Get the latest response content
   */
  async getLatestResponse() {
    const containers = await this.page.$$(this.selectors.responseContainer);
    if (containers.length === 0) return '';

    const lastContainer = containers[containers.length - 1];
    return await lastContainer.textContent();
  }

  /**
   * Start a new conversation
   */
  async newConversation() {
    // Will be implemented by specific interfaces
    throw new Error('newConversation not implemented for this interface');
  }

  /**
   * Navigate to a specific conversation by URL or ID
   * @param {string} conversationUrlOrId - Full URL or just the conversation ID
   */
  async goToConversation(conversationUrlOrId) {
    let url = conversationUrlOrId;

    // If it's just an ID, construct the full URL
    if (!conversationUrlOrId.startsWith('http')) {
      url = this.buildConversationUrl(conversationUrlOrId);
    }

    await this.page.goto(url);
    const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
    await this.page.waitForSelector(chatInputSelector, { timeout: 15000 });
    console.log(`  [Navigated to conversation: ${url}]`);
    return url;
  }

  /**
   * Build conversation URL from ID (override in subclasses)
   */
  buildConversationUrl(conversationId) {
    return `${this.url}/${conversationId}`;
  }

  /**
   * Get the current conversation URL
   */
  async getCurrentConversationUrl() {
    return this.page.url();
  }

  /**
   * Disconnect
   */
  async disconnect() {
    await this.browser.disconnect();
    this.connected = false;
  }
}

/**
 * Claude Chat Interface
 */
export class ClaudeInterface extends ChatInterface {
  constructor(config = {}) {
    super({
      name: 'claude',
      url: 'https://claude.ai',
      selectors: {
        chatInput: '[contenteditable="true"]',
        sendButton: 'button[type="submit"]',
        responseContainer: 'div.grid.standard-markdown:has(> .font-claude-response-body)',
        newChatButton: 'button[aria-label="New chat"]',
        thinkingIndicator: '[class*="thinking"], [class*="loading"]',
        toolsMenuButton: '#input-tools-menu-trigger, [data-testid="input-menu-tools"]',
        researchToggle: '[data-testid*="research"], button:has-text("Research")',
        // File attachment selectors
        fileInput: 'input[type="file"]',
        attachmentButton: 'button[aria-label*="Attach"], button[data-testid*="attach"]'
      },
      ...config
    });
  }

  /**
   * Select Claude model (e.g., "Opus 4.5", "Sonnet 4.5", "Haiku 4.5")
   *
   * ⚠️ UNVERIFIED ACTION - Model selection MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify the model actually changed in the UI.
   * ALWAYS check the returned screenshot to verify model selected.
   *
   * @param {string} modelName - Model name to select (e.g., "Opus 4.5", "Sonnet 4.5", "Haiku 4.5")
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot: string, automationCompleted: boolean }
   */
  async selectModel(modelName = "Opus 4.5", options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-claude-${sessionId}-model-selected.png`;

    console.log(`[claude] selectModel(${modelName})`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click model selector dropdown button
    const modelBtn = await this.page.waitForSelector('[data-testid="model-selector-dropdown"]', { timeout: 5000 });
    await modelBtn.click();
    await this.page.waitForTimeout(400);

    // Find and click the model menu item
    const modelItem = this.page.locator(`div[role="menuitem"]:has-text("${modelName}")`).first();
    const itemExists = await modelItem.count() > 0;

    if (!itemExists) {
      await this.page.keyboard.press('Escape');
      throw new Error(`Model "${modelName}" not found in model selector menu`);
    }

    await modelItem.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      modelName
    };
  }

  /**
   * ATOMIC ACTION: Attach file (Claude-specific override)
   * Uses + menu instead of direct attach button
   *
   * ⚠️ UNVERIFIED ACTION - File attachment MUST be confirmed via screenshot
   * This method only confirms automation steps completed without errors.
   * It does NOT verify the file actually appeared in the UI attachment area.
   * ALWAYS check the returned screenshot to verify file is visible in input.
   *
   * @param {string} filePath - Absolute path to file
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot: string, automationCompleted: boolean, filePath: string }
   * @throws {Error} If + menu or file attachment fails
   */
  async attachFile(filePath, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-file-attached.png`;

    console.log(`[${this.name}] attachFile(${filePath})`);

    // Validate file exists
    try {
      await import('fs/promises').then(fs => fs.access(filePath));
    } catch {
      throw new Error(`File not found: ${filePath}`);
    }

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click + menu
    const plusBtn = await this.page.waitForSelector('[data-testid="input-menu-plus"]', { timeout: 5000 });
    await plusBtn.click();
    await this.page.waitForTimeout(500);

    // Click "Upload a file"
    const menuItem = await this.page.waitForSelector('text="Upload a file"', { timeout: 5000 });
    await menuItem.click();
    console.log(`  ✓ Clicked "Upload a file"`);
    await this.page.waitForTimeout(1500); // Wait for file picker

    // Use osascript to navigate file picker with Cmd+Shift+G
    const dir = filePath.substring(0, filePath.lastIndexOf('/'));
    const filename = filePath.substring(filePath.lastIndexOf('/') + 1);

    // Cmd+Shift+G to open "Go to folder"
    const browserName = this._getBrowserName();
    const cmdShiftG = `tell application "System Events" to tell process "${browserName}" to keystroke "g" using {command down, shift down}`;
    await this.bridge.runScript(cmdShiftG);
    await this.page.waitForTimeout(500);

    // Type directory path
    await this.bridge.type(dir);
    await this.page.waitForTimeout(300);

    // Press Enter to navigate
    await this.bridge.pressKey('return');
    await this.page.waitForTimeout(1000);

    // Type filename to select it
    await this.bridge.type(filename);
    await this.page.waitForTimeout(300);

    // Press Enter to open/attach
    await this.bridge.pressKey('return');
    console.log(`  ✓ Automation completed - VERIFY FILE IN SCREENSHOT`);

    // Capture screenshot
    await this.page.waitForTimeout(1500); // Wait for file to appear
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      filePath
    };
  }

  /**
   * Enable or disable Research mode
   * @param {boolean} enabled - Whether to enable Research mode
   */
  async setResearchMode(enabled = true) {
    // Click tools menu button to open the menu
    const toolsBtn = await this.page.$(this.selectors.toolsMenuButton);
    if (!toolsBtn) {
      throw new Error('Tools menu button not found');
    }
    await toolsBtn.click();
    await this.page.waitForTimeout(400);

    // Find the Research button using locator (more reliable for text matching)
    const researchBtn = this.page.locator('button:has-text("Research")').first();
    const btnExists = await researchBtn.count() > 0;

    if (!btnExists) {
      await this.page.keyboard.press('Escape');
      throw new Error('Research option not found in tools menu');
    }

    // Check current toggle state via the input checkbox
    const toggleInput = this.page.locator('button:has-text("Research") input[role="switch"]').first();
    const isChecked = await toggleInput.isChecked();
    const shouldToggle = (enabled && !isChecked) || (!enabled && isChecked);

    if (shouldToggle) {
      await researchBtn.click();
      console.log(`  [Research mode ${enabled ? 'enabled' : 'disabled'}]`);
    } else {
      console.log(`  [Research mode already ${enabled ? 'enabled' : 'disabled'}]`);
    }

    // Close menu by pressing Escape
    await this.page.keyboard.press('Escape');
    await this.page.waitForTimeout(200);
    return true;
  }

  /**
   * Download artifact from Claude Chat response
   * Detects Download button and downloads the artifact file
   *
   * @param {Object} options - { downloadPath, timeout }
   * @returns {Object} { downloaded: boolean, filePath: string|null, fileName: string|null }
   */
  async downloadArtifact(options = {}) {
    const downloadPath = options.downloadPath || '/tmp';
    const timeout = options.timeout || 10000;

    console.log(`[${this.name}] downloadArtifact()`);

    // Check if Download button exists
    try {
      const downloadBtn = await this.page.waitForSelector('button[aria-label="Download"]', {
        timeout,
        state: 'visible'
      });

      if (!downloadBtn) {
        console.log('  ✗ No Download button found');
        return { downloaded: false, filePath: null, fileName: null };
      }

      console.log('  ✓ Download button found');

      // Set up download handler
      const downloadPromise = this.page.waitForEvent('download', { timeout: 30000 });

      // Click download button
      await downloadBtn.click();
      console.log('  ✓ Clicked Download button');

      // Wait for download to start
      const download = await downloadPromise;
      const fileName = download.suggestedFilename();
      const filePath = `${downloadPath}/${fileName}`;

      // Save to specified path
      await download.saveAs(filePath);
      console.log(`  ✓ Downloaded → ${filePath}`);

      return {
        downloaded: true,
        filePath,
        fileName
      };

    } catch (e) {
      if (e.message.includes('Timeout')) {
        console.log('  ✗ No Download button found (timeout)');
        return { downloaded: false, filePath: null, fileName: null };
      }
      throw e;
    }
  }

  async waitForResponse(timeout = 300000) {
    // Claude can take longer with Extended Thinking
    const startTime = Date.now();

    // Wait for thinking indicator to appear (if using Extended Thinking)
    try {
      await this.page.waitForSelector(this.selectors.thinkingIndicator, { timeout: 5000 });
      console.log('  [Claude is thinking deeply...]');

      // Wait for thinking to complete
      await this.page.waitForSelector(this.selectors.thinkingIndicator, {
        state: 'hidden',
        timeout: timeout - 5000
      });
    } catch {
      // No thinking indicator, proceed normally
    }

    // Now wait for response
    return await super.waitForResponse(timeout - (Date.now() - startTime));
  }

  async newConversation() {
    try {
      const newChatBtnSelector = await this._getSelector('new_chat_button', this.selectors.newChatButton);
      const newChatBtn = await this.page.$(newChatBtnSelector);
      if (newChatBtn) {
        await newChatBtn.click();
        await this.page.waitForTimeout(1000);
        return true;
      }
    } catch {
      // Navigate to home
      await this.page.goto('https://claude.ai/new');
      await this.page.waitForTimeout(1000);
    }
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://claude.ai/chat/${conversationId}`;
  }

  _getNewChatUrl() {
    return 'https://claude.ai/new';
  }

  _extractConversationId(url) {
    // Extract from URL like https://claude.ai/chat/abc-def-123
    const match = url.match(/\/chat\/([a-f0-9-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Attach file using human-like Finder navigation
   */
  async attachFileHumanLike(filePath) {
    console.log(`  [Claude: Attaching file "${filePath}"]`);

    // Validate file exists FIRST
    try {
      await import('fs/promises').then(fs => fs.access(filePath));
    } catch {
      throw new Error(`File not found: ${filePath}`);
    }

    // CRITICAL: Bring this tab to front before focusing Chrome
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click + menu
    console.log(`  [${this.name}: Clicking + menu]`);
    await this.page.click('[data-testid="input-menu-plus"]');
    await this.page.waitForTimeout(500);

    // Click "Upload a file"
    console.log(`  [${this.name}: Clicking "Upload a file"]`);
    const menuItem = await this.page.waitForSelector('text="Upload a file"', { timeout: 5000 });
    await menuItem.click();
    await this.page.waitForTimeout(1500);

    // Use shared Finder navigation
    await this._navigateFinderDialog(filePath);

    console.log(`  [${this.name}: Attachment complete]`);
    return true;
  }
}

/**
 * ChatGPT Interface
 */
export class ChatGPTInterface extends ChatInterface {
  constructor(config = {}) {
    super({
      name: 'chatgpt',
      url: 'https://chatgpt.com',
      selectors: {
        chatInput: '#prompt-textarea',
        sendButton: 'button[data-testid="send-button"]',
        responseContainer: '[data-message-author-role="assistant"]',
        newChatButton: 'nav button:first-child',
        thinkingIndicator: '.result-thinking, [class*="thinking"]',
        // File attachment selectors
        fileInput: 'input[type="file"]',
        attachmentButton: 'button[aria-label*="Attach"], button[data-testid*="attach"]'
      },
      ...config
    });
  }

  async newConversation() {
    console.log(`[${this.name}] Starting new conversation...`);

    // Try to click the new chat button
    try {
      // First check if sidebar is visible - look for the new chat button
      const newChatBtn = await this.page.$('a[data-testid="create-new-chat-button"]');

      if (!newChatBtn) {
        // Sidebar might be collapsed - try to expand it
        console.log(`  [${this.name}] New chat button not found - checking for collapsed sidebar`);
        const sidebarToggle = await this.page.$('button[aria-label*="sidebar"], button[aria-label*="menu"]');
        if (sidebarToggle) {
          console.log(`  [${this.name}] Clicking sidebar toggle`);
          await sidebarToggle.click();
          await this.page.waitForTimeout(500);
        }
      }

      // Try again after potential sidebar expansion
      const newChatBtnRetry = await this.page.$('a[data-testid="create-new-chat-button"]');
      if (newChatBtnRetry) {
        console.log(`  [${this.name}] Clicking new chat button`);
        await newChatBtnRetry.click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ New chat button clicked`);
        return true;
      }

      // Alternative selector: a[href="/"] containing "New chat"
      const newChatLink = await this.page.evaluateHandle(() => {
        const links = Array.from(document.querySelectorAll('a[href="/"]'));
        return links.find(link => link.textContent.includes('New chat'));
      });

      if (newChatLink && newChatLink.asElement()) {
        console.log(`  [${this.name}] Clicking new chat link (alternative selector)`);
        await newChatLink.asElement().click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ New chat link clicked`);
        return true;
      }

      console.log(`  [${this.name}] New chat button not found - falling back to URL navigation`);
    } catch (error) {
      console.log(`  [${this.name}] Button click failed: ${error.message} - falling back to URL navigation`);
    }

    // Fallback: navigate to home
    console.log(`  [${this.name}] Navigating to home URL`);
    await this.page.goto('https://chatgpt.com');
    await this.page.waitForTimeout(1000);
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://chatgpt.com/c/${conversationId}`;
  }

  _getNewChatUrl() {
    // ChatGPT home auto-creates new conversation
    return 'https://chatgpt.com';
  }

  _extractConversationId(url) {
    // Extract from URL like https://chatgpt.com/c/abc123xyz
    const match = url.match(/\/c\/([a-zA-Z0-9-]+)/);
    return match ? match[1] : null;
  }

  /**
   * ATOMIC ACTION: Select AI model (ChatGPT-specific)
   *
   * @param {string} modelName - Model name: "Auto", "Instant", "Thinking", "Pro", or "GPT-4o" (legacy)
   * @param {boolean} isLegacy - Whether to access model from Legacy submenu (e.g., for GPT-4o)
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot, automationCompleted, modelName }
   */
  async selectModel(modelName = "Auto", isLegacy = false, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-chatgpt-${sessionId}-model-selected.png`;

    console.log(`[chatgpt] selectModel(${modelName}${isLegacy ? ', legacy' : ''}) - DISABLED`);
    console.log(`  ChatGPT model selection disabled - using Auto mode`);
    console.log(`  For thinking: use Deep Research mode via setMode() instead`);

    // Just bring tab to front and take screenshot
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      modelName: 'Auto (selection disabled)'
    };
  }

  /**
   * ATOMIC ACTION: Set mode (ChatGPT-specific)
   * Enables special modes like Deep research, Agent mode, Web search, or GitHub
   *
   * @param {string} modeName - Mode: "Deep research", "Agent mode", "Web search", or "GitHub"
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot, automationCompleted, mode }
   */
  async setMode(modeName, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-chatgpt-${sessionId}-mode-set.png`;

    console.log(`[chatgpt] setMode(${modeName})`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click + button
    const plusBtn = this.page.locator('[data-testid="composer-plus-btn"]').first();
    await plusBtn.waitFor({ state: 'attached', timeout: 5000 });
    await plusBtn.click();  // Use regular click, not dispatchEvent
    await this.page.waitForTimeout(800);

    // Click mode option
    const modeItem = this.page.locator(`text="${modeName}"`).first();
    const itemExists = await modeItem.count() > 0;

    if (!itemExists) {
      await this.page.keyboard.press('Escape');
      throw new Error(`Mode "${modeName}" not found in + menu`);
    }

    await modeItem.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      mode: modeName
    };
  }
}

/**
 * Gemini Interface
 */
export class GeminiInterface extends ChatInterface {
  constructor(config = {}) {
    super({
      name: 'gemini',
      url: 'https://gemini.google.com',
      selectors: {
        chatInput: '.ql-editor[contenteditable="true"], [aria-label="Enter a prompt here"]',
        sendButton: 'button[aria-label="Send message"]',
        responseContainer: 'message-content .markdown',
        newChatButton: 'button[aria-label="New chat"]',
        // File attachment selectors
        fileInput: 'input[type="file"]',
        attachmentButton: 'button[aria-label*="Upload"], button[aria-label*="Add"]'
      },
      ...config
    });
  }

  async newConversation() {
    console.log(`[${this.name}] Starting new conversation...`);

    // Try to click the new chat button
    try {
      // Look for the new chat button with text content
      const newChatBtn = await this.page.evaluateHandle(() => {
        const spans = Array.from(document.querySelectorAll('span[data-test-id="side-nav-action-button-content"]'));
        return spans.find(span => span.textContent.includes('New chat'));
      });

      if (!newChatBtn || !newChatBtn.asElement()) {
        // Sidebar might be collapsed - try to find and click menu/sidebar toggle
        console.log(`  [${this.name}] New chat button not found - checking for collapsed sidebar`);
        const menuBtn = await this.page.$('button[aria-label*="menu"], button[aria-label*="sidebar"]');
        if (menuBtn) {
          console.log(`  [${this.name}] Clicking menu toggle`);
          await menuBtn.click();
          await this.page.waitForTimeout(500);
        }
      }

      // Try again after potential sidebar expansion
      const newChatBtnRetry = await this.page.evaluateHandle(() => {
        const spans = Array.from(document.querySelectorAll('span[data-test-id="side-nav-action-button-content"]'));
        const newChatSpan = spans.find(span => span.textContent.includes('New chat'));
        // Return the button parent, not the span
        return newChatSpan ? newChatSpan.closest('button') : null;
      });

      if (newChatBtnRetry && newChatBtnRetry.asElement()) {
        console.log(`  [${this.name}] Clicking new chat button`);
        await newChatBtnRetry.asElement().click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ New chat button clicked`);
        await this.dismissOverlays();
        return true;
      }

      // Alternative: text-based selection
      const newChatTextBtn = await this.page.evaluateHandle(() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        return buttons.find(btn => btn.textContent.includes('New chat'));
      });

      if (newChatTextBtn && newChatTextBtn.asElement()) {
        console.log(`  [${this.name}] Clicking new chat button (text-based)`);
        await newChatTextBtn.asElement().click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ New chat button clicked`);
        await this.dismissOverlays();
        return true;
      }

      console.log(`  [${this.name}] New chat button not found - falling back to URL navigation`);
    } catch (error) {
      console.log(`  [${this.name}] Button click failed: ${error.message} - falling back to URL navigation`);
    }

    // Fallback: navigate to home
    console.log(`  [${this.name}] Navigating to home URL`);
    await this.page.goto('https://gemini.google.com/app');
    await this.page.waitForTimeout(1000);
    await this.dismissOverlays();
    return true;
  }

  /**
   * Dismiss any overlay popups (promotional banners, etc.)
   * Gemini often shows promotional overlays that block the input area
   */
  async dismissOverlays() {
    console.log('  [Gemini] Attempting to dismiss overlays...');

    // Try multiple approaches to close overlays
    try {
      // Approach 1: Click the X button on promotional banner
      const closeSelectors = [
        'button[aria-label="Close"]',
        'button[aria-label="Dismiss"]',
        '.cdk-overlay-container button mat-icon[fonticon="close"]',
        '.cdk-overlay-backdrop',
        '[aria-label="Close promotional banner"]'
      ];

      for (const selector of closeSelectors) {
        const closeButton = await this.page.$(selector);
        if (closeButton) {
          await closeButton.click({ force: true });
          console.log(`  [Gemini] Clicked close button: ${selector}`);
          await this.page.waitForTimeout(300);
          break;
        }
      }
    } catch {
      // No overlay button found
    }

    // Approach 2: Press Escape multiple times via xdotool (more reliable)
    try {
      await this.bridge.focusApp(this._getBrowserName());
      await this.bridge.runCommand('xdotool key Escape');
      await this.page.waitForTimeout(200);
      await this.bridge.runCommand('xdotool key Escape');
      await this.page.waitForTimeout(200);
      console.log('  [Gemini] Pressed Escape via xdotool');
    } catch (e) {
      console.log('  [Gemini] Escape key failed:', e.message);
    }

    // Approach 3: Click in an empty area to dismiss any popover
    try {
      // Click at top-left corner of the page (usually empty area)
      await this.bridge.clickAt(50, 50);
      await this.page.waitForTimeout(200);
    } catch {
      // Ignore
    }
  }

  /**
   * Override prepareInput to use xdotool click (bypasses overlay blocking)
   * Gemini has promotional overlays that block Playwright's click() method
   */
  async prepareInput(options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-focused.png`;

    console.log(`[${this.name}] prepareInput() - using xdotool to bypass overlays`);

    // Dismiss overlays first
    await this.dismissOverlays();

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(100);

    // Focus the browser window using xdotool
    await this.bridge.focusApp(this._getBrowserName());

    // Find the input element and get its coordinates
    const chatInputSelector = await this._getSelector('message_input', this.selectors.chatInput);
    const input = await this.page.waitForSelector(chatInputSelector, { timeout: 10000 });
    const box = await input.boundingBox();

    if (box) {
      // Use xdotool click (bypasses overlay blocking)
      const windowInfo = await this.page.evaluate(() => ({
        screenX: window.screenX,
        screenY: window.screenY,
        outerHeight: window.outerHeight,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        innerWidth: window.innerWidth
      }));

      const chromeHeight = windowInfo.outerHeight - windowInfo.innerHeight;
      const chromeWidth = windowInfo.outerWidth - windowInfo.innerWidth;

      const screenX = windowInfo.screenX + (chromeWidth / 2) + box.x + (box.width / 2);
      const screenY = windowInfo.screenY + chromeHeight + box.y + (box.height / 2);

      console.log(`  [Gemini] Clicking input at screen coords (${Math.round(screenX)}, ${Math.round(screenY)})`);
      await this.bridge.clickAt(Math.round(screenX), Math.round(screenY));
      await this.page.waitForTimeout(200);
    } else {
      // Fallback to Playwright click with force
      await input.click({ force: true });
      await this.page.waitForTimeout(200);
    }

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Automation completed - VERIFY FOCUS IN SCREENSHOT`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  buildConversationUrl(conversationId) {
    return `https://gemini.google.com/app/${conversationId}`;
  }

  _getNewChatUrl() {
    // Gemini app home creates new conversation
    return 'https://gemini.google.com/app';
  }

  _extractConversationId(url) {
    // Extract from URL like https://gemini.google.com/app/abc123def456
    const match = url.match(/\/app\/([a-f0-9]+)/);
    return match ? match[1] : null;
  }

  /**
   * Attach file (phase script interface)
   * Wraps attachFileHumanLike() with screenshot capture
   *
   * ⚠️ UNVERIFIED ACTION - File attachment MUST be confirmed via screenshot
   * See base class documentation for verification requirements.
   */
  async attachFile(filePath, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-file-attached.png`;

    console.log(`[${this.name}] attachFile(${filePath})`);

    // Use the tested human-like attachment method
    await this.attachFileHumanLike(filePath);

    // Capture screenshot after attachment
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      filePath
    };
  }

  /**
   * Attach file using human-like Finder navigation
   */
  async attachFileHumanLike(filePath) {
    console.log(`  [Gemini: Attaching file "${filePath}"]`);

    // Validate file exists FIRST
    try {
      await import('fs/promises').then(fs => fs.access(filePath));
    } catch {
      throw new Error(`File not found: ${filePath}`);
    }

    // CRITICAL: Bring this tab to front before focusing Chrome
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Step 1: Click "Open upload file menu" button to open the menu
    console.log(`  [${this.name}: Opening upload file menu]`);

    // Try multiple selectors as Gemini's UI changes frequently
    const menuSelectors = [
      'button[aria-label="Open upload file menu"]',
      'button[aria-label="Attach files"]',
      'button[data-test-id="upload-menu-button"]',
      'button[aria-label*="Upload"]',
      'button svg[data-icon-name="attachment_24px"]'  // Sometimes identified by icon
    ];

    let menuBtn = null;
    for (const selector of menuSelectors) {
      try {
        menuBtn = await this.page.waitForSelector(selector, { timeout: 1000 });
        if (menuBtn) {
          console.log(`  [${this.name}: Found menu button: ${selector}]`);
          break;
        }
      } catch {
        // Continue to next selector
      }
    }

    if (!menuBtn) {
      throw new Error('Could not find Gemini upload menu button');
    }

    await menuBtn.click();
    await this.page.waitForTimeout(500);

    // Step 2: Click "Upload files" in the menu
    console.log(`  [${this.name}: Clicking Upload files]`);

    const uploadSelectors = [
      'button[data-test-id="local-images-files-uploader-button"]',
      'button:has-text("Upload files")',
      'button:has-text("Upload from computer")',
      '[role="menuitem"]:has-text("Upload")',
      'div[role="menuitem"]:has-text("Local files")'
    ];

    let uploadBtn = null;
    for (const selector of uploadSelectors) {
      try {
        uploadBtn = await this.page.waitForSelector(selector, { timeout: 1000 });
        if (uploadBtn) {
          console.log(`  [${this.name}: Found upload item: ${selector}]`);
          break;
        }
      } catch {
        // Continue to next selector
      }
    }

    if (!uploadBtn) {
      throw new Error('Could not find Gemini upload menu item');
    }

    await uploadBtn.click();
    await this.page.waitForTimeout(1500);

    // Use shared Finder navigation
    await this._navigateFinderDialog(filePath);

    console.log(`  [${this.name}: Attachment complete]`);
    return true;
  }

  /**
   * ATOMIC ACTION: Select AI model (Gemini-specific)
   *
   * @param {string} modelName - Model name (e.g., "Thinking with 3 Pro", "Thinking")
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot, automationCompleted, modelName }
   */
  async selectModel(modelName = "Thinking", options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-gemini-${sessionId}-model-selected.png`;

    console.log(`[gemini] selectModel(${modelName})`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click model selector button
    const modelBtn = await this.page.waitForSelector('[data-test-id="bard-mode-menu-button"]', { timeout: 5000 });
    await modelBtn.click();
    await this.page.waitForTimeout(400);

    // Find and click the model menu item by text
    const modelItem = this.page.locator(`button[mat-menu-item]:has-text("${modelName}")`).first();
    const itemExists = await modelItem.count() > 0;

    if (!itemExists) {
      await this.page.keyboard.press('Escape');
      throw new Error(`Model "${modelName}" not found in model selector menu`);
    }

    await modelItem.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      modelName
    };
  }

  /**
   * ATOMIC ACTION: Set mode (Gemini-specific)
   * Enables special modes like Deep Research or Deep Think
   *
   * @param {string} modeName - Mode: "Deep Research" or "Deep Think"
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot, automationCompleted, mode }
   */
  async setMode(modeName, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-gemini-${sessionId}-mode-set.png`;

    console.log(`[gemini] setMode(${modeName})`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click toolbox drawer button to open modes menu
    const drawerBtn = await this.page.waitForSelector('button.toolbox-drawer-button', { timeout: 5000 });
    await drawerBtn.click();
    await this.page.waitForTimeout(400);

    // Click mode option by text
    const modeItem = this.page.locator(`button[mat-list-item]:has-text("${modeName}")`).first();
    const itemExists = await modeItem.count() > 0;

    if (!itemExists) {
      await this.page.keyboard.press('Escape');
      throw new Error(`Mode "${modeName}" not found in toolbox drawer menu`);
    }

    await modeItem.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      mode: modeName
    };
  }

  /**
   * Download artifact from Gemini conversation
   * @param {Object} options - Download options
   * @param {string} [options.format='markdown'] - Download format ('markdown' or 'html')
   * @param {string} [options.downloadPath='/tmp'] - Directory to save file
   * @param {number} [options.timeout=10000] - Timeout in ms
   * @returns {Promise<{filePath: string, screenshot: string, automationCompleted: boolean}>}
   */
  async downloadArtifact(options = {}) {
    const {
      format = 'markdown',
      downloadPath = '/tmp',
      timeout = 10000,
      sessionId = null
    } = options;

    console.log(`\n[Gemini] Downloading artifact (format: ${format})...`);
    const screenshotPath = await this.getScreenshotPath('download-artifact', sessionId);

    // Wait for and click asset card button
    console.log('  → Looking for asset card...');
    const assetCardBtn = await this.page.waitForSelector('[data-testid="asset-card-open-button"]', { timeout: 5000 });
    if (!assetCardBtn) {
      throw new Error('Asset card button not found');
    }
    await assetCardBtn.click();
    await this.page.waitForTimeout(1000);

    // Click Export button
    console.log('  → Clicking Export...');
    const exportBtn = await this.page.waitForSelector('text="Export"', { timeout: 5000 });
    if (!exportBtn) {
      throw new Error('Export button not found');
    }
    await exportBtn.click();
    await this.page.waitForTimeout(500);

    // Click appropriate download format
    const formatText = format === 'html' ? 'Download as HTML' : 'Download as Markdown';
    console.log(`  → Clicking "${formatText}"...`);
    const downloadBtn = await this.page.waitForSelector(`text="${formatText}"`, { timeout: 5000 });
    if (!downloadBtn) {
      throw new Error(`"${formatText}" button not found`);
    }

    // Set up download listener
    const downloadPromise = this.page.waitForEvent('download', { timeout });
    await downloadBtn.click();

    // Wait for download to complete
    console.log('  → Waiting for download...');
    const download = await downloadPromise;
    const fileName = download.suggestedFilename();
    const filePath = `${downloadPath}/${fileName}`;
    await download.saveAs(filePath);

    console.log(`  ✓ Downloaded → ${filePath}`);
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      filePath,
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  /**
   * Override waitForResponse to detect and click "Start research" button for Deep Research mode
   */
  async waitForResponse(timeout = 600000, options = {}) {
    const startTime = Date.now();
    const sessionId = options.sessionId || Date.now();

    console.log(`  [${this.name}: Checking for Deep Research Start button...]`);

    try {
      // Wait for either the Start Research button OR a normal response
      // This handles both Deep Research mode and regular conversations
      const startResearchButton = await this.page.waitForSelector(
        'button[data-test-id="confirm-button"][aria-label="Start research"]',
        { timeout: 10000, state: 'attached' }
      );

      if (startResearchButton) {
        console.log(`  [${this.name}: Deep Research plan ready - clicking Start research button]`);

        // Force-enable the button if it's disabled (Gemini keeps it disabled until some condition)
        await this.page.evaluate(() => {
          const button = document.querySelector('button[data-test-id="confirm-button"]');
          if (button && button.disabled) {
            console.log('  [Gemini]: Button was disabled, force-enabling...');
            button.disabled = false;
            button.classList.remove('mat-mdc-button-disabled');
            button.style.pointerEvents = 'auto';
          }
        });

        await this.page.waitForTimeout(500);
        await startResearchButton.click();
        await this.page.waitForTimeout(2000);
        console.log(`  [${this.name}: Research started, waiting for completion...]`);
      }
    } catch (err) {
      // No Start Research button found - this is a normal conversation
      console.log(`  [${this.name}: No Deep Research button - proceeding with normal response wait]`);
    }

    // Now use the base class waitForResponse with remaining time
    const elapsed = Date.now() - startTime;
    const remainingTimeout = timeout - elapsed;

    return await super.waitForResponse(remainingTimeout, options);
  }
}

/**
 * Grok Interface (grok.com - standalone, supports Heavy model)
 */
export class GrokInterface extends ChatInterface {
  constructor(config = {}) {
    super({
      name: 'grok',
      url: 'https://grok.com',
      selectors: {
        chatInput: 'textarea, [contenteditable="true"]',
        sendButton: 'button[type="submit"], button[aria-label*="send" i]',
        responseContainer: 'div.response-content-markdown',
        newChatButton: 'button[aria-label*="new" i], a[href="/"]',
        // File attachment selectors
        fileInput: 'input[type="file"]',
        attachmentButton: 'button[aria-label*="Attach"], button[aria-label*="upload" i]'
      },
      ...config
    });
  }

  async newConversation() {
    console.log(`[${this.name}] Starting new conversation...`);

    // Try to click the new chat button
    try {
      // Look for the new chat button/link in sidebar
      const newChatLink = await this.page.$('a[data-sidebar="menu-button"][href="/"]');

      if (!newChatLink) {
        // Sidebar might be collapsed - try to find and click sidebar toggle
        console.log(`  [${this.name}] New chat button not found - checking for collapsed sidebar`);
        const sidebarToggle = await this.page.$('button[aria-label*="sidebar"], button[aria-label*="menu"]');
        if (sidebarToggle) {
          console.log(`  [${this.name}] Clicking sidebar toggle`);
          await sidebarToggle.click();
          await this.page.waitForTimeout(500);
        }
      }

      // Try again after potential sidebar expansion
      const newChatLinkRetry = await this.page.$('a[data-sidebar="menu-button"][href="/"]');
      if (newChatLinkRetry) {
        console.log(`  [${this.name}] Clicking new chat link`);
        await newChatLinkRetry.click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ New chat link clicked`);
        return true;
      }

      // Alternative: text-based selection for "Chat" link with edit icon
      const chatLink = await this.page.evaluateHandle(() => {
        const links = Array.from(document.querySelectorAll('a[href="/"]'));
        return links.find(link => link.textContent.includes('Chat'));
      });

      if (chatLink && chatLink.asElement()) {
        console.log(`  [${this.name}] Clicking chat link (text-based)`);
        await chatLink.asElement().click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ Chat link clicked`);
        return true;
      }

      console.log(`  [${this.name}] New chat button not found - falling back to URL navigation`);
    } catch (error) {
      console.log(`  [${this.name}] Button click failed: ${error.message} - falling back to URL navigation`);
    }

    // Fallback: navigate to home
    console.log(`  [${this.name}] Navigating to home URL`);
    await this.page.goto('https://grok.com');
    await this.page.waitForTimeout(1000);
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://grok.com/chat/${conversationId}`;
  }

  _getNewChatUrl() {
    // Grok home creates new conversation
    return 'https://grok.com';
  }

  _extractConversationId(url) {
    // Extract from URL like https://grok.com/chat/abc-def-123
    const match = url.match(/\/chat\/([a-f0-9-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Attach file (phase script interface)
   * Wraps attachFileHumanLike() with screenshot capture
   *
   * ⚠️ UNVERIFIED ACTION - File attachment MUST be confirmed via screenshot
   * See base class documentation for verification requirements.
   */
  async attachFile(filePath, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-file-attached.png`;

    console.log(`[${this.name}] attachFile(${filePath})`);

    // Use the tested human-like attachment method
    await this.attachFileHumanLike(filePath);

    // Capture screenshot after attachment
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      filePath
    };
  }

  /**
   * Attach file using human-like Finder navigation
   */
  async attachFileHumanLike(filePath) {
    console.log(`  [Grok: Attaching file "${filePath}"]`);

    // Validate file exists FIRST
    try {
      await import('fs/promises').then(fs => fs.access(filePath));
    } catch {
      throw new Error(`File not found: ${filePath}`);
    }

    // CRITICAL: Bring this tab to front before focusing Chrome
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Step 1: Click "Attach" button to open menu
    console.log(`  [${this.name}: Opening Attach menu]`);
    const attachBtn = await this.page.waitForSelector('button[aria-label="Attach"]', { timeout: 5000 });
    await attachBtn.click();
    await this.page.waitForTimeout(500);

    // Step 2: Click "Upload a file" menu item
    console.log(`  [${this.name}: Clicking Upload a file]`);
    const uploadItem = await this.page.waitForSelector('div[role="menuitem"]:has-text("Upload a file")', { timeout: 5000 });
    await uploadItem.click();
    await this.page.waitForTimeout(1500);

    // Use shared Finder navigation
    await this._navigateFinderDialog(filePath);

    console.log(`  [${this.name}: Attachment complete]`);
    return true;
  }

  /**
   * ATOMIC ACTION: Select AI model (Grok-specific)
   *
   * @param {string} modelName - Model name: "Grok 4.1", "Grok 4.1 Thinking", or "Grok 4 Heavy"
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot, automationCompleted, modelName }
   */
  async selectModel(modelName = "Grok 4.1", options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-grok-${sessionId}-model-selected.png`;

    console.log(`[grok] selectModel(${modelName})`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click model selector button using JavaScript (bypasses Playwright visibility checks)
    await this.page.waitForSelector('#model-select-trigger', { state: 'attached', timeout: 5000 });
    await this.page.evaluate(() => {
      const button = document.querySelector('#model-select-trigger');
      if (button) button.click();
    });
    await this.page.waitForTimeout(1000); // Wait for menu to fully render

    // Find and click the model menu item by text (flexible matching)
    const modelItem = this.page.locator(`[role="menuitem"]:has-text("${modelName}"), [role="option"]:has-text("${modelName}"), div:has-text("${modelName}"), button:has-text("${modelName}")`).first();
    const itemExists = await modelItem.count() > 0;

    if (!itemExists) {
      await this.page.keyboard.press('Escape');
      throw new Error(`Model "${modelName}" not found in model selector menu`);
    }

    await modelItem.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      modelName
    };
  }
}

/**
 * Perplexity Interface
 */
export class PerplexityInterface extends ChatInterface {
  constructor(config = {}) {
    super({
      name: 'perplexity',
      url: 'https://perplexity.ai',
      selectors: {
        chatInput: '#ask-input, [data-lexical-editor="true"]',
        sendButton: 'button[aria-label*="Submit"], button[type="submit"]',
        responseContainer: '[class*="prose"], [class*="answer"]',
        newChatButton: 'a[href="/"], button[aria-label*="New"]',
        // File attachment selectors (Pro feature)
        fileInput: 'input[type="file"]',
        attachmentButton: 'button[aria-label*="Attach"], button[aria-label*="Upload"]'
      },
      ...config
    });
  }

  async newConversation() {
    console.log(`[${this.name}] Starting new conversation...`);

    // Try to click the new thread button
    try {
      // Look for the new thread button
      const newThreadBtn = await this.page.$('button[data-testid="sidebar-new-thread"]');

      if (!newThreadBtn) {
        // Sidebar might be collapsed - try to find and click sidebar toggle
        console.log(`  [${this.name}] New thread button not found - checking for collapsed sidebar`);
        const sidebarToggle = await this.page.$('button[aria-label*="sidebar"], button[aria-label*="menu"]');
        if (sidebarToggle) {
          console.log(`  [${this.name}] Clicking sidebar toggle`);
          await sidebarToggle.click();
          await this.page.waitForTimeout(500);
        }
      }

      // Try again after potential sidebar expansion
      const newThreadBtnRetry = await this.page.$('button[data-testid="sidebar-new-thread"]');
      if (newThreadBtnRetry) {
        console.log(`  [${this.name}] Clicking new thread button`);
        await newThreadBtnRetry.click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ New thread button clicked`);
        return true;
      }

      // Alternative: aria-label based selection
      const newThreadAria = await this.page.$('button[aria-label="New Thread"]');
      if (newThreadAria) {
        console.log(`  [${this.name}] Clicking new thread button (aria-label)`);
        await newThreadAria.click();
        await this.page.waitForTimeout(1000);
        console.log(`  ✓ New thread button clicked`);
        return true;
      }

      console.log(`  [${this.name}] New thread button not found - falling back to URL navigation`);
    } catch (error) {
      console.log(`  [${this.name}] Button click failed: ${error.message} - falling back to URL navigation`);
    }

    // Fallback: navigate to home
    console.log(`  [${this.name}] Navigating to home URL`);
    await this.page.goto('https://perplexity.ai');
    await this.page.waitForTimeout(1000);
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://perplexity.ai/search/${conversationId}`;
  }

  _getNewChatUrl() {
    // Perplexity home is always new
    return 'https://perplexity.ai';
  }

  _extractConversationId(url) {
    // Extract from URL like https://perplexity.ai/search/abc-def-123
    const match = url.match(/\/search\/([a-f0-9-]+)/);
    return match ? match[1] : null;
  }

  /**
   * Get the latest response content (Perplexity-specific override)
   *
   * Perplexity wraps the full answer in a single prose container with many child elements.
   * The base selector '[class*="prose"]' matches ALL child elements (p, h1, h2, ul, etc.),
   * causing us to only get the last paragraph instead of the full response.
   *
   * This override targets the parent answer container specifically.
   */
  async getLatestResponse() {
    // More specific selector for the main answer container
    // Target the parent prose div, not child elements
    const answerSelector = 'div.prose.dark\\:prose-invert.inline.leading-relaxed, div[class*="prose"][class*="inline"]';

    const containers = await this.page.$$(answerSelector);
    if (containers.length === 0) {
      console.log('[Perplexity] No response container found, returning empty');
      return '';
    }

    // Get the last (most recent) answer container
    const lastContainer = containers[containers.length - 1];

    // Get full text content (this should include all child elements)
    const text = await lastContainer.textContent();

    console.log(`[Perplexity] Extracted response (${text.length} chars)`);
    return text;
  }

  /**
   * Enable Research mode (Pro Search) on Perplexity
   * Overrides base implementation with Perplexity-specific selector
   *
   * ⚠️ UNVERIFIED ACTION - UI state change MUST be confirmed via screenshot
   * See base class documentation for verification requirements.
   */
  async enableResearchMode(options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-research-mode.png`;

    console.log(`[${this.name}] enableResearchMode()`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Find and click research mode button - STRICT (no graceful handling)
    const button = await this.page.waitForSelector('button[value="research"]', { timeout: 5000 });
    await button.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }

  /**
   * Attach file (phase script interface)
   * Wraps attachFileHumanLike() with screenshot capture
   *
   * ⚠️ UNVERIFIED ACTION - File attachment MUST be confirmed via screenshot
   * See base class documentation for verification requirements.
   */
  async attachFile(filePath, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-${this.name}-${sessionId}-file-attached.png`;

    console.log(`[${this.name}] attachFile(${filePath})`);

    // Use the tested human-like attachment method
    await this.attachFileHumanLike(filePath);

    // Capture screenshot after attachment
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      filePath
    };
  }

  /**
   * Attach file using human-like Finder navigation
   */
  async attachFileHumanLike(filePath) {
    console.log(`  [Perplexity: Attaching file "${filePath}"]`);

    // Validate file exists FIRST
    try {
      await import('fs/promises').then(fs => fs.access(filePath));
    } catch {
      throw new Error(`File not found: ${filePath}`);
    }

    // CRITICAL: Bring this tab to front before focusing Chrome
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Step 1: Click attach-files-button to open menu
    console.log(`  [${this.name}: Opening attach files menu]`);
    const attachBtn = await this.page.waitForSelector('button[data-testid="attach-files-button"]', { timeout: 5000 });
    await attachBtn.click();
    await this.page.waitForTimeout(500);

    // Step 2: Click "Local files" menu item
    console.log(`  [${this.name}: Clicking Local files]`);
    const localFilesItem = await this.page.waitForSelector('div[role="menuitem"]:has-text("Local files")', { timeout: 5000 });
    await localFilesItem.click();
    await this.page.waitForTimeout(1500);

    // Use shared Finder navigation
    await this._navigateFinderDialog(filePath);

    console.log(`  [${this.name}: Attachment complete]`);
    return true;
  }

  /**
   * ATOMIC ACTION: Set mode (Perplexity-specific)
   * Selects one of the three available modes: Search, Research Pro, or Labs
   *
   * @param {string} modeValue - Mode value: "search", "research", or "studio"
   * @param {Object} options - { sessionId, screenshotPath }
   * @returns {Object} { screenshot, automationCompleted, mode }
   */
  async setMode(modeValue, options = {}) {
    const sessionId = options.sessionId || Date.now();
    const screenshotPath = options.screenshotPath || `/tmp/taey-perplexity-${sessionId}-mode-set.png`;

    console.log(`[perplexity] setMode(${modeValue})`);

    // Bring tab to front
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Click the mode button with the specified value attribute
    const modeBtn = await this.page.waitForSelector(`button[role="radio"][value="${modeValue}"]`, { timeout: 5000 });
    await modeBtn.click();
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);
    await this.page.waitForTimeout(500);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      screenshot: screenshotPath,
      automationCompleted: true,
      mode: modeValue
    };
  }

  /**
   * Download artifact from Perplexity conversation
   * @param {Object} options - Download options
   * @param {string} [options.format='markdown'] - Download format ('markdown' or 'html')
   * @param {string} [options.downloadPath='/tmp'] - Directory to save file
   * @param {number} [options.timeout=10000] - Timeout in ms
   * @returns {Promise<{filePath: string, screenshot: string, automationCompleted: boolean}>}
   */
  async downloadArtifact(options = {}) {
    const {
      format = 'markdown',
      downloadPath = '/tmp',
      timeout = 10000,
      sessionId = null
    } = options;

    console.log(`\n[Perplexity] Downloading artifact (format: ${format})...`);
    const screenshotPath = await this.getScreenshotPath('download-artifact', sessionId);

    // Wait for and click asset card button
    console.log('  → Looking for asset card...');
    const assetCardBtn = await this.page.waitForSelector('[data-testid="asset-card-open-button"]', { timeout: 5000 });
    if (!assetCardBtn) {
      throw new Error('Asset card button not found');
    }
    await assetCardBtn.click();
    await this.page.waitForTimeout(1000);

    // Click Export button
    console.log('  → Clicking Export...');
    const exportBtn = await this.page.waitForSelector('text="Export"', { timeout: 5000 });
    if (!exportBtn) {
      throw new Error('Export button not found');
    }
    await exportBtn.click();
    await this.page.waitForTimeout(500);

    // Click appropriate download format
    const formatText = format === 'html' ? 'Download as HTML' : 'Download as Markdown';
    console.log(`  → Clicking "${formatText}"...`);
    const downloadBtn = await this.page.waitForSelector(`text="${formatText}"`, { timeout: 5000 });
    if (!downloadBtn) {
      throw new Error(`"${formatText}" button not found`);
    }

    // Set up download listener
    const downloadPromise = this.page.waitForEvent('download', { timeout });
    await downloadBtn.click();

    // Wait for download to complete
    console.log('  → Waiting for download...');
    const download = await downloadPromise;
    const fileName = download.suggestedFilename();
    const filePath = `${downloadPath}/${fileName}`;
    await download.saveAs(filePath);

    console.log(`  ✓ Downloaded → ${filePath}`);
    console.log(`  ✓ Automation completed - VERIFY IN SCREENSHOT`);

    // Capture screenshot
    await this.screenshot(screenshotPath);
    console.log(`  ✓ Screenshot → ${screenshotPath}`);

    return {
      filePath,
      screenshot: screenshotPath,
      automationCompleted: true
    };
  }
}

/**
 * Factory function to get interface by name
 */
export function getInterface(name, config = {}) {
  const interfaces = {
    claude: ClaudeInterface,
    chatgpt: ChatGPTInterface,
    gemini: GeminiInterface,
    grok: GrokInterface,
    perplexity: PerplexityInterface
  };

  const InterfaceClass = interfaces[name.toLowerCase()];
  if (!InterfaceClass) {
    throw new Error(`Unknown interface: ${name}`);
  }

  return new InterfaceClass(config);
}

export default ChatInterface;
