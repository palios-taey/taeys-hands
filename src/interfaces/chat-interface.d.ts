/**
 * TypeScript declarations for chat-interface.js
 * Unified interface system for AI chat automation
 */

export interface SessionOptions {
  sessionId?: number | string;
  screenshotPath?: string;
}

export interface AutomationResult {
  screenshot?: string;
  automationCompleted: boolean;
  [key: string]: any;
}

export interface SendMessageOptions {
  humanLike?: boolean;
  waitForResponse?: boolean;
  timeout?: number;
  mixedContent?: boolean;
  sessionId?: number;
}

export interface WaitResponseOptions {
  screenshots?: boolean;
  screenshotDir?: string;
  sessionId?: number | string;
}

export interface DownloadArtifactOptions {
  downloadPath?: string;
  timeout?: number;
}

export interface DownloadResult {
  downloaded: boolean;
  filePath: string | null;
  fileName: string | null;
}

/**
 * Base ChatInterface class
 */
export class ChatInterface {
  browser: any;
  osa: any;
  page: any;
  name: string;
  url: string;
  selectors: Record<string, string>;
  connected: boolean;

  constructor(config?: any);

  // Core methods
  connect(): Promise<this>;
  disconnect(): Promise<void>;
  isLoggedIn(): Promise<boolean>;
  screenshot(filename?: string): Promise<string>;

  // Conversation management
  startNewChat(): Promise<boolean>;
  newConversation(): Promise<boolean>;
  goToConversation(conversationUrlOrId: string): Promise<string>;
  buildConversationUrl(conversationId: string): string;
  getCurrentConversationUrl(): Promise<string>;

  // File attachment
  attachFile(filePath: string | string[] | any, options?: SessionOptions): Promise<AutomationResult | boolean>;
  sendMessageWithAttachment(message: string, filePaths: string | string[], options?: SendMessageOptions): Promise<any>;
  attachFileHumanLike?(filePath: string): Promise<boolean>;

  // Research/Pro mode
  enableResearchMode(options?: SessionOptions & { selector?: string }): Promise<AutomationResult>;

  // Message sending
  prepareInput(options?: SessionOptions): Promise<AutomationResult>;
  typeMessage(message: string, options?: SessionOptions & { humanLike?: boolean; mixedContent?: boolean }): Promise<AutomationResult>;
  clickSend(options?: SessionOptions): Promise<AutomationResult>;
  sendMessage(message: string, options?: SendMessageOptions): Promise<any>;

  // Response waiting
  waitForResponse(timeout?: number, options?: WaitResponseOptions): Promise<string>;
  getLatestResponse(): Promise<string>;
  logTimingData(elapsedSeconds: number, responseLength: number): void;

  // Internal helpers
  _navigateFinderDialog(filePath: string): Promise<void>;
}

/**
 * Claude Chat Interface
 */
export class ClaudeInterface extends ChatInterface {
  constructor(config?: any);

  selectModel(modelName?: string, options?: SessionOptions): Promise<AutomationResult & { modelName: string }>;
  setResearchMode(enabled?: boolean): Promise<boolean>;
  downloadArtifact(options?: DownloadArtifactOptions): Promise<DownloadResult>;
  attachFile(filePath: string, options?: SessionOptions): Promise<AutomationResult>;
  attachFileHumanLike(filePath: string): Promise<boolean>;
  waitForResponse(timeout?: number): Promise<string>;
  newConversation(): Promise<boolean>;
  buildConversationUrl(conversationId: string): string;
}

/**
 * ChatGPT Interface
 */
export class ChatGPTInterface extends ChatInterface {
  constructor(config?: any);

  newConversation(): Promise<boolean>;
  buildConversationUrl(conversationId: string): string;
  attachFileHumanLike(filePath: string): Promise<boolean>;
}

/**
 * Gemini Interface
 */
export class GeminiInterface extends ChatInterface {
  constructor(config?: any);

  newConversation(): Promise<boolean>;
  buildConversationUrl(conversationId: string): string;
  attachFileHumanLike(filePath: string): Promise<boolean>;
}

/**
 * Grok Interface
 */
export class GrokInterface extends ChatInterface {
  constructor(config?: any);

  newConversation(): Promise<boolean>;
  buildConversationUrl(conversationId: string): string;
  attachFileHumanLike(filePath: string): Promise<boolean>;
}

/**
 * Perplexity Interface
 */
export class PerplexityInterface extends ChatInterface {
  constructor(config?: any);

  enableResearchMode(options?: SessionOptions): Promise<AutomationResult>;
  attachFile(filePath: string, options?: SessionOptions): Promise<AutomationResult>;
  attachFileHumanLike(filePath: string): Promise<boolean>;
  newConversation(): Promise<boolean>;
  buildConversationUrl(conversationId: string): string;
}

/**
 * Factory function to get interface by name
 */
export function getInterface(name: string, config?: any): ChatInterface;

/**
 * Default export: ChatInterface base class
 */
export default ChatInterface;
