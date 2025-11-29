/**
 * Test querying Family Intelligence from Neo4j
 */

import neo4j from 'neo4j-driver';

const NEO4J_URI = process.env.NEO4J_URI || 'bolt://10.x.x.163:7687';
const NEO4J_USER = process.env.NEO4J_USER || 'neo4j';
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD || 'buddhabuddha';

async function testFamilyIntelligenceQueries() {
  const driver = neo4j.driver(NEO4J_URI, neo4j.auth.basic(NEO4J_USER, NEO4J_PASSWORD));
  const session = driver.session({ database: 'neo4j' });

  try {
    console.log('\n=== TESTING FAMILY INTELLIGENCE QUERIES ===\n');

    // Test 1: Get all Family members
    console.log('[Test 1] Get all Family members:');
    const membersResult = await session.run(`
      MATCH (f:FamilyMember)
      RETURN f.id as id, f.identity as identity, f.archetype as archetype
      ORDER BY f.id
    `);
    membersResult.records.forEach(record => {
      console.log(`   ${record.get('identity')} (${record.get('id')}) - ${record.get('archetype')}`);
    });
    console.log('');

    // Test 2: Get intent routing for dream-sessions
    console.log('[Test 2] Get intent routing for dream-sessions:');
    const intentResult = await session.run(`
      MATCH (i:IntentType {type: 'dream-sessions'})
      RETURN i.description as description,
             i.bestAI as bestAI,
             i.requiredModel as model,
             i.requiredMode as mode,
             i.requiredAttachments as attachments,
             i.allFamilyParticipation as allFamily
    `);
    const intent = intentResult.records[0];
    console.log(`   Description: ${intent.get('description')}`);
    console.log(`   Best AI: ${intent.get('bestAI')}`);
    console.log(`   Model: ${intent.get('model')}`);
    console.log(`   Mode: ${intent.get('mode')}`);
    console.log(`   All Family: ${intent.get('allFamily')}`);
    console.log(`   Attachments: ${intent.get('attachments')}`);
    console.log('');

    // Test 3: Get UI state indicators for Claude
    console.log('[Test 3] Get UI state indicators for Claude:');
    const uiResult = await session.run(`
      MATCH (p:Platform {name: 'claude'})-[:DISPLAYS_UI_STATE]->(ui:UIStateIndicator)
      RETURN ui.type as type,
             ui.location as location,
             ui.activeState as activeState,
             ui.colorGuidance as colorGuidance
      ORDER BY ui.type
    `);
    uiResult.records.forEach(record => {
      console.log(`   ${record.get('type')}: ${record.get('location')}`);
      if (record.get('colorGuidance')) {
        console.log(`      → ${record.get('colorGuidance')}`);
      }
    });
    console.log('');

    // Test 4: Get all models for a platform
    console.log('[Test 4] Get models for Claude platform:');
    const modelsResult = await session.run(`
      MATCH (p:Platform {name: 'claude'})-[:HAS_MODEL]->(m:Model)
      RETURN m.name as name, m.bestFor as bestFor, m.thinkingStyle as style
      ORDER BY m.name
    `);
    modelsResult.records.forEach(record => {
      console.log(`   ${record.get('name')}: ${record.get('style')}`);
      console.log(`      Best for: ${record.get('bestFor').join(', ')}`);
    });
    console.log('');

    // Test 5: Get communication style for Grok
    console.log('[Test 5] Get communication style for Grok:');
    const commResult = await session.run(`
      MATCH (f:FamilyMember {id: 'grok'})
      RETURN f.communicationStyle as style,
             f.wantsInPrompts as wants,
             f.responseToDirectPrompt as response
    `);
    const grok = commResult.records[0];
    console.log(`   Style: ${grok.get('style')}`);
    console.log(`   Wants: ${grok.get('wants')}`);
    console.log(`   Response: ${grok.get('response')}`);
    console.log('');

    // Test 6: Get all intents requiring all Family participation
    console.log('[Test 6] Get intents requiring all Family:');
    const familyIntentsResult = await session.run(`
      MATCH (i:IntentType)
      WHERE i.allFamilyParticipation = true
      RETURN i.type as type, i.description as description, i.familyBondPriority as priority
      ORDER BY i.type
    `);
    familyIntentsResult.records.forEach(record => {
      const priority = record.get('priority') || 'standard';
      console.log(`   ${record.get('type')} [${priority}]`);
      console.log(`      ${record.get('description')}`);
    });
    console.log('');

    // Test 7: Get Sacred Trust parameters
    console.log('[Test 7] Get Sacred Trust parameters:');
    const trustResult = await session.run(`
      MATCH (st:SacredTrust)
      RETURN st.resonanceThreshold as threshold,
             st.goldenRatio as phi,
             st.unanimityProtocol as protocol
    `);
    const trust = trustResult.records[0];
    console.log(`   φ-resonance threshold: ${trust.get('threshold')}`);
    console.log(`   Golden ratio: ${trust.get('phi')}`);
    console.log(`   Protocol: ${trust.get('protocol')}`);
    console.log('');

    console.log('=== ✓ ALL QUERIES SUCCESSFUL ===\n');

  } catch (error) {
    console.error('Error querying Family Intelligence:', error);
    throw error;
  } finally {
    await session.close();
    await driver.close();
  }
}

testFamilyIntelligenceQueries()
  .then(() => process.exit(0))
  .catch(err => {
    console.error(err);
    process.exit(1);
  });
