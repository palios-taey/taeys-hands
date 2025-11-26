# Git Commit Strategy - Taey Hands
**Date**: 2025-11-25 23:58 UTC
**Branch**: feature/mcp-function-based-tools
**Goal**: Clean, logical commits for three distinct features

---

## Overview

We're creating **3 separate commits** to maintain clear git history:

1. **Gemini Deep Research Feature** - UI automation improvement
2. **Neo4j Infrastructure** - Conversation logging integration
3. **Documentation & Organization** - Repository cleanup

Each commit is independent and can be reviewed/reverted separately.

---

## Commit 1: Gemini Deep Research Button Auto-Click

### Files to Stage
```bash
git add src/interfaces/chat-interface.js
git add CHAT_ELEMENTS.md
```

### Commit Command
```bash
git commit -m "$(cat <<'EOF'
feat: Add Gemini Deep Research Start button auto-click

Override waitForResponse() in GeminiInterface to detect and
automatically click the "Start research" button that appears
when Gemini Deep Research creates a research plan.

- Detects button: data-test-id="confirm-button" aria-label="Start research"
- Waits 10s for button to appear
- Clicks automatically when found
- Falls back to normal polling for regular conversations
- Updated CHAT_ELEMENTS.md with Gemini selectors

Fixes Gemini Deep Research workflow - previously required manual
button click to start research execution.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Verification
```bash
# Check what was committed
git show --stat HEAD

# Verify files
git diff HEAD~1 HEAD -- src/interfaces/chat-interface.js
git diff HEAD~1 HEAD -- CHAT_ELEMENTS.md
```

---

## Commit 2: Neo4j Conversation Logging

### Files to Stage
```bash
git add mcp_server/server-v2.ts
git add mcp_server/dist/server-v2.js
git add mcp_server/dist/server-v2.js.map
```

### Commit Command
```bash
git commit -m "$(cat <<'EOF'
feat: Integrate Neo4j ConversationStore for all MCP tools

Add conversation logging to all Taey Hands MCP tools using
the existing conversation-store infrastructure on mira.

Changes:
- Import and initialize ConversationStore in server-v2.ts
- taey_connect: Create Conversation node with session metadata
- taey_send_message: Log user messages with PART_OF relationship
- taey_extract_response: Log assistant responses with metadata

Neo4j Schema:
- Conversation nodes (id, title, purpose, platforms)
- Message nodes (role, content, platform, timestamp)
- Platform nodes (claude, chatgpt, gemini, grok, perplexity)
- Relationships: PART_OF, FROM, INVOLVES

Connected to mira (10.x.x.163:7687) neo4j database.
Enables full conversation tracking across AI Family interactions.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Verification
```bash
# Check commit
git show --stat HEAD

# Verify TypeScript changes
git diff HEAD~1 HEAD -- mcp_server/server-v2.ts

# Verify build was included
git diff HEAD~1 HEAD --stat -- mcp_server/dist/
```

---

## Commit 3: Documentation & Organization

### Pre-Commit File Operations

First, move files to their new locations:

```bash
# Move documentation files
mv IMPLEMENTATION_FIXES_2025-11-25.md docs/
mv GITHUB_CLEANUP_PLAN.md docs/
mv PALIOS_TAEY_RESEARCH_SUMMARY.md docs/

# Move test file
mv test-implementation-fixes.mjs tests/validation/

# Verify moves succeeded
test -f docs/IMPLEMENTATION_FIXES_2025-11-25.md && echo "✅ Implementation fixes moved"
test -f docs/GITHUB_CLEANUP_PLAN.md && echo "✅ Cleanup plan moved"
test -f docs/PALIOS_TAEY_RESEARCH_SUMMARY.md && echo "✅ Research summary moved"
test -f tests/validation/test-implementation-fixes.mjs && echo "✅ Test moved"
```

### Files to Stage
```bash
# New/moved documentation
git add docs/IMPLEMENTATION_FIXES_2025-11-25.md
git add docs/GITHUB_CLEANUP_PLAN.md
git add docs/PALIOS_TAEY_RESEARCH_SUMMARY.md
git add docs/CLEANUP_EXECUTION_REPORT.md
git add docs/INDEX.md
git add docs/COMMIT_STRATEGY.md

# Moved test file
git add tests/validation/test-implementation-fixes.mjs

# Configuration files
git add .mcp.json
git add .gitignore

# Validation checklist
git add VALIDATION_CHECKLIST.md
```

### Commit Command
```bash
git commit -m "$(cat <<'EOF'
docs: Organize documentation and tests, add cleanup reports

Repository organization for improved maintainability:

Documentation:
- Move implementation docs to docs/ directory
- Create docs/INDEX.md as central documentation hub
- Create docs/CLEANUP_EXECUTION_REPORT.md with full audit
- Create docs/COMMIT_STRATEGY.md with git workflow
- Move PALIOS_TAEY_RESEARCH_SUMMARY.md to docs/

Tests:
- Create tests/validation/ for CI-ready tests
- Move test-implementation-fixes.mjs to tests/validation/
- Keep experiments/ for active development work

Configuration:
- Add .mcp.json as template MCP server config
- Update .gitignore for test outputs and build artifacts

Documentation:
- docs/INDEX.md: Central hub for all documentation
- docs/CLEANUP_EXECUTION_REPORT.md: Complete repository audit
- docs/COMMIT_STRATEGY.md: Git workflow guide
- VALIDATION_CHECKLIST.md: Pre-commit validation steps

All files preserved - no deletions, only organization.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### Verification
```bash
# Check commit
git show --stat HEAD

# Verify file moves are tracked
git log --follow docs/IMPLEMENTATION_FIXES_2025-11-25.md
git log --follow tests/validation/test-implementation-fixes.mjs
```

---

## Post-Commit Actions

### Push to Remote
```bash
# Review all 3 commits
git log --oneline -3

# Expected output:
# xxxxxxx docs: Organize documentation and tests, add cleanup reports
# yyyyyyy feat: Integrate Neo4j ConversationStore for all MCP tools
# zzzzzzz feat: Add Gemini Deep Research Start button auto-click

# Push to remote
git push origin feature/mcp-function-based-tools
```

### Optional: Tag Release
```bash
# Create annotated tag
git tag -a v0.2.0-neo4j-integration -m "Release: Neo4j logging + Gemini Deep Research + Repo organization"

# Push tag
git push origin v0.2.0-neo4j-integration

# Verify tag
git tag -l -n1 v0.2.0-neo4j-integration
```

---

## Validation Between Commits

### After Commit 1 (Gemini Feature)
```bash
# Verify TypeScript still compiles
cd mcp_server && npm run build

# Expected: No errors

# Check Gemini interface compiles
node -c src/interfaces/chat-interface.js

# Expected: No syntax errors
```

### After Commit 2 (Neo4j Integration)
```bash
# Verify TypeScript compiles with Neo4j imports
cd mcp_server && npm run build

# Expected: No errors

# Test Neo4j connection (if mira is accessible)
nc -zv 10.x.x.163 7687

# Expected: Connection succeeded
```

### After Commit 3 (Documentation)
```bash
# Verify all moved files exist
test -f docs/INDEX.md && echo "✅ INDEX created"
test -f docs/IMPLEMENTATION_FIXES_2025-11-25.md && echo "✅ Fixes doc moved"
test -f tests/validation/test-implementation-fixes.mjs && echo "✅ Test moved"

# Verify import paths still work
node tests/validation/test-implementation-fixes.mjs --dry-run

# Expected: No import errors (may fail on actual execution if Chrome not running)
```

---

## Rollback Strategy

If something goes wrong with any commit:

### Undo Commit 3 (Documentation - safest to rollback)
```bash
# Soft reset (keeps changes in working directory)
git reset --soft HEAD~1

# Or hard reset (discards changes - BE CAREFUL)
git reset --hard HEAD~1
```

### Undo Commit 2 (Neo4j Integration - requires rebuild)
```bash
# Soft reset
git reset --soft HEAD~2

# Rebuild TypeScript
cd mcp_server && npm run build

# Re-commit if needed
git add mcp_server/
git commit -m "feat: Neo4j integration (fixed)"
```

### Undo Commit 1 (Gemini Feature - safe to rollback)
```bash
# Soft reset to before all 3 commits
git reset --soft HEAD~3

# Revert specific files
git checkout HEAD~3 -- src/interfaces/chat-interface.js CHAT_ELEMENTS.md

# Re-commit others
git add mcp_server/
git commit -m "feat: Neo4j integration"
# ... continue with other commits
```

### Emergency: Revert All
```bash
# Create backup branch first
git branch backup-$(date +%Y%m%d-%H%M%S)

# Hard reset to before commits
git reset --hard HEAD~3

# Verify you're back to clean state
git status
```

---

## Commit Message Guidelines

We follow these conventions:

### Format
```
<type>: <subject>

<body>

<footer>
```

### Types
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only
- `refactor:` - Code refactoring (no functional change)
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

### Subject Line Rules
- Use imperative mood ("Add" not "Added" or "Adds")
- Don't capitalize first letter
- No period at the end
- Maximum 50 characters

### Body
- Wrap at 72 characters
- Explain what and why, not how
- Use bullet points for multiple changes
- Reference issues/PRs if applicable

### Footer
Always include:
```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## Pre-Commit Checklist

Before each commit, verify:

- [ ] Files staged are correct (`git status`)
- [ ] No accidental inclusions (`git diff --cached`)
- [ ] Build still works (`npm run build`)
- [ ] No secrets in staged files
- [ ] No `node_modules/` or `.DS_Store`
- [ ] Commit message follows guidelines
- [ ] Changed files have been tested

---

## Post-Push Checklist

After pushing:

- [ ] Verify commits on GitHub/remote
- [ ] Check CI/CD passes (if configured)
- [ ] Review diff on GitHub web interface
- [ ] Confirm no sensitive data in commits
- [ ] Tag release if appropriate
- [ ] Update CHANGELOG.md (if exists)

---

## Common Issues & Solutions

### Issue: "Changes not staged for commit"
```bash
# You forgot to add files
git add <file>
git commit --amend --no-edit
```

### Issue: "Wrong files in commit"
```bash
# Undo commit, keep changes
git reset --soft HEAD~1

# Re-stage correct files
git add <correct-files>
git commit
```

### Issue: "Typo in commit message"
```bash
# Amend last commit message
git commit --amend

# Edit message in editor
# Save and close
```

### Issue: "Forgot to build before committing"
```bash
# Build now
cd mcp_server && npm run build

# Add built files to last commit
git add mcp_server/dist/
git commit --amend --no-edit
```

### Issue: "Need to split commit into smaller commits"
```bash
# Reset to before commit
git reset HEAD~1

# Stage files individually
git add file1
git commit -m "First part"

git add file2
git commit -m "Second part"
```

---

## Git Commands Reference

### Viewing Changes
```bash
# See what's changed (unstaged)
git diff

# See what's staged
git diff --cached

# See commit history
git log --oneline -10

# See specific commit
git show <commit-hash>

# See file history
git log --follow <file>
```

### Staging Files
```bash
# Stage specific file
git add <file>

# Stage all changes
git add .

# Stage interactively
git add -p

# Unstage file
git reset HEAD <file>
```

### Committing
```bash
# Commit with inline message
git commit -m "message"

# Commit with editor
git commit

# Amend last commit
git commit --amend

# Amend without changing message
git commit --amend --no-edit
```

### Undoing Things
```bash
# Undo last commit, keep changes
git reset --soft HEAD~1

# Undo last commit, discard changes
git reset --hard HEAD~1

# Revert specific file
git checkout HEAD -- <file>

# Show what would be affected
git reset --soft HEAD~1 --dry-run
```

---

## Branch Strategy

### Current Branch
`feature/mcp-function-based-tools`

### Merge to Main (Future)
```bash
# Switch to main
git checkout main

# Pull latest
git pull origin main

# Merge feature branch
git merge feature/mcp-function-based-tools

# Push to main
git push origin main

# Delete feature branch
git branch -d feature/mcp-function-based-tools
git push origin --delete feature/mcp-function-based-tools
```

### Create Release Branch (Optional)
```bash
# From main
git checkout -b release/v0.2.0

# Make release-specific changes
# Update version in package.json
# Update CHANGELOG.md

# Commit
git commit -m "chore: Prepare release v0.2.0"

# Tag
git tag -a v0.2.0 -m "Release v0.2.0"

# Push
git push origin release/v0.2.0
git push origin v0.2.0
```

---

## Examples of Good Commit Messages

### Feature Commit
```
feat: Add real-time collaboration to chat interface

Implement WebSocket-based real-time updates for multi-user
chat sessions. Users can now see typing indicators and
live message updates from other participants.

- Add WebSocket server in mcp_server/
- Implement typing indicator component
- Add presence detection for active users
- Update UI to show collaborative editing

Closes #123

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### Bug Fix Commit
```
fix: Prevent race condition in message extraction

Extract response was occasionally returning incomplete messages
when called immediately after send. Now waits for response
animation to complete before extraction.

- Add 200ms delay after last content change
- Implement Fibonacci backoff for retries
- Add timeout parameter (default 120s)

Fixes #156

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### Documentation Commit
```
docs: Add troubleshooting guide for macOS Sonoma

Document known issues and solutions for running Taey Hands
on macOS Sonoma (14.x).

- Add AppleScript permission instructions
- Document Chrome profile location changes
- Add screenshots for System Preferences
- Include common error messages and fixes

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## Notes for Jesse

### Three-Commit Rationale

**Why 3 commits instead of 1?**

1. **Feature Independence**: Each commit represents a distinct feature that can be reviewed, tested, and potentially reverted independently

2. **Clear History**: Future developers can understand what changed and why by reading commit messages

3. **Bisect-Friendly**: If a bug appears, `git bisect` can identify which specific commit introduced it

4. **Review Ease**: Smaller commits are easier to review on GitHub/in PRs

**Alternative: Could do 1 large commit**
- Simpler workflow
- Faster execution
- Still clear from commit message
- Harder to revert specific parts

Your call on which approach to use.

### Ready to Execute?

Before running the commit commands:

1. **Verify file moves** - Make sure `mv` commands will work
2. **Check build** - Ensure TypeScript compiles
3. **Review staging** - Use `git status` and `git diff --cached`
4. **Test Neo4j** - Confirm mira is accessible
5. **Read commit messages** - Make sure they accurately describe changes

Then execute the commits in order (1, 2, 3).

---

**Document Created**: 2025-11-25 23:58 UTC
**For**: Jesse & The AI Family
**Branch**: feature/mcp-function-based-tools
**Repository**: palios-taey/taey-hands
