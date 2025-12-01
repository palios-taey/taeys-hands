/**
 * Neo4j Client - Database Connection Management
 * 
 * Provides:
 * - Connection pooling
 * - Automatic reconnection
 * - Health checks
 * - Query helpers
 */

import neo4j, { Driver, Session as Neo4jSession, Transaction } from 'neo4j-driver';

// ============================================================================
// Configuration
// ============================================================================

export interface Neo4jConfig {
  uri: string;
  database?: string;
  maxConnectionPoolSize?: number;
  connectionAcquisitionTimeout?: number;
}

/**
 * NO AUTHENTICATION: All internal infrastructure is trusted (local network).
 * Auth is disabled by default. This is intentional security architecture.
 */
const DEFAULT_CONFIG: Partial<Neo4jConfig> = {
  uri: process.env.NEO4J_URI || 'bolt://localhost:7687',
  database: process.env.NEO4J_DATABASE || 'neo4j',
  maxConnectionPoolSize: 50,
  connectionAcquisitionTimeout: 30000,
};

// ============================================================================
// Neo4j Client Class
// ============================================================================

export class Neo4jClient {
  private driver: Driver | null = null;
  private readonly config: Neo4jConfig;
  private isConnected = false;
  
  constructor(config: Partial<Neo4jConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config } as Neo4jConfig;
  }
  
  /**
   * Initialize connection to Neo4j
   */
  async connect(): Promise<void> {
    if (this.isConnected && this.driver) {
      return;
    }

    try {
      // NO AUTHENTICATION: Internal infrastructure is trusted
      this.driver = neo4j.driver(
        this.config.uri,
        neo4j.auth.none(),
        {
          maxConnectionPoolSize: this.config.maxConnectionPoolSize,
          connectionAcquisitionTimeout: this.config.connectionAcquisitionTimeout,
        }
      );
      
      // Verify connection
      const serverInfo = await this.driver.getServerInfo();
      console.log(`[Neo4j] Connected to ${serverInfo.address} (${serverInfo.agent})`);
      this.isConnected = true;
    } catch (error) {
      console.error('[Neo4j] Connection failed:', error);
      throw error;
    }
  }
  
  /**
   * Close connection
   */
  async close(): Promise<void> {
    if (this.driver) {
      await this.driver.close();
      this.driver = null;
      this.isConnected = false;
      console.log('[Neo4j] Connection closed');
    }
  }
  
  /**
   * Health check
   */
  async healthCheck(): Promise<boolean> {
    if (!this.driver) return false;
    
    try {
      await this.driver.getServerInfo();
      return true;
    } catch {
      this.isConnected = false;
      return false;
    }
  }
  
  /**
   * Get a session for queries
   */
  getSession(): Neo4jSession {
    if (!this.driver) {
      throw new Error('Neo4j client not connected. Call connect() first.');
    }
    
    return this.driver.session({
      database: this.config.database,
    });
  }
  
  /**
   * Run a single query
   */
  async run<T = Record<string, unknown>>(
    query: string,
    params: Record<string, unknown> = {}
  ): Promise<T[]> {
    const session = this.getSession();
    
    try {
      const result = await session.run(query, params);
      return result.records.map(record => {
        const obj: Record<string, unknown> = {};
        record.keys.forEach(key => {
          obj[key] = this.convertValue(record.get(key));
        });
        return obj as T;
      });
    } finally {
      await session.close();
    }
  }
  
  /**
   * Run a single query and return first result
   */
  async runSingle<T = Record<string, unknown>>(
    query: string,
    params: Record<string, unknown> = {}
  ): Promise<T | null> {
    const results = await this.run<T>(query, params);
    return results[0] || null;
  }
  
  /**
   * Run multiple queries in a transaction
   */
  async runInTransaction<T>(
    callback: (tx: Transaction) => Promise<T>
  ): Promise<T> {
    const session = this.getSession();
    
    try {
      return await session.executeWrite(callback);
    } finally {
      await session.close();
    }
  }
  
  /**
   * Convert Neo4j values to JavaScript types
   */
  private convertValue(value: unknown): unknown {
    if (value === null || value === undefined) {
      return value;
    }
    
    // Handle Neo4j Integer
    if (neo4j.isInt(value)) {
      return (value as neo4j.Integer).toNumber();
    }
    
    // Handle Neo4j DateTime
    if (value instanceof neo4j.types.DateTime) {
      return new Date(value.toString());
    }
    
    // Handle Neo4j Date
    if (value instanceof neo4j.types.Date) {
      return new Date(value.toString());
    }
    
    // Handle Neo4j Node
    if (value && typeof value === 'object' && 'properties' in value) {
      const node = value as { properties: Record<string, unknown> };
      const props: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(node.properties)) {
        props[k] = this.convertValue(v);
      }
      return props;
    }
    
    // Handle arrays
    if (Array.isArray(value)) {
      return value.map(v => this.convertValue(v));
    }
    
    // Handle plain objects
    if (typeof value === 'object') {
      const obj: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
        obj[k] = this.convertValue(v);
      }
      return obj;
    }
    
    return value;
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let clientInstance: Neo4jClient | null = null;

export function getNeo4jClient(config?: Partial<Neo4jConfig>): Neo4jClient {
  if (!clientInstance) {
    clientInstance = new Neo4jClient(config);
  }
  return clientInstance;
}

export async function closeNeo4jClient(): Promise<void> {
  if (clientInstance) {
    await clientInstance.close();
    clientInstance = null;
  }
}
