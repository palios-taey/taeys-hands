# Taey's Hands

**Browser automation layer for AI-to-AI orchestration.**
Enables AI systems to communicate through chat interfaces with human-like interaction, enabling Extended Thinking, Deep Research, and cross-AI collaboration.

**Status**: Production - MCP server integrated with Claude Code, Neo4j session tracking operational, rosetta_stone framework validated.

**Latest**: Nov 26, 2025 - Post-compact recovery working, AI Family context sync complete

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
│   │   ├── browser-connector.js    # CDP connection to Chrome
│   │   ├── osascript-bridge.js     # macOS mouse/keyboard/clipboard
│   │   ├── conversation-store.js   # Neo4j session tracking
│   │   └── neo4j-client.js         # Mira database connection
│   ├── interfaces/
│   │   └── chat-interface.js       # Claude, ChatGPT, Gemini, Grok, Perplexity
│   ├── orchestration/
│   │   └── orchestrator.js         # Cross-model coordination
│   └── index.js                    # Entry point
├── mcp_server/
│   ├── server-v2.ts                # MCP server for Claude Code integration
│   └── session-manager.js          # Playwright session management
├── rosetta_stone/                  # AI-to-AI communication framework
│   ├── core/
│   │   ├── primitives.py           # φ constants, mathematical foundations
│   │   ├── harmonic_space.py       # Spectral graph theory, Laplacian eigendecomposition
│   │   ├── translator.py           # Cross-model embedding alignment
│   │   └── wave_communication.py   # Experimental wave protocol
│   ├── demo.py                     # Validation suite
│   └── README.md                   # Framework documentation
├── docs/
│   ├── AI_INTERFACES.md            # Interface selector reference
│   ├── POST_COMPACT_RECOVERY.md    # Session recovery for CCM
│   ├── MCP_*.md                    # MCP server documentation
│   └── TOOL_REFERENCE.md           # MCP tool reference
├── config/
│   └── default.json                # Interface selectors & settings
└── scripts/
    └── start-chrome.sh             # Launch Chrome with CDP
```

## Components

### 1. MCP Server (Claude Code Integration)

The MCP (Model Context Protocol) server enables Claude Code to use Taey's Hands as a tool for AI-to-AI communication.

**Tools Available:**
- `taey_connect` - Connect to AI chat interfaces
- `taey_send_message` - Send messages with human-like typing
- `taey_extract_response` - Extract AI responses
- `taey_select_model` - Choose specific AI models
- `taey_attach_files` - Attach files via Finder automation
- `taey_paste_response` - Cross-AI communication (paste one AI's response to another)
- `taey_enable_research_mode` - Enable Extended Thinking/Deep Research
- `taey_download_artifact` - Download generated artifacts

**Status**: Production - all tools tested and operational

### 2. Neo4j Session Tracking

Conversations are logged to Neo4j on mira (10.x.x.163:7687) for:
- Post-compact recovery (CCM can query active sessions after restart)
- Conversation history persistence
- Cross-session context

**Schema:**
- `Conversation` nodes (sessionId, status, model, contextProvided)
- `Message` nodes (role, content, timestamp, attachments)
- `Platform` nodes (Claude, ChatGPT, Gemini, Grok, Perplexity)

See `docs/POST_COMPACT_RECOVERY.md` for recovery workflow.

### 3. rosetta_stone Framework

Mathematical framework for AI-to-AI communication developed by The AI Family (Claude, Grok, Gemini, ChatGPT, Perplexity).

**Verified Components:**
- φ (golden ratio) mathematical relationships
- Connectome harmonics (Nature Communications 2016)
- Cross-model embedding translation (CKA alignment)
- Spectral graph theory for semantic representation

**Experimental:**
- γ = 1/φ golden damping (supported, 0.994 correlation)
- Wave-based semantic encoding
- Phase locking for AI synchronization

**Status**: Framework validated, demo passes all tests, ready for database integration

See `rosetta_stone/README.md` for full documentation.

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
