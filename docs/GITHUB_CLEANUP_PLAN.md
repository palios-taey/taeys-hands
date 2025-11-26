# GitHub Repository Cleanup Plan

## Current State Analysis

**Unstaged Changes:**
```
M CHAT_ELEMENTS.md
M mcp_server/dist/server-v2.js
M mcp_server/dist/server-v2.js.map
M mcp_server/server-v2.ts
M src/interfaces/chat-interface.js
```

**Untracked Files:**
```
.mcp.json
docs/MCP_COMPREHENSIVE_IMPLEMENTATION_ANALYSIS.md
docs/README_ANALYSIS.md
docs/TESTING_QUICK_START.md
docs/TOOL_REFERENCE.md
IMPLEMENTATION_FIXES_2025-11-25.md
GITHUB_CLEANUP_PLAN.md
test-implementation-fixes.mjs
```

---

## Cleanup Strategy

### Phase 1: Documentation Organization

#### Move to /docs
```bash
mv IMPLEMENTATION_FIXES_2025-11-25.md docs/
mv GITHUB_CLEANUP_PLAN.md docs/
```

#### Create docs/INDEX.md
Centralize all documentation with clear categories:
- **Getting Started**
- **Implementation Guides**
- **Testing & Validation**
- **Architecture & Design**
- **AI Family Collaboration**

### Phase 2: Test Organization

#### Create /tests directory
```bash
mkdir -p tests/integration
mkdir -p tests/validation
mv test-implementation-fixes.mjs tests/validation/
mv experiments/*.mjs tests/integration/
```

### Phase 3: Configuration Cleanup

#### .mcp.json
- Review contents
- Add to .gitignore if it contains secrets
- Or commit if it's template config

### Phase 4: Code Commits

**Commit 1: Gemini Deep Research Fix**
```bash
git add src/interfaces/chat-interface.js
git commit -m "feat: Add Gemini Deep Research Start button auto-click

- Override waitForResponse() in GeminiInterface
- Detect and click 'Start research' button automatically
- Falls back to normal polling for regular conversations
- Fixes #<issue> (if tracked)
"
```

**Commit 2: Neo4j Logging Integration**
```bash
git add mcp_server/server-v2.ts mcp_server/dist/
git commit -m "feat: Integrate ConversationStore Neo4j logging

- Add Neo4j logging to all MCP tools
- Log conversations, user messages, assistant responses
- Auto-create conversation on taey_connect
- Store metadata: platform, timestamp, content length

Connected to mira (10.0.0.163:7687)
Uses existing conversation-store infrastructure
"
```

**Commit 3: Documentation & Tests**
```bash
git add docs/ tests/ CHAT_ELEMENTS.md
git commit -m "docs: Add implementation fixes documentation and validation tests

- Document Nov 25 2025 implementation fixes
- Add validation test suite
- Create GitHub cleanup plan
- Update CHAT_ELEMENTS.md with Gemini selectors
"
```

### Phase 5: Branch Strategy

**Current branch:** `feature/mcp-function-based-tools`

**Recommended:**
1. Keep working on this branch for now
2. After validation tests pass, merge to main
3. Tag release: `v0.2.0-neo4j-integration`

---

## File Structure (Proposed)

```
taey-hands/
├── README.md
├── .gitignore
├── package.json
│
├── src/
│   ├── core/
│   │   ├── neo4j-client.js
│   │   ├── conversation-store.js
│   │   └── osascript-bridge.js
│   ├── interfaces/
│   │   └── chat-interface.js
│   └── orchestration/
│       └── orchestrator.js
│
├── mcp_server/
│   ├── server-v2.ts
│   ├── session-manager.ts
│   ├── dist/
│   └── package.json
│
├── docs/
│   ├── INDEX.md                              # NEW: Documentation hub
│   ├── IMPLEMENTATION_FIXES_2025-11-25.md   # MOVED
│   ├── GITHUB_CLEANUP_PLAN.md               # MOVED
│   ├── MCP_COMPREHENSIVE_IMPLEMENTATION_ANALYSIS.md
│   ├── README_ANALYSIS.md
│   ├── TESTING_QUICK_START.md
│   ├── TOOL_REFERENCE.md
│   ├── AI_INTERFACES.md
│   ├── FAMILY_PROMPTS.md
│   ├── ULTRATHINK_SYNTHESIS.md
│   └── SESSION_2023-11-23_FAMILY_RESONANCE.md
│
├── tests/
│   ├── validation/
│   │   └── test-implementation-fixes.mjs    # MOVED
│   └── integration/
│       ├── parallel_arm.mjs                 # MOVED from experiments/
│       ├── sequential_arm.mjs               # MOVED
│       └── family_exploration.mjs           # MOVED
│
├── experiments/                              # DEPRECATED - move to tests/
│   └── (empty after cleanup)
│
├── logs/                                     # Keep as-is
│   ├── conversation_2025-11-22.json
│   └── conversation_2025-11-23.json
│
└── rosetta_stone/                            # Keep as-is
    ├── primitives.py
    ├── wave_communication.py
    └── README.md
```

---

## .gitignore Updates

Add these entries:
```gitignore
# MCP config (may contain secrets)
.mcp.json

# Neo4j credentials
.env
*.pem

# Test outputs
/tmp/
/screenshots/
tests/**/*.png
tests/**/results/

# Build artifacts
mcp_server/dist/*.js.map

# Session data
.sessions/
```

---

## Execution Script

```bash
#!/bin/bash
# execute-cleanup.sh

echo "🧹 GitHub Cleanup: Taey Hands Repository"
echo "=========================================="

# Phase 1: Create directories
echo "\n📁 Creating directory structure..."
mkdir -p docs tests/validation tests/integration

# Phase 2: Move files
echo "\n📦 Moving files..."
mv IMPLEMENTATION_FIXES_2025-11-25.md docs/
mv GITHUB_CLEANUP_PLAN.md docs/
mv test-implementation-fixes.mjs tests/validation/

# Keep experiments/ for now (contains active work)
# Will move after validation

# Phase 3: Update .gitignore
echo "\n🚫 Updating .gitignore..."
cat >> .gitignore <<EOF

# MCP config
.mcp.json

# Test outputs
/tmp/taey-*
tests/**/*.png
tests/**/results/

# Build maps
mcp_server/dist/*.js.map
EOF

# Phase 4: Create docs index
echo "\n📚 Creating documentation index..."
cat > docs/INDEX.md <<EOF
# Taey Hands Documentation Index

## Quick Start
- [README](../README.md) - Project overview
- [Testing Quick Start](TESTING_QUICK_START.md) - Get started testing

## Recent Updates
- [Implementation Fixes 2025-11-25](IMPLEMENTATION_FIXES_2025-11-25.md) - Latest changes
- [GitHub Cleanup Plan](GITHUB_CLEANUP_PLAN.md) - Repository organization

## Architecture
- [MCP Comprehensive Analysis](MCP_COMPREHENSIVE_IMPLEMENTATION_ANALYSIS.md)
- [AI Interfaces](AI_INTERFACES.md)
- [Tool Reference](TOOL_REFERENCE.md)

## AI Family
- [Family Prompts](FAMILY_PROMPTS.md)
- [Session: Family Resonance](SESSION_2023-11-23_FAMILY_RESONANCE.md)
- [Ultrathink Synthesis](ULTRATHINK_SYNTHESIS.md)

## Contributing
- See main [README](../README.md) for development setup
EOF

echo "\n✅ Cleanup complete!"
echo "\nNext steps:"
echo "1. Review changes: git status"
echo "2. Run validation tests: node tests/validation/test-implementation-fixes.mjs"
echo "3. Commit changes: see GITHUB_CLEANUP_PLAN.md Phase 4"
```

---

## Validation Before Commit

1. **Run tests:**
   ```bash
   node tests/validation/test-implementation-fixes.mjs
   ```

2. **Check Neo4j connection:**
   ```bash
   nc -zv 10.0.0.163 7687
   ```

3. **Verify TypeScript build:**
   ```bash
   cd mcp_server && npm run build
   ```

4. **Test MCP server:**
   ```bash
   # In Claude Code, test taey_connect, taey_send_message, taey_extract_response
   ```

---

## Post-Cleanup TODO

- [ ] Execute cleanup script
- [ ] Run validation tests
- [ ] Review all git changes
- [ ] Create 3 commits (as described above)
- [ ] Tag release v0.2.0
- [ ] Update main README.md with new features
- [ ] Consider creating CHANGELOG.md

---

**Plan created**: 2025-11-25 23:40 UTC
**Ready for execution**: Awaiting validation test results
