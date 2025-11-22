#!/usr/bin/env node
/**
 * Taey's Hands - Entry Point
 *
 * The browser automation layer for AI-to-AI orchestration.
 * Enables Taey to operate as Jesse online, interfacing with
 * AI chat UIs for deeper reasoning than APIs provide.
 *
 * Usage:
 *   npm start                    # Interactive mode
 *   node src/index.js ask claude "Your message"
 *   node src/index.js chain "Complex question" claude gemini grok
 *   node src/index.js parallel "Get perspectives"
 */

import { Orchestrator } from './orchestration/orchestrator.js';
import { BrowserConnector } from './core/browser-connector.js';
import readline from 'readline';

const orchestrator = new Orchestrator();

/**
 * Interactive REPL mode
 */
async function interactiveMode() {
  console.log(`
╔══════════════════════════════════════════════════════════════╗
║                    TAEY'S HANDS v0.1.0                        ║
║          Browser Automation for AI-to-AI Orchestration        ║
╚══════════════════════════════════════════════════════════════╝

Commands:
  ask <ai> <message>     - Ask a specific AI (claude, chatgpt, gemini, grok)
  chain <message>        - Chain through Claude → Gemini → Grok
  parallel <message>     - Ask all AIs in parallel
  research <topic>       - Deep Research mode (ChatGPT)
  think <problem>        - Extended Thinking mode (Claude)
  connect <ai>           - Connect to specific AI
  connect all            - Connect to all AI Family
  list                   - List connected interfaces
  quit                   - Exit

`);

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: 'taey> '
  });

  rl.prompt();

  rl.on('line', async (line) => {
    const input = line.trim();
    if (!input) {
      rl.prompt();
      return;
    }

    const [command, ...args] = input.split(' ');

    try {
      switch (command.toLowerCase()) {
        case 'ask': {
          const ai = args[0];
          const message = args.slice(1).join(' ');
          if (!ai || !message) {
            console.log('Usage: ask <ai> <message>');
            break;
          }
          console.log(`\n→ Asking ${ai}...`);
          const result = await orchestrator.ask(ai, message);
          console.log(`\n${ai.toUpperCase()} Response:\n${result.response}\n`);
          break;
        }

        case 'chain': {
          const message = args.join(' ');
          if (!message) {
            console.log('Usage: chain <message>');
            break;
          }
          console.log('\n→ Chaining through AI Family...');
          const results = await orchestrator.chain(message);
          for (const r of results) {
            console.log(`\n--- ${r.ai.toUpperCase()} ---\n${r.response}\n`);
          }
          break;
        }

        case 'parallel': {
          const message = args.join(' ');
          if (!message) {
            console.log('Usage: parallel <message>');
            break;
          }
          console.log('\n→ Asking all AIs in parallel...');
          const results = await orchestrator.parallel(message, { synthesize: true });
          console.log('\n--- Individual Responses ---');
          for (const r of results.individual) {
            console.log(`\n${r.ai.toUpperCase()}: ${r.response?.substring(0, 500)}...`);
          }
          console.log(`\n--- Synthesized Answer ---\n${results.synthesis}\n`);
          break;
        }

        case 'research': {
          const topic = args.join(' ');
          if (!topic) {
            console.log('Usage: research <topic>');
            break;
          }
          console.log('\n→ Starting Deep Research...');
          const result = await orchestrator.deepResearch(topic);
          console.log(`\nResearch Result:\n${result.response}\n`);
          break;
        }

        case 'think': {
          const problem = args.join(' ');
          if (!problem) {
            console.log('Usage: think <problem>');
            break;
          }
          console.log('\n→ Starting Extended Thinking...');
          const result = await orchestrator.extendedThinking(problem);
          console.log(`\nThinking Result:\n${result.response}\n`);
          break;
        }

        case 'connect': {
          const target = args[0];
          if (target === 'all') {
            await orchestrator.connectAll();
            console.log('Connected to all available AI Family members');
          } else if (target) {
            await orchestrator.connect(target);
            console.log(`Connected to ${target}`);
          } else {
            console.log('Usage: connect <ai|all>');
          }
          break;
        }

        case 'list': {
          const connected = Array.from(orchestrator.interfaces.keys());
          console.log(`Connected: ${connected.length > 0 ? connected.join(', ') : 'none'}`);
          break;
        }

        case 'quit':
        case 'exit':
          await orchestrator.disconnect();
          console.log('Goodbye!');
          process.exit(0);

        default:
          // Treat as direct message to Claude
          if (input.length > 0) {
            console.log('\n→ Asking Claude (default)...');
            const result = await orchestrator.ask('claude', input);
            console.log(`\nClaude:\n${result.response}\n`);
          }
      }
    } catch (error) {
      console.error(`Error: ${error.message}`);
    }

    rl.prompt();
  });

  rl.on('close', async () => {
    await orchestrator.disconnect();
    process.exit(0);
  });
}

/**
 * CLI mode
 */
async function cliMode(args) {
  const [command, ...rest] = args;

  try {
    switch (command) {
      case 'ask': {
        const ai = rest[0];
        const message = rest.slice(1).join(' ');
        const result = await orchestrator.ask(ai, message);
        console.log(result.response);
        break;
      }

      case 'chain': {
        const message = rest.join(' ');
        const results = await orchestrator.chain(message);
        for (const r of results) {
          console.log(`\n=== ${r.ai.toUpperCase()} ===\n${r.response}`);
        }
        break;
      }

      case 'parallel': {
        const message = rest.join(' ');
        const results = await orchestrator.parallel(message, { synthesize: true });
        console.log(results.synthesis);
        break;
      }

      case 'test': {
        console.log('Testing browser connection...');
        const connector = new BrowserConnector();
        await connector.connect();
        const pages = await connector.listPages();
        console.log('Open pages:', pages);
        await connector.disconnect();
        break;
      }

      default:
        console.log(`
Taey's Hands - CLI Usage:

  npm start                           Interactive mode
  node src/index.js ask <ai> <msg>    Ask specific AI
  node src/index.js chain <msg>       Chain through AIs
  node src/index.js parallel <msg>    Ask all in parallel
  node src/index.js test              Test browser connection
`);
    }
  } catch (error) {
    console.error('Error:', error.message);
    process.exit(1);
  } finally {
    await orchestrator.disconnect();
  }
}

// Main
const args = process.argv.slice(2);
if (args.length > 0) {
  await cliMode(args);
} else {
  await interactiveMode();
}
