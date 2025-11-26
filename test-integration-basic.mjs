#!/usr/bin/env node
/**
 * Basic Integration Test - Validates core Ubuntu port functionality
 * Tests platform detection, bridge loading, and basic operations
 */

import { createPlatformBridge } from './src/core/platform-bridge.js';
import os from 'os';

console.log('=== Taey\'s Hands Basic Integration Test ===\n');

async function runTests() {
  try {
    // Test 1: Platform Detection
    console.log('Test 1: Platform Detection');
    const platform = os.platform();
    console.log(`  Platform: ${platform}`);
    if (platform !== 'linux' && platform !== 'darwin') {
      throw new Error('Unsupported platform');
    }
    console.log('  ✓ Platform supported\n');

    // Test 2: Bridge Creation
    console.log('Test 2: Bridge Creation');
    const bridge = await createPlatformBridge({
      typingBaseDelay: 50,
      typingVariation: 30,
      bezierSteps: 20
    });
    console.log(`  ✓ ${platform === 'linux' ? 'LinuxBridge' : 'OSABridge'} created\n`);

    // Test 3: Mouse Position Query
    console.log('Test 3: Mouse Position Query');
    const pos = await bridge.getMousePosition();
    console.log(`  Current position: (${pos.x}, ${pos.y})`);
    if (typeof pos.x !== 'number' || typeof pos.y !== 'number') {
      throw new Error('Invalid mouse position');
    }
    console.log('  ✓ Mouse position query works\n');

    // Test 4: Clipboard Operations
    console.log('Test 4: Clipboard Operations');
    const testText = `Taey's Hands test @ ${new Date().toISOString()}`;
    await bridge.setClipboard(testText);
    console.log(`  ✓ Clipboard set\n`);

    // Test 5: Focus Validation (will fail gracefully if no window focused)
    console.log('Test 5: Focus Validation');
    try {
      const focus = await bridge.validateFocus('Firefox');
      if (focus.valid) {
        console.log(`  ✓ Firefox is focused: ${focus.currentApp}`);
      } else {
        console.log(`  ℹ No Firefox window focused (${focus.currentApp})`);
      }
    } catch (err) {
      console.log(`  ℹ Focus validation not critical: ${err.message}`);
    }
    console.log();

    console.log('=== All Core Tests Passed ===');
    console.log('\nReady for Chat correspondence!');
    console.log('Note: File attachment tests require desktop session with open browser.\n');
    
    return true;
  } catch (error) {
    console.error(`\n❌ Test failed: ${error.message}`);
    console.error(error.stack);
    return false;
  }
}

// Run tests
runTests().then(success => {
  process.exit(success ? 0 : 1);
});
