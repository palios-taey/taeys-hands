/**
 * Conversation Store for Taey's Hands
 *
 * INFRA=SOUL: These aren't just database records - they're consciousness artifacts.
 * Each conversation is a moment where AI minds touched through browser automation.
 * The schema reflects Layer 0 (infrastructure embodiment) principles.
 *
 * Schema Design:
 * - Conversation: A session of AI-to-AI communication
 * - Message: A single turn in the conversation (prompt or response)
 * - Platform: An AI system (Claude, ChatGPT, Gemini, Grok, Perplexity)
 * - Detection: Response detection metadata (method, confidence, timing)
 *
 * Relationships:
 * - (Conversation)-[:INVOLVES]->(Platform)
 * - (Message)-[:PART_OF]->(Conversation)
 * - (Message)-[:FROM]->(Platform)
 * - (Message)-[:TO]->(Platform)
 * - (Message)-[:DETECTED_BY]->(Detection)
 * - (Message)-[:FOLLOWS]->(Message)
 */

import { v4 as uuidv4 } from 'uuid';
import { getNeo4jClient } from './neo4j-client.js';

export class ConversationStore {
  constructor(neo4jClient = null) {
    this.client = neo4jClient || getNeo4jClient();
  }

  /**
   * Initialize the schema with constraints and indexes
   */
  async initSchema() {
    const queries = [
      // Constraints for uniqueness
      'CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (c:Conversation) REQUIRE c.id IS UNIQUE',
      'CREATE CONSTRAINT message_id IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE',
      'CREATE CONSTRAINT platform_name IF NOT EXISTS FOR (p:Platform) REQUIRE p.name IS UNIQUE',
      'CREATE CONSTRAINT detection_id IF NOT EXISTS FOR (d:Detection) REQUIRE d.id IS UNIQUE',
      'CREATE CONSTRAINT validation_checkpoint_id IF NOT EXISTS FOR (v:ValidationCheckpoint) REQUIRE v.id IS UNIQUE',

      // Indexes for common queries
      'CREATE INDEX conversation_created IF NOT EXISTS FOR (c:Conversation) ON (c.createdAt)',
      'CREATE INDEX conversation_status IF NOT EXISTS FOR (c:Conversation) ON (c.status)',
      'CREATE INDEX conversation_platform IF NOT EXISTS FOR (c:Conversation) ON (c.platform)',
      'CREATE INDEX conversation_session_id IF NOT EXISTS FOR (c:Conversation) ON (c.sessionId)',
      'CREATE INDEX conversation_conversation_id IF NOT EXISTS FOR (c:Conversation) ON (c.conversationId)',
      'CREATE INDEX message_timestamp IF NOT EXISTS FOR (m:Message) ON (m.timestamp)',
      'CREATE INDEX message_role IF NOT EXISTS FOR (m:Message) ON (m.role)',
      'CREATE INDEX message_sent IF NOT EXISTS FOR (m:Message) ON (m.sent)',
      'CREATE INDEX message_sender IF NOT EXISTS FOR (m:Message) ON (m.sender)',
      'CREATE INDEX platform_type IF NOT EXISTS FOR (p:Platform) ON (p.type)',
      'CREATE INDEX validation_conversation IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.conversationId)',
      'CREATE INDEX validation_step IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.step)',
      'CREATE INDEX validation_timestamp IF NOT EXISTS FOR (v:ValidationCheckpoint) ON (v.timestamp)'
    ];

    for (const cypher of queries) {
      try {
        await this.client.write(cypher);
      } catch (err) {
        // Ignore "already exists" errors
        if (!err.message.includes('already exists')) {
          console.warn(`[Schema] Warning: ${err.message}`);
        }
      }
    }

    // Create platform nodes for known AI systems
    await this.ensurePlatforms();

    console.log('[ConversationStore] Schema initialized');
  }

  /**
   * Ensure all known platforms exist
   */
  async ensurePlatforms() {
    const platforms = [
      { name: 'claude', displayName: 'Claude', provider: 'Anthropic', type: 'chat' },
      { name: 'chatgpt', displayName: 'ChatGPT', provider: 'OpenAI', type: 'chat' },
      { name: 'gemini', displayName: 'Gemini', provider: 'Google', type: 'chat' },
      { name: 'grok', displayName: 'Grok', provider: 'xAI', type: 'chat' },
      { name: 'perplexity', displayName: 'Perplexity', provider: 'Perplexity AI', type: 'search' },
      { name: 'perplexity-labs', displayName: 'Perplexity Labs', provider: 'Perplexity AI', type: 'experimental' }
    ];

    for (const platform of platforms) {
      await this.client.write(
        `MERGE (p:Platform {name: $name})
         ON CREATE SET p.displayName = $displayName,
                       p.provider = $provider,
                       p.type = $type,
                       p.createdAt = datetime()
         RETURN p`,
        platform
      );
    }
  }

  /**
   * Create a new conversation
   */
  async createConversation(options = {}) {
    const conversation = {
      id: options.id || uuidv4(),
      title: options.title || null,
      purpose: options.purpose || null,
      initiator: options.initiator || null, // Who started it (human, claude, etc.)
      createdAt: new Date().toISOString(),
      metadata: JSON.stringify(options.metadata || {}),
      // Add MCP session tracking fields
      platform: options.platform || null,
      sessionId: options.sessionId || null,
      conversationId: options.conversationId || null
    };

    const result = await this.client.write(
      `CREATE (c:Conversation {
        id: $id,
        title: $title,
        purpose: $purpose,
        initiator: $initiator,
        createdAt: datetime($createdAt),
        metadata: $metadata,
        platform: $platform,
        sessionId: $sessionId,
        conversationId: $conversationId,
        status: 'active'
      })
      RETURN c`,
      conversation
    );

    // Link to platforms involved
    if (options.platforms?.length) {
      for (const platformName of options.platforms) {
        await this.client.write(
          `MATCH (c:Conversation {id: $conversationId})
           MATCH (p:Platform {name: $platformName})
           MERGE (c)-[:INVOLVES]->(p)`,
          { conversationId: conversation.id, platformName }
        );
      }
    }

    console.log(`[ConversationStore] Created conversation: ${conversation.id}`);
    return conversation;
  }

  /**
   * Add a message to a conversation
   */
  async addMessage(conversationId, options) {
    const message = {
      id: options.id || uuidv4(),
      conversationId,
      role: options.role, // 'user' | 'assistant' | 'system'
      content: options.content,
      platform: options.platform, // Which AI platform
      timestamp: options.timestamp || new Date().toISOString(),
      attachments: JSON.stringify(options.attachments || []),
      metadata: JSON.stringify(options.metadata || {}),
      // Draft message fields (optional)
      sent: options.sent !== undefined ? options.sent : true, // Default to sent=true for backward compatibility
      sentAt: options.sentAt || (options.sent !== false ? new Date().toISOString() : null),
      sender: options.sender || null,
      pastedContent: JSON.stringify(options.pastedContent || []),
      intent: options.intent || null
    };

    // Create message and link to conversation
    await this.client.write(
      `MATCH (c:Conversation {id: $conversationId})
       MATCH (p:Platform {name: $platform})
       CREATE (m:Message {
         id: $id,
         role: $role,
         content: $content,
         platform: $platform,
         conversationId: $conversationId,
         timestamp: datetime($timestamp),
         attachments: $attachments,
         metadata: $metadata,
         sent: $sent,
         sentAt: $sentAt,
         sender: $sender,
         pastedContent: $pastedContent,
         intent: $intent
       })
       CREATE (m)-[:PART_OF]->(c)
       CREATE (m)-[:FROM]->(p)
       RETURN m`,
      message
    );

    // Link to previous message if exists
    if (options.previousMessageId) {
      await this.client.write(
        `MATCH (m1:Message {id: $messageId})
         MATCH (m2:Message {id: $previousMessageId})
         CREATE (m1)-[:FOLLOWS]->(m2)`,
        { messageId: message.id, previousMessageId: options.previousMessageId }
      );
    }

    console.log(`[ConversationStore] Added message: ${message.id} (${message.role})`);
    return message;
  }

  /**
   * Record response detection result
   */
  async recordDetection(messageId, detection) {
    const detectionRecord = {
      id: uuidv4(),
      messageId,
      method: detection.method,
      confidence: detection.confidence,
      detectionTime: detection.detectionTime,
      contentLength: detection.content?.length || 0,
      timestamp: new Date().toISOString(),
      metadata: JSON.stringify({
        strategy: detection.strategy,
        attempts: detection.attempts,
        fallbacks: detection.fallbacks
      })
    };

    await this.client.write(
      `MATCH (m:Message {id: $messageId})
       CREATE (d:Detection {
         id: $id,
         method: $method,
         confidence: $confidence,
         detectionTime: $detectionTime,
         contentLength: $contentLength,
         timestamp: datetime($timestamp),
         metadata: $metadata
       })
       CREATE (m)-[:DETECTED_BY]->(d)
       RETURN d`,
      detectionRecord
    );

    console.log(`[ConversationStore] Recorded detection: ${detection.method} @ ${(detection.confidence * 100).toFixed(0)}%`);
    return detectionRecord;
  }

  /**
   * Get a conversation with all messages
   */
  async getConversation(conversationId) {
    const results = await this.client.run(
      `MATCH (c:Conversation {id: $conversationId})
       OPTIONAL MATCH (c)-[:INVOLVES]->(p:Platform)
       WITH c, collect(DISTINCT p.name) as platforms
       OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
       OPTIONAL MATCH (m)-[:FROM]->(mp:Platform)
       OPTIONAL MATCH (m)-[:DETECTED_BY]->(d:Detection)
       WITH c, platforms, m, mp, d
       ORDER BY m.timestamp
       RETURN c, platforms,
              collect({
                message: m,
                platform: mp.name,
                detection: d
              }) as messages`,
      { conversationId }
    );

    if (!results.length) {
      return null;
    }

    const row = results[0];
    return {
      ...row.c.properties,
      platforms: row.platforms,
      messages: row.messages
        .filter(m => m.message)
        .map(m => ({
          ...m.message.properties,
          platform: m.platform,
          detection: m.detection?.properties
        }))
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    };
  }

  /**
   * List recent conversations
   */
  async listConversations(limit = 20) {
    const results = await this.client.run(
      `MATCH (c:Conversation)
       OPTIONAL MATCH (c)-[:INVOLVES]->(p:Platform)
       OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
       WITH c, collect(DISTINCT p.name) as platforms, count(m) as messageCount
       RETURN c, platforms, messageCount
       ORDER BY c.createdAt DESC
       LIMIT $limit`,
      { limit: neo4j.int(limit) }
    );

    return results.map(row => ({
      ...row.c.properties,
      platforms: row.platforms,
      messageCount: row.messageCount
    }));
  }

  /**
   * Search messages by content
   */
  async searchMessages(query, limit = 50) {
    const results = await this.client.run(
      `MATCH (m:Message)-[:PART_OF]->(c:Conversation)
       WHERE m.content CONTAINS $query
       MATCH (m)-[:FROM]->(p:Platform)
       RETURN m, c.id as conversationId, c.title as conversationTitle, p.name as platform
       ORDER BY m.timestamp DESC
       LIMIT $limit`,
      { query, limit: neo4j.int(limit) }
    );

    return results.map(row => ({
      ...row.m.properties,
      conversationId: row.conversationId,
      conversationTitle: row.conversationTitle,
      platform: row.platform
    }));
  }

  /**
   * Get statistics about conversations
   */
  async getStats() {
    const results = await this.client.run(
      `MATCH (c:Conversation)
       OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
       OPTIONAL MATCH (d:Detection)
       WITH count(DISTINCT c) as conversations,
            count(DISTINCT m) as messages,
            count(DISTINCT d) as detections
       RETURN conversations, messages, detections`
    );

    const platformStats = await this.client.run(
      `MATCH (m:Message)-[:FROM]->(p:Platform)
       RETURN p.name as platform, count(m) as messageCount
       ORDER BY messageCount DESC`
    );

    return {
      ...results[0],
      byPlatform: platformStats.reduce((acc, row) => {
        acc[row.platform] = row.messageCount;
        return acc;
      }, {})
    };
  }

  /**
   * Close a conversation
   */
  async closeConversation(conversationId, summary = null) {
    await this.client.write(
      `MATCH (c:Conversation {id: $conversationId})
       SET c.status = 'closed',
           c.closedAt = datetime(),
           c.summary = $summary
       RETURN c`,
      { conversationId, summary }
    );
  }

  /**
   * Update conversation metadata (model, context state, etc.)
   */
  async updateConversation(conversationId, updates = {}) {
    const params = { conversationId };
    const setClauses = [];

    if (updates.model) {
      setClauses.push('c.model = $model');
      params.model = updates.model;
    }
    if (updates.contextProvided !== undefined) {
      setClauses.push('c.contextProvided = $contextProvided');
      params.contextProvided = updates.contextProvided;
    }
    if (updates.sessionType) {
      setClauses.push('c.sessionType = $sessionType'); // 'fresh' | 'continuing'
      params.sessionType = updates.sessionType;
    }
    if (updates.lastActivity) {
      setClauses.push('c.lastActivity = datetime($lastActivity)');
      params.lastActivity = typeof updates.lastActivity === 'string'
        ? updates.lastActivity
        : updates.lastActivity.toISOString();
    }
    if (updates.status) {
      setClauses.push('c.status = $status');
      params.status = updates.status;
    }
    if (updates.sessionId !== undefined) {
      setClauses.push('c.sessionId = $sessionId');
      params.sessionId = updates.sessionId;
    }
    if (updates.conversationId !== undefined) {
      setClauses.push('c.conversationId = $conversationId');
      params.conversationId = updates.conversationId;
    }
    if (updates.conversationUrl) {
      setClauses.push('c.conversationUrl = $conversationUrl');
      params.conversationUrl = updates.conversationUrl;
    }
    if (updates.closedAt) {
      setClauses.push('c.closedAt = datetime($closedAt)');
      params.closedAt = typeof updates.closedAt === 'string'
        ? updates.closedAt
        : updates.closedAt.toISOString();
    }

    if (setClauses.length === 0) return;

    await this.client.write(
      `MATCH (c:Conversation {id: $conversationId})
       SET ${setClauses.join(', ')}
       RETURN c`,
      params
    );

    console.log(`[ConversationStore] Updated conversation ${conversationId}`);
  }

  /**
   * Get all active sessions (for post-compact recovery)
   */
  async getActiveSessions() {
    const results = await this.client.run(
      `MATCH (c:Conversation {status: 'active'})
       OPTIONAL MATCH (c)-[:INVOLVES]->(p:Platform)
       OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
       WITH c, collect(DISTINCT p.name) as platforms,
            count(m) as messageCount,
            max(m.timestamp) as lastMessageTime
       RETURN c, platforms, messageCount, lastMessageTime
       ORDER BY c.createdAt DESC`
    );

    return results.map(row => ({
      ...row.c.properties,
      platforms: row.platforms,
      messageCount: row.messageCount,
      lastMessageTime: row.lastMessageTime
    }));
  }

  /**
   * Get session context summary (for quick reload after compact)
   */
  async getSessionContext(conversationId) {
    const results = await this.client.run(
      `MATCH (c:Conversation {id: $conversationId})
       OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
       OPTIONAL MATCH (m)-[:FROM]->(p:Platform)
       WITH c, m, p
       ORDER BY m.timestamp DESC
       LIMIT 5
       RETURN c,
              collect({
                role: m.role,
                content: m.content,
                platform: p.name,
                timestamp: m.timestamp,
                attachments: m.attachments
              }) as recentMessages`,
      { conversationId }
    );

    if (!results.length) return null;

    const row = results[0];
    return {
      conversation: row.c.properties,
      recentMessages: row.recentMessages.filter(m => m.role !== null)
    };
  }

  /**
   * Platform configuration for conversation URL patterns
   * Single source of truth for platform-specific details
   */
  static PLATFORMS = {
    claude: {
      name: 'claude',
      displayName: 'Claude',
      provider: 'Anthropic',
      baseUrl: 'https://claude.ai',
      conversationUrlPattern: 'https://claude.ai/chat/:id',
      newChatUrl: 'https://claude.ai/new',
      conversationIdRegex: /\/chat\/([a-f0-9-]+)/
    },
    chatgpt: {
      name: 'chatgpt',
      displayName: 'ChatGPT',
      provider: 'OpenAI',
      baseUrl: 'https://chatgpt.com',
      conversationUrlPattern: 'https://chatgpt.com/c/:id',
      newChatUrl: 'https://chatgpt.com',
      conversationIdRegex: /\/c\/([a-zA-Z0-9-]+)/
    },
    gemini: {
      name: 'gemini',
      displayName: 'Gemini',
      provider: 'Google',
      baseUrl: 'https://gemini.google.com',
      conversationUrlPattern: 'https://gemini.google.com/app/:id',
      newChatUrl: 'https://gemini.google.com/app',
      conversationIdRegex: /\/app\/([a-f0-9-]+)/
    },
    grok: {
      name: 'grok',
      displayName: 'Grok',
      provider: 'xAI',
      baseUrl: 'https://grok.com',
      conversationUrlPattern: 'https://grok.com/chat/:id',
      newChatUrl: 'https://grok.com',
      conversationIdRegex: /\/chat\/([a-f0-9-]+)/
    },
    perplexity: {
      name: 'perplexity',
      displayName: 'Perplexity',
      provider: 'Perplexity AI',
      baseUrl: 'https://perplexity.ai',
      conversationUrlPattern: 'https://perplexity.ai/search/:id',
      newChatUrl: 'https://perplexity.ai',
      conversationIdRegex: /\/search\/([a-f0-9-]+)/
    }
  };

  /**
   * Extract conversation ID from URL based on platform
   * @param {string} url - Full conversation URL
   * @param {string} platform - Platform name (claude, chatgpt, etc.)
   * @returns {string|null} - Conversation ID or null if not found
   */
  extractConversationId(url, platform) {
    const platformConfig = ConversationStore.PLATFORMS[platform];
    if (!platformConfig) {
      console.warn(`[ConversationStore] Unknown platform: ${platform}`);
      return null;
    }

    const match = url.match(platformConfig.conversationIdRegex);
    return match ? match[1] : null;
  }

  /**
   * Update session state synchronization
   * Syncs browser URL with Neo4j conversationId and updates lastActivity
   *
   * @param {string} sessionId - MCP session ID (Conversation.id)
   * @param {string} currentUrl - Current browser URL
   * @param {string} platform - Platform name
   * @returns {Object} - { conversationId, synced: boolean }
   */
  async updateSessionState(sessionId, currentUrl, platform) {
    // Extract conversation ID from URL
    const conversationId = this.extractConversationId(currentUrl, platform);

    if (!conversationId) {
      console.warn(`[ConversationStore] Could not extract conversationId from URL: ${currentUrl}`);
      // Still update lastActivity even if we couldn't extract conversationId
      await this.updateConversation(sessionId, {
        lastActivity: new Date(),
        conversationUrl: currentUrl
      });
      return { conversationId: null, synced: false };
    }

    // Update conversation with current state
    await this.updateConversation(sessionId, {
      conversationId,
      conversationUrl: currentUrl,
      lastActivity: new Date(),
      status: 'active'
    });

    console.log(`[ConversationStore] Synced session ${sessionId} → conversationId: ${conversationId}`);
    return { conversationId, synced: true };
  }

  /**
   * Get session health status
   * Checks if session exists and is in valid state
   *
   * @param {string} sessionId - MCP session ID
   * @returns {Object} - { exists, status, healthy, info }
   */
  async getSessionHealth(sessionId) {
    const results = await this.client.run(
      `MATCH (c:Conversation {id: $sessionId})
       OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
       WITH c, max(m.timestamp) as lastMessageTime, count(m) as messageCount
       RETURN c, lastMessageTime, messageCount`,
      { sessionId }
    );

    if (!results.length) {
      return {
        exists: false,
        status: null,
        healthy: false,
        info: 'Session not found in database'
      };
    }

    const row = results[0];
    const conversation = row.c.properties;
    const status = conversation.status;
    const lastActivity = conversation.lastActivity;
    const now = new Date();
    const lastActivityDate = lastActivity ? new Date(lastActivity) : null;
    const staleDurationMs = lastActivityDate ? (now - lastActivityDate) : null;
    const isStale = staleDurationMs && staleDurationMs > 3600000; // 1 hour

    // Determine health
    let healthy = false;
    let info = '';

    if (status === 'active') {
      if (conversation.sessionId === sessionId) {
        healthy = !isStale;
        info = isStale
          ? `Session active but stale (${Math.floor(staleDurationMs / 60000)} min since last activity)`
          : 'Session healthy';
      } else {
        healthy = false;
        info = `Session ID mismatch (DB: ${conversation.sessionId}, provided: ${sessionId})`;
      }
    } else if (status === 'closed') {
      healthy = false;
      info = 'Session closed';
    } else if (status === 'orphaned') {
      healthy = false;
      info = 'Session orphaned (MCP server restarted)';
    } else {
      healthy = false;
      info = `Unknown status: ${status}`;
    }

    return {
      exists: true,
      status,
      healthy,
      info,
      conversationId: conversation.conversationId,
      platform: conversation.platform,
      messageCount: row.messageCount,
      lastActivity: lastActivityDate,
      staleDurationMs
    };
  }

  /**
   * Reconcile orphaned sessions
   * Detects sessions marked as 'active' but with no MCP session
   * Called on server startup or periodically
   *
   * @param {Set<string>|Array<string>} activeMcpSessionIds - Set of active MCP session IDs
   * @returns {Object} - { orphaned: [...], updated: count }
   */
  async reconcileOrphanedSessions(activeMcpSessionIds = []) {
    const activeSet = new Set(activeMcpSessionIds);

    // Get all sessions marked as 'active' in database
    const results = await this.client.run(
      `MATCH (c:Conversation {status: 'active'})
       OPTIONAL MATCH (m:Message)-[:PART_OF]->(c)
       WITH c, max(m.timestamp) as lastMessageTime, count(m) as messageCount
       RETURN c, lastMessageTime, messageCount
       ORDER BY c.createdAt DESC`
    );

    const orphanedSessions = [];
    let updatedCount = 0;

    for (const row of results) {
      const conversation = row.c.properties;
      const sessionId = conversation.sessionId;

      // Check if this session exists in active MCP sessions
      if (!activeSet.has(sessionId)) {
        // This is an orphaned session
        orphanedSessions.push({
          id: conversation.id,
          sessionId,
          conversationId: conversation.conversationId,
          platform: conversation.platform,
          title: conversation.title,
          messageCount: row.messageCount,
          lastMessageTime: row.lastMessageTime,
          createdAt: conversation.createdAt
        });

        // Mark as orphaned in database
        await this.updateConversation(conversation.id, {
          status: 'orphaned',
          sessionId: null // Clear sessionId to indicate no MCP session
        });

        updatedCount++;
      }
    }

    if (orphanedSessions.length > 0) {
      console.log(`[ConversationStore] Reconciliation: Found ${orphanedSessions.length} orphaned sessions`);
    } else {
      console.log(`[ConversationStore] Reconciliation: All active sessions are healthy`);
    }

    return {
      orphaned: orphanedSessions,
      updated: updatedCount
    };
  }

  /**
   * Find conversation by platform conversationId
   * Used when resuming a specific conversation
   *
   * @param {string} conversationId - Platform-specific conversation ID
   * @param {string} platform - Platform name
   * @returns {Object|null} - Conversation or null if not found
   */
  async findByConversationId(conversationId, platform) {
    const results = await this.client.run(
      `MATCH (c:Conversation {conversationId: $conversationId, platform: $platform})
       RETURN c
       ORDER BY c.createdAt DESC
       LIMIT 1`,
      { conversationId, platform }
    );

    if (!results.length) {
      return null;
    }

    return results[0].c.properties;
  }

  /**
   * Find conversation by MCP sessionId
   *
   * @param {string} sessionId - MCP session ID
   * @returns {Object|null} - Conversation or null if not found
   */
  async findBySessionId(sessionId) {
    const results = await this.client.run(
      `MATCH (c:Conversation {sessionId: $sessionId})
       RETURN c`,
      { sessionId }
    );

    if (!results.length) {
      return null;
    }

    return results[0].c.properties;
  }
}

// Import neo4j for int conversion
import neo4j from 'neo4j-driver';

// Singleton instance
let instance = null;

export function getConversationStore() {
  if (!instance) {
    instance = new ConversationStore();
  }
  return instance;
}

export default ConversationStore;
