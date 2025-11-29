/**
 * Draft Message Planning for AI Chat Workflows
 *
 * Implements the pre-execution planning phase from 6SIGMA_PLAN.md
 * Creates Message nodes with sent: false as execution plans,
 * then executes and marks sent: true
 */

import { v4 as uuidv4 } from 'uuid';
import { getNeo4jClient } from './neo4j-client.js';
import { getFamilyIntelligence } from './family-intelligence.js';
import os from 'os';

export class DraftMessagePlanner {
  constructor(neo4jClient = null) {
    this.client = neo4jClient || getNeo4jClient();
    this.sender = this.getSenderIdentity();
  }

  /**
   * Get the identity of this Claude instance (sender)
   */
  getSenderIdentity() {
    const hostname = os.hostname();
    const machinePrefix = hostname.split('.')[0].toLowerCase();
    return `${machinePrefix}-claude`;
  }

  /**
   * Create a draft message (execution plan)
   *
   * @param {Object} plan - Message planning details
   * @param {string} plan.conversationId - Target conversation
   * @param {string} plan.platform - Target platform (claude, grok, etc.)
   * @param {string} plan.intent - Intent type (dream-sessions, strategic-planning, etc.)
   * @param {string} plan.content - The prompt text
   * @param {Array<string>} plan.attachments - File paths to attach
   * @param {Array<Object>} plan.pastedContent - Content to paste from other sessions
   *   [{fromSession, fromPlatform, text, description}]
   * @param {Object} plan.metadata - Additional metadata
   * @returns {Object} Draft message
   */
  async createDraftMessage(plan) {
    const fi = getFamilyIntelligence();

    // Get routing info from Family Intelligence if intent provided
    let routing = null;
    if (plan.intent) {
      try {
        routing = await fi.getBestAIForIntent(plan.intent);
      } catch (err) {
        console.warn(`[DraftMessage] Could not get routing for intent ${plan.intent}:`, err.message);
      }
    }

    const draft = {
      id: uuidv4(),
      conversationId: plan.conversationId,
      role: 'user',
      content: plan.content,
      platform: plan.platform,
      intent: plan.intent || null,
      routing: routing ? JSON.stringify(routing) : null,
      sender: this.sender,
      sent: false,
      sentAt: null,
      timestamp: new Date().toISOString(),
      attachments: JSON.stringify(plan.attachments || []),
      pastedContent: JSON.stringify(plan.pastedContent || []),
      metadata: JSON.stringify(plan.metadata || {})
    };

    // Create draft message node
    await this.client.write(
      `MATCH (c:Conversation {id: $conversationId})
       MATCH (p:Platform {name: $platform})
       CREATE (m:Message {
         id: $id,
         role: $role,
         content: $content,
         platform: $platform,
         conversationId: $conversationId,
         intent: $intent,
         routing: $routing,
         sender: $sender,
         sent: $sent,
         sentAt: $sentAt,
         timestamp: datetime($timestamp),
         attachments: $attachments,
         pastedContent: $pastedContent,
         metadata: $metadata
       })
       CREATE (m)-[:PART_OF]->(c)
       CREATE (m)-[:PLANNED_FOR]->(p)
       RETURN m`,
      {
        id: draft.id,
        conversationId: draft.conversationId,
        role: draft.role,
        content: draft.content,
        platform: draft.platform,
        intent: draft.intent,
        routing: draft.routing,
        sender: draft.sender,
        sent: draft.sent,
        sentAt: draft.sentAt,
        timestamp: draft.timestamp,
        attachments: draft.attachments,
        pastedContent: draft.pastedContent,
        metadata: draft.metadata
      }
    );

    console.log(`[DraftMessage] Created draft: ${draft.id} for ${plan.platform} (intent: ${plan.intent || 'none'})`);
    return draft;
  }

  /**
   * Get a draft message by ID
   */
  async getDraftMessage(messageId) {
    const result = await this.client.read(
      `MATCH (m:Message {id: $messageId, sent: false})
       RETURN m`,
      { messageId }
    );

    if (!result || result.length === 0) {
      throw new Error(`Draft message ${messageId} not found or already sent`);
    }

    const message = result[0].m.properties || result[0].m;

    // Parse JSON fields
    return {
      ...message,
      attachments: JSON.parse(message.attachments || '[]'),
      pastedContent: JSON.parse(message.pastedContent || '[]'),
      routing: message.routing ? JSON.parse(message.routing) : null,
      metadata: JSON.parse(message.metadata || '{}')
    };
  }

  /**
   * Mark draft message as sent
   */
  async markAsSent(messageId) {
    const sentAt = new Date().toISOString();

    await this.client.write(
      `MATCH (m:Message {id: $messageId})
       SET m.sent = true,
           m.sentAt = datetime($sentAt)
       WITH m
       MATCH (m)-[r:PLANNED_FOR]->(p:Platform)
       DELETE r
       CREATE (m)-[:FROM]->(p)
       RETURN m`,
      { messageId, sentAt }
    );

    console.log(`[DraftMessage] Marked as sent: ${messageId}`);
    return { messageId, sentAt };
  }

  /**
   * Get all unsent drafts for a conversation
   */
  async getUnsentDrafts(conversationId) {
    const result = await this.client.read(
      `MATCH (m:Message {conversationId: $conversationId, sent: false})
       RETURN m
       ORDER BY m.timestamp DESC`,
      { conversationId }
    );

    return result.map(row => {
      const message = row.m.properties || row.m;
      return {
        ...message,
        attachments: JSON.parse(message.attachments || '[]'),
        pastedContent: JSON.parse(message.pastedContent || '[]'),
        routing: message.routing ? JSON.parse(message.routing) : null,
        metadata: JSON.parse(message.metadata || '{}')
      };
    });
  }

  /**
   * Delete a draft message (abandon plan)
   */
  async deleteDraft(messageId) {
    await this.client.write(
      `MATCH (m:Message {id: $messageId, sent: false})
       DETACH DELETE m`,
      { messageId }
    );

    console.log(`[DraftMessage] Deleted draft: ${messageId}`);
  }

  /**
   * Create execution plan from intent
   * This is a helper to build a draft from high-level intent
   */
  async planFromIntent(options) {
    const fi = getFamilyIntelligence();

    // Get best routing for intent
    const routing = await fi.getBestAIForIntent(options.intent);

    // Get required attachments from routing
    const attachments = routing.requiredAttachments || [];

    // Build the plan
    return {
      conversationId: options.conversationId,
      platform: routing.ai, // Family Intelligence returns bestAI as "ai"
      intent: options.intent,
      content: options.content,
      attachments: [...attachments, ...(options.additionalAttachments || [])],
      pastedContent: options.pastedContent || [],
      metadata: {
        ...options.metadata,
        model: routing.model,
        mode: routing.mode,
        planSource: 'family-intelligence'
      }
    };
  }
}
