/**
 * Selector Registry - Centralized UI Selector Management
 * 
 * All platform-specific selectors in one place with:
 * - Primary selectors
 * - Fallback selectors
 * - Descriptions for debugging
 * - Version tracking
 * 
 * When platforms update their UI, only this file needs to change.
 */

import { PlatformType, SelectorWithFallbacks } from '../../types.js';

// ============================================================================
// Selector Definitions
// ============================================================================

export interface PlatformSelectorConfig {
  // Input & Send
  chatInput: SelectorWithFallbacks;
  sendButton: SelectorWithFallbacks;
  
  // Model Selection
  modelSelector?: SelectorWithFallbacks;
  modelMenuItem?: (modelName: string) => string;
  
  // Mode Selection
  modeSelector?: SelectorWithFallbacks;
  modeMenuItem?: (modeName: string) => string;
  
  // File Attachment
  attachButton: SelectorWithFallbacks;
  uploadMenuItem: SelectorWithFallbacks;
  
  // Response Detection
  responseContainer: SelectorWithFallbacks;
  thinkingIndicator?: SelectorWithFallbacks;
  streamingClass?: string;
  
  // Artifact Download
  downloadButton?: SelectorWithFallbacks;
  exportMenu?: SelectorWithFallbacks;
  markdownOption?: SelectorWithFallbacks;
  
  // Platform Quirks
  overlayContainer?: string;
  closeOverlayButton?: SelectorWithFallbacks;
  startResearchButton?: SelectorWithFallbacks;
}

// ============================================================================
// Claude Selectors
// ============================================================================

const claudeSelectors: PlatformSelectorConfig = {
  chatInput: {
    primary: 'div[contenteditable="true"]',
    fallbacks: [
      '[data-testid="chat-input"]',
      '.ProseMirror[contenteditable="true"]',
    ],
    description: 'Claude chat input field (contenteditable div)',
  },
  
  sendButton: {
    primary: 'button[type="submit"]',
    fallbacks: [
      'button[aria-label*="Send"]',
      '[data-testid="send-button"]',
    ],
    description: 'Claude send message button',
  },
  
  modelSelector: {
    primary: 'button[data-testid="model-selector-dropdown"]',
    fallbacks: [
      '[aria-label="Model selector"]',
      'button:has-text("Opus")',
      'button:has-text("Sonnet")',
    ],
    description: 'Claude model selection dropdown',
  },
  
  modelMenuItem: (modelName: string) => `div[role="menuitem"]:has-text("${modelName}")`,
  
  modeSelector: {
    primary: '#input-tools-menu-trigger',
    fallbacks: [
      'button[aria-label="Tools"]',
      '[data-testid="tools-menu"]',
    ],
    description: 'Claude tools/modes menu trigger',
  },
  
  modeMenuItem: (modeName: string) => `button:has-text("${modeName}")`,
  
  attachButton: {
    primary: '[data-testid="input-menu-plus"]',
    fallbacks: [
      'button[aria-label="Add files"]',
      'button:has(svg[class*="plus"])',
    ],
    description: 'Claude plus menu button for attachments',
  },
  
  uploadMenuItem: {
    primary: 'text="Upload a file"',
    fallbacks: [
      '[role="menuitem"]:has-text("Upload")',
      'button:has-text("Upload a file")',
    ],
    description: 'Upload file menu item',
  },
  
  responseContainer: {
    primary: '[data-testid="assistant-message"]',
    fallbacks: [
      '.assistant-message',
      '[class*="AssistantMessage"]',
      'div[data-is-streaming]',
    ],
    description: 'Claude assistant response container',
  },
  
  thinkingIndicator: {
    primary: '[data-testid="thinking-indicator"]',
    fallbacks: [
      '.thinking-indicator',
      '[aria-label*="thinking"]',
    ],
    description: 'Claude Extended Thinking indicator',
  },
  
  streamingClass: 'data-is-streaming',
  
  downloadButton: {
    primary: 'button[aria-label="Download"]',
    fallbacks: [
      '[data-testid="download-button"]',
      'button:has(svg[class*="download"])',
    ],
    description: 'Claude artifact download button',
  },
};

// ============================================================================
// ChatGPT Selectors (Updated from CLEAN_SELECTORS.md)
// ============================================================================

const chatgptSelectors: PlatformSelectorConfig = {
  chatInput: {
    primary: 'div[contenteditable="true"]',
    fallbacks: [
      '#prompt-textarea',
      'textarea[data-id="root"]',
      '[data-testid="text-input"]',
    ],
    description: 'ChatGPT message input (contenteditable in composer)',
  },
  
  sendButton: {
    primary: 'button[data-testid="send-button"]',
    fallbacks: [
      'button[aria-label*="Send"]',
      'button:has(svg[class*="send"])',
    ],
    description: 'ChatGPT send button',
  },
  
  // Model selection - now uses model-switcher-dropdown-button
  modelSelector: {
    primary: 'button[data-testid="model-switcher-dropdown-button"]',
    fallbacks: [
      'button[aria-label*="Model selector"]',
    ],
    description: 'ChatGPT model selector dropdown',
  },
  
  // Text-based model selection
  modelMenuItem: (modelName: string) => `text="${modelName}"`,
  
  modeSelector: {
    primary: 'button[data-testid="composer-plus-btn"]',
    fallbacks: [
      'button[aria-label="Add files and more"]',
      'button:has(svg[class*="plus"])',
    ],
    description: 'ChatGPT plus menu for modes',
  },
  
  // Text-based mode selection: "Deep research", "Agent mode", "Web search", "GitHub"
  modeMenuItem: (modeName: string) => `text="${modeName}"`,
  
  attachButton: {
    primary: 'button[data-testid="composer-plus-btn"]',
    fallbacks: [
      'button[aria-label="Add files and more"]',
    ],
    description: 'ChatGPT plus menu button',
  },
  
  uploadMenuItem: {
    primary: 'text="Add photos & files"',
    fallbacks: [
      '[role="menuitem"]:has-text("photos")',
      '[role="menuitem"]:has-text("files")',
    ],
    description: 'Upload files menu item',
  },
  
  responseContainer: {
    primary: '[data-message-author-role="assistant"]',
    fallbacks: [
      '.markdown.prose',
      '[class*="agent-turn"]',
    ],
    description: 'ChatGPT assistant response',
  },
  
  thinkingIndicator: {
    primary: '[data-testid="thinking"]',
    fallbacks: [
      '.thinking-content',
    ],
    description: 'ChatGPT thinking indicator',
  },
};

// ============================================================================
// Gemini Selectors (Updated from CLEAN_SELECTORS.md)
// ============================================================================

const geminiSelectors: PlatformSelectorConfig = {
  chatInput: {
    primary: 'div.ql-editor[contenteditable="true"][aria-label="Enter a prompt here"]',
    fallbacks: [
      '.ql-editor[contenteditable="true"]',
      'div[aria-label="Enter a prompt here"]',
      '[contenteditable="true"][role="textbox"]',
    ],
    description: 'Gemini Quill editor input',
  },
  
  sendButton: {
    primary: 'button[aria-label="Send message"]',
    fallbacks: [
      'button:has(mat-icon[fonticon="send"])',
      '[data-test-id="send-button"]',
    ],
    description: 'Gemini send button',
  },
  
  modelSelector: {
    primary: 'button[data-test-id="bard-mode-menu-button"]',
    fallbacks: [
      '[aria-label*="model"]',
      'button:has-text("Thinking")',
    ],
    description: 'Gemini model selector',
  },
  
  // Model items with specific data-test-id patterns
  modelMenuItem: (modelName: string) => {
    const modelMap: Record<string, string> = {
      'Thinking with 3 Pro': 'button[data-test-id="bard-mode-option-thinkingwith3pro"]',
      'Thinking': 'button[data-test-id="bard-mode-option-thinking"]',
    };
    return modelMap[modelName] || `button[mat-menu-item]:has-text("${modelName}")`;
  },
  
  modeSelector: {
    primary: 'button[aria-label="Tools"]',
    fallbacks: [
      'button.toolbox-drawer-button',
      'button:has-text("Deep")',
    ],
    description: 'Gemini toolbox drawer / Tools button',
  },
  
  modeMenuItem: (modeName: string) => `button[mat-list-item]:has-text("${modeName}")`,
  
  attachButton: {
    primary: 'button[aria-label="Open upload file menu"]',
    fallbacks: [
      'button:has(mat-icon[fonticon="add_2"])',
      '[data-test-id="upload-menu-button"]',
      'button[aria-label*="upload"]',
      'button[aria-label*="attach"]',
    ],
    description: 'Gemini upload menu button',
  },
  
  uploadMenuItem: {
    primary: 'button[data-test-id="local-images-files-uploader-button"]',
    fallbacks: [
      'button[data-test-id="hidden-local-file-upload-button"]',
      'button:has-text("Upload files")',
      '[role="menuitem"]:has-text("Upload")',
    ],
    description: 'Upload files option',
  },
  
  responseContainer: {
    primary: 'message-content',
    fallbacks: [
      '.model-response-text',
      '[class*="response-container"]',
    ],
    description: 'Gemini response container',
  },
  
  overlayContainer: '.cdk-overlay-container',
  
  closeOverlayButton: {
    primary: 'button[aria-label="Close"]',
    fallbacks: [
      'button[aria-label="Dismiss"]',
      '.cdk-overlay-container button mat-icon[fonticon="close"]',
      '.cdk-overlay-backdrop',
      '[aria-label="Close promotional banner"]',
    ],
    description: 'Overlay close buttons',
  },
  
  // CRITICAL: Start Research button (often disabled)
  startResearchButton: {
    primary: 'button[data-test-id="confirm-button"]',
    fallbacks: [
      'button[data-test-id="confirm-button"][aria-label="Start research"]',
      'button:has-text("Start research")',
    ],
    description: 'Deep Research start button (often programmatically disabled)',
  },
  
  // Deselect Deep Research button
  deselectResearchButton: {
    primary: 'button[aria-label="Deselect Deep Research"]',
    fallbacks: [],
    description: 'Deselect Deep Research mode',
  },
  
  downloadButton: {
    primary: '[data-testid="asset-card-open-button"]',
    fallbacks: [
      'button:has-text("Export")',
    ],
    description: 'Gemini artifact card',
  },
  
  exportMenu: {
    primary: 'button:has-text("Export")',
    fallbacks: [],
    description: 'Export menu button',
  },
  
  markdownOption: {
    primary: 'text="Download as Markdown"',
    fallbacks: [
      '[role="menuitem"]:has-text("Markdown")',
    ],
    description: 'Markdown download option',
  },
};

// ============================================================================
// Grok Selectors
// ============================================================================

const grokSelectors: PlatformSelectorConfig = {
  chatInput: {
    primary: 'div[contenteditable="true"]',
    fallbacks: [
      'textarea',
      '[role="textbox"]',
    ],
    description: 'Grok input field',
  },
  
  sendButton: {
    primary: 'button[type="submit"]',
    fallbacks: [
      'button[aria-label*="send" i]',
      'button:has(svg[class*="send"])',
    ],
    description: 'Grok send button',
  },
  
  modelSelector: {
    primary: '#model-select-trigger',
    fallbacks: [
      'button[id="model-select-trigger"]',
      'button[aria-label="Model select"]',
    ],
    description: 'Grok model selector (requires JS click)',
  },
  
  modelMenuItem: (modelName: string) => `[role="menuitem"]:has-text("${modelName}")`,
  
  attachButton: {
    primary: 'button[aria-label="Attach"]',
    fallbacks: [
      'button:has(svg[class*="paperclip"])',
    ],
    description: 'Grok attach button',
  },
  
  uploadMenuItem: {
    primary: 'div[role="menuitem"]:has-text("Upload a file")',
    fallbacks: [
      'button:has-text("Upload")',
    ],
    description: 'Upload file option',
  },
  
  responseContainer: {
    primary: '[class*="response"]',
    fallbacks: [
      '.message-content',
      '[data-role="assistant"]',
    ],
    description: 'Grok response container',
  },
};

// ============================================================================
// Perplexity Selectors (Updated from CLEAN_SELECTORS.md)
// ============================================================================

const perplexitySelectors: PlatformSelectorConfig = {
  chatInput: {
    primary: 'textarea',
    fallbacks: [
      '[data-lexical-editor="true"]',
      'div[contenteditable="true"]',
      '[aria-label*="prompt"]',
    ],
    description: 'Perplexity input',
  },
  
  sendButton: {
    primary: 'button[aria-label="Submit"]',
    fallbacks: [
      'button[type="submit"]',
      'button:has(svg[class*="send"])',
    ],
    description: 'Perplexity send button',
  },
  
  // Perplexity has NO model selector - uses modes instead
  modelSelector: undefined,
  
  // Mode selector - radiogroup pattern
  modeSelector: {
    primary: 'div[role="radiogroup"]',
    fallbacks: [],
    description: 'Perplexity mode radiogroup container',
  },
  
  // Mode menu items - radio buttons with specific data-testid values
  modeMenuItem: (modeName: string) => {
    const modeMap: Record<string, string> = {
      'search': 'button[role="radio"][value="search"]',
      'Search': 'button[role="radio"][value="search"]',
      'research': 'button[role="radio"][value="research"]',
      'Research': 'button[role="radio"][value="research"]',
      'Pro': 'button[role="radio"][value="research"]',
      'studio': 'button[role="radio"][value="studio"]',
      'Labs': 'button[role="radio"][value="studio"]',
    };
    return modeMap[modeName] || `button[role="radio"][value="${modeName.toLowerCase()}"]`;
  },
  
  attachButton: {
    primary: 'button[data-testid="attach-files-button"]',
    fallbacks: [
      'button[aria-label*="attach"]',
      'button:has(svg[class*="paperclip"])',
    ],
    description: 'Perplexity attach button',
  },
  
  uploadMenuItem: {
    primary: 'div[role="menuitem"]:has-text("Local files")',
    fallbacks: [
      'button:has-text("Local files")',
      '[role="menuitem"]:has-text("Upload")',
    ],
    description: 'Local files option',
  },
  
  // CRITICAL: Use parent container, not child elements
  responseContainer: {
    primary: 'div.prose.dark\\:prose-invert.inline.leading-relaxed',
    fallbacks: [
      '.prose:not(.prose *)',  // Parent prose, not children
      '[class*="answer-content"]',
    ],
    description: 'Perplexity response (parent container only - CRITICAL)',
  },
  
  downloadButton: {
    primary: '[data-testid="asset-card-open-button"]',
    fallbacks: [],
    description: 'Perplexity artifact card',
  },
  
  exportMenu: {
    primary: 'button:has-text("Export")',
    fallbacks: [],
    description: 'Export menu',
  },
  
  markdownOption: {
    primary: 'text="Download as Markdown"',
    fallbacks: [],
    description: 'Markdown option',
  },
};

// ============================================================================
// Selector Registry
// ============================================================================

const SELECTORS: Record<PlatformType, PlatformSelectorConfig> = {
  claude: claudeSelectors,
  chatgpt: chatgptSelectors,
  gemini: geminiSelectors,
  grok: grokSelectors,
  perplexity: perplexitySelectors,
};

// ============================================================================
// Selector Registry Class
// ============================================================================

export class SelectorRegistry {
  private readonly platform: PlatformType;
  private readonly config: PlatformSelectorConfig;
  
  constructor(platform: PlatformType) {
    this.platform = platform;
    this.config = SELECTORS[platform];
    
    if (!this.config) {
      throw new Error(`Unknown platform: ${platform}`);
    }
  }
  
  /**
   * Get selector with fallbacks
   */
  get(key: keyof PlatformSelectorConfig): SelectorWithFallbacks | undefined {
    const value = this.config[key];
    if (value && typeof value === 'object' && 'primary' in value) {
      return value as SelectorWithFallbacks;
    }
    return undefined;
  }
  
  /**
   * Get primary selector only
   */
  getPrimary(key: keyof PlatformSelectorConfig): string | undefined {
    const selector = this.get(key);
    return selector?.primary;
  }
  
  /**
   * Get all selectors (primary + fallbacks) as array
   */
  getAll(key: keyof PlatformSelectorConfig): string[] {
    const selector = this.get(key);
    if (!selector) return [];
    return [selector.primary, ...selector.fallbacks];
  }
  
  /**
   * Get model menu item selector
   */
  getModelMenuItem(modelName: string): string | undefined {
    return this.config.modelMenuItem?.(modelName);
  }
  
  /**
   * Get mode menu item selector
   */
  getModeMenuItem(modeName: string): string | undefined {
    return this.config.modeMenuItem?.(modeName);
  }
  
  /**
   * Get streaming class name
   */
  getStreamingClass(): string | undefined {
    return this.config.streamingClass;
  }
  
  /**
   * Get overlay container selector
   */
  getOverlayContainer(): string | undefined {
    return this.config.overlayContainer;
  }
  
  /**
   * Check if platform has a specific selector
   */
  has(key: keyof PlatformSelectorConfig): boolean {
    return this.get(key) !== undefined;
  }
  
  /**
   * Get combined selector string for Playwright
   * Joins primary and fallbacks with comma for OR matching
   */
  getCombined(key: keyof PlatformSelectorConfig): string {
    const selectors = this.getAll(key);
    return selectors.join(', ');
  }
}

// ============================================================================
// Factory Function
// ============================================================================

export function createSelectorRegistry(platform: PlatformType): SelectorRegistry {
  return new SelectorRegistry(platform);
}
