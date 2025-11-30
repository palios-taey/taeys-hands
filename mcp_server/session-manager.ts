/**
 * Session Manager for Taey-Hands MCP Tools
 *
 * Manages active chat interface sessions with in-memory registry.
 * Each session holds a ChatInterface instance (Claude, ChatGPT, Gemini, Grok, or Perplexity).
 *
 * Architecture: Function-based tools → SessionManager → Interface dispatch
 */

import { randomUUID } from "crypto";

// Use dynamic import to avoid TypeScript module resolution issues
// The chat-interface module is pure JavaScript without type declarations
let ChatInterface: any;
let ClaudeInterface: any;
let ChatGPTInterface: any;
let GeminiInterface: any;
let GrokInterface: any;
let PerplexityInterface: any;

// Load at module initialization
// Path is relative to dist/ directory after compilation (not mcp_server/ source)
// @ts-expect-error - TypeScript checks from source location, but runtime needs dist/ path
const interfaceModule = await import("../../src/interfaces/chat-interface.js");
ChatInterface = interfaceModule.default;
ClaudeInterface = interfaceModule.ClaudeInterface;
ChatGPTInterface = interfaceModule.ChatGPTInterface;
GeminiInterface = interfaceModule.GeminiInterface;
GrokInterface = interfaceModule.GrokInterface;
PerplexityInterface = interfaceModule.PerplexityInterface;

/**
 * Supported interface types
 */
export type InterfaceType = "claude" | "chatgpt" | "gemini" | "grok" | "perplexity";

/**
 * Session data structure
 */
export interface Session {
  sessionId: string;
  interface: any; // ChatInterface instance (dynamically loaded)
  interfaceType: InterfaceType;
  createdAt: Date;
  connected: boolean;
  conversationId: string | null; // Platform-specific conversation ID
  conversationUrl: string | null; // Current conversation URL
  lastActivity: Date; // Last tool call timestamp
  healthStatus: 'healthy' | 'stale' | 'dead';
  lastHealthCheck: Date;
}

/**
 * Session Manager
 *
 * Singleton that manages all active chat interface sessions.
 */
export class SessionManager {
  private sessions: Map<string, Session>;
  private static instance: SessionManager | null = null;

  private constructor() {
    this.sessions = new Map();
  }

  /**
   * Get singleton instance
   */
  static getInstance(): SessionManager {
    if (!SessionManager.instance) {
      SessionManager.instance = new SessionManager();
    }
    return SessionManager.instance;
  }

  /**
   * Create a new session
   *
   * @param interfaceType - Which chat interface to use
   * @param options - Options to pass to connect() (newConversation, conversationId)
   * @returns Session ID
   */
  async createSession(interfaceType: InterfaceType, options?: { newConversation?: boolean; conversationId?: string }): Promise<string> {
    const sessionId = randomUUID();

    // Factory: create correct interface subclass
    let chatInterface: any;
    switch (interfaceType) {
      case "claude":
        chatInterface = new ClaudeInterface();
        break;
      case "chatgpt":
        chatInterface = new ChatGPTInterface();
        break;
      case "gemini":
        chatInterface = new GeminiInterface();
        break;
      case "grok":
        chatInterface = new GrokInterface();
        break;
      case "perplexity":
        chatInterface = new PerplexityInterface();
        break;
      default:
        throw new Error(`Unknown interface type: ${interfaceType}`);
    }

    // Store session BEFORE connecting (so interface is available)
    const now = new Date();
    const session: Session = {
      sessionId,
      interface: chatInterface,
      interfaceType,
      createdAt: now,
      connected: false,  // Will be set to true after connect succeeds
      conversationId: null,
      conversationUrl: null,
      lastActivity: now,
      healthStatus: 'healthy',
      lastHealthCheck: now
    };

    this.sessions.set(sessionId, session);

    // Connect the interface with options
    await chatInterface.connect({
      sessionId,
      newConversation: options?.newConversation,
      conversationId: options?.conversationId
    });

    // Mark as connected
    session.connected = true;

    // Get current URL and extract conversationId
    try {
      const currentUrl = await chatInterface.getCurrentConversationUrl();
      session.conversationUrl = currentUrl;
      // conversationId extraction will happen in updateSessionState
    } catch (err: any) {
      console.warn(`[SessionManager] Could not get conversation URL: ${err.message}`);
    }

    console.log(`[SessionManager] Created session ${sessionId} (${interfaceType})`);

    return sessionId;
  }

  /**
   * Get an existing session
   *
   * @param sessionId - Session ID
   * @returns Session or null if not found
   */
  getSession(sessionId: string): Session | null {
    return this.sessions.get(sessionId) || null;
  }

  /**
   * Get interface from session
   *
   * @param sessionId - Session ID
   * @returns ChatInterface instance
   * @throws Error if session not found
   */
  getInterface(sessionId: string): any {
    const session = this.getSession(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }
    if (!session.connected) {
      throw new Error(`Session disconnected: ${sessionId}`);
    }
    return session.interface;
  }

  /**
   * Destroy a session
   *
   * @param sessionId - Session ID
   */
  async destroySession(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      console.warn(`[SessionManager] Session not found: ${sessionId}`);
      return;
    }

    // Disconnect interface (cleanup browser)
    try {
      await session.interface.disconnect();
    } catch (error) {
      console.error(`[SessionManager] Error disconnecting session ${sessionId}:`, error);
    }

    // Remove from registry
    this.sessions.delete(sessionId);
    console.log(`[SessionManager] Destroyed session ${sessionId}`);
  }

  /**
   * Get all active sessions
   *
   * @returns Array of session IDs
   */
  getActiveSessions(): string[] {
    return Array.from(this.sessions.keys());
  }

  /**
   * Get session count
   */
  getSessionCount(): number {
    return this.sessions.size;
  }

  /**
   * Destroy all sessions (cleanup)
   */
  async destroyAllSessions(): Promise<void> {
    const sessionIds = Array.from(this.sessions.keys());
    console.log(`[SessionManager] Destroying ${sessionIds.length} sessions`);

    for (const sessionId of sessionIds) {
      await this.destroySession(sessionId);
    }
  }

  /**
   * Health check for a specific session
   * Verifies browser is responsive and updates health status
   *
   * @param sessionId - Session ID to check
   * @returns Health status ('healthy' | 'stale' | 'dead')
   */
  async healthCheck(sessionId: string): Promise<'healthy' | 'stale' | 'dead'> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    try {
      // Try to get page URL - will fail if browser dead
      await session.interface.page.url();
      session.healthStatus = 'healthy';
      session.lastHealthCheck = new Date();
      return 'healthy';
    } catch (err: any) {
      session.healthStatus = 'dead';
      session.lastHealthCheck = new Date();
      console.error(`[SessionManager] Session ${sessionId} health check failed: ${err.message}`);
      return 'dead';
    }
  }

  /**
   * Update session state from browser
   * Syncs conversationId and URL from current browser state
   *
   * @param sessionId - Session ID
   * @returns Updated session info
   */
  async updateSessionState(sessionId: string): Promise<{ conversationId: string | null; conversationUrl: string }> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    // Get current URL from browser
    const currentUrl = await session.interface.getCurrentConversationUrl();
    session.conversationUrl = currentUrl;
    session.lastActivity = new Date();

    // ConversationId extraction will be handled by ConversationStore
    // We just return the URL for the store to process
    return {
      conversationId: session.conversationId,
      conversationUrl: currentUrl
    };
  }

  /**
   * Validate session health before tool execution
   * Throws error if session is dead
   *
   * @param sessionId - Session ID
   */
  async validateSessionHealth(sessionId: string): Promise<void> {
    const health = await this.healthCheck(sessionId);
    if (health === 'dead') {
      throw new Error(`Session ${sessionId} is dead (browser crashed or closed)`);
    }
  }

  /**
   * Sync with database to detect orphaned sessions
   * Called on server startup
   *
   * @param conversationStore - ConversationStore instance
   */
  async syncWithDatabase(conversationStore: any): Promise<void> {
    const activeMcpSessionIds = this.getActiveSessions();
    const result = await conversationStore.reconcileOrphanedSessions(activeMcpSessionIds);

    if (result.orphaned.length > 0) {
      console.log(`[SessionManager] Reconciled ${result.updated} orphaned sessions`);
    }
  }
}

/**
 * Get the singleton session manager instance
 */
export function getSessionManager(): SessionManager {
  return SessionManager.getInstance();
}

export default SessionManager;
