/**
 * Session Manager
 * 
 * Purpose: Registry for active browser sessions with health monitoring
 * Dependencies: uuid
 * Exports: SessionManager class
 * 
 * Key concepts:
 * - sessionId: Our UUID identifier (MCP session)
 * - conversationId: Platform-specific chat ID (from URL)
 * - Session lifecycle: creating → active → stale → disconnected
 * 
 * @module core/browser/session-manager
 */

import { v4 as uuidv4 } from 'uuid';

/**
 * Session health states
 */
export const SESSION_STATES = {
  CREATING: 'creating',
  ACTIVE: 'active',
  STALE: 'stale',
  DISCONNECTED: 'disconnected'
};

/**
 * Session registry and lifecycle management
 */
export class SessionManager {
  constructor() {
    /**
     * Map of sessionId → Session
     * @type {Map<string, Session>}
     */
    this.sessions = new Map();
    
    /**
     * Health check interval (ms)
     */
    this.healthCheckInterval = 30000;
    
    /**
     * Health check timer
     */
    this.healthCheckTimer = null;
  }

  /**
   * Create a new session
   * 
   * @param {Object} options
   * @param {string} options.platform - Platform name (claude, chatgpt, etc.)
   * @param {Object} options.page - Playwright page object
   * @param {Object} options.adapter - Platform adapter instance
   * @param {string} [options.conversationId] - Platform conversation ID
   * @returns {Session}
   */
  createSession(options) {
    const { platform, page, adapter, conversationId } = options;
    
    const sessionId = uuidv4();
    const now = new Date();
    
    const session = {
      sessionId,
      platform,
      page,
      adapter,
      conversationId: conversationId || null,
      conversationUrl: null,
      state: SESSION_STATES.CREATING,
      createdAt: now,
      lastActivity: now,
      lastHealthCheck: now,
      healthStatus: 'healthy',
      messageCount: 0,
      metadata: {}
    };
    
    this.sessions.set(sessionId, session);
    
    console.log(`[SessionManager] Created session ${sessionId} for ${platform}`);
    
    return session;
  }

  /**
   * Activate a session (mark as ready for use)
   * 
   * @param {string} sessionId
   * @param {Object} [options]
   * @param {string} [options.conversationId] - Platform conversation ID
   * @param {string} [options.conversationUrl] - Full conversation URL
   * @returns {Session}
   */
  activateSession(sessionId, options = {}) {
    const session = this.getSession(sessionId);
    
    session.state = SESSION_STATES.ACTIVE;
    session.conversationId = options.conversationId || session.conversationId;
    session.conversationUrl = options.conversationUrl || null;
    session.lastActivity = new Date();
    
    console.log(`[SessionManager] Activated session ${sessionId}`);
    
    return session;
  }

  /**
   * Get a session by ID
   * 
   * @param {string} sessionId
   * @returns {Session}
   * @throws {Error} If session not found
   */
  getSession(sessionId) {
    const session = this.sessions.get(sessionId);
    
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }
    
    return session;
  }

  /**
   * Check if a session exists
   * 
   * @param {string} sessionId
   * @returns {boolean}
   */
  hasSession(sessionId) {
    return this.sessions.has(sessionId);
  }

  /**
   * Update session activity timestamp
   * 
   * @param {string} sessionId
   */
  touchSession(sessionId) {
    const session = this.getSession(sessionId);
    session.lastActivity = new Date();
  }

  /**
   * Increment message count for a session
   * 
   * @param {string} sessionId
   */
  incrementMessageCount(sessionId) {
    const session = this.getSession(sessionId);
    session.messageCount++;
    session.lastActivity = new Date();
  }

  /**
   * Update session metadata
   * 
   * @param {string} sessionId
   * @param {Object} metadata
   */
  updateMetadata(sessionId, metadata) {
    const session = this.getSession(sessionId);
    session.metadata = { ...session.metadata, ...metadata };
    session.lastActivity = new Date();
  }

  /**
   * Mark a session as stale (browser may be dead)
   * 
   * @param {string} sessionId
   */
  markStale(sessionId) {
    const session = this.getSession(sessionId);
    session.state = SESSION_STATES.STALE;
    session.healthStatus = 'stale';
    
    console.log(`[SessionManager] Session ${sessionId} marked as stale`);
  }

  /**
   * Remove a session
   * 
   * @param {string} sessionId
   * @returns {boolean} True if removed
   */
  removeSession(sessionId) {
    const session = this.sessions.get(sessionId);
    
    if (session) {
      session.state = SESSION_STATES.DISCONNECTED;
      this.sessions.delete(sessionId);
      console.log(`[SessionManager] Removed session ${sessionId}`);
      return true;
    }
    
    return false;
  }

  /**
   * Get all active sessions
   * 
   * @returns {Session[]}
   */
  getActiveSessions() {
    return Array.from(this.sessions.values())
      .filter(s => s.state === SESSION_STATES.ACTIVE);
  }

  /**
   * Get sessions by platform
   * 
   * @param {string} platform
   * @returns {Session[]}
   */
  getSessionsByPlatform(platform) {
    return Array.from(this.sessions.values())
      .filter(s => s.platform === platform);
  }

  /**
   * Check health of all sessions
   * 
   * @returns {Promise<Object[]>} Health status of each session
   */
  async checkHealth() {
    const results = [];
    
    for (const session of this.sessions.values()) {
      const result = await this.checkSessionHealth(session);
      results.push(result);
    }
    
    return results;
  }

  /**
   * Check health of a single session
   * 
   * @param {Session} session
   * @returns {Promise<Object>}
   */
  async checkSessionHealth(session) {
    const now = new Date();
    
    try {
      // Check if page is still connected
      const isAlive = await this.isPageAlive(session.page);
      
      if (isAlive) {
        // Check URL matches expected
        const currentUrl = session.page.url();
        const urlMatches = !session.conversationUrl || 
                          currentUrl.includes(session.conversationId || '');
        
        session.lastHealthCheck = now;
        session.healthStatus = urlMatches ? 'healthy' : 'url_mismatch';
        
        return {
          sessionId: session.sessionId,
          healthy: true,
          urlMatches,
          currentUrl,
          lastActivity: session.lastActivity
        };
      } else {
        // Page is dead
        this.markStale(session.sessionId);
        
        return {
          sessionId: session.sessionId,
          healthy: false,
          reason: 'Page disconnected',
          lastActivity: session.lastActivity
        };
      }
    } catch (error) {
      this.markStale(session.sessionId);
      
      return {
        sessionId: session.sessionId,
        healthy: false,
        reason: error.message,
        lastActivity: session.lastActivity
      };
    }
  }

  /**
   * Check if a Playwright page is still alive
   * 
   * @param {Page} page
   * @returns {Promise<boolean>}
   */
  async isPageAlive(page) {
    try {
      await page.evaluate(() => true);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Start periodic health checks
   * 
   * @param {number} [intervalMs=30000] - Check interval in ms
   */
  startHealthChecks(intervalMs = 30000) {
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
    }
    
    this.healthCheckInterval = intervalMs;
    
    this.healthCheckTimer = setInterval(async () => {
      try {
        await this.checkHealth();
      } catch (error) {
        console.error('[SessionManager] Health check error:', error);
      }
    }, intervalMs);
    
    console.log(`[SessionManager] Started health checks every ${intervalMs}ms`);
  }

  /**
   * Stop health checks
   */
  stopHealthChecks() {
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
      console.log('[SessionManager] Stopped health checks');
    }
  }

  /**
   * Clean up all sessions (for shutdown)
   * 
   * @returns {Promise<number>} Number of sessions cleaned up
   */
  async cleanupAll() {
    const count = this.sessions.size;
    
    for (const session of this.sessions.values()) {
      try {
        if (session.page) {
          await session.page.close();
        }
      } catch (error) {
        console.warn(`[SessionManager] Error closing page for ${session.sessionId}:`, error.message);
      }
    }
    
    this.sessions.clear();
    this.stopHealthChecks();
    
    console.log(`[SessionManager] Cleaned up ${count} sessions`);
    
    return count;
  }

  /**
   * Get session summary for debugging
   * 
   * @returns {Object}
   */
  getSummary() {
    const sessions = Array.from(this.sessions.values());
    
    return {
      total: sessions.length,
      byState: {
        creating: sessions.filter(s => s.state === SESSION_STATES.CREATING).length,
        active: sessions.filter(s => s.state === SESSION_STATES.ACTIVE).length,
        stale: sessions.filter(s => s.state === SESSION_STATES.STALE).length,
        disconnected: sessions.filter(s => s.state === SESSION_STATES.DISCONNECTED).length
      },
      byPlatform: sessions.reduce((acc, s) => {
        acc[s.platform] = (acc[s.platform] || 0) + 1;
        return acc;
      }, {}),
      sessions: sessions.map(s => ({
        sessionId: s.sessionId,
        platform: s.platform,
        state: s.state,
        conversationId: s.conversationId,
        messageCount: s.messageCount,
        lastActivity: s.lastActivity
      }))
    };
  }
}

/**
 * Singleton instance
 */
let managerInstance = null;

/**
 * Get the singleton SessionManager instance
 * 
 * @returns {SessionManager}
 */
export function getSessionManager() {
  if (!managerInstance) {
    managerInstance = new SessionManager();
  }
  return managerInstance;
}
