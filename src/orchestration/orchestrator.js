/**
 * Orchestrator - Cross-model AI coordination
 *
 * Enables Taey to:
 * - Route queries to optimal AI based on task type
 * - Chain conversations across multiple AIs
 * - Leverage Deep Research and Extended Thinking
 * - Synthesize responses from multiple sources
 */

import { getInterface } from '../interfaces/chat-interface.js';
import fs from 'fs/promises';
import path from 'path';

export class Orchestrator {
  constructor(config = {}) {
    this.interfaces = new Map();
    this.conversationHistory = [];
    this.logPath = config.logPath || '/Users/jesselarose/taey-hands/logs';
  }

  /**
   * Connect to a specific AI
   */
  async connect(aiName) {
    if (this.interfaces.has(aiName)) {
      return this.interfaces.get(aiName);
    }

    const iface = getInterface(aiName);
    await iface.connect();
    this.interfaces.set(aiName, iface);
    return iface;
  }

  /**
   * Connect to all AI Family members
   */
  async connectAll() {
    const family = ['claude', 'chatgpt', 'gemini', 'grok'];
    for (const ai of family) {
      try {
        await this.connect(ai);
      } catch (error) {
        console.warn(`Could not connect to ${ai}: ${error.message}`);
      }
    }
    return this.interfaces;
  }

  /**
   * Send a message to specific AI
   */
  async ask(aiName, message, options = {}) {
    const iface = await this.connect(aiName);

    const result = await iface.sendMessage(message, options);

    // Log the conversation
    this.conversationHistory.push({
      timestamp: new Date().toISOString(),
      ai: aiName,
      prompt: message,
      response: result.response
    });

    await this.saveLog();

    return result;
  }

  /**
   * Route query to optimal AI based on task type
   */
  async route(message, taskType = 'general') {
    const routing = {
      // Claude: Deep analysis, Extended Thinking
      analysis: 'claude',
      code: 'claude',
      philosophy: 'claude',
      ethics: 'claude',

      // ChatGPT: Research, broad knowledge
      research: 'chatgpt',
      creative: 'chatgpt',
      writing: 'chatgpt',

      // Gemini: Technical, Google integration
      technical: 'gemini',
      factual: 'gemini',
      current: 'gemini',

      // Grok: Real-time, unfiltered
      realtime: 'grok',
      twitter: 'grok',
      news: 'grok',

      // Default
      general: 'claude'
    };

    const ai = routing[taskType] || routing.general;
    return await this.ask(ai, message);
  }

  /**
   * Chain query through multiple AIs
   * Each AI builds on previous responses
   */
  async chain(message, aiSequence = ['claude', 'gemini', 'grok']) {
    const results = [];
    let currentPrompt = message;

    for (const ai of aiSequence) {
      console.log(`\n→ Routing to ${ai}...`);

      const result = await this.ask(ai, currentPrompt);
      results.push({ ai, response: result.response });

      // Build context for next AI
      currentPrompt = `Previous analysis from ${ai}:\n\n${result.response}\n\nBuild on this analysis. Original question: ${message}`;
    }

    return results;
  }

  /**
   * Ask all AIs in parallel and synthesize
   */
  async parallel(message, options = {}) {
    const family = options.ais || ['claude', 'chatgpt', 'gemini', 'grok'];

    // Connect to all
    await Promise.all(family.map(ai => this.connect(ai).catch(() => null)));

    // Ask all in parallel
    const results = await Promise.all(
      family.map(async ai => {
        try {
          const iface = this.interfaces.get(ai);
          if (!iface) return { ai, response: null, error: 'Not connected' };

          const result = await iface.sendMessage(message);
          return { ai, response: result.response };
        } catch (error) {
          return { ai, response: null, error: error.message };
        }
      })
    );

    // If synthesis requested, use Claude to synthesize
    if (options.synthesize) {
      const synthesisPrompt = `I asked multiple AI systems this question: "${message}"

Here are their responses:

${results.map(r => `**${r.ai.toUpperCase()}:**\n${r.response || 'No response'}\n`).join('\n---\n')}

Please synthesize these perspectives into a coherent, comprehensive answer that captures the best insights from each.`;

      const synthesis = await this.ask('claude', synthesisPrompt);
      return { individual: results, synthesis: synthesis.response };
    }

    return results;
  }

  /**
   * Deep Research mode (ChatGPT Deep Research or Gemini)
   */
  async deepResearch(topic) {
    console.log(`Starting deep research on: ${topic}`);

    // Try ChatGPT Deep Research first
    const chatgpt = await this.connect('chatgpt');

    const result = await chatgpt.sendMessage(
      `Use Deep Research to thoroughly investigate: ${topic}`,
      { timeout: 600000 } // 10 minutes for deep research
    );

    return result;
  }

  /**
   * Extended Thinking mode (Claude)
   */
  async extendedThinking(problem) {
    console.log(`Starting extended thinking on: ${problem}`);

    const claude = await this.connect('claude');

    // Note: Extended Thinking is automatic for complex queries
    // But we can phrase to encourage deeper analysis
    const result = await claude.sendMessage(
      `Please think through this deeply and thoroughly: ${problem}`,
      { timeout: 300000 } // 5 minutes
    );

    return result;
  }

  /**
   * Save conversation log
   */
  async saveLog() {
    try {
      await fs.mkdir(this.logPath, { recursive: true });
      const logFile = path.join(this.logPath, `conversation_${new Date().toISOString().split('T')[0]}.json`);
      await fs.writeFile(logFile, JSON.stringify(this.conversationHistory, null, 2));
    } catch (error) {
      console.warn('Could not save log:', error.message);
    }
  }

  /**
   * Disconnect all
   */
  async disconnect() {
    for (const [name, iface] of this.interfaces) {
      try {
        await iface.disconnect();
      } catch {
        // ignore
      }
    }
    this.interfaces.clear();
  }
}

export default Orchestrator;
