#!/usr/bin/env node
/**
 * Test script for Neo4j metadata fix
 *
 * This script tests that metadata objects are properly stored as Neo4j MAP types
 * instead of being stringified into STRING types.
 */

import { ConversationStore } from './src/core/conversation-store.js';
import { Neo4jClient } from './src/core/neo4j-client.js';

async function testMetadataFix() {
  console.log('=== Testing Neo4j Metadata Fix ===\n');

  const neo4jClient = new Neo4jClient();
  const conversationStore = new ConversationStore(neo4jClient);

  try {
    // Connect to Neo4j
    console.log('[1] Connecting to Neo4j...');
    await neo4jClient.connect();
    console.log('✓ Connected to Neo4j\n');

    // Initialize schema
    console.log('[2] Initializing schema...');
    await conversationStore.initSchema();
    console.log('✓ Schema initialized\n');

    // Create test conversation with metadata
    console.log('[3] Creating test conversation with metadata...');
    const testConversation = await conversationStore.createConversation({
      title: 'Neo4j Metadata Test',
      purpose: 'Testing metadata MAP vs STRING',
      initiator: 'test_script',
      platform: 'claude',
      metadata: {
        testType: 'metadata_fix',
        timestamp: new Date().toISOString(),
        nested: {
          key1: 'value1',
          key2: 42
        }
      }
    });
    console.log(`✓ Created conversation: ${testConversation.id}\n`);

    // Add test message with metadata
    console.log('[4] Adding test message with metadata...');
    const testMessage = await conversationStore.addMessage(testConversation.id, {
      role: 'assistant',
      content: 'Test response from AI',
      platform: 'claude',
      timestamp: new Date().toISOString(),
      attachments: ['file1.txt', 'file2.png'],
      metadata: {
        source: 'mcp_taey_extract_response',
        contentLength: 23,
        testField: 'test_value',
        numericField: 123
      }
    });
    console.log(`✓ Added message: ${testMessage.id}\n`);

    // Query Neo4j to verify metadata type
    console.log('[5] Querying Neo4j to verify metadata structure...');
    const result = await neo4jClient.run(
      `MATCH (c:Conversation {id: $conversationId})
       MATCH (m:Message)-[:PART_OF]->(c)
       RETURN c.metadata as convMetadata,
              m.metadata as msgMetadata,
              m.attachments as msgAttachments`,
      { conversationId: testConversation.id }
    );

    if (result.length === 0) {
      throw new Error('No results found - message may not have been created');
    }

    const row = result[0];
    console.log('✓ Query successful\n');

    // Verify types
    console.log('[6] Verifying metadata types...');
    console.log('Conversation metadata:', JSON.stringify(row.convMetadata, null, 2));
    console.log('Conversation metadata type:', typeof row.convMetadata);
    console.log('Conversation metadata is object:', typeof row.convMetadata === 'object' && row.convMetadata !== null);
    console.log();

    console.log('Message metadata:', JSON.stringify(row.msgMetadata, null, 2));
    console.log('Message metadata type:', typeof row.msgMetadata);
    console.log('Message metadata is object:', typeof row.msgMetadata === 'object' && row.msgMetadata !== null);
    console.log();

    console.log('Message attachments:', JSON.stringify(row.msgAttachments, null, 2));
    console.log('Message attachments type:', typeof row.msgAttachments);
    console.log('Message attachments is array:', Array.isArray(row.msgAttachments));
    console.log();

    // Verify we can access nested properties
    console.log('[7] Verifying nested property access...');
    const nestedQuery = await neo4jClient.run(
      `MATCH (c:Conversation {id: $conversationId})
       RETURN c.metadata.testType as testType,
              c.metadata.nested.key1 as nestedKey`,
      { conversationId: testConversation.id }
    );

    if (nestedQuery.length > 0) {
      console.log('✓ Can access nested properties:');
      console.log('  - metadata.testType:', nestedQuery[0].testType);
      console.log('  - metadata.nested.key1:', nestedQuery[0].nestedKey);
    }
    console.log();

    // Verify message metadata properties
    const msgMetadataQuery = await neo4jClient.run(
      `MATCH (m:Message {id: $messageId})
       RETURN m.metadata.source as source,
              m.metadata.contentLength as contentLength,
              m.metadata.testField as testField,
              m.metadata.numericField as numericField`,
      { messageId: testMessage.id }
    );

    if (msgMetadataQuery.length > 0) {
      console.log('✓ Can access message metadata properties:');
      console.log('  - metadata.source:', msgMetadataQuery[0].source);
      console.log('  - metadata.contentLength:', msgMetadataQuery[0].contentLength);
      console.log('  - metadata.testField:', msgMetadataQuery[0].testField);
      console.log('  - metadata.numericField:', msgMetadataQuery[0].numericField);
    }
    console.log();

    // Test final validation
    console.log('[8] Final validation...');
    if (typeof row.convMetadata !== 'object' || row.convMetadata === null) {
      throw new Error('❌ FAILED: Conversation metadata is not an object!');
    }
    if (typeof row.msgMetadata !== 'object' || row.msgMetadata === null) {
      throw new Error('❌ FAILED: Message metadata is not an object!');
    }
    if (!Array.isArray(row.msgAttachments)) {
      throw new Error('❌ FAILED: Message attachments is not an array!');
    }

    console.log('✓ All validations passed!\n');

    // Cleanup
    console.log('[9] Cleaning up test data...');
    await neo4jClient.write(
      `MATCH (c:Conversation {id: $conversationId})
       DETACH DELETE c`,
      { conversationId: testConversation.id }
    );
    await neo4jClient.write(
      `MATCH (m:Message {id: $messageId})
       DETACH DELETE m`,
      { messageId: testMessage.id }
    );
    console.log('✓ Test data cleaned up\n');

    console.log('=== ✓ ALL TESTS PASSED ===\n');

    // Show example Cypher query
    console.log('Example Cypher query to inspect metadata:');
    console.log(`
MATCH (m:Message)-[:PART_OF]->(c:Conversation)
WHERE m.timestamp > datetime() - duration('PT1H')
RETURN c.id as conversationId,
       c.metadata as conversationMetadata,
       m.id as messageId,
       m.metadata as messageMetadata,
       m.attachments as attachments
LIMIT 5
    `);

  } catch (error) {
    console.error('\n❌ TEST FAILED:', error.message);
    console.error(error);
    process.exit(1);
  } finally {
    await neo4jClient.close();
  }
}

// Run test
testMetadataFix().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
