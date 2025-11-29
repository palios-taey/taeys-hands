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
   * Stable agent ID based on machine identity (not timestamp)
   * @param {Object} identity - From CLAUDE.md or config
   * @returns {Object} Agent node data
   */
  async registerAgent(identity = {}) {
    const hostname = os.hostname();
    const platform = os.platform();

    // Stable agent ID: {machine-prefix}-claude
    // e.g., "spark-78c6-claude", "ccm-claude"
    const machinePrefix = identity.machinePrefix || hostname.split('.')[0].toLowerCase();
    this.agentId = identity.agentId || `${machinePrefix}-claude`;

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
   * Send heartbeat (simple liveness signal)
   * No lease renewal - tasks have stable ownership
   * @returns {Object} Updated agent status
   */
  async heartbeat() {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const now = new Date().toISOString();

    // Update agent heartbeat
    const result = await this.client.write(
      `MATCH (a:Agent {id: $agentId})
       SET a.lastHeartbeat = $now,
           a.status = 'active'
       WITH a
       OPTIONAL MATCH (a)-[:WORKS_ON]->(t:Task)
       WHERE t.status IN ['in_progress', 'blocked']
       RETURN a, collect(t.id) as activeTasks`,
      { agentId: this.agentId, now }
    );

    // Handle the array of objects return format
    const activeTasks = result && result.length > 0 && result[0].activeTasks
      ? result[0].activeTasks
      : [];

    return {
      agentId: this.agentId,
      lastHeartbeat: now,
      activeTasks
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
   * Assign a Task to this Agent (stable ownership)
   * No leases - simple assignment until completion or handoff
   * @param {string} taskId - Specific task to assign
   * @returns {Object} Assigned task
   */
  async assignTask(taskId) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId})
       WHERE t.status = 'pending'
       MATCH (a:Agent {id: $agentId})
       SET t.status = 'in_progress',
           t.assignedTo = $agentId,
           t.assignedAt = datetime()
       MERGE (a)-[:WORKS_ON]->(t)
       RETURN t`,
      { taskId, agentId: this.agentId }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found or already assigned`);
    }

    const task = result[0].t.properties || result[0].t;
    console.log(`[IntentionGraph] Task assigned: ${task.title}`);
    return task;
  }

  /**
   * Get next available Task (highest priority, oldest first)
   * @param {Array} activeProjects - Project IDs to consider
   * @returns {Object|null} Available task or null if none
   */
  async getNextTask(activeProjects = []) {
    const query = `
      MATCH (t:Task {status: 'pending'})
      ${activeProjects.length > 0 ? 'WHERE t.projectId IN $activeProjects' : ''}
      RETURN t
      ORDER BY t.priority DESC, t.created ASC
      LIMIT 1
    `;

    const result = await this.client.read(query, { activeProjects });

    if (!result || result.length === 0) {
      return null;
    }

    return result[0].t.properties || result[0].t;
  }

  /**
   * Update Task status (in_progress → done, blocked, etc.)
   * @param {string} taskId
   * @param {string} status - pending | in_progress | blocked | done
   * @param {Object} outcome - Optional results, insights, artifacts
   * @returns {Object} Updated task
   */
  async updateTaskStatus(taskId, status, outcome = {}) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const validStatuses = ['pending', 'in_progress', 'blocked', 'done'];
    if (!validStatuses.includes(status)) {
      throw new Error(`Invalid status: ${status}. Must be one of: ${validStatuses.join(', ')}`);
    }

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId, assignedTo: $agentId})
       SET t.status = $status,
           t.updatedAt = datetime(),
           t.outcome = $outcome
       ${status === 'done' ? ', t.completedAt = datetime()' : ''}
       RETURN t`,
      {
        taskId,
        agentId: this.agentId,
        status,
        outcome: JSON.stringify(outcome)
      }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found or not assigned to ${this.agentId}`);
    }

    console.log(`[IntentionGraph] Task status updated: ${taskId} → ${status}`);
    return result[0].t.properties || result[0].t;
  }

  /**
   * Complete a Task (convenience method for updateTaskStatus)
   * @param {string} taskId
   * @param {Object} outcome
   * @returns {Object} Updated task
   */
  async completeTask(taskId, outcome = {}) {
    return this.updateTaskStatus(taskId, 'done', outcome);
  }

  /**
   * Add a note to a Task (for context sharing)
   * @param {string} taskId
   * @param {string} note - Text note
   * @returns {Object} Updated task with notes
   */
  async addTaskNote(taskId, note) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId})
       SET t.notes = COALESCE(t.notes, []) + [{
         agentId: $agentId,
         timestamp: datetime(),
         note: $note
       }],
       t.updatedAt = datetime()
       RETURN t`,
      { taskId, agentId: this.agentId, note }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found`);
    }

    console.log(`[IntentionGraph] Note added to task ${taskId}`);
    return result[0].t.properties || result[0].t;
  }

  /**
   * Hand off a Task to another Agent
   * @param {string} taskId
   * @param {string} targetAgentId - Agent to hand off to
   * @param {string} message - Handoff message with context
   * @returns {Object} Updated task
   */
  async handoffTask(taskId, targetAgentId, message) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId, assignedTo: $sourceAgentId})
       MATCH (source:Agent {id: $sourceAgentId})
       MATCH (target:Agent {id: $targetAgentId})
       SET t.status = 'pending',
           t.assignedTo = null,
           t.assignedAt = null,
           t.updatedAt = datetime(),
           t.notes = COALESCE(t.notes, []) + [{
             agentId: $sourceAgentId,
             timestamp: datetime(),
             note: "HANDOFF to " + $targetAgentId + ": " + $message
           }]
       WITH t, source, target
       MATCH (source)-[r:WORKS_ON]->(t)
       DELETE r
       RETURN t`,
      {
        taskId,
        sourceAgentId: this.agentId,
        targetAgentId,
        message
      }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found or not assigned to ${this.agentId}`);
    }

    console.log(`[IntentionGraph] Task ${taskId} handed off: ${this.agentId} → ${targetAgentId}`);
    return result[0].t.properties || result[0].t;
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
   * @returns {Object} Agent status and active tasks
   */
  async getAgentWorkload() {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const result = await this.client.read(
      `MATCH (a:Agent {id: $agentId})
       OPTIONAL MATCH (a)-[:WORKS_ON]->(t:Task)
       WHERE t.status IN ['in_progress', 'blocked']
       RETURN a, collect(t) as activeTasks`,
      { agentId: this.agentId }
    );

    if (!result || result.length === 0) {
      return null;
    }

    return {
      agent: result[0].a.properties || result[0].a,
      activeTasks: (result[0].activeTasks || []).map(t => t.properties || t)
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