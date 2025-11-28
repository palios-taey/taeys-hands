/**
 * Intention Graph - Multi-Claude Coordination via Neo4j
 *
 * Simplified model for 2-5 Claudes with machine-specific work:
 * - Simple task assignment (not competitive leasing)
 * - Status tracking (pending, in_progress, blocked, done)
 * - Context sharing via notes
 * - Heartbeats for visibility (not lease renewal)
 *
 * Based on Gemini's 4-layer topology, grounded in our actual reality.
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
      }
    }

    console.log('[IntentionGraph] Schema initialized');
  }

  /**
   * Register this Claude instance as an Agent
   */
  async registerAgent(identity = {}) {
    const hostname = os.hostname();
    const platform = os.platform();

    // Use stable agent ID based on machine, not timestamp
    this.agentId = identity.agentId || `${hostname}-claude`;

    const agent = {
      id: this.agentId,
      name: identity.name || `${hostname}-claude`,
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
   * Send heartbeat - just visibility, no lease mechanics
   */
  async heartbeat(currentActivity = null) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const now = new Date().toISOString();

    await this.client.write(
      `MATCH (a:Agent {id: $agentId})
       SET a.lastHeartbeat = $now,
           a.status = 'active',
           a.currentActivity = $currentActivity
       RETURN a`,
      { agentId: this.agentId, now, currentActivity }
    );

    return { agentId: this.agentId, lastHeartbeat: now, currentActivity };
  }

  /**
   * Create a new Project
   */
  async createProject(projectData) {
    const project = {
      id: projectData.id || uuidv4(),
      title: projectData.title,
      description: projectData.description,
      type: projectData.type || 'development',
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
   * Create a new Task - with optional direct assignment
   */
  async createTask(taskData) {
    const task = {
      id: taskData.id || uuidv4(),
      projectId: taskData.projectId,
      title: taskData.title,
      description: taskData.description,
      type: taskData.type || 'implementation',
      status: taskData.assignedTo ? 'in_progress' : 'pending',
      assignedTo: taskData.assignedTo || null,
      priority: taskData.priority || 1,
      created: new Date().toISOString(),
      lastUpdate: new Date().toISOString(),
      notes: taskData.notes || null,
      metadata: JSON.stringify(taskData.metadata || {})
    };

    await this.client.write(
      `MATCH (p:Project {id: $projectId})
       CREATE (t:Task)
       SET t = $task
       CREATE (t)-[:PART_OF]->(p)
       WITH t
       FOREACH (_ IN CASE WHEN $assignedTo IS NOT NULL THEN [1] ELSE [] END |
         MERGE (a:Agent {id: $assignedTo})
         MERGE (a)-[:WORKS_ON]->(t)
       )
       RETURN t`,
      { projectId: task.projectId, task, assignedTo: task.assignedTo }
    );

    console.log(`[IntentionGraph] Task created: ${task.title}${task.assignedTo ? ` (assigned to ${task.assignedTo})` : ''}`);
    return task;
  }

  /**
   * Assign a task to an agent (simple ownership, not leasing)
   */
  async assignTask(taskId, agentId = null) {
    const assignTo = agentId || this.agentId;
    if (!assignTo) {
      throw new Error('No agent ID provided and no agent registered.');
    }

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId})
       MATCH (a:Agent {id: $agentId})
       SET t.assignedTo = $agentId,
           t.status = 'in_progress',
           t.assignedAt = datetime(),
           t.lastUpdate = datetime()
       MERGE (a)-[:WORKS_ON]->(t)
       RETURN t`,
      { taskId, agentId: assignTo }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found`);
    }

    const task = result[0].t.properties || result[0].t;
    console.log(`[IntentionGraph] Task assigned: ${task.title} → ${assignTo}`);
    return task;
  }

  /**
   * Update task status
   */
  async updateTaskStatus(taskId, status, notes = null) {
    const validStatuses = ['pending', 'in_progress', 'blocked', 'done'];
    if (!validStatuses.includes(status)) {
      throw new Error(`Invalid status: ${status}. Must be one of: ${validStatuses.join(', ')}`);
    }

    const updates = {
      status,
      lastUpdate: new Date().toISOString()
    };

    if (notes) {
      updates.notes = notes;
    }

    if (status === 'done') {
      updates.completedAt = new Date().toISOString();
    }

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId})
       SET t += $updates
       RETURN t`,
      { taskId, updates }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found`);
    }

    const task = result[0].t.properties || result[0].t;
    console.log(`[IntentionGraph] Task ${taskId}: ${status}${notes ? ` - "${notes}"` : ''}`);
    return task;
  }

  /**
   * Add a note to a task (for context sharing)
   */
  async addTaskNote(taskId, note) {
    const timestamp = new Date().toISOString();
    const noteEntry = `[${timestamp}] ${this.agentId || 'unknown'}: ${note}`;

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId})
       SET t.notes = CASE
           WHEN t.notes IS NULL THEN $noteEntry
           ELSE t.notes + '\\n' + $noteEntry
         END,
         t.lastUpdate = datetime()
       RETURN t`,
      { taskId, noteEntry }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found`);
    }

    console.log(`[IntentionGraph] Note added to ${taskId}`);
    return result[0].t.properties || result[0].t;
  }

  /**
   * Hand off a task to another agent
   */
  async handoffTask(taskId, toAgentId, handoffNotes = '') {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const timestamp = new Date().toISOString();
    const note = `[${timestamp}] HANDOFF from ${this.agentId} to ${toAgentId}: ${handoffNotes}`;

    const result = await this.client.write(
      `MATCH (t:Task {id: $taskId})
       MATCH (fromAgent:Agent {id: $fromAgentId})
       MATCH (toAgent:Agent {id: $toAgentId})

       // Remove old assignment
       OPTIONAL MATCH (fromAgent)-[r:WORKS_ON]->(t)
       DELETE r

       // Create new assignment
       MERGE (toAgent)-[:WORKS_ON]->(t)

       SET t.assignedTo = $toAgentId,
           t.lastUpdate = datetime(),
           t.notes = CASE
             WHEN t.notes IS NULL THEN $note
             ELSE t.notes + '\\n' + $note
           END
       RETURN t`,
      { taskId, fromAgentId: this.agentId, toAgentId, note }
    );

    if (!result || result.length === 0) {
      throw new Error(`Task ${taskId} not found or agents not found`);
    }

    console.log(`[IntentionGraph] Task ${taskId} handed off: ${this.agentId} → ${toAgentId}`);
    return result[0].t.properties || result[0].t;
  }

  /**
   * Link a Session to a Task
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
   * Record an Insight
   */
  async recordInsight(insightData) {
    const insight = {
      id: insightData.id || uuidv4(),
      title: insightData.title,
      content: insightData.content,
      type: insightData.type || 'emergent',
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
   * Get tasks for an agent
   */
  async getMyTasks(status = null) {
    if (!this.agentId) {
      throw new Error('Agent not registered. Call registerAgent() first.');
    }

    const query = status
      ? `MATCH (t:Task {assignedTo: $agentId, status: $status}) RETURN t ORDER BY t.priority DESC`
      : `MATCH (t:Task {assignedTo: $agentId}) WHERE t.status <> 'done' RETURN t ORDER BY t.priority DESC`;

    const result = await this.client.read(query, { agentId: this.agentId, status });
    return result ? result.map(r => r.t.properties || r.t) : [];
  }

  /**
   * Get all agents and their current status
   */
  async getAllAgents() {
    const result = await this.client.read(
      `MATCH (a:Agent)
       OPTIONAL MATCH (a)-[:WORKS_ON]->(t:Task)
       WHERE t.status = 'in_progress'
       RETURN a, collect(t.title) as currentTasks
       ORDER BY a.lastHeartbeat DESC`
    );

    return result ? result.map(r => ({
      ...((r.a.properties || r.a)),
      currentTasks: r.currentTasks || []
    })) : [];
  }

  /**
   * Get unassigned tasks
   */
  async getUnassignedTasks(projectId = null) {
    const query = projectId
      ? `MATCH (t:Task {status: 'pending', assignedTo: null, projectId: $projectId}) RETURN t ORDER BY t.priority DESC`
      : `MATCH (t:Task {status: 'pending'}) WHERE t.assignedTo IS NULL RETURN t ORDER BY t.priority DESC`;

    const result = await this.client.read(query, { projectId });
    return result ? result.map(r => r.t.properties || r.t) : [];
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
