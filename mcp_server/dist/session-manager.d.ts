/**
 * Session Manager for Taey-Hands MCP Tools
 *
 * Manages active chat interface sessions with in-memory registry.
 * Each session holds a ChatInterface instance (Claude, ChatGPT, Gemini, Grok, or Perplexity).
 *
 * Architecture: Function-based tools → SessionManager → Interface dispatch
 */
/**
 * Supported interface types
 */
export type InterfaceType = "claude" | "chatgpt" | "gemini" | "grok" | "perplexity";
/**
 * Session data structure
 */
export interface Session {
    sessionId: string;
    interface: any;
    interfaceType: InterfaceType;
    createdAt: Date;
    connected: boolean;
    conversationId: string | null;
    conversationUrl: string | null;
    lastActivity: Date;
    healthStatus: 'healthy' | 'stale' | 'dead';
    lastHealthCheck: Date;
}
/**
 * Session Manager
 *
 * Singleton that manages all active chat interface sessions.
 */
export declare class SessionManager {
    private sessions;
    private static instance;
    private constructor();
    /**
     * Get singleton instance
     */
    static getInstance(): SessionManager;
    /**
     * Create a new session
     *
     * @param interfaceType - Which chat interface to use
     * @param options - Options to pass to connect() (newConversation, conversationId)
     * @returns Session ID
     */
    createSession(interfaceType: InterfaceType, options?: {
        newConversation?: boolean;
        conversationId?: string;
    }): Promise<string>;
    /**
     * Get an existing session
     *
     * @param sessionId - Session ID
     * @returns Session or null if not found
     */
    getSession(sessionId: string): Session | null;
    /**
     * Get interface from session
     *
     * @param sessionId - Session ID
     * @returns ChatInterface instance
     * @throws Error if session not found
     */
    getInterface(sessionId: string): any;
    /**
     * Destroy a session
     *
     * @param sessionId - Session ID
     */
    destroySession(sessionId: string): Promise<void>;
    /**
     * Get all active sessions
     *
     * @returns Array of session IDs
     */
    getActiveSessions(): string[];
    /**
     * Get session count
     */
    getSessionCount(): number;
    /**
     * Destroy all sessions (cleanup)
     */
    destroyAllSessions(): Promise<void>;
    /**
     * Health check for a specific session
     * Verifies browser is responsive and updates health status
     *
     * @param sessionId - Session ID to check
     * @returns Health status ('healthy' | 'stale' | 'dead')
     */
    healthCheck(sessionId: string): Promise<'healthy' | 'stale' | 'dead'>;
    /**
     * Update session state from browser
     * Syncs conversationId and URL from current browser state
     *
     * @param sessionId - Session ID
     * @returns Updated session info
     */
    updateSessionState(sessionId: string): Promise<{
        conversationId: string | null;
        conversationUrl: string;
    }>;
    /**
     * Validate session health before tool execution
     * Throws error if session is dead
     *
     * @param sessionId - Session ID
     */
    validateSessionHealth(sessionId: string): Promise<void>;
    /**
     * Sync with database to detect orphaned sessions
     * Called on server startup
     *
     * @param conversationStore - ConversationStore instance
     */
    syncWithDatabase(conversationStore: any): Promise<void>;
}
/**
 * Get the singleton session manager instance
 */
export declare function getSessionManager(): SessionManager;
export default SessionManager;
//# sourceMappingURL=session-manager.d.ts.map