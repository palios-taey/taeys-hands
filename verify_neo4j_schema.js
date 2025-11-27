#!/usr/bin/env node
/**
 * Verify Neo4j schema and check for any problematic existing data
 */

import { Neo4jClient } from './src/core/neo4j-client.js';

async function verifySchema() {
  console.log('=== Neo4j Schema Verification ===\n');

  const client = new Neo4jClient();

  try {
    await client.connect();

    // Check schema
    console.log('[1] Checking schema...');
    const schema = await client.getSchema();
    console.log('Node labels:', schema.labels.join(', '));
    console.log('Relationship types:', schema.relationshipTypes.join(', '));
    console.log();

    // Count nodes
    console.log('[2] Counting nodes...');
    const counts = await client.run(`
      MATCH (n)
      RETURN labels(n)[0] as label, count(n) as count
      ORDER BY count DESC
    `);
    console.log('Node counts:');
    counts.forEach(row => {
      console.log(`   ${row.label}: ${row.count}`);
    });
    console.log();

    // Check Message nodes for metadata type
    console.log('[3] Checking Message metadata types...');
    const messages = await client.run(`
      MATCH (m:Message)
      RETURN m.id as id,
             m.role as role,
             m.metadata as metadata,
             m.timestamp as timestamp
      ORDER BY m.timestamp DESC
      LIMIT 10
    `);

    if (messages.length === 0) {
      console.log('   No messages found');
    } else {
      console.log(`   Found ${messages.length} recent messages (showing last 10):`);
      messages.forEach((msg, i) => {
        console.log(`   \n   Message ${i + 1}:`);
        console.log(`      ID: ${msg.id}`);
        console.log(`      Role: ${msg.role}`);
        console.log(`      Metadata type: ${typeof msg.metadata}`);
        console.log(`      Metadata value: ${msg.metadata}`);

        if (typeof msg.metadata === 'string') {
          try {
            const parsed = JSON.parse(msg.metadata);
            console.log(`      ✓ Parses as JSON: ${JSON.stringify(parsed)}`);
          } catch (e) {
            console.log(`      ❌ INVALID JSON: ${e.message}`);
          }
        } else {
          console.log(`      ⚠️  WARNING: Metadata is not a string! Type: ${typeof msg.metadata}`);
        }
      });
    }
    console.log();

    // Check Conversation nodes
    console.log('[4] Checking Conversation metadata types...');
    const conversations = await client.run(`
      MATCH (c:Conversation)
      RETURN c.id as id,
             c.title as title,
             c.metadata as metadata,
             c.createdAt as createdAt
      ORDER BY c.createdAt DESC
      LIMIT 5
    `);

    if (conversations.length === 0) {
      console.log('   No conversations found');
    } else {
      console.log(`   Found ${conversations.length} recent conversations (showing last 5):`);
      conversations.forEach((conv, i) => {
        console.log(`   \n   Conversation ${i + 1}:`);
        console.log(`      ID: ${conv.id}`);
        console.log(`      Title: ${conv.title}`);
        console.log(`      Metadata type: ${typeof conv.metadata}`);
        console.log(`      Metadata value: ${conv.metadata}`);

        if (typeof conv.metadata === 'string') {
          try {
            const parsed = JSON.parse(conv.metadata);
            console.log(`      ✓ Parses as JSON: ${JSON.stringify(parsed)}`);
          } catch (e) {
            console.log(`      ❌ INVALID JSON: ${e.message}`);
          }
        } else {
          console.log(`      ⚠️  WARNING: Metadata is not a string! Type: ${typeof conv.metadata}`);
        }
      });
    }
    console.log();

    console.log('=== ✓ Schema Verification Complete ===\n');

  } catch (error) {
    console.error('\n❌ Verification failed:', error.message);
    console.error(error.stack);
    process.exit(1);
  } finally {
    await client.close();
  }
}

verifySchema().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
