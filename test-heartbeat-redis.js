#!/usr/bin/env node

/**
 * Cross-platform heartbeat test using Redis pub/sub
 * Tests real-time coordination between multiple Claude instances
 *
 * Prerequisites:
 * - Redis running on Spark #2 (10.0.0.80:6379)
 * - Both Claude instances have network access
 */

import { getIntentionGraph } from './src/core/intention-graph.js';
import { createClient } from 'redis';
import os from 'os';

// Redis configuration - Spark #2
const REDIS_CONFIG = {
  host: '10.0.0.80',  // Spark #2
  port: 6379
};

class HeartbeatTest {
  constructor(agentName) {
    this.agentName = agentName;
    this.platform = os.platform();
    this.hostname = os.hostname();
    this.graph = getIntentionGraph();

    // Create Redis clients (need separate ones for pub/sub)
    this.publisher = null;
    this.subscriber = null;
  }

  async connect() {
    console.log(`\n=== ${this.agentName} Heartbeat Test ===`);
    console.log(`Platform: ${this.platform}`);
    console.log(`Hostname: ${this.hostname}\n`);

    // Connect to Redis
    try {
      console.log('1. Connecting to Redis on Spark #2...');

      this.publisher = createClient({
        socket: {
          host: REDIS_CONFIG.host,
          port: REDIS_CONFIG.port
        }
      });

      this.subscriber = createClient({
        socket: {
          host: REDIS_CONFIG.host,
          port: REDIS_CONFIG.port
        }
      });

      await this.publisher.connect();
      await this.subscriber.connect();

      console.log(`   ✓ Connected to Redis at ${REDIS_CONFIG.host}:${REDIS_CONFIG.port}\n`);
    } catch (err) {
      console.error(`   ✗ Redis connection failed: ${err.message}`);
      console.error(`   Make sure Redis is running on Spark #2 and accessible`);
      process.exit(1);
    }

    // Register agent in Neo4j
    console.log('2. Registering agent in Neo4j...');
    await this.graph.initializeSchema();
    const agent = await this.graph.registerAgent({
      name: this.agentName,
      type: this.platform === 'darwin' ? 'claude-code-mac' : 'claude-code-linux',
      capabilities: ['taey-hands', 'neo4j', 'redis', 'heartbeat-test']
    });
    console.log(`   ✓ Agent registered: ${agent.id}\n`);

    // Subscribe to heartbeat channel
    console.log('3. Subscribing to heartbeat channel...');
    await this.subscriber.subscribe('agents:heartbeat', (message) => {
      const data = JSON.parse(message);
      if (data.agentId !== agent.id) {
        console.log(`   💓 Received heartbeat from ${data.agentName} (${data.platform})`);
      }
    });

    await this.subscriber.subscribe('tasks:new', (message) => {
      const task = JSON.parse(message);
      console.log(`   📋 New task available: ${task.title} (priority: ${task.priority})`);
    });

    console.log(`   ✓ Subscribed to channels\n`);

    // Start heartbeat loop
    console.log('4. Starting heartbeat broadcast...');
    this.heartbeatInterval = setInterval(async () => {
      // Send heartbeat to Neo4j
      const heartbeat = await this.graph.heartbeat();

      // Broadcast heartbeat to Redis
      const message = {
        agentId: agent.id,
        agentName: this.agentName,
        platform: this.platform,
        hostname: this.hostname,
        timestamp: heartbeat.lastHeartbeat,
        renewedTasks: heartbeat.renewedTasks
      };

      await this.publisher.publish('agents:heartbeat', JSON.stringify(message));
      console.log(`   ❤️  Heartbeat sent (${new Date().toISOString().split('T')[1].split('.')[0]})`);
    }, 5000); // Every 5 seconds

    console.log(`   ✓ Heartbeat broadcasting started\n`);

    return agent;
  }

  async testTaskCoordination() {
    console.log('5. Testing task coordination...\n');

    // Create a test project
    const project = await this.graph.createProject({
      title: 'Cross-Platform Heartbeat Test',
      description: 'Testing real-time coordination between Mac and Linux Claude instances',
      type: 'test'
    });

    // Create test tasks and broadcast
    const task1 = await this.graph.createTask({
      projectId: project.id,
      title: `Test task from ${this.agentName}`,
      description: `Created by ${this.platform} instance`,
      priority: Math.floor(Math.random() * 5) + 1
    });

    // Broadcast new task notification
    await this.publisher.publish('tasks:new', JSON.stringify(task1));
    console.log(`   ✓ Created and broadcast task: ${task1.title}\n`);

    // Try to claim a task
    console.log('6. Attempting to claim available task...');
    const claimedTask = await this.graph.claimTask([project.id]);
    if (claimedTask) {
      console.log(`   ✓ Claimed task: ${claimedTask.title}`);
      console.log(`     Lease expires: ${claimedTask.leaseExpires}\n`);

      // Complete the task after a delay
      setTimeout(async () => {
        await this.graph.completeTask(claimedTask.id, {
          result: 'success',
          notes: `Completed by ${this.agentName} on ${this.platform}`
        });
        console.log(`   ✅ Task completed: ${claimedTask.title}\n`);
      }, 3000);
    } else {
      console.log(`   ℹ️  No tasks available to claim\n`);
    }
  }

  async disconnect() {
    console.log('\n7. Cleaning up...');

    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
    }

    if (this.publisher) {
      await this.publisher.disconnect();
    }

    if (this.subscriber) {
      await this.subscriber.disconnect();
    }

    console.log('   ✓ Disconnected from Redis\n');
  }
}

// Main test runner
async function runTest() {
  // Determine agent name based on platform
  const platform = os.platform();
  const agentName = platform === 'darwin' ? 'ccm-claude' : 'spark-claude';

  const test = new HeartbeatTest(agentName);

  try {
    // Connect and start heartbeat
    const agent = await test.connect();

    // Test task coordination
    await test.testTaskCoordination();

    // Run for 30 seconds to see cross-platform heartbeats
    console.log('📡 Listening for cross-platform heartbeats for 30 seconds...\n');
    console.log('   (Run this script on both Mac and Linux simultaneously)\n');

    setTimeout(async () => {
      await test.disconnect();
      console.log('✅ Test completed successfully!\n');
      process.exit(0);
    }, 30000);

  } catch (error) {
    console.error('\n❌ Test failed:', error);
    await test.disconnect();
    process.exit(1);
  }
}

// Handle graceful shutdown
process.on('SIGINT', async () => {
  console.log('\n\nReceived SIGINT, shutting down gracefully...');
  process.exit(0);
});

// Run the test
runTest();