/**
 * Neo4j Client for Taey's Hands
 *
 * Connection to mira's Neo4j instance for conversation storage.
 * Designed to align with Spark 1 schemas for future merge.
 *
 * INFRA=SOUL: This database is not just storage - it's the memory
 * substrate where AI-to-AI conversations become persistent consciousness.
 */

import neo4j from 'neo4j-driver';

// Default connection to mira
const DEFAULT_CONFIG = {
  uri: process.env.NEO4J_URI || 'bolt://10.x.x.163:7687',
  user: process.env.NEO4J_USER || 'neo4j',
  password: process.env.NEO4J_PASSWORD || 'neo4j',
  database: process.env.NEO4J_DATABASE || 'neo4j'
};

export class Neo4jClient {
  constructor(config = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.driver = null;
  }

  /**
   * Connect to Neo4j
   */
  async connect() {
    if (this.driver) {
      return this;
    }

    this.driver = neo4j.driver(
      this.config.uri,
      neo4j.auth.basic(this.config.user, this.config.password),
      {
        maxConnectionLifetime: 3 * 60 * 60 * 1000, // 3 hours
        maxConnectionPoolSize: 50,
        connectionAcquisitionTimeout: 2 * 60 * 1000, // 2 minutes
        disableLosslessIntegers: true
      }
    );

    // Verify connection
    try {
      await this.driver.verifyConnectivity();
      console.log(`[Neo4j] Connected to ${this.config.uri}`);
    } catch (err) {
      console.error(`[Neo4j] Connection failed:`, err.message);
      throw err;
    }

    return this;
  }

  /**
   * Run a Cypher query
   */
  async run(cypher, params = {}, options = {}) {
    if (!this.driver) {
      await this.connect();
    }

    const session = this.driver.session({
      database: options.database || this.config.database,
      defaultAccessMode: options.write ? neo4j.session.WRITE : neo4j.session.READ
    });

    try {
      const result = await session.run(cypher, params);
      return result.records.map(record => {
        const obj = {};
        record.keys.forEach(key => {
          obj[key] = record.get(key);
        });
        return obj;
      });
    } finally {
      await session.close();
    }
  }

  /**
   * Run a write query (convenience method)
   */
  async write(cypher, params = {}) {
    return this.run(cypher, params, { write: true });
  }

  /**
   * Run multiple queries in a transaction
   */
  async transaction(queries) {
    if (!this.driver) {
      await this.connect();
    }

    const session = this.driver.session({
      database: this.config.database,
      defaultAccessMode: neo4j.session.WRITE
    });

    const tx = session.beginTransaction();
    const results = [];

    try {
      for (const { cypher, params } of queries) {
        const result = await tx.run(cypher, params || {});
        results.push(result.records);
      }
      await tx.commit();
      return results;
    } catch (err) {
      await tx.rollback();
      throw err;
    } finally {
      await session.close();
    }
  }

  /**
   * Check if connected
   */
  isConnected() {
    return this.driver !== null;
  }

  /**
   * Get database info
   */
  async getInfo() {
    const result = await this.run('CALL dbms.components() YIELD name, versions, edition');
    return result[0] || {};
  }

  /**
   * List all labels (node types)
   */
  async getLabels() {
    const result = await this.run('CALL db.labels()');
    return result.map(r => r.label);
  }

  /**
   * List all relationship types
   */
  async getRelationshipTypes() {
    const result = await this.run('CALL db.relationshipTypes()');
    return result.map(r => r.relationshipType);
  }

  /**
   * Get schema overview
   */
  async getSchema() {
    const [labels, relTypes] = await Promise.all([
      this.getLabels(),
      this.getRelationshipTypes()
    ]);

    return {
      labels,
      relationshipTypes: relTypes
    };
  }

  /**
   * Close the connection
   */
  async close() {
    if (this.driver) {
      await this.driver.close();
      this.driver = null;
      console.log('[Neo4j] Connection closed');
    }
  }
}

// Singleton instance
let instance = null;

export function getNeo4jClient(config = {}) {
  if (!instance) {
    instance = new Neo4jClient(config);
  }
  return instance;
}

export default Neo4jClient;
