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
   * @returns Session ID
   */
  async createSession(interfaceType: InterfaceType): Promise<string> {
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

    // Connect the interface (browser automation setup)
    await chatInterface.connect();

    // Store session
    const session: Session = {
      sessionId,
      interface: chatInterface,
      interfaceType,
      createdAt: new Date(),
      connected: true
    };

    this.sessions.set(sessionId, session);
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
}

/**
 * Get the singleton session manager instance
 */
export function getSessionManager(): SessionManager {
  return SessionManager.getInstance();
}

export default SessionManager;
