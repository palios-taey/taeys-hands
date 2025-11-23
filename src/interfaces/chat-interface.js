/**
 * Chat Interface Abstraction - Unified API for AI Family chat UIs
 *
 * Abstracts the differences between Claude, ChatGPT, Gemini, and Grok
 * so Taey can orchestrate conversations across all of them.
 */

import BrowserConnector from '../core/browser-connector.js';
import OSABridge from '../core/osascript-bridge.js';
import fs from 'fs/promises';
import path from 'path';

export class ChatInterface {
  constructor(config = {}) {
    this.browser = new BrowserConnector(config.browser);
    this.osa = new OSABridge(config.mimesis);
    this.page = null;
    this.name = config.name || 'unknown';
    this.url = config.url;
    this.selectors = config.selectors || {};
    this.connected = false;
  }

  /**
   * Connect to this chat interface
   */
  async connect() {
    await this.browser.connect();
    this.page = await this.browser.getPage(this.name, this.url);
    this.connected = true;
    console.log(`✓ Connected to ${this.name}`);
    return this;
  }

  /**
   * Check if logged in (by looking for chat input)
   */
  async isLoggedIn() {
    try {
      await this.page.waitForSelector(this.selectors.chatInput, { timeout: 5000 });
      return true;
    } catch {
      return false;
    }
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

    // Find the file input element (usually hidden)
    const fileInputSelector = this.selectors.fileInput;
    if (!fileInputSelector) {
      throw new Error(`File attachments not supported for ${this.name}`);
    }

    // Try to find an existing file input, or click the attachment button to reveal one
    let fileInput = await this.page.$(fileInputSelector);

    if (!fileInput && this.selectors.attachmentButton) {
      // Click attachment button to potentially reveal file input
      const attachBtn = await this.page.$(this.selectors.attachmentButton);
      if (attachBtn) {
        await attachBtn.click();
        await this.page.waitForTimeout(500);
        fileInput = await this.page.$(fileInputSelector);
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
   * Send a message and wait for response
   */
  async sendMessage(message, options = {}) {
    const useHumanInput = options.humanLike !== false;
    const waitForResponse = options.waitForResponse !== false;
    const timeout = options.timeout || 120000; // 2 min default for long responses

    // Bring this tab to foreground (critical for osascript typing)
    await this.page.bringToFront();
    await this.page.waitForTimeout(100);

    // Focus the input
    const input = await this.page.waitForSelector(this.selectors.chatInput, { timeout: 10000 });
    await input.click();
    await this.page.waitForTimeout(200);

    // Type the message
    if (useHumanInput) {
      // Use osascript for human-like typing
      await this.osa.focusApp('Google Chrome');
      await this.osa.type(message);
    } else {
      // Direct injection (faster but detectable)
      await input.fill(message);
    }

    // Send the message
    await this.page.waitForTimeout(300);
    await this.osa.pressKey('return');

    if (!waitForResponse) {
      return { sent: true, response: null };
    }

    // Wait for response
    const response = await this.waitForResponse(timeout);
    return { sent: true, response };
  }

  /**
   * Wait for AI response to complete
   * @param {number} timeout - Max wait time in ms (default 1 hour for deep thinking modes)
   */
  async waitForResponse(timeout = 3600000) {
    const startTime = Date.now();
    const checkInterval = 1000; // Check every second
    const stabilityThreshold = 6; // 6 seconds of unchanged content = complete

    // Get initial response count
    const initialCount = (await this.page.$$(this.selectors.responseContainer)).length;

    // Wait for a new response to appear (up to 60 seconds to start)
    let newResponseFound = false;
    const initialWaitTimeout = 60000; // 60 seconds to start responding
    console.log(`  [Waiting for ${this.name} to start responding...]`);

    while (!newResponseFound && Date.now() - startTime < initialWaitTimeout) {
      const currentCount = (await this.page.$$(this.selectors.responseContainer)).length;
      if (currentCount > initialCount) {
        newResponseFound = true;
        console.log(`  [${this.name} started responding]`);
      } else {
        await this.page.waitForTimeout(checkInterval);
      }
    }

    if (!newResponseFound) {
      console.log(`  [Warning: ${this.name} hasn't started responding yet, continuing to wait...]`);
    }

    // Wait for streaming to complete (response stops changing)
    let lastContent = '';
    let unchangedCount = 0;
    let lastLogTime = Date.now();

    while (Date.now() - startTime < timeout) {
      const content = await this.getLatestResponse();

      if (content === lastContent && content.length > 0) {
        unchangedCount++;
        if (unchangedCount >= stabilityThreshold) {
          const elapsed = Math.round((Date.now() - startTime) / 1000);
          console.log(`  [${this.name} response complete after ${elapsed}s]`);
          return content;
        }
      } else {
        unchangedCount = 0;
        lastContent = content;

        // Log progress every 30 seconds
        if (Date.now() - lastLogTime > 30000) {
          const elapsed = Math.round((Date.now() - startTime) / 1000);
          console.log(`  [${this.name} still thinking... ${elapsed}s elapsed]`);
          lastLogTime = Date.now();
        }
      }

      await this.page.waitForTimeout(checkInterval);
    }

    const elapsed = Math.round((Date.now() - startTime) / 1000);
    console.log(`  [${this.name} response timeout after ${elapsed}s, returning partial]`);
    return lastContent;
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
    await this.page.waitForSelector(this.selectors.chatInput, { timeout: 15000 });
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
        responseContainer: '.font-claude-response-body',
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
      const newChatBtn = await this.page.$(this.selectors.newChatButton);
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
    await this.page.goto('https://chatgpt.com');
    await this.page.waitForTimeout(1000);
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://chatgpt.com/c/${conversationId}`;
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
        responseContainer: 'p[data-path-to-node]',
        newChatButton: 'button[aria-label="New chat"]',
        // File attachment selectors
        fileInput: 'input[type="file"]',
        attachmentButton: 'button[aria-label*="Upload"], button[aria-label*="Add"]'
      },
      ...config
    });
  }

  async newConversation() {
    await this.page.goto('https://gemini.google.com/app');
    await this.page.waitForTimeout(1000);
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://gemini.google.com/app/${conversationId}`;
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
    await this.page.goto('https://grok.com');
    await this.page.waitForTimeout(1000);
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://grok.com/chat/${conversationId}`;
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
    await this.page.goto('https://perplexity.ai');
    await this.page.waitForTimeout(1000);
    return true;
  }

  buildConversationUrl(conversationId) {
    return `https://perplexity.ai/search/${conversationId}`;
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
