/**
 * Conversation Store - Neo4j Persistence Layer
 * 
 * Manages:
 * - Conversation nodes (sessions)
 * - Message nodes (turns)
 * - Platform nodes (AI interfaces)
 * - Detection nodes (response timing)
 * 
 * Schema initialization and CRUD operations.
 */

import { v4 as uuidv4 } from 'uuid';
import { Neo4jClient, getNeo4jClient } from './neo4j-client.js';
import {
  PlatformType,
  ConversationNode,
  Message,
  MessageRole,
  DetectionNode,
  DetectionMethod,
  PLATFORM_CONFIGS,
} from '../../types.js';

// ============================================================================
// Conversation Store Class
// ============================================================================

export class ConversationStore {
  private readonly client: Neo4jClient;
  private initialized = false;
  
  constructor(client?: Neo4jClient) {
    this.client = client || getNeo4jClient();
  }
  
  /**
   * Initialize schema (constraints, indexes, seed data)
   */
  async initSchema(): Promise<void> {
    if (this.initialized) return;
    
    await this.client.connect();
    
    // Constraints
    const constraints = [
      'CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (c:Conversation) REQUIRE c.id IS UNIQUE',
      'CREATE CONSTRAINT message_id IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE',
      'CREATE CONSTRAINT platform_name IF NOT EXISTS FOR (p:Platform) REQUIRE p.name IS UNIQUE',
      'CREATE CONSTRAINT detection_id IF NOT EXISTS FOR (d:Detection) REQUIRE d.id IS UNIQUE',
    ];
    
    // Indexes
    const indexes = [
      'CREATE INDEX conversation_created IF NOT EXISTS FOR (c:Conversation) ON (c.createdAt)',
      'CREATE INDEX conversation_status IF NOT EXISTS FOR (c:Conversation) ON (c.status)',
      'CREATE INDEX conversation_platform IF NOT EXISTS FOR (c:Conversation) ON (c.platform)',
      'CREATE INDEX conversation_session IF NOT EXISTS FOR (c:Conversation) ON (c.sessionId)',
      'CREATE INDEX message_timestamp IF NOT EXISTS FOR (m:Message) ON (m.timestamp)',
      'CREATE INDEX message_role IF NOT EXISTS FOR (m:Message) ON (m.role)',
      'CREATE INDEX message_conversation IF NOT EXISTS FOR (m:Message) ON (m.conversationId)',
      'CREATE INDEX detection_message IF NOT EXISTS FOR (d:Detection) ON (d.messageId)',
    ];
    
    // Execute schema creation
    for (const query of [...constraints, ...indexes]) {
      try {
        await this.client.run(query);
      } catch (error) {
        // Ignore "already exists" errors
        const msg = String(error);
        if (!msg.includes('already exists')) {
          console.error(`[ConversationStore] Schema error: ${msg}`);
        }
      }
    }
    
    // Seed platform data
    await this.seedPlatforms();
    
    this.initialized = true;
    console.log('[ConversationStore] Schema initialized');
  }
  
  /**
   * Seed platform nodes
   */
  private async seedPlatforms(): Promise<void> {
    for (const config of Object.values(PLATFORM_CONFIGS)) {
      await this.client.run(`
        MERGE (p:Platform { name: $name })
        ON CREATE SET
          p.displayName = $displayName,
          p.provider = $provider,
          p.type = 'chat',
          p.createdAt = datetime()
        ON MATCH SET
          p.displayName = $displayName,
          p.provider = $provider
      `, {
        name: config.name,
        displayName: config.displayName,
        provider: config.provider,
      });
    }
  }
  
  // ==========================================================================
  // Conversation Operations
  // ==========================================================================
  
  /**
   * Create a new conversation
   */
  async createConversation(options: {
    platform: PlatformType;
    sessionId: string;
    title?: string;
    purpose?: string;
    conversationId?: string;
    model?: string;
    metadata?: Record<string, unknown>;
  }): Promise<ConversationNode> {
    const id = uuidv4();
    const now = new Date().toISOString();
    
    const result = await this.client.runSingle<{ c: ConversationNode }>(`
      MATCH (p:Platform { name: $platform })
      CREATE (c:Conversation {
        id: $id,
        title: $title,
        purpose: $purpose,
        platform: $platform,
        sessionId: $sessionId,
        conversationId: $conversationId,
        status: 'active',
        createdAt: datetime($now),
        lastActivity: datetime($now),
        model: $model,
        metadata: $metadata
      })
      CREATE (c)-[:INVOLVES]->(p)
      RETURN c
    `, {
      id,
      platform: options.platform,
      sessionId: options.sessionId,
      title: options.title || null,
      purpose: options.purpose || null,
      conversationId: options.conversationId || null,
      model: options.model || null,
      metadata: options.metadata ? JSON.stringify(options.metadata) : null,
      now,
    });
    
    return result?.c || {
      id,
      platform: options.platform,
      sessionId: options.sessionId,
      status: 'active',
      createdAt: new Date(now),
    };
  }
  
  /**
   * Get conversation by ID
   */
  async getConversation(id: string): Promise<ConversationNode | null> {
    const result = await this.client.runSingle<{ c: ConversationNode }>(`
      MATCH (c:Conversation { id: $id })
      RETURN c
    `, { id });
    
    return result?.c || null;
  }
  
  /**
   * Get conversation by session ID
   */
  async getConversationBySession(sessionId: string): Promise<ConversationNode | null> {
    const result = await this.client.runSingle<{ c: ConversationNode }>(`
      MATCH (c:Conversation { sessionId: $sessionId, status: 'active' })
      RETURN c
      ORDER BY c.createdAt DESC
      LIMIT 1
    `, { sessionId });
    
    return result?.c || null;
  }
  
  /**
   * Update conversation
   */
  async updateConversation(
    id: string,
    updates: Partial<Omit<ConversationNode, 'id' | 'createdAt'>>
  ): Promise<ConversationNode | null> {
    const setClause = Object.entries(updates)
      .filter(([_, v]) => v !== undefined)
      .map(([k, _]) => {
        if (k === 'closedAt' || k === 'lastActivity') {
          return `c.${k} = datetime($${k})`;
        }
        return `c.${k} = $${k}`;
      })
      .join(', ');
    
    if (!setClause) return this.getConversation(id);
    
    const result = await this.client.runSingle<{ c: ConversationNode }>(`
      MATCH (c:Conversation { id: $id })
      SET ${setClause}
      RETURN c
    `, { id, ...updates });
    
    return result?.c || null;
  }
  
  /**
   * Close conversation
   */
  async closeConversation(id: string, summary?: string): Promise<void> {
    await this.updateConversation(id, {
      status: 'closed',
      closedAt: new Date(),
      summary,
    } as Partial<ConversationNode>);
  }
  
  /**
   * Mark conversation as orphaned
   */
  async markOrphaned(id: string): Promise<void> {
    await this.updateConversation(id, { status: 'orphaned' });
  }
  
  /**
   * Get active conversations
   */
  async getActiveConversations(): Promise<ConversationNode[]> {
    const results = await this.client.run<{ c: ConversationNode }>(`
      MATCH (c:Conversation { status: 'active' })
      RETURN c
      ORDER BY c.lastActivity DESC
    `);
    
    return results.map(r => r.c);
  }
  
  /**
   * Get orphaned conversations
   */
  async getOrphanedConversations(): Promise<ConversationNode[]> {
    const results = await this.client.run<{ c: ConversationNode }>(`
      MATCH (c:Conversation)
      WHERE c.status = 'orphaned' OR c.status = 'active'
      RETURN c
      ORDER BY c.createdAt DESC
    `);
    
    return results.map(r => r.c);
  }
  
  // ==========================================================================
  // Message Operations
  // ==========================================================================
  
  /**
   * Add a message to conversation
   */
  async addMessage(options: {
    conversationId: string;
    role: MessageRole;
    content: string;
    platform: PlatformType;
    attachments?: string[];
    metadata?: Record<string, unknown>;
  }): Promise<Message> {
    const id = uuidv4();
    const now = new Date().toISOString();
    
    const result = await this.client.runSingle<{ m: Message }>(`
      MATCH (c:Conversation { id: $conversationId })
      MATCH (p:Platform { name: $platform })
      CREATE (m:Message {
        id: $id,
        conversationId: $conversationId,
        role: $role,
        content: $content,
        platform: $platform,
        timestamp: datetime($now),
        attachments: $attachments,
        sent: true,
        metadata: $metadata
      })
      CREATE (m)-[:PART_OF]->(c)
      CREATE (m)-[:FROM]->(p)
      WITH m, c
      SET c.lastActivity = datetime($now)
      RETURN m
    `, {
      id,
      conversationId: options.conversationId,
      role: options.role,
      content: options.content,
      platform: options.platform,
      attachments: options.attachments || [],
      metadata: options.metadata ? JSON.stringify(options.metadata) : null,
      now,
    });
    
    return result?.m || {
      id,
      conversationId: options.conversationId,
      role: options.role,
      content: options.content,
      platform: options.platform,
      timestamp: new Date(now),
      attachments: options.attachments || [],
      sent: true,
    };
  }
  
  /**
   * Get messages for conversation
   */
  async getMessages(conversationId: string, limit = 50): Promise<Message[]> {
    const results = await this.client.run<{ m: Message }>(`
      MATCH (m:Message { conversationId: $conversationId })
      RETURN m
      ORDER BY m.timestamp ASC
      LIMIT $limit
    `, { conversationId, limit });
    
    return results.map(r => r.m);
  }
  
  /**
   * Get latest message
   */
  async getLatestMessage(conversationId: string, role?: MessageRole): Promise<Message | null> {
    const roleClause = role ? 'AND m.role = $role' : '';
    
    const result = await this.client.runSingle<{ m: Message }>(`
      MATCH (m:Message { conversationId: $conversationId })
      WHERE true ${roleClause}
      RETURN m
      ORDER BY m.timestamp DESC
      LIMIT 1
    `, { conversationId, role });
    
    return result?.m || null;
  }
  
  // ==========================================================================
  // Detection Operations
  // ==========================================================================
  
  /**
   * Add detection record for a message
   */
  async addDetection(options: {
    messageId: string;
    method: DetectionMethod;
    confidence: number;
    detectionTime: number;
    contentLength: number;
    metadata?: Record<string, unknown>;
  }): Promise<DetectionNode> {
    const id = uuidv4();
    const now = new Date().toISOString();
    
    const result = await this.client.runSingle<{ d: DetectionNode }>(`
      MATCH (m:Message { id: $messageId })
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
      messageId: options.messageId,
      method: options.method,
      confidence: options.confidence,
      detectionTime: options.detectionTime,
      contentLength: options.contentLength,
      metadata: options.metadata ? JSON.stringify(options.metadata) : null,
      now,
    });
    
    return result?.d || {
      id,
      messageId: options.messageId,
      method: options.method,
      confidence: options.confidence,
      detectionTime: options.detectionTime,
      contentLength: options.contentLength,
      timestamp: new Date(now),
    };
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let storeInstance: ConversationStore | null = null;

export function getConversationStore(): ConversationStore {
  if (!storeInstance) {
    storeInstance = new ConversationStore();
  }
  return storeInstance;
}
