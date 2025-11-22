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
   */
  async waitForResponse(timeout = 120000) {
    const startTime = Date.now();
    const checkInterval = 500;

    // Get initial response count
    const initialCount = (await this.page.$$(this.selectors.responseContainer)).length;

    // Wait for a new response to appear
    let newResponseFound = false;
    while (!newResponseFound && Date.now() - startTime < 30000) {
      const currentCount = (await this.page.$$(this.selectors.responseContainer)).length;
      if (currentCount > initialCount) {
        newResponseFound = true;
      } else {
        await this.page.waitForTimeout(checkInterval);
      }
    }

    // Wait for streaming to complete (response stops changing)
    let lastContent = '';
    let unchangedCount = 0;

    while (Date.now() - startTime < timeout) {
      const content = await this.getLatestResponse();

      if (content === lastContent && content.length > 0) {
        unchangedCount++;
        if (unchangedCount >= 4) { // 2 seconds of no changes
          return content;
        }
      } else {
        unchangedCount = 0;
        lastContent = content;
      }

      await this.page.waitForTimeout(checkInterval);
    }

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
        researchToggle: '[data-testid*="research"], button:has-text("Research")'
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
        thinkingIndicator: '.result-thinking, [class*="thinking"]'
      },
      ...config
    });
  }

  async newConversation() {
    await this.page.goto('https://chat.openai.com');
    await this.page.waitForTimeout(1000);
    return true;
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
        newChatButton: 'button[aria-label="New chat"]'
      },
      ...config
    });
  }

  async newConversation() {
    await this.page.goto('https://gemini.google.com/app');
    await this.page.waitForTimeout(1000);
    return true;
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
        responseContainer: 'p.break-words',
        newChatButton: 'button[aria-label*="new" i], a[href="/"]'
      },
      ...config
    });
  }

  async newConversation() {
    await this.page.goto('https://grok.com');
    await this.page.waitForTimeout(1000);
    return true;
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
        newChatButton: 'a[href="/"], button[aria-label*="New"]'
      },
      ...config
    });
  }

  async newConversation() {
    await this.page.goto('https://perplexity.ai');
    await this.page.waitForTimeout(1000);
    return true;
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
