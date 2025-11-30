/**
 * Example: Using SelectorRegistry in Platform Classes
 *
 * This file demonstrates how to integrate the SelectorRegistry
 * into platform automation classes for the v2 rebuild.
 */

import { SelectorRegistry } from './selector-registry.js';

// ============================================================================
// Example 1: Basic Platform Class
// ============================================================================

class ChatGPTPlatform {
  constructor(page) {
    this.page = page;
    this.registry = new SelectorRegistry();
    this.platform = 'chatgpt';
  }

  /**
   * Attach files to the conversation
   */
  async attachFiles(filePaths) {
    // Get selectors from registry
    const attachBtn = await this.registry.getSelector(this.platform, 'attach_button');
    const menuItem = await this.registry.getSelector(this.platform, 'menu_item_attach_files');

    // Click plus button to open menu
    await this.page.click(attachBtn);

    // Click "Add photos & files" menu item
    await this.page.click(menuItem);

    // Handle file dialog
    // ... file upload logic here
  }

  /**
   * Send a message
   */
  async sendMessage(message) {
    const inputSelector = await this.registry.getSelector(this.platform, 'message_input');
    const sendSelector = await this.registry.getSelector(this.platform, 'send_button');

    await this.page.fill(inputSelector, message);
    await this.page.click(sendSelector);
  }

  /**
   * Select a model
   */
  async selectModel(modelName) {
    const modelSelector = await this.registry.getSelector(this.platform, 'model_selector');

    // Click model selector dropdown
    await this.page.click(modelSelector);

    // Map model name to selector key
    const modelKey = `model_${modelName.toLowerCase()}`;
    const modelOption = await this.registry.getSelector(this.platform, modelKey);

    await this.page.click(modelOption);
  }

  /**
   * Enable Deep Research mode
   */
  async enableDeepResearch() {
    const attachBtn = await this.registry.getSelector(this.platform, 'attach_button');
    const deepResearchItem = await this.registry.getSelector(this.platform, 'menu_item_deep_research');

    await this.page.click(attachBtn);
    await this.page.click(deepResearchItem);
  }
}

// ============================================================================
// Example 2: Platform Class with Fallback Handling
// ============================================================================

class ClaudePlatform {
  constructor(page) {
    this.page = page;
    this.registry = new SelectorRegistry();
    this.platform = 'claude';
  }

  /**
   * Get element with fallback support
   */
  async getElement(key, timeout = 5000) {
    const def = await this.registry.getDefinition(this.platform, key);

    try {
      // Try primary selector first
      return await this.page.waitForSelector(def.primary, { timeout });
    } catch (error) {
      if (def.fallback) {
        console.log(`Primary selector failed for ${key}, trying fallback...`);
        return await this.page.waitForSelector(def.fallback, { timeout });
      }
      throw new Error(`Could not find element for ${key}: ${error.message}`);
    }
  }

  /**
   * Enable Extended Thinking mode
   */
  async enableExtendedThinking() {
    const toggle = await this.getElement('extended_thinking_toggle');

    // Check if already enabled
    const isEnabled = await toggle.evaluate(el => {
      const checkbox = el.querySelector('input[type="checkbox"]');
      return checkbox ? checkbox.checked : false;
    });

    if (!isEnabled) {
      await toggle.click();
    }
  }

  /**
   * Download artifact as Markdown
   */
  async downloadArtifact() {
    const downloadBtn = await this.getElement('download_artifact_button');
    await downloadBtn.click();

    const markdownOption = await this.getElement('download_as_markdown');
    await markdownOption.click();
  }
}

// ============================================================================
// Example 3: Gemini Platform with Force-Enable Pattern
// ============================================================================

class GeminiPlatform {
  constructor(page) {
    this.page = page;
    this.registry = new SelectorRegistry();
    this.platform = 'gemini';
  }

  /**
   * Start Deep Research mode (requires force-enable)
   */
  async startDeepResearch() {
    // Get the research button selector
    const btnSelector = await this.registry.getSelector(this.platform, 'start_research_button');

    // Force-enable the button (Gemini often disables it programmatically)
    await this.page.evaluate((selector) => {
      const button = document.querySelector(selector);
      if (button) {
        button.disabled = false;
        button.click();
      }
    }, btnSelector);

    console.log('Deep Research started (force-enabled)');
  }

  /**
   * Attach files using hidden upload button
   */
  async attachFiles(filePaths) {
    const uploadBtn = await this.registry.getSelector(this.platform, 'attach_button');
    await this.page.click(uploadBtn);

    // Use hidden file upload button
    const hiddenUpload = await this.registry.getSelector(this.platform, 'hidden_file_upload');
    const fileInput = await this.page.$(hiddenUpload + ' input[type="file"]');

    if (fileInput) {
      await fileInput.setInputFiles(filePaths);
    }
  }
}

// ============================================================================
// Example 4: Perplexity Platform (Mode Selection)
// ============================================================================

class PerplexityPlatform {
  constructor(page) {
    this.page = page;
    this.registry = new SelectorRegistry();
    this.platform = 'perplexity';
  }

  /**
   * Select mode (Search, Research, Labs)
   */
  async selectMode(mode) {
    const modeKey = `mode_${mode.toLowerCase()}`;
    const modeSelector = await this.registry.getSelector(this.platform, modeKey);

    // Click the radio button
    await this.page.click(modeSelector);

    console.log(`Mode set to: ${mode}`);
  }

  /**
   * Send message (uses textarea instead of contenteditable)
   */
  async sendMessage(message) {
    const inputSelector = await this.registry.getSelector(this.platform, 'message_input');
    const sendSelector = await this.registry.getSelector(this.platform, 'send_button');

    // Note: Perplexity uses <textarea>, not contenteditable div
    await this.page.fill(inputSelector, message);
    await this.page.click(sendSelector);
  }

  /**
   * Enable Pro Research mode
   */
  async enableProResearch() {
    await this.selectMode('research');
  }
}

// ============================================================================
// Example 5: Generic Platform Factory
// ============================================================================

class PlatformFactory {
  static async create(platform, page) {
    const registry = new SelectorRegistry();

    // Validate platform exists
    try {
      await registry.getPlatformConfig(platform);
    } catch (error) {
      throw new Error(`Invalid platform: ${platform}. ${error.message}`);
    }

    // Create appropriate platform class
    switch (platform) {
      case 'chatgpt':
        return new ChatGPTPlatform(page);
      case 'claude':
        return new ClaudePlatform(page);
      case 'gemini':
        return new GeminiPlatform(page);
      case 'perplexity':
        return new PerplexityPlatform(page);
      default:
        return new GenericPlatform(platform, page);
    }
  }
}

// ============================================================================
// Example 6: Generic Platform (works with any platform)
// ============================================================================

class GenericPlatform {
  constructor(platform, page) {
    this.platform = platform;
    this.page = page;
    this.registry = new SelectorRegistry();
  }

  async getSelector(key) {
    return await this.registry.getSelector(this.platform, key);
  }

  async getDefinition(key) {
    return await this.registry.getDefinition(this.platform, key);
  }

  async attachFiles(filePaths) {
    const selector = await this.getSelector('attach_button');
    await this.page.click(selector);
    // Platform-specific logic would go here
  }

  async sendMessage(message) {
    const input = await this.getSelector('message_input');
    const send = await this.getSelector('send_button');

    await this.page.fill(input, message);
    await this.page.click(send);
  }

  async startNewChat() {
    const selector = await this.getSelector('new_chat_button');
    await this.page.click(selector);
  }
}

// ============================================================================
// Example 7: MCP Tool Handler Integration
// ============================================================================

class MCPToolHandler {
  constructor() {
    this.registry = new SelectorRegistry();
    this.platforms = new Map();
  }

  /**
   * Handle taey_send_message MCP tool
   */
  async handleSendMessage({ sessionId, message, platform }) {
    // Get or create platform instance
    let platformInstance = this.platforms.get(sessionId);
    if (!platformInstance) {
      platformInstance = await PlatformFactory.create(platform, this.getPage(sessionId));
      this.platforms.set(sessionId, platformInstance);
    }

    // Send the message
    await platformInstance.sendMessage(message);

    return { success: true };
  }

  /**
   * Handle taey_attach_files MCP tool
   */
  async handleAttachFiles({ sessionId, filePaths, platform }) {
    let platformInstance = this.platforms.get(sessionId);
    if (!platformInstance) {
      platformInstance = await PlatformFactory.create(platform, this.getPage(sessionId));
      this.platforms.set(sessionId, platformInstance);
    }

    await platformInstance.attachFiles(filePaths);

    return { success: true };
  }

  // Mock method - would get actual page from session manager
  getPage(sessionId) {
    return {}; // Would return actual Playwright page
  }
}

// ============================================================================
// Export examples for reference
// ============================================================================

export {
  ChatGPTPlatform,
  ClaudePlatform,
  GeminiPlatform,
  PerplexityPlatform,
  PlatformFactory,
  GenericPlatform,
  MCPToolHandler
};
