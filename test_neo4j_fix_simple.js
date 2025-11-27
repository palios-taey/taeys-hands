#!/usr/bin/env node
/**
 * Simple test for Neo4j metadata storage
 *
 * Tests that flat metadata is properly stored and retrieved.
 */

import { ConversationStore } from './src/core/conversation-store.js';
import { Neo4jClient } from './src/core/neo4j-client.js';

async function testMetadataStorage() {
  console.log('=== Testing Neo4j Metadata Storage ===\n');

  const neo4jClient = new Neo4jClient();
  const conversationStore = new ConversationStore(neo4jClient);

  try {
    // Connect
    console.log('[1] Connecting to Neo4j...');
    await neo4jClient.connect();
    console.log('✓ Connected\n');

    // Initialize schema
    console.log('[2] Initializing schema...');
    await conversationStore.initSchema();
    console.log('✓ Schema initialized\n');

    // Create test conversation
    console.log('[3] Creating test conversation...');
    const testConv = await conversationStore.createConversation({
      title: 'Test Conversation',
      purpose: 'Testing metadata',
      initiator: 'test_script',
      platform: 'claude',
      metadata: {
        testType: 'metadata_fix',
        count: 42
      }
    });
    console.log(`✓ Created: ${testConv.id}\n`);

    // Add test message with flat metadata (like MCP server does)
    console.log('[4] Adding test message with metadata...');
    const testMsg = await conversationStore.addMessage(testConv.id, {
      role: 'assistant',
      content: 'Test response',
      platform: 'claude',
      timestamp: new Date().toISOString(),
      attachments: ['file1.txt'],
      metadata: {
        source: 'mcp_taey_extract_response',
        contentLength: 13
      }
    });
    console.log(`✓ Added: ${testMsg.id}\n`);

    // Query to verify storage
    console.log('[5] Querying Neo4j to verify storage...');
    const result = await neo4jClient.run(
      `MATCH (m:Message {id: $messageId})
       RETURN m.metadata as metadata,
              m.attachments as attachments`,
      { messageId: testMsg.id }
    );

    if (result.length === 0) {
      throw new Error('Message not found in Neo4j');
    }

    const row = result[0];
    console.log('Raw metadata from Neo4j:', row.metadata);
    console.log('Raw attachments from Neo4j:', row.attachments);
    console.log();

    // Verify it's stored as STRING (which is correct for Neo4j)
    console.log('[6] Verifying storage types...');
    if (typeof row.metadata !== 'string') {
      throw new Error(`❌ metadata should be string, got: ${typeof row.metadata}`);
    }
    if (typeof row.attachments !== 'string') {
      throw new Error(`❌ attachments should be string, got: ${typeof row.attachments}`);
    }
    console.log('✓ Both stored as strings (correct)\n');

    // Parse and verify content
    console.log('[7] Parsing JSON strings...');
    const parsedMetadata = JSON.parse(row.metadata);
    const parsedAttachments = JSON.parse(row.attachments);

    console.log('Parsed metadata:', parsedMetadata);
    console.log('Parsed attachments:', parsedAttachments);
    console.log();

    // Verify values
    console.log('[8] Verifying parsed values...');
    if (parsedMetadata.source !== 'mcp_taey_extract_response') {
      throw new Error(`❌ Wrong source: ${parsedMetadata.source}`);
    }
    if (parsedMetadata.contentLength !== 13) {
      throw new Error(`❌ Wrong contentLength: ${parsedMetadata.contentLength}`);
    }
    if (!Array.isArray(parsedAttachments) || parsedAttachments[0] !== 'file1.txt') {
      throw new Error(`❌ Wrong attachments: ${JSON.stringify(parsedAttachments)}`);
    }
    console.log('✓ All values correct\n');

    // Test conversation retrieval (which should parse automatically)
    console.log('[9] Testing conversation retrieval...');
    const retrieved = await conversationStore.getConversation(testConv.id);

    if (!retrieved) {
      throw new Error('Could not retrieve conversation');
    }

    console.log('Retrieved conversation has', retrieved.messages.length, 'messages');
    const retrievedMsg = retrieved.messages[0];
    console.log('Retrieved message metadata:', retrievedMsg.metadata);
    console.log('Retrieved message metadata type:', typeof retrievedMsg.metadata);
    console.log();

    // Cleanup
    console.log('[10] Cleaning up...');
    await neo4jClient.write(
      `MATCH (c:Conversation {id: $id}) DETACH DELETE c`,
      { id: testConv.id }
    );
    await neo4jClient.write(
      `MATCH (m:Message {id: $id}) DETACH DELETE m`,
      { id: testMsg.id }
    );
    console.log('✓ Cleaned up\n');

    console.log('=== ✓ ALL TESTS PASSED ===\n');
    console.log('Summary:');
    console.log('- Metadata is stored as JSON STRING in Neo4j (correct for complex data)');
    console.log('- Attachments are stored as JSON STRING in Neo4j (correct for arrays)');
    console.log('- Data can be parsed back into objects successfully');
    console.log('- The original error must have been from a different cause');

  } catch (error) {
    console.error('\n❌ TEST FAILED:', error.message);
    console.error(error.stack);
    process.exit(1);
  } finally {
    await neo4jClient.close();
  }
}

testMetadataStorage().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
