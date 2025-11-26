# Validation Checklist - Taey Hands Repository Cleanup
**Date**: 2025-11-25 23:58 UTC
**Branch**: feature/mcp-function-based-tools
**Purpose**: Pre-commit validation for Nov 25, 2025 implementation fixes

---

## Quick Reference

**Run this checklist BEFORE committing** to ensure:
- Build works
- Tests pass
- Files are correctly organized
- No accidental inclusions
- Neo4j connection is valid

**Estimated time**: 5-10 minutes

---

## Pre-Execution Validation

### 1. Repository State Check

```bash
# Verify you're on the correct branch
git branch --show-current
# Expected: feature/mcp-function-based-tools

# Check current status
git status
# Expected: Modified files (5) and untracked files (8)
```

**Checklist**:
- [ ] On correct branch: `feature/mcp-function-based-tools`
- [ ] Working directory is clean (no unexpected changes)
- [ ] No staged changes yet

---

## Build Validation

### 2. TypeScript Compilation

```bash
cd /Users/REDACTED/taey-hands/mcp_server
npm run build
```

**Expected Output**:
```
> tsc
(no errors)
```

**Checklist**:
- [ ] TypeScript compiles successfully
- [ ] No type errors reported
- [ ] `dist/server-v2.js` generated
- [ ] `dist/server-v2.js.map` generated

### 3. JavaScript Syntax Check

```bash
cd /Users/REDACTED/taey-hands

# Check chat-interface.js (Gemini changes)
node -c src/interfaces/chat-interface.js
```

**Expected Output**:
```
(no output = success)
```

**Checklist**:
- [ ] No syntax errors in chat-interface.js
- [ ] No syntax errors in other source files

---

## Infrastructure Validation

### 4. Neo4j Connection Test

```bash
# Test connection to mira
nc -zv 10.x.x.163 7687
```

**Expected Output**:
```
Connection to 10.x.x.163 port 7687 [tcp/*] succeeded!
```

**If connection fails**:
- Verify mira is running
- Check network connectivity
- Try: `ping 10.x.x.163`

**Checklist**:
- [ ] Neo4j connection succeeds
- [ ] Port 7687 is accessible
- [ ] No firewall blocking connection

### 5. Conversation Store Schema

```bash
# Run a quick Node.js check
cd /Users/REDACTED/taey-hands
node -e "
import('./src/core/conversation-store.js').then(m => {
  const store = m.getConversationStore();
  store.initSchema().then(() => {
    console.log('✅ ConversationStore schema initialized');
    process.exit(0);
  }).catch(err => {
    console.error('❌ Schema init failed:', err.message);
    process.exit(1);
  });
});
"
```

**Expected Output**:
```
✅ ConversationStore schema initialized
```

**Checklist**:
- [ ] Schema initialization succeeds
- [ ] No connection errors
- [ ] No authentication errors

---

## File Organization Validation

### 6. Directory Structure

```bash
# Verify required directories exist
cd /Users/REDACTED/taey-hands

test -d docs && echo "✅ docs/ exists" || echo "❌ docs/ missing"
test -d tests && echo "✅ tests/ exists" || echo "❌ tests/ missing"
test -d experiments && echo "✅ experiments/ exists" || echo "❌ experiments/ missing"
test -d mcp_server && echo "✅ mcp_server/ exists" || echo "❌ mcp_server/ missing"
test -d src && echo "✅ src/ exists" || echo "❌ src/ missing"
```

**Checklist**:
- [ ] All required directories exist
- [ ] No unexpected directories

### 7. File Counts (Pre-Move)

```bash
# Count files before organization
find docs -type f -name "*.md" | wc -l
# Expected: 12

find . -maxdepth 1 -type f -name "*.md" | wc -l
# Expected: 5 (including README.md)

find experiments -type f -name "*.mjs" -o -name "*.js" | wc -l
# Expected: ~30
```

**Record current counts**:
- [ ] docs/*.md: _____
- [ ] root/*.md: _____
- [ ] experiments/*.mjs: _____

---

## Git Staging Validation

### 8. No Accidental Inclusions

```bash
# Check for files that should NOT be staged
git status | grep -E "(node_modules|\.DS_Store|\.env|\.pem)"
```

**Expected Output**:
```
(no output = good)
```

**Checklist**:
- [ ] No node_modules/ in staging
- [ ] No .DS_Store files
- [ ] No .env files
- [ ] No .pem files (credentials)
- [ ] No personal data

### 9. Verify Modified Files

```bash
# List modified files
git diff --name-only
```

**Expected Output**:
```
CHAT_ELEMENTS.md
mcp_server/dist/server-v2.js
mcp_server/dist/server-v2.js.map
mcp_server/server-v2.ts
src/interfaces/chat-interface.js
```

**Checklist**:
- [ ] Exactly 5 modified files
- [ ] All expected files present
- [ ] No unexpected modifications

### 10. Verify Untracked Files

```bash
# List untracked files
git ls-files --others --exclude-standard
```

**Expected Output**:
```
.mcp.json
docs/MCP_COMPREHENSIVE_IMPLEMENTATION_ANALYSIS.md
docs/README_ANALYSIS.md
docs/TESTING_QUICK_START.md
docs/TOOL_REFERENCE.md
GITHUB_CLEANUP_PLAN.md
IMPLEMENTATION_FIXES_2025-11-25.md
rosetta_stone/...
test-implementation-fixes.mjs
```

**Checklist**:
- [ ] Exactly 8 new files (excluding rosetta_stone/)
- [ ] All expected files present
- [ ] No unexpected additions

---

## Implementation Testing

### 11. Gemini Deep Research Feature

**Manual Test** (if Chrome is running):

```bash
# This is a manual check - requires browser open
# 1. Open Gemini Deep Research
# 2. Send research query
# 3. Verify "Start research" button appears
# 4. Check selector matches:
#    button[data-test-id="confirm-button"][aria-label="Start research"]
```

**Checklist**:
- [ ] Gemini Deep Research accessible
- [ ] "Start research" button visible
- [ ] Selector matches code

**Skip if**:
- Chrome not running
- Gemini not logged in
- Will test after commit

### 12. Validation Test (Dry Run)

```bash
cd /Users/REDACTED/taey-hands

# Check test file syntax
node -c test-implementation-fixes.mjs
```

**Expected Output**:
```
(no output = success)
```

**Checklist**:
- [ ] Test file has no syntax errors
- [ ] Imports resolve correctly

---

## File Move Validation (Pre-Execution)

### 13. Verify Files Exist Before Move

```bash
# Files that will be moved - verify they exist
test -f IMPLEMENTATION_FIXES_2025-11-25.md && echo "✅ exists"
test -f GITHUB_CLEANUP_PLAN.md && echo "✅ exists"
test -f PALIOS_TAEY_RESEARCH_SUMMARY.md && echo "✅ exists"
test -f test-implementation-fixes.mjs && echo "✅ exists"
```

**Checklist**:
- [ ] IMPLEMENTATION_FIXES_2025-11-25.md exists
- [ ] GITHUB_CLEANUP_PLAN.md exists
- [ ] PALIOS_TAEY_RESEARCH_SUMMARY.md exists
- [ ] test-implementation-fixes.mjs exists

### 14. Verify Target Directories Exist

```bash
# Create if needed
mkdir -p tests/validation

# Verify
test -d tests/validation && echo "✅ tests/validation/ exists"
test -d docs && echo "✅ docs/ exists"
```

**Checklist**:
- [ ] tests/validation/ exists
- [ ] docs/ exists

---

## Security Validation

### 15. Check for Secrets

```bash
# Search for potential secrets in modified files
git diff | grep -iE "(password|secret|key|token|api_key)" | grep -v "# "
```

**Expected Output**:
```
(no output = good)
```

**Checklist**:
- [ ] No passwords in diff
- [ ] No API keys in diff
- [ ] No secrets in diff

### 16. Review .mcp.json

```bash
cat .mcp.json
```

**Expected Content**:
```json
{
  "mcpServers": {
    "taey-hands": {
      "type": "stdio",
      "command": "node",
      "args": ["./mcp_server/dist/server-v2.js"],
      "env": {}
    }
  }
}
```

**Checklist**:
- [ ] No secrets in .mcp.json
- [ ] Only local paths
- [ ] Empty env object

---

## Documentation Validation

### 17. Check New Documentation Files

```bash
# Verify new docs were created
test -f docs/CLEANUP_EXECUTION_REPORT.md && echo "✅ Cleanup report"
test -f docs/INDEX.md && echo "✅ Index"
test -f docs/COMMIT_STRATEGY.md && echo "✅ Commit strategy"
test -f VALIDATION_CHECKLIST.md && echo "✅ Validation checklist"
```

**Checklist**:
- [ ] CLEANUP_EXECUTION_REPORT.md created
- [ ] INDEX.md created
- [ ] COMMIT_STRATEGY.md created
- [ ] VALIDATION_CHECKLIST.md created

### 18. Verify Documentation Links

```bash
# Check README links (sample)
grep -n "docs/" README.md
```

**Checklist**:
- [ ] Links in README.md work
- [ ] Links in INDEX.md work
- [ ] No broken references

---

## Final Pre-Commit Checks

### 19. Review Diff Summary

```bash
# Show summary of all changes
git diff --stat
```

**Review**:
- [ ] Changes make sense
- [ ] No unexpected file sizes
- [ ] All changes are intentional

### 20. Three-Commit Preview

```bash
# Review commit strategy
cat docs/COMMIT_STRATEGY.md | grep "^## Commit"
```

**Checklist**:
- [ ] Understand Commit 1 (Gemini)
- [ ] Understand Commit 2 (Neo4j)
- [ ] Understand Commit 3 (Docs)
- [ ] Ready to execute in order

---

## Post-Move Validation

### 21. Verify Files Moved Correctly

**After running `mv` commands**:

```bash
# Check files are in new locations
test -f docs/IMPLEMENTATION_FIXES_2025-11-25.md && echo "✅ moved"
test -f docs/GITHUB_CLEANUP_PLAN.md && echo "✅ moved"
test -f docs/PALIOS_TAEY_RESEARCH_SUMMARY.md && echo "✅ moved"
test -f tests/validation/test-implementation-fixes.mjs && echo "✅ moved"

# Check files NOT in old locations
test ! -f IMPLEMENTATION_FIXES_2025-11-25.md && echo "✅ removed from root"
test ! -f test-implementation-fixes.mjs && echo "✅ removed from root"
```

**Checklist**:
- [ ] All files in new locations
- [ ] No files left in old locations
- [ ] No broken symlinks

### 22. Update Import Paths (If Needed)

```bash
# Check if test file imports still work
node tests/validation/test-implementation-fixes.mjs --help 2>&1 | head -5
```

**If imports break**:
```javascript
// Update paths in test-implementation-fixes.mjs
// OLD: import { getSessionManager } from './mcp_server/session-manager.js';
// NEW: import { getSessionManager } from '../../mcp_server/session-manager.js';
```

**Checklist**:
- [ ] Test imports resolve
- [ ] No "Cannot find module" errors

---

## Post-Commit Validation

### 23. Verify Commits

```bash
# After all 3 commits
git log --oneline -3
```

**Expected Output**:
```
xxxxxxx docs: Organize documentation and tests, add cleanup reports
yyyyyyy feat: Integrate Neo4j ConversationStore for all MCP tools
zzzzzzz feat: Add Gemini Deep Research Start button auto-click
```

**Checklist**:
- [ ] 3 commits created
- [ ] Commits in correct order
- [ ] Commit messages correct

### 24. Verify Build After Commits

```bash
cd mcp_server && npm run build
```

**Checklist**:
- [ ] Build still works
- [ ] No new errors introduced

### 25. Verify Git Status Clean

```bash
git status
```

**Expected Output**:
```
On branch feature/mcp-function-based-tools
Your branch is ahead of 'origin/feature/mcp-function-based-tools' by 7 commits.
nothing to commit, working tree clean
```

**Checklist**:
- [ ] Working tree clean
- [ ] No uncommitted changes
- [ ] Branch ahead by 7 commits (4 existing + 3 new)

---

## Integration Testing (Optional)

### 26. Full MCP Server Test

**If you want to test the MCP server end-to-end**:

```bash
# Start MCP server manually
cd mcp_server
node dist/server-v2.js
```

**Then in Claude Code**:
```
Test taey_connect to claude
Test taey_send_message
Test taey_extract_response
```

**Checklist**:
- [ ] MCP server starts
- [ ] Tools respond correctly
- [ ] Neo4j logging works

**Skip if**:
- Will test after push
- Not running Chrome
- Not critical for commit

### 27. Run Validation Test Suite

```bash
# Run the full validation test
node tests/validation/test-implementation-fixes.mjs
```

**Expected**:
- Test 1: Neo4j connection ✅
- Test 2: Gemini regular conversation ✅
- Test 3: Gemini Deep Research (if Chrome running) ✅

**Checklist**:
- [ ] All tests pass (or skip if Chrome not running)
- [ ] No unexpected errors

---

## Push Validation

### 28. Pre-Push Check

```bash
# Review what will be pushed
git log origin/feature/mcp-function-based-tools..HEAD
```

**Checklist**:
- [ ] 3 new commits ready to push
- [ ] Commits look correct
- [ ] No sensitive data

### 29. Push to Remote

```bash
git push origin feature/mcp-function-based-tools
```

**Expected Output**:
```
Counting objects: ...
Writing objects: ...
To github.com:palios-taey/taey-hands.git
   xxxxx..yyyyy  feature/mcp-function-based-tools -> feature/mcp-function-based-tools
```

**Checklist**:
- [ ] Push succeeds
- [ ] No errors
- [ ] Branch updated on remote

### 30. Verify on GitHub

**Navigate to GitHub repository**:

```
https://github.com/palios-taey/taey-hands/tree/feature/mcp-function-based-tools
```

**Checklist**:
- [ ] 3 new commits visible
- [ ] Files in correct locations
- [ ] Commit messages display correctly
- [ ] No weird diffs or artifacts

---

## Rollback Procedures (If Needed)

### If Build Breaks
```bash
# Undo last commit, keep changes
git reset --soft HEAD~1

# Fix the issue
cd mcp_server && npm run build

# Re-commit
git add .
git commit -m "fix: [describe fix]"
```

### If Files Wrong
```bash
# Undo file moves
git reset --soft HEAD~1

# Move files back
mv docs/IMPLEMENTATION_FIXES_2025-11-25.md .

# Re-organize correctly
mv IMPLEMENTATION_FIXES_2025-11-25.md docs/

# Re-commit
git add .
git commit
```

### If Need to Start Over
```bash
# Create backup first
git branch backup-$(date +%Y%m%d-%H%M%S)

# Hard reset to before changes
git reset --hard HEAD~3

# Verify
git status
```

---

## Summary Checklist

**Before executing anything**:
- [ ] Read CLEANUP_EXECUTION_REPORT.md
- [ ] Read COMMIT_STRATEGY.md
- [ ] Read this VALIDATION_CHECKLIST.md
- [ ] Understand what will happen

**Before Commit 1 (Gemini)**:
- [ ] Build works
- [ ] Syntax valid
- [ ] Gemini feature reviewed

**Before Commit 2 (Neo4j)**:
- [ ] Neo4j connection works
- [ ] Schema initializes
- [ ] TypeScript compiles

**Before Commit 3 (Docs)**:
- [ ] Files moved correctly
- [ ] Docs created
- [ ] .gitignore updated

**After All Commits**:
- [ ] 3 commits created
- [ ] Build still works
- [ ] Git status clean
- [ ] Ready to push

**After Push**:
- [ ] Verify on GitHub
- [ ] Tag release (optional)
- [ ] Update team

---

## Questions to Ask Yourself

Before committing:
- Have I tested the build?
- Are all file moves correct?
- Do the commit messages accurately describe changes?
- Is there any sensitive data in the commits?
- Will this break anything for other developers?

Before pushing:
- Have I verified all 3 commits locally?
- Is the branch ahead by the correct number of commits?
- Have I reviewed the changes on the command line?
- Am I pushing to the correct branch?

---

## Success Criteria

**You're ready to commit if**:
- ✅ All validation steps pass
- ✅ Build works
- ✅ No secrets in commits
- ✅ File organization makes sense
- ✅ Commit messages are clear

**You're ready to push if**:
- ✅ All 3 commits created
- ✅ Build works after each commit
- ✅ Git status is clean
- ✅ Reviewed changes on GitHub (mentally)

---

**Document Created**: 2025-11-25 23:58 UTC
**For**: Jesse & The AI Family
**Repository**: palios-taey/taey-hands
**Branch**: feature/mcp-function-based-tools

**IMPORTANT**: This checklist should be followed step-by-step. Don't skip steps. If anything fails, stop and investigate before proceeding.
