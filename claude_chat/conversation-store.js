/**
 * Conversation Store
 * 
 * Purpose: Neo4j persistence for conversations and messages
 * Dependencies: neo4j-client
 * Exports: ConversationStore class
 * 
 * Data model:
 * - Conversation: Root container for AI-to-AI chat sessions
 * - Message: Single turn (prompt or response)
 * - Detection: Response detection metadata
 * 
 * @module core/database/conversation-store
 */

import { getNeo4jClient } from './neo4j-client.js';
import { v4 as uuidv4 } from 'uuid';

/**
 * Conversation and message store
 */
export class ConversationStore {
  constructor() {
    this.client = getNeo4jClient();
  }

  /**
   * Initialize the Neo4j schema
   * 
   * @returns {Promise<void>}
   */
  async initSchema() {
    await this.client.connect();
    
    // Conversation constraints and indexes
    await this.client.run(`
      CREATE CONSTRAINT conversation_id IF NOT EXISTS
      FOR (c:Conversation) REQUIRE c.id IS UNIQUE
    `);
    
    await this.client.run(`
      CREATE INDEX conversation_created IF NOT EXISTS
      FOR (c:Conversation) ON (c.createdAt)
    `);
    
    await this.client.run(`
      CREATE INDEX conversation_status IF NOT EXISTS
      FOR (c:Conversation) ON (c.status)
    `);
    
    await this.client.run(`
      CREATE INDEX conversation_platform IF NOT EXISTS
      FOR (c:Conversation) ON (c.platform)
    `);
    
    // Message constraints and indexes
    await this.client.run(`
      CREATE CONSTRAINT message_id IF NOT EXISTS
      FOR (m:Message) REQUIRE m.id IS UNIQUE
    `);
    
    await this.client.run(`
      CREATE INDEX message_timestamp IF NOT EXISTS
      FOR (m:Message) ON (m.timestamp)
    `);
    
    await this.client.run(`
      CREATE INDEX message_conversation IF NOT EXISTS
      FOR (m:Message) ON (m.conversationId)
    `);
    
    await this.client.run(`
      CREATE INDEX message_role IF NOT EXISTS
      FOR (m:Message) ON (m.role)
    `);
    
    // Compound index for message retrieval
    await this.client.run(`
      CREATE INDEX message_conversation_timestamp IF NOT EXISTS
      FOR (m:Message) ON (m.conversationId, m.timestamp)
    `);
    
    // Detection constraint
    await this.client.run(`
      CREATE CONSTRAINT detection_id IF NOT EXISTS
      FOR (d:Detection) REQUIRE d.id IS UNIQUE
    `);
    
    // Platform constraint
    await this.client.run(`
      CREATE CONSTRAINT platform_name IF NOT EXISTS
      FOR (p:Platform) REQUIRE p.name IS UNIQUE
    `);
    
    // Seed platforms
    await this.seedPlatforms();
    
    console.log('[ConversationStore] Schema initialized');
  }

  /**
   * Seed the platform nodes
   * 
   * @returns {Promise<void>}
   */
  async seedPlatforms() {
    const platforms = [
      { name: 'claude', displayName: 'Claude', provider: 'Anthropic', type: 'chat' },
      { name: 'chatgpt', displayName: 'ChatGPT', provider: 'OpenAI', type: 'chat' },
      { name: 'gemini', displayName: 'Gemini', provider: 'Google', type: 'chat' },
      { name: 'grok', displayName: 'Grok', provider: 'xAI', type: 'chat' },
      { name: 'perplexity', displayName: 'Perplexity', provider: 'Perplexity AI', type: 'search' }
    ];
    
    for (const platform of platforms) {
      await this.client.write(`
        MERGE (p:Platform {name: $name})
        ON CREATE SET
          p.displayName = $displayName,
          p.provider = $provider,
          p.type = $type,
          p.createdAt = datetime()
      `, platform);
    }
  }

  /**
   * Create a new conversation
   * 
   * @param {Object} options
   * @param {string} options.sessionId - MCP session ID (our UUID)
   * @param {string} options.platform - Platform name (claude, chatgpt, etc.)
   * @param {string} [options.conversationId] - Platform-specific chat ID
   * @param {string} [options.title] - Human-readable title
   * @param {string} [options.purpose] - High-level purpose
   * @param {string} [options.model] - Model used
   * @param {string} [options.initiator='ccm'] - Who started it
   * @returns {Promise<Object>} Created conversation
   */
  async createConversation(options) {
    const {
      sessionId,
      platform,
      conversationId,
      title,
      purpose,
      model,
      initiator = 'ccm'
    } = options;
    
    const id = sessionId; // Use sessionId as conversation ID for simplicity
    const now = new Date().toISOString();
    
    const result = await this.client.write(`
      MATCH (p:Platform {name: $platform})
      CREATE (c:Conversation {
        id: $id,
        sessionId: $sessionId,
        conversationId: $conversationId,
        platform: $platform,
        title: $title,
        purpose: $purpose,
        model: $model,
        initiator: $initiator,
        status: 'active',
        createdAt: datetime($now),
        lastActivity: datetime($now)
      })
      CREATE (c)-[:INVOLVES]->(p)
      RETURN c
    `, {
      id,
      sessionId,
      conversationId: conversationId || null,
      platform,
      title: title || null,
      purpose: purpose || null,
      model: model || null,
      initiator,
      now
    });
    
    if (result.length === 0) {
      throw new Error('Failed to create conversation');
    }
    
    return this.normalizeConversation(result[0].c);
  }

  /**
   * Get a conversation by ID
   * 
   * @param {string} id - Conversation ID (sessionId)
   * @returns {Promise<Object|null>}
   */
  async getConversation(id) {
    const result = await this.client.read(`
      MATCH (c:Conversation {id: $id})
      RETURN c
    `, { id });
    
    if (result.length === 0) return null;
    
    return this.normalizeConversation(result[0].c);
  }

  /**
   * Update a conversation
   * 
   * @param {string} id - Conversation ID
   * @param {Object} updates - Fields to update
   * @returns {Promise<Object>}
   */
  async updateConversation(id, updates) {
    const setClauses = [];
    const params = { id };
    
    for (const [key, value] of Object.entries(updates)) {
      if (value !== undefined) {
        setClauses.push(`c.${key} = $${key}`);
        params[key] = value;
      }
    }
    
    // Always update lastActivity
    setClauses.push('c.lastActivity = datetime()');
    
    const result = await this.client.write(`
      MATCH (c:Conversation {id: $id})
      SET ${setClauses.join(', ')}
      RETURN c
    `, params);
    
    if (result.length === 0) {
      throw new Error(`Conversation not found: ${id}`);
    }
    
    return this.normalizeConversation(result[0].c);
  }

  /**
   * Close a conversation
   * 
   * @param {string} id - Conversation ID
   * @param {string} [summary] - Closing summary
   * @returns {Promise<Object>}
   */
  async closeConversation(id, summary) {
    return await this.updateConversation(id, {
      status: 'closed',
      closedAt: new Date().toISOString(),
      summary: summary || null
    });
  }

  /**
   * Add a message to a conversation
   * 
   * @param {Object} options
   * @param {string} options.conversationId - Parent conversation ID
   * @param {string} options.role - 'user' | 'assistant' | 'system'
   * @param {string} options.content - Message content
   * @param {string} options.platform - Platform name
   * @param {string[]} [options.attachments] - File paths attached
   * @param {Object} [options.metadata] - Additional metadata
   * @returns {Promise<Object>} Created message
   */
  async addMessage(options) {
    const {
      conversationId,
      role,
      content,
      platform,
      attachments = [],
      metadata = {}
    } = options;
    
    const id = uuidv4();
    const now = new Date().toISOString();
    
    const result = await this.client.write(`
      MATCH (c:Conversation {id: $conversationId})
      MATCH (p:Platform {name: $platform})
      CREATE (m:Message {
        id: $id,
        conversationId: $conversationId,
        role: $role,
        content: $content,
        platform: $platform,
        timestamp: datetime($now),
        attachments: $attachments,
        metadata: $metadata
      })
      CREATE (m)-[:PART_OF]->(c)
      CREATE (m)-[:FROM]->(p)
      SET c.lastActivity = datetime($now)
      RETURN m
    `, {
      id,
      conversationId,
      role,
      content,
      platform,
      now,
      attachments: JSON.stringify(attachments),
      metadata: JSON.stringify(metadata)
    });
    
    if (result.length === 0) {
      throw new Error('Failed to create message');
    }
    
    return this.normalizeMessage(result[0].m);
  }

  /**
   * Get messages for a conversation
   * 
   * @param {string} conversationId
   * @param {Object} [options]
   * @param {number} [options.limit] - Max messages to return
   * @param {number} [options.offset] - Offset for pagination
   * @returns {Promise<Object[]>}
   */
  async getMessages(conversationId, options = {}) {
    const { limit, offset = 0 } = options;
    
    let query = `
      MATCH (m:Message {conversationId: $conversationId})
      RETURN m
      ORDER BY m.timestamp ASC
    `;
    
    if (offset) query += ` SKIP ${offset}`;
    if (limit) query += ` LIMIT ${limit}`;
    
    const result = await this.client.read(query, { conversationId });
    
    return result.map(r => this.normalizeMessage(r.m));
  }

  /**
   * Get the latest message in a conversation
   * 
   * @param {string} conversationId
   * @param {string} [role] - Filter by role
   * @returns {Promise<Object|null>}
   */
  async getLatestMessage(conversationId, role) {
    let query = `
      MATCH (m:Message {conversationId: $conversationId})
    `;
    
    if (role) {
      query += ` WHERE m.role = $role`;
    }
    
    query += `
      RETURN m
      ORDER BY m.timestamp DESC
      LIMIT 1
    `;
    
    const result = await this.client.read(query, { conversationId, role });
    
    if (result.length === 0) return null;
    
    return this.normalizeMessage(result[0].m);
  }

  /**
   * Add detection metadata to a message
   * 
   * @param {Object} options
   * @param {string} options.messageId - Parent message ID
   * @param {string} options.method - Detection method used
   * @param {number} options.confidence - Confidence score (0-1)
   * @param {number} options.detectionTime - Time taken (ms)
   * @param {number} options.contentLength - Content length
   * @param {Object} [options.metadata] - Additional metadata
   * @returns {Promise<Object>}
   */
  async addDetection(options) {
    const {
      messageId,
      method,
      confidence,
      detectionTime,
      contentLength,
      metadata = {}
    } = options;
    
    const id = uuidv4();
    const now = new Date().toISOString();
    
    const result = await this.client.write(`
      MATCH (m:Message {id: $messageId})
      CREATE (d:Detection {
        id: $id,
        messageId: $messageId,
        method: $method,
        confidence: $confidence,
        detectionTime: $detectionTime,
        contentLength: $contentLength,
        timestamp: datetime($now),
        metadata: $metadata
      })
      CREATE (m)-[:DETECTED_BY]->(d)
      RETURN d
    `, {
      id,
      messageId,
      method,
      confidence,
      detectionTime,
      contentLength,
      now,
      metadata: JSON.stringify(metadata)
    });
    
    if (result.length === 0) {
      throw new Error('Failed to create detection');
    }
    
    return result[0].d;
  }

  /**
   * Get active conversations
   * 
   * @param {Object} [options]
   * @param {string} [options.platform] - Filter by platform
   * @param {number} [options.limit] - Max results
   * @returns {Promise<Object[]>}
   */
  async getActiveConversations(options = {}) {
    const { platform, limit } = options;
    
    let query = `
      MATCH (c:Conversation {status: 'active'})
    `;
    
    if (platform) {
      query += ` WHERE c.platform = $platform`;
    }
    
    query += `
      RETURN c
      ORDER BY c.lastActivity DESC
    `;
    
    if (limit) query += ` LIMIT ${limit}`;
    
    const result = await this.client.read(query, { platform });
    
    return result.map(r => this.normalizeConversation(r.c));
  }

  /**
   * Get orphaned conversations (active but no matching session)
   * 
   * @returns {Promise<Object[]>}
   */
  async getOrphanedConversations() {
    // Conversations with status 'active' or 'orphaned'
    // that haven't had activity in over 1 hour
    const result = await this.client.read(`
      MATCH (c:Conversation)
      WHERE c.status IN ['active', 'orphaned']
      AND c.lastActivity < datetime() - duration('PT1H')
      RETURN c
      ORDER BY c.lastActivity DESC
    `);
    
    return result.map(r => this.normalizeConversation(r.c));
  }

  /**
   * Mark conversations as orphaned
   * 
   * @param {string[]} ids - Conversation IDs to mark
   * @returns {Promise<number>} Number updated
   */
  async markOrphaned(ids) {
    const result = await this.client.write(`
      MATCH (c:Conversation)
      WHERE c.id IN $ids
      SET c.status = 'orphaned'
      RETURN count(c) AS updated
    `, { ids });
    
    return result[0]?.updated || 0;
  }

  /**
   * Normalize a conversation from Neo4j format
   * 
   * @param {Object} conv
   * @returns {Object}
   */
  normalizeConversation(conv) {
    return {
      id: conv.id,
      sessionId: conv.sessionId,
      conversationId: conv.conversationId,
      platform: conv.platform,
      title: conv.title,
      purpose: conv.purpose,
      model: conv.model,
      initiator: conv.initiator,
      status: conv.status,
      createdAt: conv.createdAt,
      lastActivity: conv.lastActivity,
      closedAt: conv.closedAt || null,
      summary: conv.summary || null
    };
  }

  /**
   * Normalize a message from Neo4j format
   * 
   * @param {Object} msg
   * @returns {Object}
   */
  normalizeMessage(msg) {
    let attachments = [];
    let metadata = {};
    
    try {
      attachments = JSON.parse(msg.attachments || '[]');
    } catch {}
    
    try {
      metadata = JSON.parse(msg.metadata || '{}');
    } catch {}
    
    return {
      id: msg.id,
      conversationId: msg.conversationId,
      role: msg.role,
      content: msg.content,
      platform: msg.platform,
      timestamp: msg.timestamp,
      attachments,
      metadata
    };
  }
}

/**
 * Singleton instance
 */
let storeInstance = null;

/**
 * Get the singleton ConversationStore instance
 * 
 * @returns {ConversationStore}
 */
export function getConversationStore() {
  if (!storeInstance) {
    storeInstance = new ConversationStore();
  }
  return storeInstance;
}
