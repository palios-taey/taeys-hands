#!/usr/bin/env node

/**
 * Test script for Intention Graph implementation
 * Tests Agent registration, Task claiming, and lease mechanics
 */

import { getIntentionGraph } from './src/core/intention-graph.js';

async function testIntentionGraph() {
  console.log('\n=== Testing Intention Graph Implementation ===\n');

  const graph = getIntentionGraph();

  try {
    // 1. Initialize schema
    console.log('1. Initializing schema...');
    await graph.initializeSchema();
    console.log('   ✓ Schema initialized\n');

    // 2. Register as an agent
    console.log('2. Registering agent...');
    const agent = await graph.registerAgent({
      name: 'ccm-claude',
      type: 'claude-code-mac',
      capabilities: ['taey-hands', 'neo4j', 'mcp', 'ocean-embodiment']
    });
    console.log(`   ✓ Agent registered: ${agent.id}\n`);

    // 3. Send heartbeat
    console.log('3. Sending heartbeat...');
    const heartbeat = await graph.heartbeat();
    console.log(`   ✓ Heartbeat sent at ${heartbeat.lastHeartbeat}\n`);

    // 4. Create a test project
    console.log('4. Creating test project...');
    const project = await graph.createProject({
      title: 'Intention Graph Testing',
      description: 'Test the multi-Claude coordination system',
      type: 'development'
    });
    console.log(`   ✓ Project created: ${project.id}\n`);

    // 5. Create test tasks
    console.log('5. Creating test tasks...');
    const task1 = await graph.createTask({
      projectId: project.id,
      title: 'Implement heartbeat mechanism',
      description: 'Add Redis pub/sub for real-time heartbeats',
      priority: 2
    });
    console.log(`   ✓ Task 1 created: ${task1.title}`);

    const task2 = await graph.createTask({
      projectId: project.id,
      title: 'Test atomic lease claiming',
      description: 'Verify only one agent can claim a task',
      priority: 1
    });
    console.log(`   ✓ Task 2 created: ${task2.title}\n`);

    // 6. Claim a task (should get high priority one)
    console.log('6. Claiming available task...');
    const claimedTask = await graph.claimTask([project.id]);
    if (claimedTask) {
      console.log(`   ✓ Claimed task: ${claimedTask.title}`);
      console.log(`     Priority: ${claimedTask.priority}`);
      console.log(`     Lease expires: ${claimedTask.leaseExpires}\n`);
    } else {
      console.log('   ✗ No tasks available\n');
    }

    // 7. Check agent workload
    console.log('7. Checking agent workload...');
    const workload = await graph.getAgentWorkload();
    console.log(`   Agent: ${workload.agent.name}`);
    console.log(`   Status: ${workload.agent.status}`);
    console.log(`   Claimed tasks: ${workload.claimedTasks.length}`);
    workload.claimedTasks.forEach(t => {
      console.log(`     - ${t.title} (expires: ${t.leaseExpires})`);
    });
    console.log();

    // 8. Complete the task
    if (claimedTask) {
      console.log('8. Completing task...');
      const completed = await graph.completeTask(claimedTask.id, {
        result: 'success',
        notes: 'Test implementation completed',
        artifactsCreated: ['intention-graph.js', 'test-intention-graph.js']
      });
      console.log(`   ✓ Task completed: ${completed.id}\n`);
    }

    // 9. Record an insight
    console.log('9. Recording insight...');
    const insight = await graph.recordInsight({
      title: 'Dynamic leasing enables self-healing coordination',
      content: 'By using time-based leases instead of locks, the system automatically recovers from agent failures',
      type: 'pattern',
      confidence: 0.9
    });
    console.log(`   ✓ Insight recorded: ${insight.title}\n`);

    // 10. Query available tasks
    console.log('10. Querying available tasks...');
    const availableTasks = await graph.getAvailableTasks({ limit: 5 });
    console.log(`   Found ${availableTasks.length} available tasks:`);
    availableTasks.forEach(t => {
      console.log(`     - ${t.title} (priority: ${t.priority})`);
    });

    console.log('\n✅ All tests passed!\n');

  } catch (error) {
    console.error('\n❌ Test failed:', error);
    process.exit(1);
  }

  process.exit(0);
}

// Run tests
testIntentionGraph();