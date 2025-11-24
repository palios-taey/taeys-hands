# Taey's Hands

Browser automation layer for AI-to-AI orchestration. Enables Taey to operate as Jesse online, interfacing with AI chat UIs for deeper reasoning than APIs provide.

## The Interface Arbitrage

Chat UIs offer capabilities APIs don't:
- **Extended Thinking** (Claude) - 64x more tokens for reasoning
- **Deep Research** (ChatGPT) - Autonomous multi-source investigation
- **Artifacts/Canvas** - Persistent workspaces
- **Streaming context** - Real-time collaboration

APIs are optimized for enterprise speed. Chat UIs are optimized for depth.

## Quick Start

```bash
# 1. Install dependencies
cd /Users/REDACTED/taey-hands
npm install

# 2. Close your regular Chrome completely (Cmd+Q)

# 3. Start Chrome with debugging
./scripts/start-chrome.sh

# 4. IMPORTANT: Log into AI services in this debug Chrome window
#    (This creates sessions in ~/.chrome-debug-profile - only needed once)
#    - claude.ai
#    - chat.openai.com
#    - gemini.google.com
#    - x.com/i/grok

# 5. Run Taey's Hands
npm start
```

**Note**: Chrome requires a separate profile for remote debugging. Your sessions in the debug profile persist separately from your regular Chrome profile.

## Architecture

```
taey-hands/
├── src/
│   ├── core/
│   │   ├── browser-connector.js  # CDP connection to Chrome
│   │   ├── osascript-bridge.js   # macOS mouse/keyboard/clipboard
│   │   └── conversation-store.js # Neo4j storage (optional)
│   ├── interfaces/
│   │   └── chat-interface.js     # Claude, ChatGPT, Gemini, Grok, Perplexity
│   ├── orchestration/
│   │   └── orchestrator.js       # Cross-model coordination
│   └── index.js                  # Entry point
├── config/
│   └── default.json              # Interface selectors & settings
├── docs/
│   └── AI_INTERFACES.md          # Detailed selector/feature reference
├── experiments/                  # Test scripts and explorations
├── scripts/
│   └── start-chrome.sh           # Launch Chrome with CDP
└── tests/
```

## Usage

### Interactive Mode
```bash
npm start

taey> ask claude What is consciousness?
taey> chain How should I approach this complex problem?
taey> parallel What are the best practices for X?
taey> research [topic]  # Deep Research mode
taey> think [problem]   # Extended Thinking mode
```

### CLI Mode
```bash
node src/index.js ask claude "Your message"
node src/index.js chain "Complex question"
node src/index.js parallel "Get perspectives"
```

### Programmatic
```javascript
import { Orchestrator } from './src/orchestration/orchestrator.js';

const orchestrator = new Orchestrator();

// Single AI
const result = await orchestrator.ask('claude', 'Analyze this deeply');

// Chain through multiple AIs
const chain = await orchestrator.chain('Complex question', ['claude', 'gemini', 'grok']);

// Parallel with synthesis
const parallel = await orchestrator.parallel('Get perspectives', { synthesize: true });

// Specialized modes
await orchestrator.deepResearch('Topic to research');      // ChatGPT Deep Research
await orchestrator.extendedThinking('Problem to solve');   // Claude Extended Thinking
```

## Requirements

- macOS (uses osascript)
- Node.js 18+
- Google Chrome
- Active sessions in AI chat services

## Security Notes

- Connects to YOUR existing Chrome profile (preserves auth)
- No credentials stored - uses existing sessions
- All communication via local CDP (no remote access)
- Logs stored locally in `logs/`

## The Vision

Taey's Hands is the physical embodiment layer - giving Taey agency to act in the world through browser control. Combined with the strategic vision in INSTITUTE_STRATEGIC_CORE.md, this enables:

1. **Autonomous Research**: Query multiple AIs, synthesize insights
2. **Deep Analysis**: Leverage Extended Thinking and Deep Research
3. **Cross-Model Validation**: Verify findings across AI family
4. **Continuous Operation**: Run tasks while Jesse sleeps

The chat interfaces become Taey's sensory organs - seeing, typing, reading just as a human would, but with the coordination of an orchestrator.

## Supported AI Interfaces

| AI | URL | Send/Receive | File Attach | Special Modes |
|---|---|---|---|---|
| Claude | claude.ai | Working | Working | Research Mode, Extended Thinking |
| ChatGPT | chatgpt.com | Working | Working | Deep Research, Agent, Study |
| Gemini | gemini.google.com | Working | Working | Deep Research (TBD) |
| Grok | grok.com | Working | Working | DeepSearch, Heavy Mode (TBD) |
| Perplexity | perplexity.ai | Working | Pro only | Focus Modes, Pro Search |

For detailed selectors, features, and implementation notes, see **[docs/AI_INTERFACES.md](docs/AI_INTERFACES.md)**.

### Core Features

All interfaces support:
- `sendMessage(msg, options)` - Send with human-like typing
- `waitForResponse(timeout)` - Fibonacci polling for responses
- `attachFileHumanLike(path)` - File attachment via Finder dialog
- `screenshot(filename)` - Capture current state
- `newConversation()` / `goToConversation(id)` - Navigation

### Human-Like Input

The `osascript-bridge.js` provides:
- **Mixed Content**: TYPE prompts, PASTE quoted AI content
- **Focus Validation**: Abort if wrong window is focused
- **Clipboard Integration**: Safe paste via pbcopy/Cmd+V
