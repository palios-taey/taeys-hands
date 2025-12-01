/**
 * Neo4j Database Client
 * 
 * Purpose: Connection pooling and query execution for Neo4j
 * Dependencies: neo4j-driver
 * Exports: Neo4jClient class, getNeo4jClient singleton
 * 
 * @module core/database/neo4j-client
 */

import neo4j from 'neo4j-driver';

/**
 * Singleton Neo4j client instance
 * @type {Neo4jClient|null}
 */
let clientInstance = null;

/**
 * Neo4j database client with connection pooling
 */
export class Neo4jClient {
  /**
   * @param {Object} options
   * @param {string} [options.uri] - Neo4j connection URI (default: bolt://localhost:7687)
   * @param {string} [options.database] - Database name (default: neo4j)
   *
   * NO AUTHENTICATION: All internal infrastructure is trusted (local network).
   * Auth is disabled by default. This is intentional security architecture.
   */
  constructor(options = {}) {
    this.uri = options.uri || process.env.NEO4J_URI || 'bolt://localhost:7687';
    this.database = options.database || process.env.NEO4J_DATABASE || 'neo4j';

    this.driver = null;
    this.connected = false;
  }

  /**
   * Connect to Neo4j
   * 
   * @returns {Promise<void>}
   * @throws {Error} If connection fails
   */
  async connect() {
    if (this.connected) return;

    try {
      // NO AUTHENTICATION: Internal infrastructure is trusted
      this.driver = neo4j.driver(
        this.uri,
        neo4j.auth.none(),
        {
          maxConnectionPoolSize: 50,
          connectionAcquisitionTimeout: 30000,
          maxTransactionRetryTime: 30000
        }
      );

      // Verify connection
      await this.driver.verifyConnectivity();
      this.connected = true;

      console.log(`[Neo4jClient] Connected to ${this.uri} (no auth - internal infrastructure)`);
    } catch (error) {
      // FAIL LOUD: Neo4j connection is critical infrastructure
      throw new Error(
        `CRITICAL: Neo4j connection failed to ${this.uri}\n` +
        `Error: ${error.message}\n` +
        `Neo4j must be persistent and always available.`
      );
    }
  }

  /**
   * Close the connection
   * 
   * @returns {Promise<void>}
   */
  async close() {
    if (this.driver) {
      await this.driver.close();
      this.connected = false;
      console.log('[Neo4jClient] Connection closed');
    }
  }

  /**
   * Get a session for queries
   * 
   * @returns {Session}
   */
  getSession() {
    if (!this.connected) {
      throw new Error('Neo4j client not connected. Call connect() first.');
    }
    return this.driver.session({ database: this.database });
  }

  /**
   * Execute a read query
   * 
   * @param {string} cypher - Cypher query
   * @param {Object} [params={}] - Query parameters
   * @returns {Promise<Record[]>} Query results as array of records
   */
  async read(cypher, params = {}) {
    const session = this.getSession();
    try {
      const result = await session.executeRead(tx => tx.run(cypher, params));
      return result.records.map(record => this.recordToObject(record));
    } finally {
      await session.close();
    }
  }

  /**
   * Execute a write query
   * 
   * @param {string} cypher - Cypher query
   * @param {Object} [params={}] - Query parameters
   * @returns {Promise<Record[]>} Query results as array of records
   */
  async write(cypher, params = {}) {
    const session = this.getSession();
    try {
      const result = await session.executeWrite(tx => tx.run(cypher, params));
      return result.records.map(record => this.recordToObject(record));
    } finally {
      await session.close();
    }
  }

  /**
   * Execute a raw query (for schema operations)
   * 
   * @param {string} cypher - Cypher query
   * @param {Object} [params={}] - Query parameters
   * @returns {Promise<Record[]>}
   */
  async run(cypher, params = {}) {
    const session = this.getSession();
    try {
      const result = await session.run(cypher, params);
      return result.records.map(record => this.recordToObject(record));
    } finally {
      await session.close();
    }
  }

  /**
   * Convert a Neo4j record to a plain JavaScript object
   * 
   * @param {Record} record - Neo4j record
   * @returns {Object}
   */
  recordToObject(record) {
    const obj = {};
    record.keys.forEach(key => {
      const value = record.get(key);
      obj[key] = this.convertValue(value);
    });
    return obj;
  }

  /**
   * Convert Neo4j types to JavaScript types
   * 
   * @param {any} value - Neo4j value
   * @returns {any} JavaScript value
   */
  convertValue(value) {
    if (value === null || value === undefined) {
      return null;
    }
    
    // Neo4j Integer
    if (neo4j.isInt(value)) {
      return value.toNumber();
    }
    
    // Neo4j Node
    if (value.constructor && value.constructor.name === 'Node') {
      return { ...value.properties, _id: value.identity.toNumber() };
    }
    
    // Neo4j Relationship
    if (value.constructor && value.constructor.name === 'Relationship') {
      return {
        ...value.properties,
        _id: value.identity.toNumber(),
        _type: value.type,
        _start: value.start.toNumber(),
        _end: value.end.toNumber()
      };
    }
    
    // Neo4j DateTime
    if (value.constructor && value.constructor.name === 'DateTime') {
      return new Date(value.toString()).toISOString();
    }
    
    // Array
    if (Array.isArray(value)) {
      return value.map(v => this.convertValue(v));
    }
    
    // Object (recursively convert)
    if (typeof value === 'object') {
      const obj = {};
      for (const key of Object.keys(value)) {
        obj[key] = this.convertValue(value[key]);
      }
      return obj;
    }
    
    return value;
  }

  /**
   * Check if database is healthy
   * 
   * @returns {Promise<{healthy: boolean, latency: number}>}
   */
  async healthCheck() {
    const start = Date.now();
    try {
      await this.read('RETURN 1');
      return {
        healthy: true,
        latency: Date.now() - start
      };
    } catch (error) {
      return {
        healthy: false,
        latency: Date.now() - start,
        error: error.message
      };
    }
  }
}

/**
 * Get the singleton Neo4j client instance
 * 
 * @param {Object} [options] - Connection options (only used on first call)
 * @returns {Neo4jClient}
 */
export function getNeo4jClient(options) {
  if (!clientInstance) {
    clientInstance = new Neo4jClient(options);
  }
  return clientInstance;
}

/**
 * Close the singleton client
 * 
 * @returns {Promise<void>}
 */
export async function closeNeo4jClient() {
  if (clientInstance) {
    await clientInstance.close();
    clientInstance = null;
  }
}
