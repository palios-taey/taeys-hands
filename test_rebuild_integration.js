#!/usr/bin/env node

/**
 * Integration Tests for Taey-Hands v2 Rebuild
 *
 * Tests RequirementEnforcer, SelectorRegistry, session synchronization, and newSession fix
 *
 * Run: node test_rebuild_integration.js
 */

import { strict as assert } from 'assert';
import { RequirementEnforcer } from './src/v2/core/validation/requirement-enforcer.js';
import { ValidationCheckpointStore } from './src/core/validation-checkpoints.js';
import { SelectorRegistry } from './src/v2/core/selectors/selector-registry.js';
import { ConversationStore } from './src/core/conversation-store.js';
import { v4 as uuidv4 } from 'uuid';
import path from 'path';

// Test utilities
let testCounter = 0;
let passedTests = 0;
let failedTests = 0;

function testSection(name) {
  console.log(`\n${'='.repeat(80)}`);
  console.log(`  ${name}`);
  console.log(`${'='.repeat(80)}\n`);
}

async function test(description, fn) {
  testCounter++;
  const testNum = testCounter.toString().padStart(2, '0');
  try {
    await fn();
    passedTests++;
    console.log(`✓ Test ${testNum}: ${description}`);
  } catch (error) {
    failedTests++;
    console.error(`✗ Test ${testNum}: ${description}`);
    console.error(`  Error: ${error.message}`);
    if (error.stack) {
      console.error(`  ${error.stack.split('\n').slice(1, 3).join('\n  ')}`);
    }
  }
}

// Mock Neo4j client for testing
class MockNeo4jClient {
  constructor() {
    this.data = new Map();
    this.checkpoints = [];
    this.conversations = [];
  }

  async write(query, params = {}) {
    // Handle ValidationCheckpoint creation
    if (query.includes('CREATE (v:ValidationCheckpoint')) {
      this.checkpoints.push({
        id: params.id,
        conversationId: params.conversationId,
        step: params.step,
        validated: params.validated,
        notes: params.notes,
        screenshot: params.screenshot,
        validator: params.validator,
        timestamp: params.timestamp,
        requiredAttachments: params.requiredAttachments || [],
        actualAttachments: params.actualAttachments || []
      });
      return [{ v: { properties: this.checkpoints[this.checkpoints.length - 1] } }];
    }

    // Handle Conversation creation
    if (query.includes('CREATE (c:Conversation')) {
      this.conversations.push({
        id: params.id,
        title: params.title,
        platform: params.platform,
        sessionId: params.sessionId,
        conversationId: params.conversationId,
        status: params.status || 'active',
        createdAt: params.createdAt,
        metadata: params.metadata
      });
      return [{ c: { properties: this.conversations[this.conversations.length - 1] } }];
    }

    // Handle Conversation updates
    if (query.includes('SET c.')) {
      const conv = this.conversations.find(c => c.id === params.conversationId);
      if (conv) {
        if (params.conversationId !== undefined) conv.conversationId = params.conversationId;
        if (params.conversationUrl !== undefined) conv.conversationUrl = params.conversationUrl;
        if (params.lastActivity !== undefined) conv.lastActivity = params.lastActivity;
        if (params.status !== undefined) conv.status = params.status;
        if (params.sessionId !== undefined) conv.sessionId = params.sessionId;
      }
      return [{ c: { properties: conv } }];
    }

    return [];
  }

  async read(query, params = {}) {
    // Handle ValidationCheckpoint queries
    if (query.includes('ValidationCheckpoint')) {
      const { conversationId, step } = params;

      // Parse step from query string if not in params (e.g., "step: 'plan'")
      let stepFilter = step;
      if (!stepFilter) {
        const stepMatch = query.match(/step:\s*['"]([^'"]+)['"]/);
        if (stepMatch) {
          stepFilter = stepMatch[1];
        }
      }

      let filtered = this.checkpoints.filter(c => c.conversationId === conversationId);

      if (stepFilter) {
        filtered = filtered.filter(c => c.step === stepFilter);
      }

      // Sort by timestamp DESC (most recent first)
      filtered.sort((a, b) => {
        const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
        const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
        return timeB - timeA;
      });

      if (query.includes('LIMIT 1') && filtered.length > 0) {
        return [{ v: { properties: filtered[0] } }];
      }

      return filtered.map(v => ({ v: { properties: v } }));
    }

    // Handle Conversation queries
    if (query.includes('Conversation')) {
      const { sessionId, conversationId, platform } = params;

      let filtered = this.conversations;

      if (sessionId) {
        filtered = filtered.filter(c => c.id === sessionId || c.sessionId === sessionId);
      }
      if (conversationId && platform) {
        filtered = filtered.filter(c => c.conversationId === conversationId && c.platform === platform);
      }

      if (filtered.length === 0) return [];

      return filtered.map(c => ({
        c: { properties: c },
        platforms: [c.platform],
        messageCount: 0,
        lastMessageTime: null
      }));
    }

    return [];
  }

  async run(query, params = {}) {
    return this.read(query, params);
  }

  // Schema initialization (no-op for mock)
  async initSchema() {}
}

// ============================================================================
// Test Suite 1: RequirementEnforcer
// ============================================================================
testSection('RequirementEnforcer Tests');

await test('Cannot send without plan validated', async () => {
  const mockClient = new MockNeo4jClient();
  const validationStore = new ValidationCheckpointStore(mockClient);
  const enforcer = new RequirementEnforcer(validationStore);

  const conversationId = uuidv4();

  // No checkpoints exist
  let errorThrown = false;
  try {
    await enforcer.ensureCanSendMessage(conversationId);
  } catch (error) {
    errorThrown = true;
    assert(error.message.includes('No validation checkpoints found'));
    assert(error.message.includes("must validate at least the 'plan' step"));
  }

  assert(errorThrown, 'Should throw error when no plan exists');
});

await test('Cannot send when plan requires attachments but none attached', async () => {
  const mockClient = new MockNeo4jClient();
  const validationStore = new ValidationCheckpointStore(mockClient);
  const enforcer = new RequirementEnforcer(validationStore);

  const conversationId = uuidv4();

  // Create plan checkpoint with required attachments
  await validationStore.createCheckpoint({
    conversationId,
    step: 'plan',
    validated: true,
    notes: 'Plan requires 2 attachments',
    requiredAttachments: ['/path/to/file1.js', '/path/to/file2.json']
  });

  // Try to send without attaching files
  let errorThrown = false;
  try {
    await enforcer.ensureCanSendMessage(conversationId);
  } catch (error) {
    errorThrown = true;
    assert(error.message.includes('Draft plan requires 2 attachment(s)'));
    assert(error.message.includes('Last validated step was \'plan\''));
    assert(error.message.includes('You MUST'));
    assert(error.message.includes('Call taey_attach_files'));
  }

  assert(errorThrown, 'Should throw error when attachments required but not attached');
});

await test('Can send when all requirements met (with attachments)', async () => {
  const mockClient = new MockNeo4jClient();
  const validationStore = new ValidationCheckpointStore(mockClient);
  const enforcer = new RequirementEnforcer(validationStore);

  const conversationId = uuidv4();

  // Create plan checkpoint with required attachments (timestamp T+0)
  await validationStore.createCheckpoint({
    conversationId,
    step: 'plan',
    validated: true,
    notes: 'Plan requires 2 attachments',
    requiredAttachments: ['/path/to/file1.js', '/path/to/file2.json']
  });

  // Small delay to ensure different timestamp
  await new Promise(resolve => setTimeout(resolve, 10));

  // Attach files and validate - needs to be LAST checkpoint for getLastValidation to work (timestamp T+10)
  await validationStore.createCheckpoint({
    conversationId,
    step: 'attach_files',
    validated: true,
    notes: 'All files attached successfully',
    requiredAttachments: [], // Not used for attach_files checkpoint
    actualAttachments: ['/path/to/file1.js', '/path/to/file2.json']
  });

  // Should NOT throw - the logic checks requiresAttachments() which looks at 'plan' checkpoint
  // and last validated step which should be 'attach_files' with correct count
  await enforcer.ensureCanSendMessage(conversationId);
});

await test('Can send when all requirements met (no attachments)', async () => {
  const mockClient = new MockNeo4jClient();
  const validationStore = new ValidationCheckpointStore(mockClient);
  const enforcer = new RequirementEnforcer(validationStore);

  const conversationId = uuidv4();

  // Create plan checkpoint with no required attachments
  await validationStore.createCheckpoint({
    conversationId,
    step: 'plan',
    validated: true,
    notes: 'Simple message, no attachments needed',
    requiredAttachments: []
  });

  // Should NOT throw
  await enforcer.ensureCanSendMessage(conversationId);
});

await test('Cannot attach files without plan validated', async () => {
  const mockClient = new MockNeo4jClient();
  const validationStore = new ValidationCheckpointStore(mockClient);
  const enforcer = new RequirementEnforcer(validationStore);

  const conversationId = uuidv4();

  // No plan checkpoint exists
  let errorThrown = false;
  try {
    await enforcer.ensureCanAttachFiles(conversationId);
  } catch (error) {
    errorThrown = true;
    assert(error.message.includes('No validation checkpoints found'));
    assert(error.message.includes("must validate the 'plan' step"));
  }

  assert(errorThrown, 'Should throw error when trying to attach files without plan');
});

await test('Cannot attach files when plan is pending validation', async () => {
  const mockClient = new MockNeo4jClient();
  const validationStore = new ValidationCheckpointStore(mockClient);
  const enforcer = new RequirementEnforcer(validationStore);

  const conversationId = uuidv4();

  // Create plan checkpoint but mark as not validated
  await validationStore.createCheckpoint({
    conversationId,
    step: 'plan',
    validated: false, // Pending!
    notes: 'Plan created, awaiting review',
    requiredAttachments: ['/path/to/file.js']
  });

  let errorThrown = false;
  try {
    await enforcer.ensureCanAttachFiles(conversationId);
  } catch (error) {
    errorThrown = true;
    assert(error.message.includes('Plan step is pending validation'));
    assert(error.message.includes('validated=false'));
  }

  assert(errorThrown, 'Should throw error when plan is not validated');
});

await test('Cannot send with attachment count mismatch', async () => {
  const mockClient = new MockNeo4jClient();
  const validationStore = new ValidationCheckpointStore(mockClient);
  const enforcer = new RequirementEnforcer(validationStore);

  const conversationId = uuidv4();

  // Plan requires 2 files (timestamp T+0)
  await validationStore.createCheckpoint({
    conversationId,
    step: 'plan',
    validated: true,
    notes: 'Plan requires 2 files',
    requiredAttachments: ['/path/to/file1.js', '/path/to/file2.json']
  });

  // Small delay to ensure different timestamp
  await new Promise(resolve => setTimeout(resolve, 10));

  // But only 1 file attached (timestamp T+10, will be last)
  await validationStore.createCheckpoint({
    conversationId,
    step: 'attach_files',
    validated: true,
    notes: 'Attached 1 file',
    requiredAttachments: [], // Not used for attach_files checkpoint
    actualAttachments: ['/path/to/file1.js'] // Missing file2.json!
  });

  // Verify our test setup is correct
  const requirement = await validationStore.requiresAttachments(conversationId);
  const last = await validationStore.getLastValidation(conversationId);
  assert(requirement.required === true, `Requirement should be required: ${JSON.stringify(requirement)}`);
  assert(requirement.count === 2, `Requirement count should be 2: ${JSON.stringify(requirement)}`);
  assert(last.step === 'attach_files', `Last step should be attach_files: ${JSON.stringify(last)}`);
  assert(last.actualAttachments.length === 1, `Should have 1 actual attachment: ${JSON.stringify(last.actualAttachments)}`);

  let errorThrown = false;
  let errorMessage = '';
  try {
    await enforcer.ensureCanSendMessage(conversationId);
  } catch (error) {
    errorThrown = true;
    errorMessage = error.message;
    // The actual error message says "required X file(s), but Y were attached"
    assert(error.message.includes('required 2 file(s)'), `Error should mention required count: ${error.message}`);
    assert(error.message.includes('but 1 were attached'), `Error should mention actual count: ${error.message}`);
  }

  assert(errorThrown, `Should throw error when attachment count does not match. Got: ${errorMessage}`);
});

// ============================================================================
// Test Suite 2: SelectorRegistry
// ============================================================================
testSection('SelectorRegistry Tests');

await test('Can load all 5 platform configs', async () => {
  const registry = new SelectorRegistry();

  const platforms = ['claude', 'chatgpt', 'gemini', 'grok', 'perplexity'];

  for (const platform of platforms) {
    const config = await registry.getPlatformConfig(platform);
    assert(config.platform === platform, `Platform should be ${platform}`);
    assert(config.version, 'Should have version');
    assert(config.url, 'Should have URL');
  }
});

await test('Returns correct selectors for each platform', async () => {
  const registry = new SelectorRegistry();

  // Test Claude
  const claudeAttach = await registry.getSelector('claude', 'attach_button');
  assert(claudeAttach.includes('Attach'), 'Claude attach button should reference Attach label');

  const claudeSend = await registry.getSelector('claude', 'send_button');
  assert(claudeSend.includes('Send'), 'Claude send button should reference Send label');

  // Test ChatGPT
  const chatgptAttach = await registry.getSelector('chatgpt', 'attach_button');
  assert(chatgptAttach, 'ChatGPT should have attach button selector');

  // Test Gemini
  const geminiSend = await registry.getSelector('gemini', 'send_button');
  assert(geminiSend, 'Gemini should have send button selector');

  // Test Grok
  const grokInput = await registry.getSelector('grok', 'message_input');
  assert(grokInput, 'Grok should have message input selector');

  // Test Perplexity
  const perplexitySend = await registry.getSelector('perplexity', 'send_button');
  assert(perplexitySend, 'Perplexity should have send button selector');
});

await test('Throws helpful error for invalid platform', async () => {
  const registry = new SelectorRegistry();

  let errorThrown = false;
  try {
    await registry.getSelector('invalid-platform', 'send_button');
  } catch (error) {
    errorThrown = true;
    assert(error.message.includes('Selector config file not found'));
    assert(error.message.includes('invalid-platform'));
    assert(error.message.includes('Available platforms'));
  }

  assert(errorThrown, 'Should throw error for invalid platform');
});

await test('Throws helpful error for invalid selector key', async () => {
  const registry = new SelectorRegistry();

  let errorThrown = false;
  try {
    await registry.getSelector('claude', 'nonexistent_selector');
  } catch (error) {
    errorThrown = true;
    assert(error.message.includes('Selector key \'nonexistent_selector\' not found'));
    assert(error.message.includes('Available keys:'));
  }

  assert(errorThrown, 'Should throw error for invalid selector key');
});

await test('Fallback selectors work', async () => {
  const registry = new SelectorRegistry();

  // Get full definition to check fallback
  const def = await registry.getDefinition('claude', 'attach_button');
  assert(def.primary, 'Should have primary selector');
  assert(def.fallback, 'Should have fallback selector');
  assert(def.description, 'Should have description');

  // getSelector should return primary by default
  const selector = await registry.getSelector('claude', 'attach_button');
  assert(selector === def.primary, 'getSelector should return primary selector');
});

await test('getAvailableKeys returns sorted list', async () => {
  const registry = new SelectorRegistry();

  const keys = await registry.getAvailableKeys('claude');
  assert(Array.isArray(keys), 'Should return array');
  assert(keys.length > 0, 'Should have keys');
  assert(keys.includes('send_button'), 'Should include send_button');
  assert(keys.includes('attach_button'), 'Should include attach_button');

  // Check sorted
  const sorted = [...keys].sort();
  assert.deepEqual(keys, sorted, 'Keys should be sorted alphabetically');
});

await test('clearCache invalidates cached configs', async () => {
  const registry = new SelectorRegistry();

  // Load config (will cache)
  await registry.getSelector('claude', 'send_button');
  assert(registry.platformCache.has('claude'), 'Should cache claude config');

  // Clear specific platform
  registry.clearCache('claude');
  assert(!registry.platformCache.has('claude'), 'Should clear claude from cache');

  // Load multiple configs
  await registry.getSelector('claude', 'send_button');
  await registry.getSelector('chatgpt', 'send_button');
  assert(registry.platformCache.size === 2, 'Should cache 2 platforms');

  // Clear all
  registry.clearCache();
  assert(registry.platformCache.size === 0, 'Should clear all cache');
});

// ============================================================================
// Test Suite 3: Session Synchronization (ConversationStore)
// ============================================================================
testSection('Session Synchronization Tests');

await test('updateSessionState extracts conversationId correctly', async () => {
  const mockClient = new MockNeo4jClient();
  const store = new ConversationStore(mockClient);

  const sessionId = uuidv4();

  // Create a conversation first
  await mockClient.write(
    'CREATE (c:Conversation',
    {
      id: sessionId,
      title: 'Test',
      platform: 'claude',
      sessionId,
      conversationId: null,
      status: 'active',
      createdAt: new Date().toISOString()
    }
  );

  // Test Claude URL pattern
  const claudeUrl = 'https://claude.ai/chat/abc-123-def-456';
  const result1 = await store.updateSessionState(sessionId, claudeUrl, 'claude');
  assert(result1.conversationId === 'abc-123-def-456', 'Should extract Claude conversation ID');
  assert(result1.synced === true, 'Should mark as synced');

  // Test ChatGPT URL pattern
  const chatgptUrl = 'https://chatgpt.com/c/xyz789';
  const result2 = await store.updateSessionState(sessionId, chatgptUrl, 'chatgpt');
  assert(result2.conversationId === 'xyz789', 'Should extract ChatGPT conversation ID');

  // Test Gemini URL pattern
  const geminiUrl = 'https://gemini.google.com/app/deadbeef-1234';
  const result3 = await store.updateSessionState(sessionId, geminiUrl, 'gemini');
  assert(result3.conversationId === 'deadbeef-1234', 'Should extract Gemini conversation ID');
});

await test('getSessionHealth detects stale sessions', async () => {
  const mockClient = new MockNeo4jClient();
  const store = new ConversationStore(mockClient);

  const sessionId = uuidv4();

  // Create a conversation with old lastActivity (2 hours ago)
  const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000);

  // Use ConversationStore's createConversation instead of direct mock.write
  // This ensures proper structure
  await store.createConversation({
    id: sessionId,
    title: 'Old session',
    platform: 'claude',
    platforms: ['claude'],
    sessionId,
    conversationId: 'test-conv-id'
  });

  // Update with old lastActivity
  await store.updateConversation(sessionId, {
    lastActivity: twoHoursAgo
  });

  const health = await store.getSessionHealth(sessionId);
  assert(health.exists === true, 'Session should exist');
  assert(health.status === 'active', 'Status should be active');
  assert(health.staleDurationMs > 3600000, `staleDurationMs should be > 1 hour. Got: ${health.staleDurationMs}`);
  assert(health.healthy === false, `Should be marked unhealthy (stale). Health: ${JSON.stringify(health)}`);
  assert(health.info.includes('stale'), `Info should mention staleness. Info: ${health.info}`);
});

await test('getSessionHealth detects healthy sessions', async () => {
  const mockClient = new MockNeo4jClient();
  const store = new ConversationStore(mockClient);

  const sessionId = uuidv4();

  // Create a conversation with recent lastActivity (5 minutes ago)
  const fiveMinutesAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
  await mockClient.write(
    'CREATE (c:Conversation',
    {
      id: sessionId,
      title: 'Active session',
      platform: 'claude',
      sessionId,
      conversationId: 'test-conv-id',
      status: 'active',
      createdAt: new Date().toISOString(),
      lastActivity: fiveMinutesAgo
    }
  );

  const health = await store.getSessionHealth(sessionId);
  assert(health.exists === true, 'Session should exist');
  assert(health.status === 'active', 'Status should be active');
  assert(health.healthy === true, 'Should be marked healthy');
  assert(health.info.includes('healthy'), 'Info should mention healthy');
});

await test('reconcileOrphanedSessions finds orphaned sessions', async () => {
  const mockClient = new MockNeo4jClient();
  const store = new ConversationStore(mockClient);

  // Create 3 sessions
  const session1 = uuidv4();
  const session2 = uuidv4();
  const session3 = uuidv4();

  for (const sessionId of [session1, session2, session3]) {
    await mockClient.write(
      'CREATE (c:Conversation',
      {
        id: sessionId,
        title: 'Test session',
        platform: 'claude',
        sessionId,
        conversationId: null,
        status: 'active',
        createdAt: new Date().toISOString()
      }
    );
  }

  // Only session1 is still active in MCP
  const activeMcpSessions = [session1];

  const result = await store.reconcileOrphanedSessions(activeMcpSessions);

  assert(result.orphaned.length === 2, 'Should find 2 orphaned sessions');
  assert(result.updated === 2, 'Should update 2 sessions');

  const orphanedIds = result.orphaned.map(s => s.sessionId);
  assert(orphanedIds.includes(session2), 'Should mark session2 as orphaned');
  assert(orphanedIds.includes(session3), 'Should mark session3 as orphaned');
  assert(!orphanedIds.includes(session1), 'Should NOT mark session1 as orphaned');
});

// ============================================================================
// Test Suite 4: newSession Fix (Conceptual)
// ============================================================================
testSection('newSession Fix Tests (Conceptual)');

await test('newSession=true generates correct /new URL', () => {
  // Conceptual test - verify URL generation logic
  const platforms = ConversationStore.PLATFORMS;

  assert(platforms.claude.newChatUrl === 'https://claude.ai/new', 'Claude new chat URL');
  assert(platforms.chatgpt.newChatUrl === 'https://chatgpt.com', 'ChatGPT new chat URL');
  assert(platforms.gemini.newChatUrl === 'https://gemini.google.com/app', 'Gemini new chat URL');
  assert(platforms.grok.newChatUrl === 'https://grok.com', 'Grok new chat URL');
  assert(platforms.perplexity.newChatUrl === 'https://perplexity.ai', 'Perplexity new chat URL');
});

await test('conversationId provided navigates to conversation', () => {
  // Conceptual test - verify URL pattern construction
  const platforms = ConversationStore.PLATFORMS;

  // Test URL pattern templates
  assert(
    platforms.claude.conversationUrlPattern === 'https://claude.ai/chat/:id',
    'Claude conversation URL pattern'
  );
  assert(
    platforms.chatgpt.conversationUrlPattern === 'https://chatgpt.com/c/:id',
    'ChatGPT conversation URL pattern'
  );
  assert(
    platforms.gemini.conversationUrlPattern === 'https://gemini.google.com/app/:id',
    'Gemini conversation URL pattern'
  );
});

await test('conversationId extracted from URL correctly', () => {
  const mockClient = new MockNeo4jClient();
  const store = new ConversationStore(mockClient);

  // Test Claude
  const claudeId = store.extractConversationId('https://claude.ai/chat/abc-123-def', 'claude');
  assert(claudeId === 'abc-123-def', 'Should extract Claude conversation ID');

  // Test ChatGPT
  const chatgptId = store.extractConversationId('https://chatgpt.com/c/xyz-789', 'chatgpt');
  assert(chatgptId === 'xyz-789', 'Should extract ChatGPT conversation ID');

  // Test Gemini
  const geminiId = store.extractConversationId('https://gemini.google.com/app/deadbeef', 'gemini');
  assert(geminiId === 'deadbeef', 'Should extract Gemini conversation ID');

  // Test Grok
  const grokId = store.extractConversationId('https://grok.com/chat/feed-face', 'grok');
  assert(grokId === 'feed-face', 'Should extract Grok conversation ID');

  // Test Perplexity
  const perplexityId = store.extractConversationId('https://perplexity.ai/search/cafe-babe', 'perplexity');
  assert(perplexityId === 'cafe-babe', 'Should extract Perplexity conversation ID');

  // Test invalid URL
  const invalidId = store.extractConversationId('https://claude.ai/settings', 'claude');
  assert(invalidId === null, 'Should return null for non-conversation URL');
});

// ============================================================================
// Test Summary
// ============================================================================
console.log('\n' + '='.repeat(80));
console.log('  TEST SUMMARY');
console.log('='.repeat(80));
console.log(`Total tests: ${testCounter}`);
console.log(`Passed: ${passedTests} ✓`);
console.log(`Failed: ${failedTests} ✗`);
console.log('='.repeat(80));

if (failedTests > 0) {
  console.log('\n⚠️  Some tests failed. Review errors above.');
  process.exit(1);
} else {
  console.log('\n✅ All tests passed!');
  process.exit(0);
}
