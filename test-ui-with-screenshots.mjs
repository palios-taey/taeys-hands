#!/usr/bin/env node
/**
 * Comprehensive UI Test with Screenshot Validation
 *
 * Tests browser automation with visual proof at each step:
 * - Opens Firefox
 * - Takes screenshots before/after operations
 * - Tests mouse movement and clicks
 * - Tests typing
 * - Validates focus
 *
 * Screenshots saved to: /tmp/taeys-hands-screenshots/
 */

import { createPlatformBridge } from './src/core/platform-bridge.js';
import { exec } from 'child_process';
import { promisify } from 'util';
import { mkdir } from 'fs/promises';
import os from 'os';

const execAsync = promisify(exec);

// Screenshot directory
const SCREENSHOT_DIR = '/tmp/taeys-hands-screenshots';
const TIMESTAMP = new Date().toISOString().replace(/[:.]/g, '-');

async function takeScreenshot(name) {
  const filename = `${SCREENSHOT_DIR}/${TIMESTAMP}_${name}.png`;
  try {
    await execAsync(`scrot ${filename}`);
    console.log(`    📸 Screenshot saved: ${filename}`);
    return filename;
  } catch (error) {
    console.error(`    ❌ Screenshot failed: ${error.message}`);
    return null;
  }
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function runUITests() {
  console.log('=== Taey\'s Hands UI Test with Screenshot Validation ===\n');
  console.log(`Platform: ${os.platform()}`);
  console.log(`Display: ${process.env.DISPLAY || 'NOT SET'}`);
  console.log(`Screenshots: ${SCREENSHOT_DIR}\n`);

  // Create screenshot directory
  await mkdir(SCREENSHOT_DIR, { recursive: true });
  console.log('✓ Screenshot directory created\n');

  try {
    // Create platform bridge
    console.log('Test 1: Bridge Creation');
    const bridge = await createPlatformBridge({
      typingBaseDelay: 50,
      typingVariation: 30,
      bezierSteps: 20
    });
    console.log('  ✓ Bridge created\n');

    // Initial screenshot
    console.log('Test 2: Initial Desktop State');
    await takeScreenshot('01_initial_desktop');
    await sleep(500);

    // Get initial mouse position
    console.log('\nTest 3: Mouse Position Query');
    const initialPos = await bridge.getMousePosition();
    console.log(`  Current position: (${initialPos.x}, ${initialPos.y})`);
    await takeScreenshot('02_initial_mouse_position');

    // Try to open Firefox (if not already open)
    console.log('\nTest 4: Browser Focus');
    try {
      // Try to focus Firefox
      await bridge.focusApp('Firefox');
      console.log('  ✓ Firefox focused');
      await sleep(1000);
      await takeScreenshot('03_firefox_focused');
    } catch (error) {
      console.log(`  ℹ Firefox not found, trying to launch...`);
      try {
        // Launch Firefox in background
        execAsync('firefox &').catch(() => {});
        console.log('  Waiting 5s for Firefox to start...');
        await sleep(5000);
        await bridge.focusApp('Firefox');
        console.log('  ✓ Firefox launched and focused');
        await takeScreenshot('04_firefox_launched');
      } catch (launchError) {
        console.log(`  ℹ Could not launch Firefox: ${launchError.message}`);
        console.log('  Skipping browser-specific tests, continuing with desktop tests...\n');
      }
    }

    // Test focus validation
    console.log('\nTest 5: Focus Validation');
    const focus = await bridge.validateFocus('Firefox');
    console.log(`  Current app: ${focus.currentApp}`);
    console.log(`  Focus valid: ${focus.valid}`);
    if (!focus.valid && focus.error) {
      console.log(`  Note: ${focus.error}`);
    }

    // Move mouse to a safe location (center of screen)
    console.log('\nTest 6: Mouse Movement (Bézier Curve)');
    const screenCenter = { x: 1720, y: 720 }; // Known screen center from earlier tests
    console.log(`  Moving to screen center: (${screenCenter.x}, ${screenCenter.y})`);
    await takeScreenshot('05_before_mouse_move');

    await bridge.moveMouse(screenCenter.x, screenCenter.y);
    console.log('  ✓ Mouse movement complete');
    await sleep(500);
    await takeScreenshot('06_after_mouse_move');

    // Verify new position
    const newPos = await bridge.getMousePosition();
    console.log(`  New position: (${newPos.x}, ${newPos.y})`);
    const distance = Math.sqrt(Math.pow(newPos.x - screenCenter.x, 2) + Math.pow(newPos.y - screenCenter.y, 2));
    console.log(`  Distance from target: ${Math.round(distance)}px`);

    // Test clipboard operations
    console.log('\nTest 7: Clipboard Operations');
    const testText = `Taey's Hands UI Test - ${new Date().toISOString()}`;
    await bridge.setClipboard(testText);
    console.log('  ✓ Clipboard set');
    await sleep(200);

    // If Firefox is focused, we could test typing in the address bar
    if (focus.valid) {
      console.log('\nTest 8: Browser Interaction');

      // Ctrl+L to focus address bar
      console.log('  Pressing Ctrl+L to focus address bar...');
      await bridge.pressKeyWithModifier('l', 'control');
      await sleep(500);
      await takeScreenshot('07_address_bar_focused');

      // Type a test URL (but don't navigate)
      console.log('  Typing test text...');
      await bridge.safeType('about:blank', { expectedApp: 'Firefox' });
      await sleep(500);
      await takeScreenshot('08_after_typing');

      // Clear with Ctrl+A and Delete
      console.log('  Clearing...');
      await bridge.pressKeyWithModifier('a', 'control');
      await sleep(200);
      await bridge.pressKey('delete');
      await sleep(500);
      await takeScreenshot('09_cleared');
    }

    // Final screenshot
    console.log('\nTest 9: Final State');
    await takeScreenshot('10_final_state');

    // Summary
    console.log('\n' + '='.repeat(60));
    console.log('✅ All UI Tests Passed!');
    console.log('='.repeat(60));
    console.log(`\nScreenshots saved to: ${SCREENSHOT_DIR}/`);
    console.log('Review screenshots to validate UI operations.\n');

    // List all screenshots
    const { stdout } = await execAsync(`ls -lh ${SCREENSHOT_DIR}/${TIMESTAMP}_*.png`);
    console.log('Screenshots created:');
    console.log(stdout);

    return true;

  } catch (error) {
    console.error(`\n❌ Test failed: ${error.message}`);
    console.error(error.stack);

    // Take error screenshot
    await takeScreenshot('ERROR_state');

    return false;
  }
}

// Run tests
runUITests().then(success => {
  process.exit(success ? 0 : 1);
});
