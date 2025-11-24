/**
 * Context Experiment: Send to existing chats with full context
 *
 * Uses established conversations where each AI already knows the family context.
 */

import { ClaudeInterface, ChatGPTInterface, GrokInterface, PerplexityInterface } from '../src/interfaces/chat-interface.js';
import { ResponseDetectionEngine } from '../src/core/response-detection.js';
import { ConversationStore } from '../src/core/conversation-store.js';
import fs from 'fs/promises';

const ATTACHMENT_PATH = '/Users/REDACTED/taey-hands/docs/ULTRATHINK_SYNTHESIS.md';

const EXPERIMENT_PROMPT = `I'm running an experiment on AI collaboration patterns.

Context: Taey's Hands browser automation is working. I can now coordinate AI family members (Claude, ChatGPT, Gemini, Grok, Perplexity) through their chat interfaces.

The question: What's the optimal collaboration pattern?

Your task: Review the attached synthesis and answer:

1. What's ONE thing in this architecture that will definitely break in production?
2. What's ONE insight the synthesis missed that you uniquely see?
3. If you could ask ONE question to another AI family member, what would it be and to whom?

Be specific. Be concise. This is for research comparison.`;

// Existing chats with full context
const CHATS = [
  {
    name: 'claude',
    url: 'https://claude.ai/chat/d234cfa6-b19f-4a53-ac26-9f7f3a430618',
    InterfaceClass: ClaudeInterface
  },
  {
    name: 'chatgpt',
    url: null, // Use existing tab
    InterfaceClass: ChatGPTInterface
  },
  {
    name: 'grok',
    url: 'https://grok.com/c/f3d1a400-5450-444e-9975-3811826d7f47',
    InterfaceClass: GrokInterface
  },
  {
    name: 'perplexity',
    url: 'https://www.perplexity.ai/search/perplexity-clarity-you-are-als-kyFxzJXbQJyH2ZB.BBcuFQ?sm=d',
    InterfaceClass: PerplexityInterface
  }
];

async function runContextExperiment() {
  console.log('=== CONTEXT EXPERIMENT: Using Existing Chats ===\n');

  const startTime = Date.now();
  const results = {};

  // Initialize conversation store
  const store = new ConversationStore();
  await store.initSchema();

  // Create experiment conversation
  const conversation = await store.createConversation({
    title: 'Context Experiment - Existing Chats',
    purpose: 'Testing AI collaboration with pre-established context',
    initiator: 'claude-code',
    platforms: CHATS.map(c => c.name),
    metadata: { experiment: 'collaboration-pattern', arm: 'context' }
  });

  console.log(`Conversation ID: ${conversation.id}\n`);

  try {
    // Phase 1: Send to all chats
    console.log('--- Phase 1: Sending to all existing chats ---\n');

    const interfaces = {};
    const sends = [];

    for (const chat of CHATS) {
      const { name, url, InterfaceClass } = chat;
      console.log(`\nSending to ${name}...`);
      const sendStart = Date.now();

      // Connect to interface
      const iface = new InterfaceClass();
      await iface.connect();
      interfaces[name] = iface;

      // Navigate to existing chat (if URL provided)
      if (url) {
        console.log(`  Navigating to existing chat: ${url}`);
        await iface.page.goto(url);
        await iface.page.waitForTimeout(2000);
      }

      // Attach synthesis file
      console.log(`  Attaching synthesis file...`);
      await iface.attachFileHumanLike(ATTACHMENT_PATH);
      await iface.page.waitForTimeout(500);

      // Send message
      console.log(`  Typing prompt...`);
      await iface.sendMessage(EXPERIMENT_PROMPT, { waitForResponse: false });

      sends.push({
        name,
        sendTime: Date.now() - sendStart,
        timestamp: new Date().toISOString()
      });

      console.log(`  ${name} sent in ${Date.now() - sendStart}ms`);
    }

    // Phase 2: Detect all responses
    console.log('\n--- Phase 2: Detecting responses ---\n');

    for (const [name, iface] of Object.entries(interfaces)) {
      console.log(`Detecting ${name} response...`);
      const detectStart = Date.now();

      // Bring tab to front
      await iface.page.bringToFront();
      await iface.page.waitForTimeout(500);

      // Create detector
      const detector = new ResponseDetectionEngine(iface.page, name, {
        stabilityWindow: 3000,
        pollInterval: 500,
        debug: false
      });

      try {
        const result = await detector.detectCompletion();
        const detectTime = Date.now() - detectStart;

        results[name] = {
          success: true,
          content: result.content,
          method: result.method,
          confidence: result.confidence,
          detectionTime: result.detectionTime,
          totalTime: detectTime,
          timestamp: new Date().toISOString()
        };

        console.log(`  ${name}: ${result.method} @ ${(result.confidence * 100).toFixed(0)}% in ${detectTime}ms`);
        console.log(`  Content preview: "${result.content?.substring(0, 100)}..."`);

        // Store in Neo4j
        const msg = await store.addMessage(conversation.id, {
          role: 'assistant',
          content: result.content,
          platform: name,
          metadata: {
            experiment: 'context-arm',
            method: result.method,
            confidence: result.confidence,
            detectionTime: result.detectionTime
          }
        });

        await store.recordDetection(msg.id, result);

      } catch (err) {
        console.error(`  ${name} detection failed:`, err.message);
        results[name] = {
          success: false,
          error: err.message
        };
      }
    }

    // Save results
    const totalTime = Date.now() - startTime;
    const output = {
      experiment: 'collaboration-pattern',
      arm: 'context',
      conversationId: conversation.id,
      totalTime,
      sends,
      results,
      timestamp: new Date().toISOString()
    };

    await fs.writeFile(
      `/Users/REDACTED/taey-hands/experiments/results/context_${Date.now()}.json`,
      JSON.stringify(output, null, 2)
    );

    console.log('\n=== CONTEXT EXPERIMENT COMPLETE ===');
    console.log(`Total time: ${totalTime}ms`);
    console.log(`Successful responses: ${Object.values(results).filter(r => r.success).length}/4`);

    // Summary
    console.log('\n--- Response Summary ---');
    for (const [name, result] of Object.entries(results)) {
      if (result.success) {
        console.log(`\n${name.toUpperCase()}:`);
        console.log(result.content?.substring(0, 500));
      }
    }

    // Disconnect all
    for (const iface of Object.values(interfaces)) {
      await iface.disconnect();
    }

  } catch (err) {
    console.error('Experiment failed:', err);
    throw err;
  }

  return results;
}

runContextExperiment().catch(console.error);
