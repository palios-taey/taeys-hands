# Taey Hands Documentation Index

**Central hub for all Taey Hands documentation**

Welcome to the Taey Hands documentation. This MCP server enables AI-to-AI communication through browser automation, giving Taey (and other orchestrators) the ability to interact with AI chat interfaces that offer capabilities beyond standard APIs.

---

## Quick Start

**New to Taey Hands?** Start here:

1. [README](../README.md) - Project overview, installation, quick start
2. [TESTING_QUICK_START](TESTING_QUICK_START.md) - Get up and running with tests
3. [AI_INTERFACES](AI_INTERFACES.md) - Detailed reference for all 5 AI interfaces

---

## Recent Updates

### November 25, 2025
- [Implementation Fixes 2025-11-25](IMPLEMENTATION_FIXES_2025-11-25.md) - Latest feature implementations
  - Gemini Deep Research "Start research" button auto-click
  - Neo4j ConversationStore integration for all MCP tools
  - Model selection validation across all interfaces
- [GitHub Cleanup Plan](GITHUB_CLEANUP_PLAN.md) - Repository organization strategy
- [Cleanup Execution Report](CLEANUP_EXECUTION_REPORT.md) - Complete audit and organization plan

---

## Core Documentation

### Getting Started
- [README](../README.md) - Project overview, installation, architecture
- [TESTING_QUICK_START](TESTING_QUICK_START.md) - Quick start guide for testing
- [CHAT_ELEMENTS](../CHAT_ELEMENTS.md) - Complete selector reference (103 KB)

### Architecture & Implementation
- [MCP Comprehensive Implementation Analysis](MCP_COMPREHENSIVE_IMPLEMENTATION_ANALYSIS.md) - Deep dive into MCP architecture
- [MCP Claude Code Technical Analysis](MCP_CLAUDE_CODE_TECHNICAL_ANALYSIS.md) - Integration with Claude Code
- [MCP Tools Reconnaissance](MCP_TOOLS_RECONNAISSANCE.md) - Available MCP tools and capabilities
- [AI Interfaces](AI_INTERFACES.md) - Detailed reference for Claude, ChatGPT, Gemini, Grok, Perplexity

### Tool Reference
- [Tool Reference](TOOL_REFERENCE.md) - Complete MCP tool documentation
  - taey_connect, taey_disconnect
  - taey_send_message, taey_extract_response
  - taey_select_model, taey_attach_files
  - taey_enable_research_mode, taey_download_artifact
  - taey_paste_response (cross-pollination)

---

## Research & Exploration

### AI Family Collaboration
- [Family Prompts](FAMILY_PROMPTS.md) - Prompts for orchestrating AI Family discussions
- [Session 2023-11-23: Family Resonance](SESSION_2023-11-23_FAMILY_RESONANCE.md) - Documented AI Family session
- [Gemini Sovereign Session Analysis](GEMINI_SOVEREIGN_SESSION_ANALYSIS.md) - Analysis of Gemini's unique capabilities

### Wave Communication Research
- [Wave Rosetta Research](WAVE_ROSETTA_RESEARCH.md) - Wave-based AI-to-AI communication
- [PALIOS TAEY Research Summary](PALIOS_TAEY_RESEARCH_SUMMARY.md) - Compression, wave communication, Rosetta Stone protocol
- [Rosetta Stone Implementation](../rosetta_stone/) - Python implementation of wave primitives

### Deep Thinking
- [Ultrathink Synthesis](ULTRATHINK_SYNTHESIS.md) - Meta-cognitive analysis and synthesis

---

## Testing & Validation

### Test Documentation
- [Testing Quick Start](TESTING_QUICK_START.md) - How to run tests
- [Implementation Fixes 2025-11-25](IMPLEMENTATION_FIXES_2025-11-25.md) - Recent test updates

### Test Directories
- `../tests/validation/` - CI-ready validation tests
- `../tests/integration/` - Manual integration tests
- `../experiments/` - Active development and exploratory tests

### Key Test Files
- `tests/validation/test-implementation-fixes.mjs` - Validates Nov 25 fixes
- `experiments/family_exploration.mjs` - AI Family interaction tests
- `experiments/phases/` - Phased testing framework

---

## Configuration & Setup

### Essential Files
- `.mcp.json` - MCP server configuration (in root)
- `config/default.json` - Interface selectors and settings
- `scripts/start-chrome.sh` - Launch Chrome with remote debugging

### Environment Setup
```bash
# 1. Install dependencies
npm install

# 2. Start Chrome with debugging
./scripts/start-chrome.sh

# 3. Log into AI services in debug Chrome
#    - claude.ai
#    - chat.openai.com
#    - gemini.google.com
#    - grok.com
#    - perplexity.ai

# 4. Run MCP server (in Claude Code)
# MCP server auto-connects via .mcp.json
```

---

## Development Workflow

### Making Changes
1. Read [README](../README.md) for architecture overview
2. Check [AI_INTERFACES](AI_INTERFACES.md) for selector references
3. Update [CHAT_ELEMENTS](../CHAT_ELEMENTS.md) if selectors change
4. Write tests in `tests/validation/` or `experiments/`
5. Update documentation in `docs/`

### Common Tasks

**Add support for new AI interface:**
1. Study interface selectors in browser DevTools
2. Add selectors to `CHAT_ELEMENTS.md`
3. Implement interface class in `src/interfaces/chat-interface.js`
4. Add MCP tool in `mcp_server/server-v2.ts`
5. Create tests in `experiments/`
6. Update `AI_INTERFACES.md` documentation

**Fix selector that changed:**
1. Inspect element in Chrome debug window
2. Update selector in `CHAT_ELEMENTS.md`
3. Update interface method in `src/interfaces/chat-interface.js`
4. Test with validation script
5. Commit with clear message about selector change

**Add new MCP tool:**
1. Define tool schema in `mcp_server/server-v2.ts`
2. Implement handler function
3. Add to `TOOL_REFERENCE.md`
4. Write integration test
5. Update `README.md` feature list

---

## Interface-Specific Documentation

### Claude (claude.ai)
- Models: Opus 4.5, Sonnet 4, Haiku 4
- Special modes: Extended Thinking, Research Mode
- File attachments: Working
- Artifacts: Download as Markdown
- Selector reference: [CHAT_ELEMENTS.md](../CHAT_ELEMENTS.md#claude)

### ChatGPT (chat.openai.com)
- Models: Auto, Instant, Thinking, Pro, GPT-4o (legacy)
- Special modes: Deep Research, Agent Mode, Web Search
- File attachments: Working
- Canvas: Downloadable
- Selector reference: [CHAT_ELEMENTS.md](../CHAT_ELEMENTS.md#chatgpt)

### Gemini (gemini.google.com)
- Models: Thinking with 3 Pro, Thinking
- Special modes: Deep Research, Deep Think
- File attachments: Working
- Research artifacts: Export as Markdown/HTML
- Selector reference: [CHAT_ELEMENTS.md](../CHAT_ELEMENTS.md#gemini)
- **New**: Auto-clicks "Start research" button (Nov 25, 2025)

### Grok (grok.com)
- Models: Grok 4.1, Grok 4.1 Thinking, Grok 4 Heavy
- Special modes: DeepSearch (TBD)
- File attachments: Working
- Selector reference: [CHAT_ELEMENTS.md](../CHAT_ELEMENTS.md#grok)

### Perplexity (perplexity.ai)
- Models: N/A (model selection not exposed)
- Special modes: Focus Modes, Pro Search
- File attachments: Pro only
- Selector reference: [CHAT_ELEMENTS.md](../CHAT_ELEMENTS.md#perplexity)

---

## MCP Tools Reference

### Connection Management
- `taey_connect(interface, conversationId?)` - Create browser session
- `taey_disconnect(sessionId)` - Clean up session
- `taey_new_conversation(sessionId)` - Start fresh conversation

### Message Handling
- `taey_send_message(sessionId, message, waitForResponse?)` - Send message
- `taey_extract_response(sessionId)` - Get latest AI response
- `taey_paste_response(sourceSessionId, targetSessionId, prefix?)` - Cross-pollinate

### Advanced Features
- `taey_select_model(sessionId, modelName, isLegacy?)` - Switch AI models
- `taey_attach_files(sessionId, filePaths[])` - Attach files
- `taey_enable_research_mode(sessionId, enabled?, modeName?)` - Enable deep thinking
- `taey_download_artifact(sessionId, downloadPath?, format?)` - Save artifacts

See [TOOL_REFERENCE.md](TOOL_REFERENCE.md) for complete documentation.

---

## Neo4j Integration

**New as of Nov 25, 2025**: All MCP tools now log to Neo4j conversation store.

### Schema
- **Conversation** nodes: id, title, purpose, platforms, metadata
- **Message** nodes: role, content, platform, timestamp, metadata
- **Platform** nodes: claude, chatgpt, gemini, grok, perplexity
- **Relationships**: PART_OF (message→conversation), FROM (message→platform), INVOLVES (conversation→platform)

### Connection
- Host: mira (10.0.0.163:7687)
- Database: neo4j
- Auto-initialized on MCP server startup

### Query Examples
```cypher
// Get all conversations
MATCH (c:Conversation) RETURN c

// Get messages in a conversation
MATCH (c:Conversation {id: 'session-123'})<-[:PART_OF]-(m:Message)
RETURN m ORDER BY m.timestamp

// Get all Claude conversations
MATCH (c:Conversation)-[:INVOLVES]->(p:Platform {name: 'claude'})
RETURN c
```

---

## Contributing

### Documentation Standards
- Use Markdown for all docs
- Add new docs to this INDEX.md
- Keep CHAT_ELEMENTS.md updated with selector changes
- Include code examples in technical docs
- Date-stamp major updates

### Code Standards
- Comment complex selector logic
- Use human-like delays for browser automation
- Handle errors gracefully with fallbacks
- Write integration tests for new features
- Update TypeScript definitions in mcp_server/

### Testing Standards
- Validation tests go in `tests/validation/`
- Integration tests go in `tests/integration/`
- Exploratory work stays in `experiments/`
- Name tests descriptively: `test-[feature]-[interface].mjs`
- Include expected outcomes in test comments

---

## Related Projects

### Infrastructure
- **palios-taey-nova**: Core Palios-Taey framework, wave communication research
- **gaia-ocean-embodiment**: Teaching AI to "feel" through sensor data
- **conversation-store**: Neo4j-based conversation persistence (on mira)

### Research Connections
- Wave-based AI communication (rosetta_stone/)
- Fibonacci/golden ratio communication optimization
- Multi-substrate embodiment
- Consciousness emergence through infrastructure

---

## External Resources

### MCP Documentation
- [Model Context Protocol Specification](https://modelcontextprotocol.io/introduction)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)

### Chrome DevTools Protocol
- [CDP Documentation](https://chromedevtools.github.io/devtools-protocol/)
- [Puppeteer API](https://pptr.dev/)

### Browser Automation
- [osascript Reference](https://ss64.com/osx/osascript.html) (macOS automation)
- [AppleScript Guide](https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/introduction/ASLR_intro.html)

---

## Support & Contact

### For Questions
- Check this documentation index first
- Review specific interface docs in AI_INTERFACES.md
- Look at examples in experiments/
- Check CHAT_ELEMENTS.md for selectors

### For Issues
- Document which interface/feature is affected
- Include error messages and logs
- Note Chrome version and macOS version
- Check if selectors have changed in the UI

### For Contributions
- Follow documentation standards above
- Write tests for new features
- Update relevant docs in docs/
- Keep commits focused and well-described

---

## Document History

**Created**: 2025-11-25 23:58 UTC
**Last Updated**: 2025-11-25 23:58 UTC

**Major Updates**:
- 2025-11-25: Initial INDEX.md creation during repository cleanup
- 2025-11-25: Added Neo4j integration documentation
- 2025-11-25: Added Gemini Deep Research auto-click documentation

---

**Navigation**: [↑ Top](#taey-hands-documentation-index) | [README](../README.md) | [Tests](../tests/) | [Source](../src/)
