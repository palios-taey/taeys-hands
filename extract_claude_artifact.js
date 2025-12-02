#!/usr/bin/env node

/**
 * Extract a specific Claude artifact by name
 * Usage: node extract_claude_artifact.js "artifact_name" output_path.py
 */

import { chromium } from 'playwright';
import fs from 'fs';

const artifactName = process.argv[2];
const outputPath = process.argv[3];

if (!artifactName || !outputPath) {
  console.error('Usage: node extract_claude_artifact.js "artifact_name" output_path');
  process.exit(1);
}

async function extractArtifact() {
  console.log(`Extracting artifact: "${artifactName}"`);

  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const contexts = browser.contexts();
  const context = contexts[0];
  const pages = context.pages();
  const page = pages.find(p => p.url().includes('claude.ai')) || pages[0];

  try {
    // Close any open artifact first
    const backBtn = page.locator('button[aria-label="Go back"]');
    if (await backBtn.count() > 0) {
      console.log('Closing currently open artifact...');
      await backBtn.click();
      await page.waitForTimeout(1000);
    }

    // Open sidebar if needed
    const sidebarBtn = page.locator('button[aria-label="Open sidebar"][data-testid="wiggle-controls-actions-toggle"]');
    if (await sidebarBtn.count() > 0) {
      await sidebarBtn.click();
      await page.waitForTimeout(1500);
    }

    // Find artifacts
    const artifactItems = page.locator('div[role="button"][aria-label="Preview contents"]');
    const count = await artifactItems.count();

    // Build artifact list
    const artifacts = [];
    for (let i = 0; i < count; i++) {
      const item = artifactItems.nth(i);
      const nameEl = item.locator('.leading-tight.text-sm');
      const name = await nameEl.textContent();
      artifacts.push({ index: i, name: name.trim() });
    }

    // Find target artifact
    const targetIndex = artifacts.findIndex(a => a.name === artifactName);
    if (targetIndex === -1) {
      console.error(`Artifact "${artifactName}" not found.`);
      console.error('Available artifacts:');
      artifacts.forEach(a => console.error(`  - ${a.name}`));
      process.exit(1);
    }

    // Click artifact
    console.log(`Found at index ${targetIndex}, clicking...`);
    await artifactItems.nth(targetIndex).click();
    await page.waitForTimeout(2000);

    // Extract content
    const content = await page.evaluate(() => {
      // Monaco editor
      const monacoContent = document.querySelector('.monaco-editor .view-lines');
      if (monacoContent) return monacoContent.innerText;

      // CodeMirror
      const codeMirror = document.querySelector('.CodeMirror');
      if (codeMirror && codeMirror.CodeMirror) {
        return codeMirror.CodeMirror.getValue();
      }

      // Pre/code blocks
      const codeBlocks = document.querySelectorAll('pre code, pre, code[class*="language"]');
      let largestCode = '';
      codeBlocks.forEach(block => {
        const text = block.textContent || block.innerText || '';
        if (text.length > largestCode.length) {
          largestCode = text;
        }
      });
      if (largestCode.length > 100) return largestCode;

      // Code-related elements
      const codeElements = document.querySelectorAll('[data-code], [class*="code-"], [class*="source"]');
      codeElements.forEach(el => {
        const text = el.textContent || el.innerText || '';
        if (text.length > largestCode.length) {
          largestCode = text;
        }
      });

      return largestCode || 'Could not find code content';
    });

    // Save
    fs.writeFileSync(outputPath, content);
    console.log(`✓ Extracted ${content.length} characters to ${outputPath}`);
    process.exit(0);

  } catch (err) {
    console.error('ERROR:', err.message);
    process.exit(1);
  }
}

extractArtifact().catch(err => {
  console.error(err);
  process.exit(1);
});
