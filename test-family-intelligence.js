#!/usr/bin/env node

/**
 * Test Family Intelligence query system
 */

import { getFamilyIntelligence } from './src/core/family-intelligence.js';

async function testFamilyIntelligence() {
  console.log('\n=== Family Intelligence F1 Test ===\n');

  const fi = getFamilyIntelligence();

  // Test 1: Get Family member
  console.log('1. Get Claude (Gaia) identity:');
  const claude = await fi.getFamilyMember('claude');
  console.log(`   Identity: ${claude.identity}`);
  console.log(`   Archetype: ${claude.archetype}`);
  console.log(`   Essence: ${claude.essence}`);
  console.log(`   Communication: ${claude.communicationStyle}\n`);

  // Test 2: Get best AI for intent
  console.log('2. Get best AI for dream-cycle:');
  const dreamCycleAI = await fi.getBestAIForIntent('dream-cycle');
  console.log(`   Best AI: ${dreamCycleAI.ai}`);
  console.log(`   Model: ${dreamCycleAI.model}`);
  console.log(`   Mode: ${dreamCycleAI.mode}`);
  console.log(`   Why: ${dreamCycleAI.why}`);
  console.log(`   Required attachments: ${dreamCycleAI.requiredAttachments.join(', ')}\n`);

  // Test 3: Get UI state indicator
  console.log('3. Get Claude Extended Thinking UI indicator:');
  const etIndicator = await fi.getUIStateIndicator('claude', 'extendedThinkingToggle');
  console.log(`   Location: ${etIndicator.location}`);
  console.log(`   Active: ${etIndicator.activeState}`);
  console.log(`   Inactive: ${etIndicator.inactiveState}\n`);

  // Test 4: Get communication style
  console.log('4. Get Grok (LOGOS) communication style:');
  const grokComm = await fi.getCommunicationStyle('grok');
  console.log(`   Archetype: ${grokComm.archetype}`);
  console.log(`   Symbol: ${grokComm.archetypeSymbol}`);
  console.log(`   Wants in prompts: ${grokComm.wantsInPrompts}`);
  console.log(`   Direct prompt style: ${grokComm.responseToDirectPrompt}\n`);

  // Test 5: Get models for platform
  console.log('5. Get Claude models:');
  const claudeModels = await fi.getModels('claude');
  Object.entries(claudeModels).forEach(([key, model]) => {
    console.log(`   ${key}: ${model.name}`);
    console.log(`      Best for: ${model.bestFor.join(', ')}`);
  });
  console.log();

  // Test 6: Get modes for platform
  console.log('6. Get Gemini modes:');
  const geminiModes = await fi.getModes('gemini');
  Object.entries(geminiModes).forEach(([key, mode]) => {
    console.log(`   ${key}: ${mode.name}`);
    console.log(`      When to use: ${mode.whenToUse}`);
  });
  console.log();

  // Test 7: Get model requirements for intent
  console.log('7. Get model requirements for mathematical-verification:');
  const mathReqs = await fi.getModelRequirementsForIntent('mathematical-verification');
  console.log(`   Platform: ${mathReqs.platform}`);
  console.log(`   Model: ${mathReqs.model}`);
  console.log(`   Mode: ${mathReqs.mode || 'none'}`);
  console.log(`   Why: ${mathReqs.why}\n`);

  // Test 8: List all intent types
  console.log('8. Available intent types:');
  const intents = await fi.getAvailableIntents();
  intents.forEach(intent => console.log(`   - ${intent}`));
  console.log();

  // Test 9: Sacred Trust physics
  console.log('9. Sacred Trust physics:');
  const physics = await fi.getSacredTrustPhysics();
  console.log(`   Resonance threshold: φ > ${physics.resonanceThreshold}`);
  console.log(`   Golden ratio: ${physics.goldenRatio}`);
  console.log(`   Heartbeat: ${physics.heartbeatFrequency}\n`);

  // Test 10: Universal Force Fields
  console.log('10. Universal Force Fields:');
  const forces = await fi.getUniversalForceFields();
  Object.entries(forces).forEach(([name, operator]) => {
    console.log(`   ${name}: ${operator}`);
  });
  console.log();

  console.log('✅ All tests passed!\n');
}

testFamilyIntelligence().catch(err => {
  console.error('❌ Test failed:', err);
  process.exit(1);
});
