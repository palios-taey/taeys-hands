/**
 * Test and discover correct selectors for each chat interface
 */

import { chromium } from 'playwright';

async function testSelectors() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const contexts = browser.contexts();
  const context = contexts[0];
  const pages = await context.pages();

  console.log('\n=== Available pages ===');
  for (const page of pages) {
    const url = page.url();
    console.log(`  - ${url}`);
  }

  // Test Claude selectors
  console.log('\n=== Testing Claude selectors ===');
  const claudePage = pages.find(p => p.url().includes('claude.ai'));
  if (claudePage) {
    await testInterfaceSelectors(claudePage, 'Claude', {
      // Current selectors
      chatInput: '[contenteditable="true"]',
      responseContainer: '.font-claude-response-body',
      // Alternative selectors to try
      alternatives: {
        chatInput: [
          '[contenteditable="true"]',
          '[data-placeholder*="Reply"]',
          'div[class*="ProseMirror"]',
          '.ProseMirror',
          'fieldset [contenteditable="true"]'
        ],
        responseContainer: [
          '.font-claude-response-body',
          '[data-is-streaming]',
          '[class*="message-content"]',
          'div[class*="prose"]',
          '.markdown-content'
        ]
      }
    });
  } else {
    console.log('  Claude tab not found - open https://claude.ai/new to test');
  }

  // Test Gemini selectors
  console.log('\n=== Testing Gemini selectors ===');
  const geminiPage = pages.find(p => p.url().includes('gemini.google'));
  if (geminiPage) {
    await testInterfaceSelectors(geminiPage, 'Gemini', {
      chatInput: '.ql-editor[contenteditable="true"], [aria-label="Enter a prompt here"]',
      responseContainer: 'p[data-path-to-node]',
      alternatives: {
        chatInput: [
          '.ql-editor[contenteditable="true"]',
          '[aria-label="Enter a prompt here"]',
          'rich-textarea [contenteditable="true"]',
          '[data-placeholder*="message"]',
          'textarea'
        ],
        responseContainer: [
          'p[data-path-to-node]',
          'model-response',
          '.response-content',
          '[class*="response"]',
          '.markdown'
        ]
      }
    });
  } else {
    console.log('  Gemini tab not found - open https://gemini.google.com to test');
  }

  // Test Perplexity selectors
  console.log('\n=== Testing Perplexity selectors ===');
  const perplexityPage = pages.find(p => p.url().includes('perplexity'));
  if (perplexityPage) {
    await testInterfaceSelectors(perplexityPage, 'Perplexity', {
      chatInput: '#ask-input, [data-lexical-editor="true"]',
      responseContainer: '[class*="prose"], [class*="answer"]',
      alternatives: {
        chatInput: [
          '#ask-input',
          '[data-lexical-editor="true"]',
          'textarea',
          '[contenteditable="true"]',
          '[class*="editor"]'
        ],
        responseContainer: [
          '[class*="prose"]',
          '[class*="answer"]',
          '[class*="markdown"]',
          '.response',
          '[data-testid*="answer"]'
        ]
      }
    });
  } else {
    console.log('  Perplexity tab not found - open https://perplexity.ai to test');
  }

  await browser.close();
}

async function testInterfaceSelectors(page, name, config) {
  console.log(`\n  Testing ${name} at: ${page.url()}`);

  // Test current chatInput
  console.log(`\n  Chat Input Selectors:`);
  for (const selector of config.alternatives.chatInput) {
    const found = await page.$(selector);
    const status = found ? '✅' : '❌';
    console.log(`    ${status} ${selector}`);
    if (found) {
      const tagName = await found.evaluate(el => el.tagName);
      const placeholder = await found.evaluate(el => el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || '');
      console.log(`       → <${tagName}> placeholder="${placeholder}"`);
    }
  }

  // Test current responseContainer
  console.log(`\n  Response Container Selectors:`);
  for (const selector of config.alternatives.responseContainer) {
    const elements = await page.$$(selector);
    const status = elements.length > 0 ? '✅' : '❌';
    console.log(`    ${status} ${selector} (${elements.length} elements)`);
    if (elements.length > 0) {
      const textLength = await elements[elements.length - 1].textContent().then(t => t.length);
      console.log(`       → Last element: ${textLength} chars`);
    }
  }

  // Also dump some useful DOM info for manual inspection
  console.log(`\n  Additional DOM info for ${name}:`);
  const allContentEditable = await page.$$('[contenteditable="true"]');
  console.log(`    [contenteditable="true"]: ${allContentEditable.length} elements`);

  const allTextareas = await page.$$('textarea');
  console.log(`    textarea: ${allTextareas.length} elements`);

  const allProse = await page.$$('[class*="prose"]');
  console.log(`    [class*="prose"]: ${allProse.length} elements`);

  const allMarkdown = await page.$$('[class*="markdown"]');
  console.log(`    [class*="markdown"]: ${allMarkdown.length} elements`);
}

testSelectors().catch(console.error);
