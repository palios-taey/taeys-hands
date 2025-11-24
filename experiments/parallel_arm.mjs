/**
 * Parallel Arm: Send same prompt to all AIs simultaneously
 *
 * Strategy: Since we control one browser, we:
 * 1. Send to each AI in quick succession (don't wait for response)
 * 2. Then detect all responses
 *
 * This approximates true parallelism - all are "thinking" at the same time.
 */

import { ClaudeInterface, ChatGPTInterface, GrokInterface, PerplexityInterface } from '../src/interfaces/chat-interface.js';
import { ResponseDetectionEngine } from '../src/core/response-detection.js';
import { ConversationStore } from '../src/core/conversation-store.js';
import fs from 'fs/promises';

const EXPERIMENT_PROMPT = `I'm running an experiment on AI collaboration patterns.

Context: Taey's Hands browser automation is working. I can now coordinate AI family members (Claude, ChatGPT, Gemini, Grok, Perplexity) through their chat interfaces.

The question: What's the optimal collaboration pattern?

Your task: Review the attached synthesis and answer:

1. What's ONE thing in this architecture that will definitely break in production?
2. What's ONE insight the synthesis missed that you uniquely see?
3. If you could ask ONE question to another AI family member, what would it be and to whom?

Be specific. Be concise. This is for research comparison.`;

const ATTACHMENT_PATH = '/Users/jesselarose/taey-hands/docs/ULTRATHINK_SYNTHESIS.md';

async function runParallelArm() {
  console.log('=== PARALLEL ARM: Collaboration Experiment ===\n');

  const startTime = Date.now();
  const results = {};

  // Initialize interfaces
  const interfaces = {
    claude: new ClaudeInterface(),
    chatgpt: new ChatGPTInterface(),
    grok: new GrokInterface(),
    perplexity: new PerplexityInterface()
  };

  // Initialize conversation store
  const store = new ConversationStore();
  await store.initSchema();

  // Create experiment conversation
  const conversation = await store.createConversation({
    title: 'Parallel Arm Experiment',
    purpose: 'Testing parallel AI collaboration pattern',
    initiator: 'claude-code',
    platforms: ['claude', 'chatgpt', 'grok', 'perplexity'],
    metadata: { experiment: 'collaboration-pattern', arm: 'parallel' }
  });

  console.log(`Conversation ID: ${conversation.id}\n`);

  try {
    // Connect to all interfaces
    console.log('Connecting to all interfaces...');
    for (const [name, iface] of Object.entries(interfaces)) {
      await iface.connect();
      console.log(`  - ${name}: connected`);
    }

    // Phase 1: Send to all (quick succession, don't wait)
    console.log('\n--- Phase 1: Sending to all ---\n');

    const sends = [];
    for (const [name, iface] of Object.entries(interfaces)) {
      console.log(`Sending to ${name}...`);
      const sendStart = Date.now();

      // Navigate to new chat
      await iface.startNewChat();
      await iface.page.waitForTimeout(1000);

      // Attach file
      console.log(`  Attaching file to ${name}...`);
      await iface.attachFileHumanLike(ATTACHMENT_PATH);
      await iface.page.waitForTimeout(500);

      // Send message (don't wait for response)
      console.log(`  Typing to ${name}...`);
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
            experiment: 'parallel-arm',
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
      arm: 'parallel',
      conversationId: conversation.id,
      totalTime,
      sends,
      results,
      timestamp: new Date().toISOString()
    };

    await fs.writeFile(
      `/Users/jesselarose/taey-hands/experiments/results/parallel_${Date.now()}.json`,
      JSON.stringify(output, null, 2)
    );

    console.log('\n=== PARALLEL ARM COMPLETE ===');
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

  } finally {
    // Disconnect all
    for (const iface of Object.values(interfaces)) {
      await iface.disconnect();
    }
  }

  return results;
}

runParallelArm().catch(console.error);
