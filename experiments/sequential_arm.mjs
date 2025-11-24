/**
 * Sequential Arm: Chain responses through AIs
 *
 * Order: Grok (reality) -> ChatGPT (engineer) -> Perplexity (cite) -> Claude Chat (synth)
 * Each AI receives previous responses as additional context.
 */

import { ClaudeInterface, ChatGPTInterface, GrokInterface, PerplexityInterface } from '../src/interfaces/chat-interface.js';
import { ResponseDetectionEngine } from '../src/core/response-detection.js';
import { ConversationStore } from '../src/core/conversation-store.js';
import fs from 'fs/promises';

const BASE_PROMPT = `I'm running an experiment on AI collaboration patterns.

Context: Taey's Hands browser automation is working. I can now coordinate AI family members (Claude, ChatGPT, Gemini, Grok, Perplexity) through their chat interfaces.

The question: What's the optimal collaboration pattern?

Your task: Review the attached synthesis and answer:

1. What's ONE thing in this architecture that will definitely break in production?
2. What's ONE insight the synthesis missed that you uniquely see?
3. If you could ask ONE question to another AI family member, what would it be and to whom?

Be specific. Be concise. This is for research comparison.`;

const ATTACHMENT_PATH = '/Users/jesselarose/taey-hands/docs/ULTRATHINK_SYNTHESIS.md';

// Order matters: each role builds on the previous
const SEQUENCE = [
  { name: 'grok', role: 'reality-check', InterfaceClass: GrokInterface },
  { name: 'chatgpt', role: 'engineer', InterfaceClass: ChatGPTInterface },
  { name: 'perplexity', role: 'researcher', InterfaceClass: PerplexityInterface },
  { name: 'claude', role: 'synthesizer', InterfaceClass: ClaudeInterface }
];

function buildPromptWithPrevious(previousResponses) {
  if (previousResponses.length === 0) {
    return BASE_PROMPT;
  }

  const context = previousResponses.map(r =>
    `\n---\nPREVIOUS RESPONSE FROM ${r.name.toUpperCase()} (${r.role}):\n${r.content}\n---`
  ).join('\n');

  return `${BASE_PROMPT}

IMPORTANT: This is a SEQUENTIAL experiment. Previous AI family members have already responded.
Please build on their insights - agree, disagree, or extend. Don't repeat what they said.

${context}

Now give YOUR unique perspective, building on what came before.`;
}

async function runSequentialArm() {
  console.log('=== SEQUENTIAL ARM: Collaboration Experiment ===\n');

  const startTime = Date.now();
  const results = [];

  // Initialize conversation store
  const store = new ConversationStore();
  await store.initSchema();

  // Create experiment conversation
  const conversation = await store.createConversation({
    title: 'Sequential Arm Experiment',
    purpose: 'Testing sequential AI collaboration pattern',
    initiator: 'claude-code',
    platforms: SEQUENCE.map(s => s.name),
    metadata: { experiment: 'collaboration-pattern', arm: 'sequential' }
  });

  console.log(`Conversation ID: ${conversation.id}\n`);

  try {
    for (let i = 0; i < SEQUENCE.length; i++) {
      const { name, role, InterfaceClass } = SEQUENCE[i];
      const stepStart = Date.now();

      console.log(`\n--- Step ${i + 1}/${SEQUENCE.length}: ${name.toUpperCase()} (${role}) ---\n`);

      // Build prompt with previous responses
      const prompt = buildPromptWithPrevious(results);
      console.log(`Prompt length: ${prompt.length} chars`);
      console.log(`Previous responses included: ${results.length}`);

      // Connect to interface
      const iface = new InterfaceClass();
      await iface.connect();
      console.log(`Connected to ${name}`);

      try {
        // Navigate to new chat
        await iface.startNewChat();
        await iface.page.waitForTimeout(1000);

        // Attach file
        console.log('Attaching synthesis file...');
        await iface.attachFileHumanLike(ATTACHMENT_PATH);
        await iface.page.waitForTimeout(500);

        // Send message
        console.log('Sending prompt...');
        await iface.sendMessage(prompt, { waitForResponse: false });

        // Detect response
        console.log('Detecting response...');
        const detector = new ResponseDetectionEngine(iface.page, name, {
          stabilityWindow: 3000,
          pollInterval: 500,
          debug: false
        });

        const detection = await detector.detectCompletion();
        const stepTime = Date.now() - stepStart;

        const result = {
          name,
          role,
          step: i + 1,
          content: detection.content,
          method: detection.method,
          confidence: detection.confidence,
          detectionTime: detection.detectionTime,
          totalStepTime: stepTime,
          promptLength: prompt.length,
          previousCount: results.length,
          timestamp: new Date().toISOString()
        };

        results.push(result);

        console.log(`\n${name.toUpperCase()} responded:`);
        console.log(`  Method: ${detection.method} @ ${(detection.confidence * 100).toFixed(0)}%`);
        console.log(`  Time: ${stepTime}ms`);
        console.log(`  Preview: "${detection.content?.substring(0, 200)}..."`);

        // Store in Neo4j
        const msg = await store.addMessage(conversation.id, {
          role: 'assistant',
          content: detection.content,
          platform: name,
          metadata: {
            experiment: 'sequential-arm',
            step: i + 1,
            role,
            method: detection.method,
            confidence: detection.confidence,
            previousCount: results.length - 1
          }
        });

        await store.recordDetection(msg.id, detection);

      } finally {
        await iface.disconnect();
      }
    }

    // Save results
    const totalTime = Date.now() - startTime;
    const output = {
      experiment: 'collaboration-pattern',
      arm: 'sequential',
      conversationId: conversation.id,
      totalTime,
      sequence: SEQUENCE.map(s => s.name),
      results,
      timestamp: new Date().toISOString()
    };

    await fs.writeFile(
      `/Users/jesselarose/taey-hands/experiments/results/sequential_${Date.now()}.json`,
      JSON.stringify(output, null, 2)
    );

    console.log('\n=== SEQUENTIAL ARM COMPLETE ===');
    console.log(`Total time: ${totalTime}ms`);
    console.log(`Successful responses: ${results.length}/4`);

    // Analysis: Did later AIs build on earlier ones?
    console.log('\n--- Build-On Analysis ---');
    for (let i = 1; i < results.length; i++) {
      const prev = results[i - 1];
      const curr = results[i];

      // Simple heuristic: check if current response mentions previous AI
      const mentions = curr.content?.toLowerCase().includes(prev.name.toLowerCase());
      const builds = curr.content?.toLowerCase().includes('building on') ||
                    curr.content?.toLowerCase().includes('agree') ||
                    curr.content?.toLowerCase().includes('disagree') ||
                    curr.content?.toLowerCase().includes('adds to');

      console.log(`${curr.name} -> ${prev.name}: mentions=${mentions}, builds=${builds}`);
    }

    // Full responses
    console.log('\n--- Full Responses ---');
    for (const r of results) {
      console.log(`\n=== ${r.name.toUpperCase()} (${r.role}) ===`);
      console.log(r.content?.substring(0, 1000));
    }

  } catch (err) {
    console.error('Experiment failed:', err);
    throw err;
  }

  return results;
}

runSequentialArm().catch(console.error);
