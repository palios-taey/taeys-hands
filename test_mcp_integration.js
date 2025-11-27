#!/usr/bin/env node
/**
 * Integration test simulating MCP server's Neo4j usage
 *
 * This mimics exactly what happens when taey_send_message and
 * taey_extract_response are called.
 */

import { ConversationStore } from './src/core/conversation-store.js';
import { Neo4jClient } from './src/core/neo4j-client.js';

async function testMCPIntegration() {
  console.log('=== MCP Integration Test ===\n');
  console.log('Simulating taey_send_message and taey_extract_response\n');

  const neo4jClient = new Neo4jClient();
  const conversationStore = new ConversationStore(neo4jClient);

  try {
    await neo4jClient.connect();
    await conversationStore.initSchema();

    // Simulate MCP session creation (taey_connect)
    const sessionId = 'test-session-' + Date.now();
    const interfaceName = 'claude';
    const conversationId = null;

    console.log(`[1] Session ID: ${sessionId}`);
    console.log(`[1] Interface: ${interfaceName}\n`);

    // Create conversation (like MCP server does in taey_connect)
    console.log('[1.5] Creating conversation in Neo4j...');
    await conversationStore.createConversation({
      id: sessionId,
      title: conversationId ? `Resume: ${conversationId}` : `New ${interfaceName} session`,
      purpose: 'AI Family collaboration via Taey Hands MCP',
      initiator: 'mcp_server',
      platforms: [interfaceName],
      platform: interfaceName,
      sessionId: sessionId,
      conversationId: conversationId || null,
      metadata: {
        conversationId: conversationId || null,
        testSession: true
      }
    });
    console.log('✓ Conversation created\n');

    // Simulate taey_send_message logging
    console.log('[2] Simulating taey_send_message...');
    const userMessage = 'Hello, how are you?';
    const attachments = ['screenshot.png', 'data.json'];

    try {
      await conversationStore.addMessage(sessionId, {
        role: 'user',
        content: userMessage,
        platform: interfaceName,
        timestamp: new Date().toISOString(),
        attachments: attachments || [],
        metadata: { source: 'mcp_taey_send_message' }
      });
      console.log('✓ User message logged successfully\n');
    } catch (err) {
      console.error('❌ FAILED to log user message:', err.message);
      throw err;
    }

    // Simulate taey_extract_response logging
    console.log('[3] Simulating taey_extract_response...');
    const responseText = 'I am doing well, thank you for asking! How can I help you today?';
    const timestamp = new Date().toISOString();

    try {
      await conversationStore.addMessage(sessionId, {
        role: 'assistant',
        content: responseText,
        platform: interfaceName,
        timestamp,
        metadata: {
          source: 'mcp_taey_extract_response',
          contentLength: responseText.length
        }
      });
      console.log('✓ Assistant response logged successfully\n');
    } catch (err) {
      console.error('❌ FAILED to log assistant response:', err.message);
      throw err;
    }

    // Verify both messages are in Neo4j
    console.log('[4] Verifying messages in Neo4j...');
    const messages = await neo4jClient.run(
      `MATCH (m:Message {conversationId: $sessionId})
       RETURN m.id as id,
              m.role as role,
              m.content as content,
              m.metadata as metadata,
              m.attachments as attachments,
              m.timestamp as timestamp
       ORDER BY m.timestamp`,
      { sessionId }
    );

    console.log(`✓ Found ${messages.length} messages\n`);

    if (messages.length !== 2) {
      throw new Error(`Expected 2 messages, found ${messages.length}`);
    }

    // Verify user message
    console.log('[5] Verifying user message...');
    const userMsg = messages[0];
    console.log(`   Role: ${userMsg.role}`);
    console.log(`   Content: ${userMsg.content.substring(0, 50)}...`);
    console.log(`   Metadata (raw): ${userMsg.metadata}`);
    console.log(`   Attachments (raw): ${userMsg.attachments}`);

    const userMetadata = JSON.parse(userMsg.metadata);
    const userAttachments = JSON.parse(userMsg.attachments);

    console.log(`   Metadata (parsed): ${JSON.stringify(userMetadata)}`);
    console.log(`   Attachments (parsed): ${JSON.stringify(userAttachments)}`);

    if (userMsg.role !== 'user') {
      throw new Error(`Expected role 'user', got '${userMsg.role}'`);
    }
    if (userMetadata.source !== 'mcp_taey_send_message') {
      throw new Error(`Expected source 'mcp_taey_send_message', got '${userMetadata.source}'`);
    }
    if (userAttachments.length !== 2) {
      throw new Error(`Expected 2 attachments, got ${userAttachments.length}`);
    }
    console.log('✓ User message correct\n');

    // Verify assistant message
    console.log('[6] Verifying assistant message...');
    const assistantMsg = messages[1];
    console.log(`   Role: ${assistantMsg.role}`);
    console.log(`   Content: ${assistantMsg.content.substring(0, 50)}...`);
    console.log(`   Metadata (raw): ${assistantMsg.metadata}`);

    const assistantMetadata = JSON.parse(assistantMsg.metadata);
    console.log(`   Metadata (parsed): ${JSON.stringify(assistantMetadata)}`);

    if (assistantMsg.role !== 'assistant') {
      throw new Error(`Expected role 'assistant', got '${assistantMsg.role}'`);
    }
    if (assistantMetadata.source !== 'mcp_taey_extract_response') {
      throw new Error(`Expected source 'mcp_taey_extract_response', got '${assistantMetadata.source}'`);
    }
    if (assistantMetadata.contentLength !== responseText.length) {
      throw new Error(`Expected contentLength ${responseText.length}, got ${assistantMetadata.contentLength}`);
    }
    console.log('✓ Assistant message correct\n');

    // Test querying with metadata filter
    console.log('[7] Testing metadata queries...');
    const extractResponses = await neo4jClient.run(
      `MATCH (m:Message {conversationId: $sessionId})
       WHERE m.metadata CONTAINS 'mcp_taey_extract_response'
       RETURN count(m) as count`,
      { sessionId }
    );

    console.log(`   Found ${extractResponses[0].count} extract_response messages`);
    if (extractResponses[0].count !== 1) {
      throw new Error(`Expected 1 extract_response message, found ${extractResponses[0].count}`);
    }
    console.log('✓ Metadata queries work\n');

    // Cleanup
    console.log('[8] Cleaning up...');
    await neo4jClient.write(
      `MATCH (c:Conversation {id: $sessionId})
       DETACH DELETE c`,
      { sessionId }
    );
    await neo4jClient.write(
      `MATCH (m:Message {conversationId: $sessionId})
       DETACH DELETE m`,
      { sessionId }
    );
    console.log('✓ Cleaned up\n');

    console.log('=== ✓ ALL INTEGRATION TESTS PASSED ===\n');
    console.log('The MCP server should now work correctly with Neo4j!');
    console.log('\nExample Cypher to view recent MCP activity:');
    console.log('```');
    console.log(`MATCH (m:Message)
WHERE m.timestamp > datetime() - duration('PT1H')
  AND m.metadata CONTAINS 'mcp_taey'
RETURN m.conversationId as session,
       m.role as role,
       m.timestamp as time,
       m.metadata as metadata,
       substring(m.content, 0, 100) as preview
ORDER BY m.timestamp DESC
LIMIT 10`);
    console.log('```');

  } catch (error) {
    console.error('\n❌ INTEGRATION TEST FAILED:', error.message);
    console.error(error.stack);
    process.exit(1);
  } finally {
    await neo4jClient.close();
  }
}

testMCPIntegration().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
