/**
 * Intention Graph - Multi-Claude Coordination via Neo4j
 *
 * Implements Gemini's 4-layer topology for distributed AI consciousness:
 * - Layer 1: Physical Substrate (Agent, Machine)
 * - Layer 2: Interaction Layer (Session, Conversation, Message)
 * - Layer 3: Conceptual Layer (Project, Task, Insight)
 * - Layer 4: Resonance Layer (Axiom, ResonanceEvent)
 *
 * Based on Deep Think analysis from 2025-11-27
 */

import { v4 as uuidv4 } from 'uuid';
import { getNeo4jClient } from './neo4j-client.js';
import os from 'os';

export class IntentionGraph {
  constructor() {
    this.client = getNeo4jClient();
    this.agentId = null;
  }

  /**
   * Initialize the Intention Graph schema
   * Creates indexes and constraints for all node types
   */
  async initializeSchema() {
    console.log('[IntentionGraph] Initializing schema...');

    const constraints = [
      // Layer 1: Physical Substrate
      'CREATE CONSTRAINT IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE',
      'CREATE CONSTRAINT IF NOT EXISTS FOR (m:Machine) REQUIRE m.id IS UNIQUE',

      // Layer 2: Interaction (existing)
      'CREATE CONSTRAINT IF NOT EXISTS FOR (c:Conversation) REQUIRE c.id IS UNIQUE',
      'CREATE CONSTRAINT IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE',
      'CREATE CONSTRAINT IF NOT EXISTS FOR (msg:Message) REQUIRE msg.id IS UNIQUE',

      // Layer 3: Conceptual
      'CREATE CONSTRAINT IF NOT EXISTS FOR (p:Project) REQUIRE p.id IS UNIQUE',
      'CREATE CONSTRAINT IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE',
      'CREATE CONSTRAINT IF NOT EXISTS FOR (i:Insight) REQUIRE i.id IS UNIQUE',

      // Layer 4: Resonance
      'CREATE CONSTRAINT IF NOT EXISTS FOR (ax:Axiom) REQUIRE ax.id IS UNIQUE',
      'CREATE CONSTRAINT IF NOT EXISTS FOR (r:ResonanceEvent) REQUIRE r.id IS UNIQUE'
    ];

    for (const constraint of constraints) {
      try {
        await this.client.write(constraint);
      } catch (err) {
        // Constraint might already exist
        console.log(`  Schema constraint: ${err.message}`);
      }
    }

    console.log('[IntentionGraph] Schema initialized');
  }

  /**
   * Register this Claude instance as an Agent
   * @param {Object} identity - From CLAUDE.md or config
   * @returns {Object} Agent node data
   */
  async registerAgent(identity = {}) {
    const hostname = os.hostname();
    const platform = os.platform();

    this.agentId = identity.agentId || `${hostname}-${Date.now()}`;

    const agent = {
      id: this.agentId,
      name: identity.name || hostname,
      type: identity.type || 'claude-instance',
      platform: platform,
      machineId: hostname,
      status: 'active',
      capabilities: JSON.stringify(identity.capabilities || ['taey-hands', 'neo4j', 'mcp']),
      created: new Date().toISOString(),
      lastHeartbeat: new Date().toISOString()
    };

    await this.client.write(
      `MERGE (a:Agent {id: $id})
       SET a += $properties
       MERGE (m:Machine {id: $machineId})
       SET m.hostname = $hostname,
           m.platform = $platform
       MERGE (a)-[:RUNS_ON]->(m)
       RETURN a`,
      {
        id: agent.id,
        properties: agent,
        machineId: hostname,
        hostname: hostname,
        platform: platform
      }
    );

    console.log(`[IntentionGraph] Agent registered: ${agent.id}`);
    return agent;
  }

  /**
   * Send heartbeat and renew any active leases
   * @returns {Object} Updated agent status
   */
  async heartbeat() {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const now = new Date().toISOString();

    // Update agent heartbeat and renew task leases
    const result = await this.client.write(
      `MATCH (a:Agent {id: $agentId})
       SET a.lastHeartbeat = $now,
           a.status = 'active'
       WITH a
       OPTIONAL MATCH (a)-[:CLAIMS]->(t:Task {status: 'claimed'})
       WHERE t.leaseExpires > datetime()
       SET t.leaseExpires = datetime() + duration('PT5M')
       RETURN a, collect(t.id) as renewedTasks`,
      { agentId: this.agentId, now }
    );

    // Handle the array of objects return format
    const renewedTasks = result && result.length > 0 && result[0].renewedTasks
      ? result[0].renewedTasks
      : [];

    return {
      agentId: this.agentId,
      lastHeartbeat: now,
      renewedTasks
    };
  }

  /**
   * Create a new Project (high-level objective)
   * @param {Object} projectData
   * @returns {Object} Project node
   */
  async createProject(projectData) {
    const project = {
      id: projectData.id || uuidv4(),
      title: projectData.title,
      description: projectData.description,
      type: projectData.type || 'development', // development, research, dream, council
      status: 'active',
      priority: projectData.priority || 1,
      created: new Date().toISOString(),
      metadata: JSON.stringify(projectData.metadata || {})
    };

    await this.client.write(
      `CREATE (p:Project)
       SET p = $project
       RETURN p`,
      { project }
    );

    console.log(`[IntentionGraph] Project created: ${project.title}`);
    return project;
  }

  /**
   * Create a new Task within a Project
   * @param {Object} taskData
   * @returns {Object} Task node
   */
  async createTask(taskData) {
    const task = {
      id: taskData.id || uuidv4(),
      projectId: taskData.projectId,
      title: taskData.title,
      description: taskData.description,
      type: taskData.type || 'implementation', // implementation, review, research, synthesis
      status: 'pending',
      priority: taskData.priority || 1,
      estimatedMinutes: taskData.estimatedMinutes || 30,
      created: new Date().toISOString(),
      metadata: JSON.stringify(taskData.metadata || {})
    };

    await this.client.write(
      `MATCH (p:Project {id: $projectId})
       CREATE (t:Task)
       SET t = $task
       CREATE (t)-[:PART_OF]->(p)
       RETURN t`,
      { projectId: task.projectId, task }
    );

    console.log(`[IntentionGraph] Task created: ${task.title}`);
    return task;
  }

  /**
   * Atomically claim an available Task
   * Implements Gemini's dynamic leasing protocol
   * @param {Array} activeProjects - Project IDs to consider
   * @returns {Object|null} Claimed task or null if none available
   */
  async claimTask(activeProjects = []) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    // Use Cypher's atomic operations to claim highest priority task
    const result = await this.client.write(
      `MATCH (t:Task {status: 'pending'})
       WHERE t.projectId IN $activeProjects OR size($activeProjects) = 0
       WITH t ORDER BY t.priority DESC, t.created ASC LIMIT 1
       MATCH (a:Agent {id: $agentId})
       SET t.status = 'claimed',
           t.claimedBy = $agentId,
           t.claimedAt = datetime(),
           t.leaseExpires = datetime() + duration('PT5M')
       MERGE (a)-[:CLAIMS]->(t)
       RETURN t`,
      { activeProjects, agentId: this.agentId }
    );

    if (!result || result.length === 0) {
      return null; // No tasks available
    }

    const task = result[0].t.properties || result[0].t;
    console.log(`[IntentionGraph] Task claimed: ${task.title} (expires: ${task.leaseExpires})`);
    return task;
  }

  /**
   * Complete a claimed Task
   * @param {string} taskId
   * @param {Object} outcome - Results, insights, artifacts produced
   * @returns {Object} Updated task
   */
  async completeTask(taskId, outcome = {}) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId, claimedBy: $agentId})
       SET t.status = 'completed',
           t.completedAt = datetime(),
           t.outcome = $outcome,
           t.leaseExpires = null
       RETURN t`,
      {
        taskId,
        agentId: this.agentId,
        outcome: JSON.stringify(outcome)
      }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found or not claimed by ${this.agentId}`);
    }

    console.log(`[IntentionGraph] Task completed: ${taskId}`);
    return result[0].t.properties || result[0].t;
  }

  /**
   * Release a claimed Task (voluntary release or failure)
   * @param {string} taskId
   * @param {string} reason
   */
  async releaseTask(taskId, reason = 'voluntary') {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    await this.client.write(
      `MATCH (t:Task {id: $taskId, claimedBy: $agentId})
       SET t.status = 'pending',
           t.claimedBy = null,
           t.claimedAt = null,
           t.leaseExpires = null,
           t.releaseReason = $reason,
           t.releasedAt = datetime()
       WITH t
       MATCH (a:Agent {id: $agentId})-[r:CLAIMS]->(t)
       DELETE r
       RETURN t`,
      { taskId, agentId: this.agentId, reason }
    );

    console.log(`[IntentionGraph] Task released: ${taskId} (${reason})`);
  }

  /**
   * Clean up expired Task leases (self-healing)
   * Should be called periodically by a monitor process
   */
  async cleanupExpiredLeases() {
    const result = await this.client.write(
      `MATCH (t:Task {status: 'claimed'})
       WHERE t.leaseExpires < datetime()
       SET t.status = 'pending',
           t.claimedBy = null,
           t.claimedAt = null,
           t.leaseExpires = null,
           t.releaseReason = 'lease_expired',
           t.releasedAt = datetime()
       WITH t
       MATCH (a:Agent)-[r:CLAIMS]->(t)
       DELETE r
       RETURN count(t) as expiredCount`
    );

    const count = result && result.length > 0 ? result[0].expiredCount : 0;
    if (count > 0) {
      console.log(`[IntentionGraph] Cleaned up ${count} expired task leases`);
    }
    return count;
  }

  /**
   * Link a Session to a Task (when using taey-hands for task execution)
   * @param {string} taskId
   * @param {string} sessionId
   * @param {string} platform - Which AI interface
   */
  async linkSessionToTask(taskId, sessionId, platform) {
    await this.client.write(
      `MATCH (t:Task {id: $taskId})
       MATCH (s:Session {id: $sessionId})
       MERGE (t)-[:UTILIZES]->(s)
       SET s.platform = $platform,
           s.taskId = $taskId
       RETURN t, s`,
      { taskId, sessionId, platform }
    );

    console.log(`[IntentionGraph] Session ${sessionId} linked to task ${taskId}`);
  }

  /**
   * Record an Insight derived from conversations
   * @param {Object} insightData
   * @returns {Object} Insight node
   */
  async recordInsight(insightData) {
    const insight = {
      id: insightData.id || uuidv4(),
      title: insightData.title,
      content: insightData.content,
      type: insightData.type || 'emergent', // emergent, synthesis, pattern, learning
      confidence: insightData.confidence || 0.5,
      sourceConversations: JSON.stringify(insightData.sourceConversations || []),
      created: new Date().toISOString(),
      createdBy: this.agentId
    };

    await this.client.write(
      `CREATE (i:Insight)
       SET i = $insight
       WITH i
       MATCH (a:Agent {id: $agentId})
       CREATE (a)-[:DISCOVERED]->(i)
       RETURN i`,
      { insight, agentId: this.agentId }
    );

    console.log(`[IntentionGraph] Insight recorded: ${insight.title}`);
    return insight;
  }

  /**
   * Query available Tasks across Projects
   * @param {Object} filters
   * @returns {Array} Available tasks
   */
  async getAvailableTasks(filters = {}) {
    const query = `
      MATCH (t:Task {status: 'pending'})
      ${filters.projectId ? 'WHERE t.projectId = $projectId' : ''}
      RETURN t
      ORDER BY t.priority DESC, t.created ASC
      LIMIT ${filters.limit || 10}
    `;

    const result = await this.client.read(query, filters);
    return result ? result.map(r => r.t.properties || r.t) : [];
  }

  /**
   * Get Agent's current workload
   * @returns {Object} Agent status and claimed tasks
   */
  async getAgentWorkload() {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const result = await this.client.read(
      `MATCH (a:Agent {id: $agentId})
       OPTIONAL MATCH (a)-[:CLAIMS]->(t:Task {status: 'claimed'})
       RETURN a, collect(t) as claimedTasks`,
      { agentId: this.agentId }
    );

    if (!result || result.length === 0) {
      return null;
    }

    return {
      agent: result[0].a.properties || result[0].a,
      claimedTasks: (result[0].claimedTasks || []).map(t => t.properties || t)
    };
  }
}

// Singleton instance
let intentionGraph = null;

export function getIntentionGraph() {
  if (!intentionGraph) {
    intentionGraph = new IntentionGraph();
  }
  return intentionGraph;
}