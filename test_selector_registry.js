/**
 * Test script for SelectorRegistry
 *
 * Validates that the registry can:
 * 1. Load selector configs for all platforms
 * 2. Return selectors by key
 * 3. Handle fallbacks correctly
 * 4. Provide helpful error messages
 * 5. List available keys
 */

import { SelectorRegistry } from './src/v2/core/selectors/selector-registry.js';

async function testSelectorRegistry() {
  console.log('=== SelectorRegistry Test Suite ===\n');

  const registry = new SelectorRegistry();
  const platforms = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'];
  const criticalSelectors = ['attach_button', 'send_button', 'message_input', 'new_chat_button'];

  let totalTests = 0;
  let passedTests = 0;
  let failedTests = 0;

  // Test 1: Load all platform configs
  console.log('Test 1: Loading platform configurations...');
  for (const platform of platforms) {
    totalTests++;
    try {
      const config = await registry.getPlatformConfig(platform);
      console.log(`  ✓ ${platform}: v${config.version} (${config.url})`);
      passedTests++;
    } catch (error) {
      console.log(`  ✗ ${platform}: ${error.message}`);
      failedTests++;
    }
  }
  console.log();

  // Test 2: Get critical selectors for each platform
  console.log('Test 2: Critical selectors across platforms...');
  for (const platform of platforms) {
    console.log(`\n  ${platform.toUpperCase()}:`);
    for (const key of criticalSelectors) {
      totalTests++;
      try {
        const selector = await registry.getSelector(platform, key);
        const def = await registry.getDefinition(platform, key);
        console.log(`    ✓ ${key}: ${selector}`);
        if (def.fallback) {
          console.log(`      (fallback: ${def.fallback})`);
        }
        if (def.description) {
          console.log(`      → ${def.description}`);
        }
        passedTests++;
      } catch (error) {
        console.log(`    ✗ ${key}: ${error.message}`);
        failedTests++;
      }
    }
  }
  console.log();

  // Test 3: Test model_selector (where applicable)
  console.log('Test 3: Model selector availability...');
  const platformsWithModelSelector = ['chatgpt', 'claude', 'gemini', 'grok'];
  for (const platform of platformsWithModelSelector) {
    totalTests++;
    try {
      const selector = await registry.getSelector(platform, 'model_selector');
      console.log(`  ✓ ${platform}: ${selector}`);
      passedTests++;
    } catch (error) {
      console.log(`  ✗ ${platform}: ${error.message}`);
      failedTests++;
    }
  }
  console.log();

  // Test 4: List all available keys for each platform
  console.log('Test 4: Available selector keys per platform...');
  for (const platform of platforms) {
    totalTests++;
    try {
      const keys = await registry.getAvailableKeys(platform);
      console.log(`  ✓ ${platform}: ${keys.length} selectors`);
      console.log(`    Keys: ${keys.join(', ')}`);
      passedTests++;
    } catch (error) {
      console.log(`  ✗ ${platform}: ${error.message}`);
      failedTests++;
    }
  }
  console.log();

  // Test 5: Error handling for invalid platform
  console.log('Test 5: Error handling...');
  totalTests++;
  try {
    await registry.getSelector('invalid_platform', 'attach_button');
    console.log('  ✗ Should have thrown error for invalid platform');
    failedTests++;
  } catch (error) {
    console.log(`  ✓ Invalid platform error: ${error.message}`);
    passedTests++;
  }

  // Test 6: Error handling for invalid key
  totalTests++;
  try {
    await registry.getSelector('chatgpt', 'invalid_key');
    console.log('  ✗ Should have thrown error for invalid key');
    failedTests++;
  } catch (error) {
    console.log(`  ✓ Invalid key error: ${error.message}`);
    passedTests++;
  }
  console.log();

  // Test 7: Platform-specific selectors
  console.log('Test 7: Platform-specific selectors...');

  // ChatGPT specific
  totalTests++;
  try {
    const selector = await registry.getSelector('chatgpt', 'menu_item_deep_research');
    console.log(`  ✓ ChatGPT Deep research: ${selector}`);
    passedTests++;
  } catch (error) {
    console.log(`  ✗ ChatGPT Deep research: ${error.message}`);
    failedTests++;
  }

  // Claude specific
  totalTests++;
  try {
    const selector = await registry.getSelector('claude', 'extended_thinking_toggle');
    console.log(`  ✓ Claude Extended thinking: ${selector}`);
    passedTests++;
  } catch (error) {
    console.log(`  ✗ Claude Extended thinking: ${error.message}`);
    failedTests++;
  }

  // Gemini specific (with force-enable note)
  totalTests++;
  try {
    const def = await registry.getDefinition('gemini', 'start_research_button');
    console.log(`  ✓ Gemini Start research: ${def.primary}`);
    console.log(`    → ${def.description}`);
    passedTests++;
  } catch (error) {
    console.log(`  ✗ Gemini Start research: ${error.message}`);
    failedTests++;
  }

  // Grok specific
  totalTests++;
  try {
    const selector = await registry.getSelector('grok', 'custom_instructions_button');
    console.log(`  ✓ Grok Custom instructions: ${selector}`);
    passedTests++;
  } catch (error) {
    console.log(`  ✗ Grok Custom instructions: ${error.message}`);
    failedTests++;
  }

  // Perplexity specific (mode selection, not model)
  totalTests++;
  try {
    const selector = await registry.getSelector('perplexity', 'mode_research');
    console.log(`  ✓ Perplexity Research mode: ${selector}`);
    passedTests++;
  } catch (error) {
    console.log(`  ✗ Perplexity Research mode: ${error.message}`);
    failedTests++;
  }
  console.log();

  // Summary
  console.log('=== Test Summary ===');
  console.log(`Total tests: ${totalTests}`);
  console.log(`Passed: ${passedTests} ✓`);
  console.log(`Failed: ${failedTests} ✗`);
  console.log(`Success rate: ${((passedTests / totalTests) * 100).toFixed(1)}%`);
  console.log();

  if (failedTests === 0) {
    console.log('🎉 All tests passed! SelectorRegistry is ready for use.');
  } else {
    console.log('⚠️  Some tests failed. Please review the errors above.');
  }

  return failedTests === 0;
}

// Run tests
testSelectorRegistry()
  .then(success => {
    process.exit(success ? 0 : 1);
  })
  .catch(error => {
    console.error('Fatal error during testing:', error);
    process.exit(1);
  });
