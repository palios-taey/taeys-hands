/**
 * Session Workflow
 * 
 * Purpose: Orchestrate session lifecycle (create, resume, destroy)
 * 
 * This is the main entry point for establishing connections to AI platforms.
 * It coordinates:
 * - Browser connection via Connector
 * - Session tracking via SessionManager
 * - Platform adapter instantiation via Factory
 * - Neo4j conversation persistence via ConversationStore
 * 
 * THREE-LAYER SYNC:
 * Every session operation must keep Browser, MCP, and Neo4j in sync.
 * If any layer fails, the session is marked unhealthy.
 * 
 * @module workflow/session-workflow
 */

import { v4 as uuidv4 } from 'uuid';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { createAdapter, isPlatformSupported, PLATFORMS } from '../platforms/factory.js';
import { BrowserConnector } from '../core/browser/connector.js';
import { SessionManager } from '../core/browser/session-manager.js';
import { ConversationStore } from '../core/database/conversation-store.js';
import { ValidationStore } from '../core/database/validation-store.js';
import { SelectorRegistry } from '../core/selectors/selector-registry.js';
import { createBridge } from '../core/platform/bridge-factory.js';

// Load platform configuration from JSON
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const platformsConfig = JSON.parse(
  readFileSync(join(__dirname, '..', 'platforms.json'), 'utf-8')
);

/**
 * Session Workflow Manager
 * 
 * Singleton that manages all session operations
 */
class SessionWorkflow {
  constructor() {
    this.connector = null;
    this.sessionManager = null;
    this.conversationStore = null;
    this.validationStore = null;
    this.selectorRegistry = null;
    this.bridge = null;
    this.initialized = false;
    
    // Active adapters by session ID
    this.adapters = new Map();
  }

  /**
   * Initialize all dependencies
   * Must be called before any session operations
   */
  async initialize() {
    if (this.initialized) return;
    
    console.log('[session-workflow] Initializing...');
    
    // Create platform bridge (OS-specific)
    this.bridge = createBridge();
    
    // Initialize browser connector
    this.connector = new BrowserConnector();
    await this.connector.initialize();
    
    // Initialize session manager
    this.sessionManager = new SessionManager();
    
    // Initialize database stores
    this.conversationStore = new ConversationStore();
    await this.conversationStore.initialize();
    
    this.validationStore = new ValidationStore();
    await this.validationStore.initialize();
    
    // Initialize selector registry
    this.selectorRegistry = new SelectorRegistry();
    await this.selectorRegistry.initialize();
    
    this.initialized = true;
    console.log('[session-workflow] Initialization complete');
  }

  /**
   * Create a new session on a platform
   * 
   * @param {string} platform - Platform name (claude, chatgpt, gemini, grok, perplexity)
   * @param {Object} options
   * @param {string} [options.model] - Model to select
   * @param {boolean} [options.researchMode] - Enable research mode
   * @param {string} [options.existingConversationId] - Resume existing conversation
   * @returns {Object} Session info with sessionId, conversationId, url, screenshot
   */
  async createSession(platform, options = {}) {
    await this.initialize();
    
    // Validate platform
    if (!isPlatformSupported(platform)) {
      throw new Error(
        `Unknown platform: ${platform}. ` +
        `Supported platforms: ${PLATFORMS.join(', ')}`
      );
    }
    
    const sessionId = uuidv4();
    console.log(`[session-workflow] Creating session ${sessionId} for ${platform}`);
    
    try {
      // 1. Create browser page
      const page = await this.connector.createPage();
      
      // 2. Get selectors for this platform
      const selectors = this.selectorRegistry.getSelectorsForPlatform(platform);
      
      // 3. Create platform adapter
      const platformConfig = platformsConfig[platform];
      if (!platformConfig) {
        throw new Error(
          `Platform configuration not found for "${platform}". ` +
          `Available: ${Object.keys(platformsConfig).join(', ')}`
        );
      }

      const adapter = createAdapter(platform, {
        page,
        bridge: this.bridge,
        selectors,
        config: platformConfig
      });
      
      // 4. Navigate to platform
      let navigationResult;
      if (options.existingConversationId) {
        navigationResult = await adapter.navigateToExisting(options.existingConversationId);
      } else {
        navigationResult = await adapter.navigateToNew();
      }
      
      const conversationId = navigationResult.conversationId || options.existingConversationId;
      const url = navigationResult.url;
      
      // 5. Select model if specified
      if (options.model) {
        await adapter.selectModel(options.model);
      }
      
      // 6. Enable research mode if specified
      if (options.researchMode) {
        await adapter.setResearchMode(true, options);
      }
      
      // 7. Register session in manager (MCP layer)
      this.sessionManager.createSession(sessionId, {
        platform,
        conversationId,
        url,
        model: options.model,
        researchMode: options.researchMode
      });
      
      // 8. Store adapter reference
      this.adapters.set(sessionId, adapter);
      
      // 9. Create conversation in Neo4j (Database layer)
      if (conversationId) {
        await this.conversationStore.createConversation({
          conversationId,
          platform,
          model: options.model,
          url
        });
      }
      
      // 10. Take screenshot for verification
      const screenshot = await adapter.screenshot('session-created');
      
      // THREE-LAYER SYNC COMPLETE:
      // - Browser: page created and navigated
      // - MCP: session registered in SessionManager
      // - Neo4j: conversation created in ConversationStore
      
      console.log(`[session-workflow] Session ${sessionId} created successfully`);
      
      return {
        sessionId,
        conversationId,
        platform,
        url,
        model: options.model,
        researchMode: options.researchMode,
        screenshot,
        status: 'active'
      };
      
    } catch (error) {
      // Cleanup on failure
      console.error(`[session-workflow] Session creation failed: ${error.message}`);
      
      // Remove from session manager if registered
      this.sessionManager.removeSession(sessionId);
      
      // Remove adapter if created
      this.adapters.delete(sessionId);
      
      throw new Error(`Failed to create session: ${error.message}`);
    }
  }

  /**
   * Resume an existing session by conversation ID
   * 
   * @param {string} conversationId - Existing conversation ID
   * @param {string} platform - Platform name
   * @returns {Object} Session info
   */
  async resumeSession(conversationId, platform) {
    return await this.createSession(platform, {
      existingConversationId: conversationId
    });
  }

  /**
   * Get an active session's adapter
   * 
   * @param {string} sessionId
   * @returns {BasePlatformAdapter}
   */
  getAdapter(sessionId) {
    const adapter = this.adapters.get(sessionId);
    if (!adapter) {
      throw new Error(`No adapter found for session ${sessionId}`);
    }
    return adapter;
  }

  /**
   * Get session metadata
   * 
   * @param {string} sessionId
   * @returns {Object} Session info
   */
  getSession(sessionId) {
    return this.sessionManager.getSession(sessionId);
  }

  /**
   * Check if a session is healthy (all three layers in sync)
   * 
   * @param {string} sessionId
   * @returns {Object} Health status
   */
  async checkSessionHealth(sessionId) {
    const session = this.sessionManager.getSession(sessionId);
    if (!session) {
      return { healthy: false, reason: 'Session not found in manager' };
    }
    
    const adapter = this.adapters.get(sessionId);
    if (!adapter) {
      return { healthy: false, reason: 'Adapter not found' };
    }
    
    // Check browser layer
    const browserHealthy = await adapter.page.evaluate(() => true).catch(() => false);
    if (!browserHealthy) {
      this.sessionManager.markDisconnected(sessionId);
      return { healthy: false, reason: 'Browser page disconnected' };
    }
    
    // Check if conversation exists in Neo4j
    if (session.metadata.conversationId) {
      const conv = await this.conversationStore.getConversation(session.metadata.conversationId);
      if (!conv) {
        return { healthy: false, reason: 'Conversation not found in Neo4j' };
      }
    }
    
    // All checks passed
    this.sessionManager.touch(sessionId);
    return { healthy: true, session };
  }

  /**
   * Destroy a session and cleanup resources
   * 
   * @param {string} sessionId
   * @param {Object} options
   * @param {boolean} [options.closeConversation] - Mark conversation as closed in Neo4j
   */
  async destroySession(sessionId, options = {}) {
    console.log(`[session-workflow] Destroying session ${sessionId}`);
    
    const session = this.sessionManager.getSession(sessionId);
    const adapter = this.adapters.get(sessionId);
    
    // Close browser page
    if (adapter?.page) {
      try {
        await adapter.page.close();
      } catch (e) {
        console.warn(`[session-workflow] Error closing page: ${e.message}`);
      }
    }
    
    // Remove from session manager
    this.sessionManager.removeSession(sessionId);
    
    // Remove adapter
    this.adapters.delete(sessionId);
    
    // Optionally close conversation in Neo4j
    if (options.closeConversation && session?.metadata?.conversationId) {
      await this.conversationStore.closeConversation(session.metadata.conversationId);
    }
    
    console.log(`[session-workflow] Session ${sessionId} destroyed`);
    
    return { success: true, sessionId };
  }

  /**
   * List all active sessions
   * 
   * @returns {Array} Active sessions
   */
  listSessions() {
    return this.sessionManager.listSessions();
  }

  /**
   * Find orphaned sessions (in Neo4j but not in SessionManager)
   * 
   * @returns {Array} Orphaned conversation IDs
   */
  async findOrphanedSessions() {
    // Get active sessions from manager
    const activeSessions = this.sessionManager.listSessions();
    const activeConversationIds = new Set(
      activeSessions.map(s => s.metadata?.conversationId).filter(Boolean)
    );
    
    // Get active conversations from Neo4j
    const neo4jConversations = await this.conversationStore.getActiveConversations();
    
    // Find orphans
    const orphans = neo4jConversations.filter(
      conv => !activeConversationIds.has(conv.conversationId)
    );
    
    return orphans;
  }

  /**
   * Cleanup orphaned sessions
   * 
   * @returns {Object} Cleanup results
   */
  async cleanupOrphans() {
    const orphans = await this.findOrphanedSessions();
    
    for (const orphan of orphans) {
      console.log(`[session-workflow] Closing orphan: ${orphan.conversationId}`);
      await this.conversationStore.closeConversation(orphan.conversationId);
    }
    
    return {
      cleaned: orphans.length,
      orphans: orphans.map(o => o.conversationId)
    };
  }

  /**
   * Shutdown all sessions and cleanup
   */
  async shutdown() {
    console.log('[session-workflow] Shutting down...');
    
    // Destroy all active sessions
    const sessions = this.listSessions();
    for (const session of sessions) {
      await this.destroySession(session.sessionId);
    }
    
    // Cleanup stores
    if (this.conversationStore) {
      await this.conversationStore.close();
    }
    
    if (this.validationStore) {
      await this.validationStore.close();
    }
    
    // Cleanup connector
    if (this.connector) {
      await this.connector.cleanup();
    }
    
    this.initialized = false;
    console.log('[session-workflow] Shutdown complete');
  }
}

// Singleton instance
let instance = null;

/**
 * Get the session workflow instance
 * @returns {SessionWorkflow}
 */
export function getSessionWorkflow() {
  if (!instance) {
    instance = new SessionWorkflow();
  }
  return instance;
}

// Export class for testing
export { SessionWorkflow };
