/**
 * Session Manager - Coordinated State Management
 * 
 * CRITICAL: Synchronizes three layers:
 * - Browser State (Playwright page/URL)
 * - MCP State (in-memory session registry)
 * - Database State (Neo4j Conversation)
 * 
 * Invariant: All three layers MUST agree on session state.
 */

import { v4 as uuidv4 } from 'uuid';
import { Page, Browser, BrowserContext } from 'playwright';
import {
  Session,
  SessionStatus,
  SessionCreateOptions,
  PlatformType,
  SessionError,
  PLATFORM_CONFIGS,
} from '../../types.js';
import { getConversationStore, ConversationStore } from '../database/conversation-store.js';
import { getValidationStore, ValidationCheckpointStore } from '../validation/checkpoint-store.js';

// ============================================================================
// Managed Session (combines all state)
// ============================================================================

export interface ManagedSession extends Session {
  page: Page;
  context: BrowserContext;
}

// ============================================================================
// Session Manager
// ============================================================================

export class SessionManager {
  private readonly sessions: Map<string, ManagedSession> = new Map();
  private browser: Browser | null = null;
  private readonly conversationStore: ConversationStore;
  private readonly validationStore: ValidationCheckpointStore;
  
  // Health check interval (30 seconds)
  private healthCheckInterval: NodeJS.Timeout | null = null;
  private readonly HEALTH_CHECK_MS = 30000;
  
  constructor() {
    this.conversationStore = getConversationStore();
    this.validationStore = getValidationStore();
  }
  
  /**
   * Initialize manager with browser instance
   */
  async initialize(browser: Browser): Promise<void> {
    this.browser = browser;
    
    // Initialize database schemas
    await this.conversationStore.initSchema();
    await this.validationStore.initSchema();
    
    // Start health check loop
    this.startHealthChecks();
    
    // Register shutdown handlers
    this.registerShutdownHandlers();
    
    console.log('[SessionManager] Initialized');
  }
  
  /**
   * Create a new session
   */
  async createSession(options: SessionCreateOptions): Promise<ManagedSession> {
    if (!this.browser) {
      throw new SessionError('SessionManager not initialized. Call initialize() first.');
    }
    
    const sessionId = uuidv4();
    const config = PLATFORM_CONFIGS[options.platform];
    
    if (!config) {
      throw new SessionError(`Unknown platform: ${options.platform}`);
    }
    
    // 1. Create browser context and page
    const context = await this.browser.newContext({
      viewport: { width: 1280, height: 800 },
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    });
    
    const page = await context.newPage();
    
    // 2. Navigate to appropriate URL
    let conversationId: string | null = null;
    let conversationUrl: string | null = null;
    
    if (options.conversationId) {
      // Resume existing conversation
      conversationUrl = this.buildConversationUrl(options.platform, options.conversationId);
      await page.goto(conversationUrl, { waitUntil: 'networkidle' });
      conversationId = options.conversationId;
    } else if (options.newSession) {
      // Create fresh conversation
      const newUrl = `${config.baseUrl}${config.newChatPath}`;
      await page.goto(newUrl, { waitUntil: 'networkidle' });
      
      // Wait for navigation to complete and extract conversation ID
      await page.waitForTimeout(2000);
      conversationUrl = page.url();
      conversationId = this.extractConversationId(options.platform, conversationUrl);
    } else {
      // Default to base URL (may resume last conversation from cookies)
      await page.goto(config.baseUrl, { waitUntil: 'networkidle' });
      conversationUrl = page.url();
      conversationId = this.extractConversationId(options.platform, conversationUrl);
    }
    
    // 3. Create database conversation record
    await this.conversationStore.createConversation({
      platform: options.platform,
      sessionId,
      conversationId: conversationId || undefined,
      model: options.model,
    });
    
    // 4. Create MCP session state
    const now = new Date();
    const session: ManagedSession = {
      sessionId,
      platform: options.platform,
      conversationId,
      conversationUrl,
      status: 'active',
      createdAt: now,
      lastActivity: now,
      healthStatus: 'healthy',
      lastHealthCheck: now,
      page,
      context,
    };
    
    this.sessions.set(sessionId, session);
    
    console.log(`[SessionManager] Created session ${sessionId} for ${options.platform}`);
    return session;
  }
  
  /**
   * Get session by ID
   */
  getSession(sessionId: string): ManagedSession | undefined {
    return this.sessions.get(sessionId);
  }
  
  /**
   * Get session, throwing if not found
   */
  requireSession(sessionId: string): ManagedSession {
    const session = this.getSession(sessionId);
    
    if (!session) {
      throw new SessionError(
        `Session not found: ${sessionId}`,
        'Create a new session with taey_connect or resume an existing conversation.'
      );
    }
    
    if (session.status !== 'active') {
      throw new SessionError(
        `Session ${sessionId} is ${session.status}`,
        session.status === 'orphaned' 
          ? 'Resume with taey_connect and the conversationId'
          : 'Create a new session with taey_connect'
      );
    }
    
    return session;
  }
  
  /**
   * Update session activity
   */
  touchSession(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.lastActivity = new Date();
    }
  }
  
  /**
   * Update session conversation ID (after navigation)
   */
  async updateConversationId(sessionId: string, conversationId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.conversationId = conversationId;
      session.conversationUrl = this.buildConversationUrl(session.platform, conversationId);
      
      // Update database
      const dbConversation = await this.conversationStore.getConversationBySession(sessionId);
      if (dbConversation) {
        await this.conversationStore.updateConversation(dbConversation.id, {
          conversationId,
        });
      }
    }
  }
  
  /**
   * Disconnect session
   */
  async disconnectSession(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    
    if (session) {
      // 1. Close browser resources
      try {
        await session.page.close();
        await session.context.close();
      } catch (error) {
        console.warn(`[SessionManager] Error closing browser for ${sessionId}:`, error);
      }
      
      // 2. Update database
      const dbConversation = await this.conversationStore.getConversationBySession(sessionId);
      if (dbConversation) {
        await this.conversationStore.closeConversation(dbConversation.id);
      }
      
      // 3. Remove from registry
      this.sessions.delete(sessionId);
      
      console.log(`[SessionManager] Disconnected session ${sessionId}`);
    }
  }
  
  /**
   * List all sessions
   */
  listSessions(): Session[] {
    return Array.from(this.sessions.values()).map(s => ({
      sessionId: s.sessionId,
      platform: s.platform,
      conversationId: s.conversationId,
      conversationUrl: s.conversationUrl,
      status: s.status,
      createdAt: s.createdAt,
      lastActivity: s.lastActivity,
      healthStatus: s.healthStatus,
      lastHealthCheck: s.lastHealthCheck,
    }));
  }
  
  /**
   * Destroy all sessions (for shutdown)
   */
  async destroyAll(): Promise<void> {
    console.log(`[SessionManager] Destroying ${this.sessions.size} sessions...`);
    
    for (const [sessionId] of this.sessions) {
      await this.disconnectSession(sessionId);
    }
    
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval);
      this.healthCheckInterval = null;
    }
  }
  
  // ==========================================================================
  // Health Checks
  // ==========================================================================
  
  private startHealthChecks(): void {
    this.healthCheckInterval = setInterval(async () => {
      await this.runHealthChecks();
    }, this.HEALTH_CHECK_MS);
  }
  
  private async runHealthChecks(): Promise<void> {
    const now = new Date();
    
    for (const [sessionId, session] of this.sessions) {
      try {
        // Check if page is still responsive
        const isResponsive = await this.checkPageHealth(session.page);
        
        if (isResponsive) {
          session.healthStatus = 'healthy';
        } else {
          session.healthStatus = 'stale';
          console.warn(`[SessionManager] Session ${sessionId} is stale`);
        }
      } catch (error) {
        session.healthStatus = 'dead';
        session.status = 'orphaned';
        
        // Mark as orphaned in database
        const dbConversation = await this.conversationStore.getConversationBySession(sessionId);
        if (dbConversation) {
          await this.conversationStore.markOrphaned(dbConversation.id);
        }
        
        console.error(`[SessionManager] Session ${sessionId} is dead:`, error);
      }
      
      session.lastHealthCheck = now;
    }
  }
  
  private async checkPageHealth(page: Page): Promise<boolean> {
    try {
      // Try to evaluate something simple
      await page.evaluate(() => document.readyState);
      return true;
    } catch {
      return false;
    }
  }
  
  // ==========================================================================
  // Shutdown Handlers
  // ==========================================================================
  
  private registerShutdownHandlers(): void {
    const shutdown = async (signal: string) => {
      console.log(`\n[SessionManager] Received ${signal}, shutting down...`);
      await this.destroyAll();
      process.exit(0);
    };
    
    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));
    process.on('uncaughtException', async (error) => {
      console.error('[SessionManager] Uncaught exception:', error);
      await this.destroyAll();
      process.exit(1);
    });
  }
  
  // ==========================================================================
  // URL Helpers
  // ==========================================================================
  
  private buildConversationUrl(platform: PlatformType, conversationId: string): string {
    const config = PLATFORM_CONFIGS[platform];
    
    switch (platform) {
      case 'claude':
        return `${config.baseUrl}/chat/${conversationId}`;
      case 'chatgpt':
        return `${config.baseUrl}/c/${conversationId}`;
      case 'gemini':
        return `${config.baseUrl}/app/${conversationId}`;
      case 'grok':
        return `${config.baseUrl}/chat/${conversationId}`;
      case 'perplexity':
        return `${config.baseUrl}/search/${conversationId}`;
      default:
        return `${config.baseUrl}/${conversationId}`;
    }
  }
  
  private extractConversationId(platform: PlatformType, url: string): string | null {
    const config = PLATFORM_CONFIGS[platform];
    const match = url.match(config.conversationPattern);
    return match?.[1] || null;
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let managerInstance: SessionManager | null = null;

export function getSessionManager(): SessionManager {
  if (!managerInstance) {
    managerInstance = new SessionManager();
  }
  return managerInstance;
}
