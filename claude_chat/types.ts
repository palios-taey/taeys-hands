/**
 * Taey's Hands - Core Type Definitions
 * Nova Rebuild v2.0.0
 * 
 * All type definitions for the system in one place.
 * Single source of truth for interface contracts.
 */

// ============================================================================
// Platform Types
// ============================================================================

export type PlatformType = 'claude' | 'chatgpt' | 'gemini' | 'grok' | 'perplexity';

export type OSType = 'darwin' | 'linux' | 'win32';

export interface PlatformConfig {
  name: PlatformType;
  displayName: string;
  provider: string;
  baseUrl: string;
  newChatPath: string;
  conversationPattern: RegExp;
  supportedFeatures: {
    modelSelection: boolean;
    researchMode: boolean;
    extendedThinking: boolean;
    fileAttachment: boolean;
    artifactDownload: boolean;
  };
  defaultTimeout: number;
  researchTimeout: number;
}

// ============================================================================
// Session Types
// ============================================================================

export type SessionStatus = 'creating' | 'active' | 'disconnected' | 'orphaned' | 'stale';

export interface Session {
  sessionId: string;
  platform: PlatformType;
  conversationId: string | null;
  conversationUrl: string | null;
  status: SessionStatus;
  createdAt: Date;
  lastActivity: Date;
  healthStatus: 'healthy' | 'stale' | 'dead';
  lastHealthCheck: Date;
}

export interface SessionCreateOptions {
  platform: PlatformType;
  newSession?: boolean;
  conversationId?: string;
  model?: string;
}

// ============================================================================
// Browser Types
// ============================================================================

export interface BrowserConfig {
  headless: boolean;
  slowMo: number;
  viewport: { width: number; height: number };
  userDataDir?: string;
}

export interface ScreenshotResult {
  path: string;
  timestamp: Date;
  base64?: string;
}

// ============================================================================
// Message Types
// ============================================================================

export type MessageRole = 'user' | 'assistant' | 'system';

export interface Message {
  id: string;
  conversationId: string;
  role: MessageRole;
  content: string;
  platform: PlatformType;
  timestamp: Date;
  attachments: string[];
  sent: boolean;
  metadata?: Record<string, unknown>;
}

export interface SendMessageOptions {
  humanLike?: boolean;
  mixedContent?: boolean;
  waitForResponse?: boolean;
  timeout?: number;
  attachments?: string[];
}

export interface SendMessageResult {
  success: boolean;
  screenshot: string;
  sentText: string;
  responseText?: string;
  responseLength?: number;
  detectionMethod?: string;
  detectionConfidence?: number;
  detectionTime?: number;
  error?: string;
}

// ============================================================================
// Response Detection Types
// ============================================================================

export type DetectionMethod = 
  | 'streamingClass' 
  | 'buttonAppearance' 
  | 'contentStability' 
  | 'thinkingIndicator'
  | 'fallback';

export interface DetectionResult {
  content: string;
  method: DetectionMethod;
  confidence: number;
  detectionTime: number;
  isComplete: boolean;
}

export interface DetectionConfig {
  primaryMethod: DetectionMethod;
  fallbackMethods: DetectionMethod[];
  stabilityThreshold: number;  // Consecutive unchanged reads
  pollingStrategy: 'fibonacci' | 'linear';
  maxTimeout: number;
}

// ============================================================================
// File Attachment Types
// ============================================================================

export interface AttachmentResult {
  success: boolean;
  filePath: string;
  screenshot: string;
  automationCompleted: boolean;
  error?: string;
}

export interface AttachFilesResult {
  success: boolean;
  filesAttached: number;
  attachments: AttachmentResult[];
  screenshot: string;
  message: string;
}

// ============================================================================
// Validation Types
// ============================================================================

export type ValidationStep = 
  | 'plan' 
  | 'attach_files' 
  | 'type_message' 
  | 'click_send' 
  | 'wait_response' 
  | 'extract_response';

export interface ValidationCheckpoint {
  id: string;
  conversationId: string;
  step: ValidationStep;
  validated: boolean;
  notes: string;
  screenshot?: string;
  validator: string;
  timestamp: Date;
  requiredAttachments: string[];
  actualAttachments: string[];
}

export interface ValidationRequirements {
  required: boolean;
  files: string[];
  count: number;
}

export interface CanProceedResult {
  canProceed: boolean;
  reason: string;
  lastValidated: ValidationStep | null;
}

// ============================================================================
// Neo4j Types
// ============================================================================

export interface ConversationNode {
  id: string;
  title?: string;
  purpose?: string;
  platform: PlatformType;
  sessionId: string;
  conversationId?: string;
  status: 'active' | 'closed' | 'orphaned';
  createdAt: Date;
  closedAt?: Date;
  lastActivity?: Date;
  model?: string;
  metadata?: Record<string, unknown>;
}

export interface DetectionNode {
  id: string;
  messageId: string;
  method: DetectionMethod;
  confidence: number;
  detectionTime: number;
  contentLength: number;
  timestamp: Date;
  metadata?: Record<string, unknown>;
}

// ============================================================================
// Selector Types
// ============================================================================

export interface PlatformSelectors {
  chatInput: string;
  sendButton: string;
  modelSelector?: string;
  modelMenuItems?: Record<string, string>;
  plusMenu?: string;
  uploadMenuItem?: string;
  responseContainer: string;
  thinkingIndicator?: string;
  streamingClass?: string;
  downloadButton?: string;
}

export interface SelectorWithFallbacks {
  primary: string;
  fallbacks: string[];
  description: string;
}

// ============================================================================
// MCP Tool Types
// ============================================================================

export interface MCPToolResult {
  success: boolean;
  message: string;
  data?: Record<string, unknown>;
  screenshot?: string;
  isError?: boolean;
}

export interface ConnectResult extends MCPToolResult {
  sessionId: string;
  platform: PlatformType;
  conversationUrl?: string;
}

// ============================================================================
// Error Types
// ============================================================================

export class TaeyError extends Error {
  constructor(
    message: string,
    public code: string,
    public recoverable: boolean = true,
    public suggestion?: string
  ) {
    super(message);
    this.name = 'TaeyError';
  }
}

export class ValidationError extends TaeyError {
  constructor(message: string, suggestion?: string) {
    super(message, 'VALIDATION_ERROR', true, suggestion);
    this.name = 'ValidationError';
  }
}

export class SessionError extends TaeyError {
  constructor(message: string, suggestion?: string) {
    super(message, 'SESSION_ERROR', true, suggestion);
    this.name = 'SessionError';
  }
}

export class SelectorError extends TaeyError {
  constructor(message: string, selector: string) {
    super(message, 'SELECTOR_ERROR', true, `Selector "${selector}" not found. Platform UI may have changed.`);
    this.name = 'SelectorError';
  }
}

export class AttachmentError extends TaeyError {
  constructor(message: string, suggestion?: string) {
    super(message, 'ATTACHMENT_ERROR', true, suggestion);
    this.name = 'AttachmentError';
  }
}

// ============================================================================
// Timing Constants
// ============================================================================

export const TIMING = {
  TAB_FOCUS: 200,
  APP_FOCUS: 500,
  MENU_RENDER: 800,
  FILE_DIALOG_SPAWN: 1500,
  APPLESCRIPT_EXEC: 500,
  TYPING_BUFFER: 300,
  FINDER_NAVIGATE: 1000,
  FILE_UPLOAD_PROCESS: 1500,
  NETWORK_SEND: 1000,
  STABILITY_POLL: 2000,
  SCREENSHOT_WAIT: 500,
  OVERLAY_DISMISS: 300,
} as const;

// ============================================================================
// Platform Configurations
// ============================================================================

export const PLATFORM_CONFIGS: Record<PlatformType, PlatformConfig> = {
  claude: {
    name: 'claude',
    displayName: 'Claude',
    provider: 'Anthropic',
    baseUrl: 'https://claude.ai',
    newChatPath: '/new',
    conversationPattern: /\/chat\/([a-f0-9-]+)/,
    supportedFeatures: {
      modelSelection: true,
      researchMode: true,
      extendedThinking: true,
      fileAttachment: true,
      artifactDownload: true,
    },
    defaultTimeout: 60000,
    researchTimeout: 300000,
  },
  chatgpt: {
    name: 'chatgpt',
    displayName: 'ChatGPT',
    provider: 'OpenAI',
    baseUrl: 'https://chatgpt.com',
    newChatPath: '/',
    conversationPattern: /\/c\/([a-f0-9-]+)/,
    supportedFeatures: {
      modelSelection: false,  // Disabled - use modes instead
      researchMode: true,
      extendedThinking: false,
      fileAttachment: true,
      artifactDownload: false,
    },
    defaultTimeout: 60000,
    researchTimeout: 180000,
  },
  gemini: {
    name: 'gemini',
    displayName: 'Gemini',
    provider: 'Google',
    baseUrl: 'https://gemini.google.com',
    newChatPath: '/app',
    conversationPattern: /\/app\/([a-f0-9]+)/,
    supportedFeatures: {
      modelSelection: true,
      researchMode: true,
      extendedThinking: true,
      fileAttachment: true,
      artifactDownload: true,
    },
    defaultTimeout: 60000,
    researchTimeout: 3600000,  // 60 min for Deep Research
  },
  grok: {
    name: 'grok',
    displayName: 'Grok',
    provider: 'xAI',
    baseUrl: 'https://grok.com',
    newChatPath: '/',
    conversationPattern: /\/chat\/([a-f0-9-]+)/,
    supportedFeatures: {
      modelSelection: true,
      researchMode: false,
      extendedThinking: true,
      fileAttachment: true,
      artifactDownload: false,
    },
    defaultTimeout: 60000,
    researchTimeout: 120000,
  },
  perplexity: {
    name: 'perplexity',
    displayName: 'Perplexity',
    provider: 'Perplexity AI',
    baseUrl: 'https://www.perplexity.ai',
    newChatPath: '/',
    conversationPattern: /\/search\/([a-f0-9-]+)/,
    supportedFeatures: {
      modelSelection: false,
      researchMode: true,
      extendedThinking: false,
      fileAttachment: true,
      artifactDownload: true,
    },
    defaultTimeout: 60000,
    researchTimeout: 1800000,  // 30 min for Pro Search
  },
};
