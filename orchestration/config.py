"""
Orchestration Configuration

Orch-specific Redis/Neo4j connections with strict namespace isolation.
All Redis keys are prefixed with 'orch:'. Neo4j uses 'orchestration' database.

ISOLATION: Zero shared state with memory infrastructure (ISMA, HMM, Weaviate).
"""

import os
from dataclasses import dataclass, field
from typing import Optional

import redis
import redis.asyncio as aioredis

# Environment overrides
ORCH_REDIS_HOST = os.environ.get("ORCH_REDIS_HOST", "192.168.100.10")
ORCH_REDIS_PORT = int(os.environ.get("ORCH_REDIS_PORT", "6379"))
ORCH_NEO4J_URI = os.environ.get("ORCH_NEO4J_URI", "bolt://192.168.100.10:7687")
# Community Edition: single DB, label-based isolation (Orch* prefix on all nodes)
ORCH_NEO4J_DB = os.environ.get("ORCH_NEO4J_DB", "neo4j")

# Redis key prefix - ALL orchestration keys MUST use this
KEY_PREFIX = "orch:"


@dataclass
class OrchConfig:
    """Orchestration layer configuration."""
    redis_host: str = ORCH_REDIS_HOST
    redis_port: int = ORCH_REDIS_PORT
    neo4j_uri: str = ORCH_NEO4J_URI
    neo4j_db: str = ORCH_NEO4J_DB

    # Heartbeat (Grok's mathematical optimum: T=12s, TTL=3T=36s)
    heartbeat_interval_s: float = 12.0
    heartbeat_ttl_s: int = 36

    # Task queue
    task_stream: str = f"{KEY_PREFIX}streams:tasks"
    event_stream: str = f"{KEY_PREFIX}streams:events"
    consumer_group: str = "orchestrators"
    stream_maxlen: int = 100_000

    # File locks
    file_lock_ttl_s: int = 1800  # 30 minutes
    file_lock_prefix: str = f"{KEY_PREFIX}lock:file:"

    # Agent registry
    agent_prefix: str = f"{KEY_PREFIX}agent:"
    heartbeat_prefix: str = f"{KEY_PREFIX}heartbeat:"
    activity_prefix: str = f"{KEY_PREFIX}activity:"

    # Notifications
    notify_prefix: str = f"{KEY_PREFIX}notify:"
    alert_channel: str = f"{KEY_PREFIX}notify:alerts"

    # Suspected dead agents set
    suspected_dead_key: str = f"{KEY_PREFIX}suspected_dead"


def key(suffix: str) -> str:
    """Generate a namespaced Redis key. All orch keys go through here."""
    return f"{KEY_PREFIX}{suffix}"


# --- Redis connection pool (singleton) ---

_sync_pool: Optional[redis.ConnectionPool] = None
_async_pool: Optional[aioredis.ConnectionPool] = None


def get_redis_sync(config: Optional[OrchConfig] = None) -> redis.Redis:
    """Get synchronous Redis client with orch connection pool."""
    global _sync_pool
    cfg = config or OrchConfig()

    if _sync_pool is None:
        _sync_pool = redis.ConnectionPool(
            host=cfg.redis_host,
            port=cfg.redis_port,
            decode_responses=True,
            max_connections=20,
        )

    return redis.Redis(connection_pool=_sync_pool)


def get_redis_async(config: Optional[OrchConfig] = None) -> aioredis.Redis:
    """Get async Redis client with orch connection pool."""
    global _async_pool
    cfg = config or OrchConfig()

    if _async_pool is None:
        _async_pool = aioredis.ConnectionPool(
            host=cfg.redis_host,
            port=cfg.redis_port,
            decode_responses=True,
            max_connections=20,
        )

    return aioredis.Redis(connection_pool=_async_pool)


def get_neo4j_driver(config: Optional[OrchConfig] = None):
    """Get Neo4j driver for the orchestration database."""
    from neo4j import GraphDatabase

    cfg = config or OrchConfig()
    return GraphDatabase.driver(cfg.neo4j_uri, auth=None)


def get_neo4j_session(config: Optional[OrchConfig] = None):
    """Get a Neo4j session targeting the orchestration database."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    return driver.session(database=cfg.neo4j_db)
