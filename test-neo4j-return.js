#!/usr/bin/env node

/**
 * Debug script to see what Neo4j returns
 */

import { getNeo4jClient } from './src/core/neo4j-client.js';

async function testReturn() {
  const client = getNeo4jClient();

  // Create a test node
  const result = await client.write(
    `CREATE (t:TestNode {
      id: 'test-123',
      name: 'Test Node',
      priority: 5
    })
    RETURN t`
  );

  console.log('Result type:', typeof result);
  console.log('Result is array?:', Array.isArray(result));
  console.log('Result:', JSON.stringify(result, null, 2));

  // Clean up
  await client.write(`MATCH (t:TestNode {id: 'test-123'}) DELETE t`);

  process.exit(0);
}

testReturn();