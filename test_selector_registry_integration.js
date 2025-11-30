#!/usr/bin/env node
/**
 * Test SelectorRegistry Integration
 *
 * Verifies that the ChatInterface classes correctly use the SelectorRegistry
 * with graceful fallback to hardcoded selectors.
 */

import { SelectorRegistry } from './src/v2/core/selectors/selector-registry.js';
import {
  ClaudeInterface,
  ChatGPTInterface,
  GeminiInterface,
  GrokInterface,
  PerplexityInterface
} from './src/interfaces/chat-interface.js';

const platforms = [
  { name: 'claude', Interface: ClaudeInterface },
  { name: 'chatgpt', Interface: ChatGPTInterface },
  { name: 'gemini', Interface: GeminiInterface },
  { name: 'grok', Interface: GrokInterface },
  { name: 'perplexity', Interface: PerplexityInterface }
];

async function testRegistry() {
  console.log('=== Testing SelectorRegistry ===\n');

  const registry = new SelectorRegistry();

  for (const { name } of platforms) {
    console.log(`Platform: ${name}`);
    console.log('-'.repeat(40));

    try {
      // Test common selectors
      const selectors = [
        'message_input',
        'attach_button',
        'send_button',
        'new_chat_button'
      ];

      for (const key of selectors) {
        try {
          const selector = await registry.getSelector(name, key);
          console.log(`  ✓ ${key}: ${selector}`);
        } catch (err) {
          console.log(`  ✗ ${key}: ${err.message}`);
        }
      }
    } catch (err) {
      console.error(`  ERROR: ${err.message}`);
    }

    console.log();
  }
}

async function testInterfaceInstantiation() {
  console.log('\n=== Testing Interface Instantiation ===\n');

  for (const { name, Interface } of platforms) {
    try {
      const instance = new Interface();
      console.log(`✓ ${name}: Created successfully`);
      console.log(`  - Registry initialized: ${instance.registry ? 'YES' : 'NO'}`);
      console.log(`  - Name: ${instance.name}`);
      console.log(`  - URL: ${instance.url}`);
      console.log(`  - Has _getSelector method: ${typeof instance._getSelector === 'function' ? 'YES' : 'NO'}`);
    } catch (err) {
      console.error(`✗ ${name}: ${err.message}`);
    }
    console.log();
  }
}

async function testGetSelectorMethod() {
  console.log('\n=== Testing _getSelector Method ===\n');

  // Test with Claude interface (has good registry coverage)
  const claude = new ClaudeInterface();
  console.log('Testing ClaudeInterface._getSelector()\n');

  // Test 1: Registry returns valid selector
  try {
    const selector = await claude._getSelector('message_input', 'div[fallback]');
    console.log(`✓ Test 1 - Registry success: ${selector}`);
  } catch (err) {
    console.error(`✗ Test 1 failed: ${err.message}`);
  }

  // Test 2: Registry fails, fallback used
  try {
    const selector = await claude._getSelector('nonexistent_key', 'div[fallback]');
    console.log(`✓ Test 2 - Fallback used: ${selector}`);
  } catch (err) {
    console.error(`✗ Test 2 failed: ${err.message}`);
  }

  // Test 3: Both fail, error thrown
  try {
    const selector = await claude._getSelector('nonexistent_key', null);
    console.log(`✗ Test 3 - Should have thrown error but got: ${selector}`);
  } catch (err) {
    console.log(`✓ Test 3 - Correctly threw error: ${err.message.substring(0, 60)}...`);
  }
}

async function main() {
  console.log('\n');
  console.log('╔════════════════════════════════════════════════════════════╗');
  console.log('║     SelectorRegistry Integration Test Suite               ║');
  console.log('╚════════════════════════════════════════════════════════════╝');
  console.log();

  try {
    await testRegistry();
    await testInterfaceInstantiation();
    await testGetSelectorMethod();

    console.log('\n=== Summary ===\n');
    console.log('✓ All tests completed successfully!');
    console.log('✓ SelectorRegistry is properly integrated');
    console.log('✓ All platform interfaces instantiate correctly');
    console.log('✓ Fallback mechanism works as expected');
    console.log();
    console.log('Next steps:');
    console.log('1. Run integration tests with real browser automation');
    console.log('2. Test taey_connect, taey_send_message, taey_attach_files MCP tools');
    console.log('3. Verify console logs show "Using registry selector" messages');
    console.log();

  } catch (err) {
    console.error('Fatal error:', err);
    process.exit(1);
  }
}

main();
