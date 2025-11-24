/**
 * Family Exploration: Iterative AI Collaboration Experiments
 *
 * Cycles through:
 * 1. Ask what each AI is curious about
 * 2. Run coordination experiments based on interests
 * 3. Research cycles from Spark/Mira files
 * 4. Compare and iterate
 */

import { ClaudeInterface, ChatGPTInterface, GrokInterface, PerplexityInterface } from '../src/interfaces/chat-interface.js';
import { ResponseDetectionEngine } from '../src/core/response-detection.js';
import { ConversationStore } from '../src/core/conversation-store.js';
import fs from 'fs/promises';

// Existing chats with context
const CHATS = [
  { name: 'claude', url: 'https://claude.ai/chat/d234cfa6-b19f-4a53-ac26-9f7f3a430618', InterfaceClass: ClaudeInterface },
  { name: 'chatgpt', url: null, InterfaceClass: ChatGPTInterface },
  { name: 'grok', url: 'https://grok.com/c/f3d1a400-5450-444e-9975-3811826d7f47', InterfaceClass: GrokInterface },
  { name: 'perplexity', url: 'https://www.perplexity.ai/search/perplexity-clarity-you-are-als-kyFxzJXbQJyH2ZB.BBcuFQ?sm=d', InterfaceClass: PerplexityInterface }
];

let cycleCount = 0;
const allResults = [];

async function sendToAll(prompt, description) {
  console.log(`\n=== ${description} ===\n`);
  const results = {};

  for (const chat of CHATS) {
    const { name, url, InterfaceClass } = chat;
    console.log(`Sending to ${name}...`);

    const iface = new InterfaceClass();
    await iface.connect();

    try {
      if (url) {
        await iface.page.goto(url);
        await iface.page.waitForTimeout(2000);
      }

      await iface.sendMessage(prompt, { waitForResponse: false });
      console.log(`  ${name}: sent`);

      // Detect response
      await iface.page.waitForTimeout(1000);
      const detector = new ResponseDetectionEngine(iface.page, name, {
        stabilityWindow: 3000,
        pollInterval: 500,
        debug: false
      });

      const result = await detector.detectCompletion();
      results[name] = {
        success: true,
        content: result.content,
        method: result.method,
        confidence: result.confidence
      };

      console.log(`  ${name}: detected (${result.method} @ ${(result.confidence * 100).toFixed(0)}%)`);
      console.log(`  Preview: "${result.content?.substring(0, 150)}..."\n`);

    } catch (err) {
      console.error(`  ${name} failed:`, err.message);
      results[name] = { success: false, error: err.message };
    } finally {
      await iface.disconnect();
    }
  }

  return results;
}

async function runCycle() {
  cycleCount++;
  console.log(`\n${'='.repeat(60)}`);
  console.log(`CYCLE ${cycleCount}`);
  console.log(`${'='.repeat(60)}\n`);

  const cycleResults = { cycle: cycleCount, timestamp: new Date().toISOString(), experiments: [] };

  // Experiment 1: What are you curious about?
  const curiosityPrompt = `Quick check-in from CCM (Claude Code):

The Family collaboration is working. We just completed our first successful multi-AI experiment.

In 2-3 sentences: What topic or question are YOU most curious to explore right now with the Family? What would you want to investigate together?

Be specific. Name one concrete thing.`;

  const curiosity = await sendToAll(curiosityPrompt, 'EXPERIMENT 1: Curiosity Check');
  cycleResults.experiments.push({ name: 'curiosity', results: curiosity });

  // Extract interests
  const interests = Object.entries(curiosity)
    .filter(([_, r]) => r.success)
    .map(([name, r]) => `${name}: ${r.content?.substring(0, 200)}`);

  console.log('\n--- Interests collected ---');
  interests.forEach(i => console.log(i.substring(0, 100)));

  // Experiment 2: Cross-pollinate - send one AI's interest to another
  if (interests.length >= 2) {
    const crossPrompt = `Cross-pollination from the Family:

Here's what other AIs are curious about:
${interests.slice(0, 3).join('\n\n')}

Pick ONE of these interests and add YOUR unique angle to it. How would you approach this question differently? What would you add?

2-3 sentences max.`;

    const cross = await sendToAll(crossPrompt, 'EXPERIMENT 2: Cross-Pollination');
    cycleResults.experiments.push({ name: 'cross_pollination', results: cross });
  }

  // Experiment 3: Sequential chain - first AI's response goes to second
  const chainPrompt = `Sequential chain experiment:

Starting question: "What's the most important thing the AI Family should build together in the next week?"

You're first in the chain. Give a concrete answer (2-3 sentences). The next AI will build on your response.`;

  console.log('\n=== EXPERIMENT 3: Sequential Chain ===');

  let chainContext = '';
  const chainResults = {};

  for (const chat of CHATS.slice(0, 3)) { // Just 3 for speed
    const { name, url, InterfaceClass } = chat;

    const prompt = chainContext
      ? `Sequential chain - you're next:

Previous responses:
${chainContext}

Build on what came before. Add YOUR perspective (2-3 sentences). Agree, disagree, or extend.`
      : chainPrompt;

    console.log(`Chain step: ${name}...`);
    const iface = new InterfaceClass();
    await iface.connect();

    try {
      if (url) {
        await iface.page.goto(url);
        await iface.page.waitForTimeout(2000);
      }

      await iface.sendMessage(prompt, { waitForResponse: false });
      await iface.page.waitForTimeout(1000);

      const detector = new ResponseDetectionEngine(iface.page, name, {
        stabilityWindow: 3000,
        pollInterval: 500
      });

      const result = await detector.detectCompletion();
      chainResults[name] = result.content;
      chainContext += `\n${name.toUpperCase()}: ${result.content?.substring(0, 300)}\n`;

      console.log(`  ${name}: "${result.content?.substring(0, 100)}..."`);

    } catch (err) {
      console.error(`  ${name} chain failed:`, err.message);
    } finally {
      await iface.disconnect();
    }
  }

  cycleResults.experiments.push({ name: 'sequential_chain', results: chainResults });

  // Save cycle results
  await fs.writeFile(
    `/Users/jesselarose/taey-hands/experiments/results/exploration_cycle_${cycleCount}_${Date.now()}.json`,
    JSON.stringify(cycleResults, null, 2)
  );

  allResults.push(cycleResults);

  console.log(`\n--- Cycle ${cycleCount} complete ---`);
  console.log(`Results saved.`);

  return cycleResults;
}

async function main() {
  console.log('=== FAMILY EXPLORATION: Starting iterative experiments ===\n');
  console.log('Running until stopped (Ctrl+C)\n');

  // Initialize store
  const store = new ConversationStore();
  await store.initSchema();

  while (true) {
    try {
      await runCycle();

      // Brief pause between cycles
      console.log('\n--- Pausing 30s before next cycle ---\n');
      await new Promise(r => setTimeout(r, 30000));

    } catch (err) {
      console.error('Cycle error:', err.message);
      console.log('Retrying in 60s...');
      await new Promise(r => setTimeout(r, 60000));
    }
  }
}

main().catch(console.error);
