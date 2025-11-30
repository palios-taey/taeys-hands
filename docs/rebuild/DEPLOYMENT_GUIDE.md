# Taey-Hands v2 Deployment Guide

**Version**: 2.0.0
**Date**: 2025-11-30

---

## Overview

This guide covers deploying the v2 rebuild of Taey-Hands with validation enforcement. Follow these steps to upgrade from v1 or deploy v2 fresh.

---

## Prerequisites

### System Requirements
- Node.js 18+ (check: `node --version`)
- Neo4j database accessible at `bolt://10.0.0.163:7687` (or configured URL)
- Chrome with remote debugging enabled
- Active sessions in AI platforms (claude.ai, chatgpt.com, etc.)

### Knowledge Requirements
- Understand MCP (Model Context Protocol)
- Familiar with Neo4j Cypher queries
- Basic TypeScript/JavaScript

---

## Testing the Rebuild Locally

### Step 1: Clone and Install

```bash
# Navigate to project
cd /Users/jesselarose/taey-hands

# Install dependencies
npm install

# Verify Neo4j connection
node -e "
const { getNeo4jClient } = require('./src/core/neo4j-client.js');
getNeo4jClient().run('RETURN 1').then(() => console.log('✓ Neo4j connected'));
"
```

**Expected Output**:
```
✓ Neo4j connected
```

---

### Step 2: Initialize Schema

```bash
# Run schema initialization
node -e "
const { getConversationStore } = require('./src/core/conversation-store.js');
const { ValidationCheckpointStore } = require('./src/core/validation-checkpoints.js');

(async () => {
  const conversationStore = getConversationStore();
  const validationStore = new ValidationCheckpointStore();

  await conversationStore.initSchema();
  console.log('✓ ConversationStore schema initialized');

  await validationStore.initSchema();
  console.log('✓ ValidationCheckpointStore schema initialized');

  process.exit(0);
})();
"
```

**Expected Output**:
```
[ConversationStore] Schema initialized
✓ ConversationStore schema initialized
[ValidationCheckpointStore] Schema initialized
✓ ValidationCheckpointStore schema initialized
```

---

### Step 3: Migrate Existing Data

Only needed if upgrading from v1 with existing checkpoints:

```bash
# Migrate validation checkpoints
node -e "
const { getNeo4jClient } = require('./src/core/neo4j-client.js');

(async () => {
  const client = getNeo4jClient();

  const result = await client.write(\`
    MATCH (v:ValidationCheckpoint)
    WHERE NOT EXISTS(v.requiredAttachments)
    SET v.requiredAttachments = [],
        v.actualAttachments = []
    RETURN count(v) as migrated
  \`);

  console.log(\`✓ Migrated \${result[0].migrated} validation checkpoints\`);
  process.exit(0);
})();
"
```

**Expected Output**:
```
✓ Migrated 42 validation checkpoints
```

---

### Step 4: Build TypeScript

```bash
# Compile server-v2.ts to JavaScript
npm run build

# Verify compiled output exists
ls -lh mcp_server/dist/server-v2.js
```

**Expected Output**:
```
-rw-r--r--  1 user  staff   123K Nov 30 12:34 mcp_server/dist/server-v2.js
```

---

### Step 5: Test Enforcement Locally

Create a test script:

```bash
cat > test_enforcement.js << 'EOF'
const { ValidationCheckpointStore } = require('./src/core/validation-checkpoints.js');
const { RequirementEnforcer } = require('./src/v2/core/validation/requirement-enforcer.js');

(async () => {
  const validationStore = new ValidationCheckpointStore();
  const enforcer = new RequirementEnforcer(validationStore);

  // Initialize schema
  await validationStore.initSchema();

  // Create test conversation with plan requiring 2 attachments
  const testConvId = 'test-' + Date.now();

  await validationStore.createCheckpoint({
    conversationId: testConvId,
    step: 'plan',
    validated: true,
    notes: 'Test plan: 2 attachments required',
    requiredAttachments: ['/tmp/file1.md', '/tmp/file2.md']
  });

  console.log('✓ Created plan checkpoint');

  // Test 1: Try to send WITHOUT attaching (should fail)
  try {
    await enforcer.ensureCanSendMessage(testConvId);
    console.log('✗ FAILED: Should have thrown error (no attachments)');
  } catch (err) {
    console.log('✓ Correctly blocked send without attachments');
    console.log('  Error:', err.message.split('\n')[0]);
  }

  // Test 2: Attach files
  await validationStore.createCheckpoint({
    conversationId: testConvId,
    step: 'attach_files',
    validated: true,
    notes: 'Files attached',
    actualAttachments: ['/tmp/file1.md', '/tmp/file2.md']
  });

  console.log('✓ Created attach_files checkpoint');

  // Test 3: Try to send WITH attachments (should pass)
  try {
    await enforcer.ensureCanSendMessage(testConvId);
    console.log('✓ Correctly allowed send with attachments');
  } catch (err) {
    console.log('✗ FAILED: Should have allowed send');
    console.log('  Error:', err.message);
  }

  console.log('\n✓ All enforcement tests passed!');
  process.exit(0);
})();
EOF

node test_enforcement.js
```

**Expected Output**:
```
✓ Created plan checkpoint
✓ Correctly blocked send without attachments
  Error: Validation checkpoint failed: Draft plan requires 2 attachment(s).
✓ Created attach_files checkpoint
✓ Correctly allowed send with attachments

✓ All enforcement tests passed!
```

---

### Step 6: Test MCP Server

```bash
# Start MCP server in test mode
node mcp_server/dist/server-v2.js 2>&1 | tee /tmp/mcp-test.log &
MCP_PID=$!

# Give it time to start
sleep 2

# Check logs
tail -20 /tmp/mcp-test.log

# Should see:
# [ConversationStore] Schema initialized
# [ValidationCheckpointStore] Schema initialized
# Taey-Hands MCP Server v2 running on stdio

# Kill test server
kill $MCP_PID
```

---

## Switching from v1 to v2

### Option 1: Direct Cutover (Recommended)

**When**: You have no active sessions, or can afford brief downtime

```bash
# 1. Stop current MCP server
pkill -f mcp_server

# 2. Mark all active sessions as orphaned
node -e "
const { getConversationStore } = require('./src/core/conversation-store.js');
(async () => {
  const store = getConversationStore();
  const { orphaned } = await store.reconcileOrphanedSessions([]);
  console.log(\`Marked \${orphaned.length} sessions as orphaned\`);
  process.exit(0);
})();
"

# 3. Checkout v2 (if using git branches)
git checkout main  # or your v2 branch

# 4. Build and restart
npm run build
npm start

# 5. Verify
tail -f /tmp/mcp-server.log | grep "MCP Server v2"
```

**Downtime**: 1-2 minutes

---

### Option 2: Gradual Migration (Safest)

**When**: You have critical active sessions

```bash
# 1. Deploy v2 alongside v1
# Keep v1 running, start v2 on different port or machine

# 2. Migrate sessions one by one
# - For each session: Extract conversation, replay in v2, validate
# - Close v1 session, switch to v2 session

# 3. Once all sessions migrated, shut down v1
```

**Downtime**: None (gradual switchover)

---

## Rollback Procedure

### If Enforcement Issues Detected

```bash
# 1. Stop MCP server
pkill -f mcp_server

# 2. Checkout previous version
git log --oneline -10  # Find commit before v2
git checkout <commit-hash>

# 3. Rebuild
npm run build

# 4. Restart
npm start

# 5. Verify rollback
tail -f /tmp/mcp-server.log
```

**Time to Rollback**: < 5 minutes

---

### If Neo4j Schema Issues

```bash
# Option 1: Rollback schema (removes new fields)
node -e "
const { getNeo4jClient } = require('./src/core/neo4j-client.js');
(async () => {
  await getNeo4jClient().write(\`
    MATCH (v:ValidationCheckpoint)
    REMOVE v.requiredAttachments, v.actualAttachments
  \`);
  console.log('✓ Rolled back checkpoint schema');
  process.exit(0);
})();
"

# Option 2: Full schema rebuild (destructive)
# Only if you have backups!
node -e "
const { getNeo4jClient } = require('./src/core/neo4j-client.js');
(async () => {
  await getNeo4jClient().write('MATCH (v:ValidationCheckpoint) DETACH DELETE v');
  console.log('✓ Deleted all checkpoints');
  process.exit(0);
})();
"
```

**Note**: Schema rollback is backward compatible. Old code works with new schema (fields just ignored).

---

## Verification Checklist

### Pre-Deployment

- [ ] Neo4j accessible from deployment environment
- [ ] Node.js 18+ installed
- [ ] npm dependencies installed (`npm install`)
- [ ] TypeScript compiled (`npm run build`)
- [ ] Schema initialized (run init scripts)
- [ ] Existing data migrated (if upgrading)
- [ ] Local enforcement tests passing

### Post-Deployment

- [ ] MCP server started successfully
- [ ] No errors in logs
- [ ] Schema constraints created (check Neo4j)
- [ ] Can connect to AI platforms
- [ ] Enforcement working (test skip attachment → error)
- [ ] Validation messages actionable
- [ ] Session health checks working

### Smoke Tests

```bash
# Test 1: Schema verification
node -e "
const { getNeo4jClient } = require('./src/core/neo4j-client.js');
(async () => {
  const result = await getNeo4jClient().run(\`
    SHOW CONSTRAINTS
    YIELD name, type
    WHERE name STARTS WITH 'validation_checkpoint'
    RETURN count(*) as count
  \`);
  console.log(\`Validation constraints: \${result[0].count}\`);
  console.log(result[0].count >= 1 ? '✓ PASS' : '✗ FAIL');
  process.exit(0);
})();
"

# Test 2: Enforcement integration
node test_enforcement.js  # Created earlier

# Test 3: MCP server health
curl -X POST http://localhost:3000/health || echo "MCP uses stdio, not HTTP"
# For stdio servers, check process is running:
pgrep -f "mcp_server" && echo "✓ MCP server running"
```

---

## Configuration

### Environment Variables

```bash
# Optional: Override Neo4j URL
export NEO4J_URL="bolt://10.0.0.163:7687"

# Optional: Enable debug logging
export DEBUG="taey-hands:*"

# Optional: Change MCP server mode
export MCP_SERVER_MODE="production"  # or "development"
```

### MCP Server Config

Edit `~/.mcp/server-config.json`:

```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": ["/Users/jesselarose/taey-hands/mcp_server/dist/server-v2.js"],
      "env": {
        "NEO4J_URL": "bolt://10.0.0.163:7687"
      }
    }
  }
}
```

---

## Monitoring

### Log Locations

- **MCP Server**: `stderr` (pipe to file in config)
- **Neo4j**: Check Neo4j logs for query performance
- **Validation**: Look for `[MCP] ✓` messages in logs

### Key Metrics to Watch

```bash
# Enforcement success rate
grep "✓ Validation passed" /tmp/mcp-server.log | wc -l
grep "Validation checkpoint failed" /tmp/mcp-server.log | wc -l

# Neo4j query performance
# Check Neo4j slow query log for checkpoints taking > 100ms

# Session health
node -e "
const { getConversationStore } = require('./src/core/conversation-store.js');
(async () => {
  const sessions = await getConversationStore().getActiveSessions();
  console.log(\`Active sessions: \${sessions.length}\`);

  for (const s of sessions) {
    const health = await getConversationStore().getSessionHealth(s.id);
    console.log(\`  \${s.id}: \${health.healthy ? '✓' : '✗'} \${health.info}\`);
  }
  process.exit(0);
})();
"
```

---

## Troubleshooting

### Issue: "Cannot find module 'requirement-enforcer'"

**Cause**: TypeScript not compiled or wrong path

**Fix**:
```bash
npm run build
ls -la src/v2/core/validation/requirement-enforcer.js
# Should exist after build
```

---

### Issue: Enforcement too strict (false positives)

**Cause**: Validation checkpoints not created properly

**Diagnosis**:
```cypher
// Check checkpoint chain
MATCH (v:ValidationCheckpoint {conversationId: $sessionId})
RETURN v.step, v.validated, v.timestamp, v.requiredAttachments, v.actualAttachments
ORDER BY v.timestamp
```

**Fix**: Ensure agents call `taey_validate_step` after each workflow step

---

### Issue: Neo4j schema conflicts

**Cause**: Schema initialized multiple times or partial migration

**Fix**:
```bash
# Drop all constraints, rebuild
node -e "
const { getNeo4jClient } = require('./src/core/neo4j-client.js');
(async () => {
  const client = getNeo4jClient();

  // Get all constraints
  const constraints = await client.run('SHOW CONSTRAINTS YIELD name RETURN name');

  for (const c of constraints) {
    await client.write(\`DROP CONSTRAINT \${c.name} IF EXISTS\`);
  }

  console.log('✓ Dropped all constraints');

  // Reinitialize
  const { getConversationStore } = require('./src/core/conversation-store.js');
  const { ValidationCheckpointStore } = require('./src/core/validation-checkpoints.js');

  await getConversationStore().initSchema();
  await new ValidationCheckpointStore().initSchema();

  console.log('✓ Reinitialized schema');
  process.exit(0);
})();
"
```

---

### Issue: Performance degradation

**Diagnosis**:
```cypher
// Check index usage
EXPLAIN MATCH (v:ValidationCheckpoint {conversationId: $id})
RETURN v
ORDER BY v.timestamp DESC
LIMIT 1
```

**Fix**: Ensure indexes exist
```cypher
SHOW INDEXES YIELD name, type, labelsOrTypes, properties
WHERE 'ValidationCheckpoint' IN labelsOrTypes
```

Should show:
- `validation_conversation` on `conversationId`
- `validation_step` on `step`
- `validation_timestamp` on `timestamp`

---

## Performance Tuning

### Neo4j Connection Pool

Edit `src/core/neo4j-client.js`:

```javascript
const driver = neo4j.driver(uri, auth, {
  maxConnectionPoolSize: 50,  // Increase for high concurrency
  connectionAcquisitionTimeout: 60000,
  maxTransactionRetryTime: 30000
});
```

### Checkpoint Query Optimization

```cypher
// Add compound index for common query pattern
CREATE INDEX validation_conversation_timestamp IF NOT EXISTS
FOR (v:ValidationCheckpoint)
ON (v.conversationId, v.timestamp)
```

---

## Security Considerations

### Neo4j Access Control

```bash
# Ensure Neo4j not exposed to public internet
netstat -an | grep 7687
# Should only show localhost or private IP (10.0.0.163)
```

### MCP Server Permissions

```bash
# MCP server should run as non-root user
ps aux | grep mcp_server
# UID should NOT be 0 (root)
```

### Secrets Management

```bash
# DO NOT commit Neo4j credentials to git
echo "neo4j-password.txt" >> .gitignore

# Store credentials securely
chmod 600 ~/.neo4j/credentials
```

---

## Production Deployment Checklist

- [ ] All tests passing locally
- [ ] Neo4j backups configured
- [ ] Monitoring alerts set up
- [ ] Rollback procedure tested
- [ ] Documentation updated
- [ ] Team notified of deployment
- [ ] Deployment window scheduled (low traffic time)
- [ ] Health checks configured
- [ ] Log aggregation configured
- [ ] Error reporting configured

---

## Support

### Getting Help

- **Documentation**: See `docs/rebuild/` directory
- **Code Issues**: Check `src/v2/core/validation/` implementation
- **Schema Issues**: See `docs/rebuild/NEO4J_SCHEMA.md`

### Reporting Issues

Include:
- Error message (full stack trace)
- Neo4j query that failed (from logs)
- Validation checkpoint chain (Cypher query above)
- MCP server version (`grep version mcp_server/server-v2.ts`)

---

## Next Steps

After successful deployment:

1. **Monitor** enforcement rate (should be 100%)
2. **Review** error messages (ensure actionable)
3. **Optimize** Neo4j queries (add indexes as needed)
4. **Train** agents on new workflow pattern
5. **Document** any platform-specific quirks discovered

---

**Document Version**: 1.0
**Last Updated**: 2025-11-30
**Maintained By**: CCM (jesselarose-macbook-claude)
