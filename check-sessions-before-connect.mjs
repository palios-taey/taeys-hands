#!/usr/bin/env node
/**
 * DATABASE-FIRST SESSION PROTOCOL
 * 
 * ALWAYS run this before connecting to ANY AI session.
 * This prevents context loss and ensures proper session management.
 */

import { getConversationStore } from './src/core/conversation-store.js';

const store = getConversationStore();

async function checkBeforeConnect(platformHint = null) {
  console.log('\n=== DATABASE-FIRST SESSION CHECK ===\n');
  
  // 1. Get all active sessions
  const activeSessions = await store.getActiveSessions();
  
  if (activeSessions.length === 0) {
    console.log('✓ No active sessions - safe to start fresh\n');
    return { canStartFresh: true };
  }
  
  console.log('⚠️  ACTIVE SESSIONS FOUND:\n');
  
  // Filter by platform if provided
  const relevant = platformHint 
    ? activeSessions.filter(s => s.platforms.includes(platformHint))
    : activeSessions;
  
  // Show recent activity
  const recent = activeSessions
    .sort((a, b) => new Date(b.lastMessageTime) - new Date(a.lastMessageTime))
    .slice(0, 10);
  
  for (const s of recent) {
    const platform = s.platforms[0];
    const shortId = s.id.substring(0, 8);
    const timeAgo = Math.round((Date.now() - new Date(s.lastMessageTime)) / 1000 / 60);
    
    console.log(`  ${platform.padEnd(10)} | ${shortId}... | ${s.messageCount} msgs | ${timeAgo}m ago`);
    
    // Get context summary if recent
    if (timeAgo < 60) {
      const context = await store.getSessionContext(s.id);
      const lastMsg = context.recentMessages[0];
      if (lastMsg) {
        const preview = lastMsg.content ? lastMsg.content.substring(0, 100) : '(empty)';
        console.log(`    Last: [${lastMsg.role}] ${preview}...`);
      }
    }
  }
  
  // Show platform-specific recommendation
  if (platformHint && relevant.length > 0) {
    console.log(`\n⚠️  ${relevant.length} active ${platformHint} session(s) exist!`);
    console.log('   Consider:');
    console.log('   1. Resume existing session (use conversationId)');
    console.log('   2. Close old session first, then start fresh');
    console.log('   3. Verify this is intentional parallel work\n');
  }
  
  return {
    canStartFresh: activeSessions.length === 0,
    activeSessions: relevant,
    totalActive: activeSessions.length
  };
}

// CLI usage
const platform = process.argv[2] || null;
checkBeforeConnect(platform).then(() => process.exit(0));
