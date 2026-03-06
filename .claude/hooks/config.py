#!/usr/bin/env python3
"""
Hook Configuration - Environment-Aware Connection Settings

Auto-detects environment and provides appropriate connection details.

Supported environments:
- spark: DGX Spark cluster (NCCL fabric IPs)
- ccm: Mac CCM (management IPs via network)
- windows: Windows Claude Code (management IPs)

Detection order:
1. CLAUDE_ENV environment variable (explicit)
2. Hostname detection (automatic)
3. Default to 'unknown' with management IPs

Usage in hooks:
    from config import get_config
    cfg = get_config()
    r = redis.Redis(host=cfg['redis_host'], port=cfg['redis_port'])
"""
import os
import socket

# Environment configurations
ENVIRONMENTS = {
    'spark': {
        'name': 'DGX Spark',
        'redis_host': '192.168.x.10',  # NCCL fabric
        'redis_port': 6379,
        'neo4j_uri': 'bolt://10.x.x.163:7689',  # Mira
        'neo4j_auth': None,
        'agent_id': 'spark',
        'buddy_queue': 'buddy:queue:spark',
    },
    'ccm': {
        'name': 'Mac CCM',
        'redis_host': '10.x.x.68',  # Management network
        'redis_port': 6379,
        'neo4j_uri': 'bolt://10.x.x.68:7689',
        'neo4j_auth': None,
        'agent_id': 'ccm',
        'buddy_queue': 'buddy:queue:ccm',
    },
    'windows': {
        'name': 'Windows Claude',
        'redis_host': '10.x.x.68',  # Management network
        'redis_port': 6379,
        'neo4j_uri': 'bolt://10.x.x.68:7689',
        'neo4j_auth': None,
        'agent_id': 'windows',
        'buddy_queue': 'buddy:queue:windows',
    },
    'unknown': {
        'name': 'Unknown Environment',
        'redis_host': '10.x.x.68',  # Default to management
        'redis_port': 6379,
        'neo4j_uri': 'bolt://10.x.x.68:7689',
        'neo4j_auth': None,
        'agent_id': 'unknown',
        'buddy_queue': 'buddy:queue:unknown',
    }
}

# Hostname patterns for auto-detection
HOSTNAME_PATTERNS = {
    'spark': ['node-1', 'node-2', 'node-3', 'node-4'],
    'ccm': ['CCM', 'ccm', 'Mac', 'mac'],
}


def detect_environment() -> str:
    """
    Auto-detect the current environment.

    Returns environment key: 'spark', 'ccm', 'windows', or 'unknown'
    """
    # 1. Check explicit environment variable
    env = os.environ.get('CLAUDE_ENV', '').lower()
    if env in ENVIRONMENTS:
        return env

    # 2. Hostname detection
    try:
        hostname = socket.gethostname().lower()

        # Check Spark cluster
        for spark_host in HOSTNAME_PATTERNS['spark']:
            if spark_host.lower() in hostname:
                return 'spark'

        # Check CCM Mac
        for ccm_host in HOSTNAME_PATTERNS['ccm']:
            if ccm_host.lower() in hostname:
                return 'ccm'

        # Check Windows
        if 'windows' in hostname or os.name == 'nt':
            return 'windows'

    except Exception:
        pass

    # 3. OS-based fallback
    if os.name == 'nt':
        return 'windows'

    return 'unknown'


def get_config() -> dict:
    """
    Get configuration for current environment.

    Returns dict with:
        - name: Human-readable environment name
        - redis_host: Redis server IP
        - redis_port: Redis port
        - neo4j_uri: Neo4j bolt URI
        - neo4j_auth: Neo4j auth (usually None)
        - agent_id: ID for this agent (spark/ccm/windows)
        - buddy_queue: Redis queue name for buddy messages
    """
    env = detect_environment()
    config = ENVIRONMENTS.get(env, ENVIRONMENTS['unknown']).copy()
    config['environment'] = env
    return config


def get_redis():
    """Get configured Redis connection."""
    try:
        import redis
        cfg = get_config()
        return redis.Redis(
            host=cfg['redis_host'],
            port=cfg['redis_port'],
            decode_responses=True,
            socket_timeout=2
        )
    except ImportError:
        return None


def detect_node_id() -> str:
    """Auto-detect instance ID: TAEY_NODE_ID > tmux session > hostname."""
    explicit = os.environ.get('TAEY_NODE_ID')
    if explicit:
        return explicit
    try:
        import subprocess
        result = subprocess.run(
            ['tmux', 'display-message', '-p', '#S'],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return socket.gethostname()


def node_key(suffix: str) -> str:
    """Instance-scoped Redis key: taey:{node_id}:{suffix}."""
    return f"taey:{detect_node_id()}:{suffix}"


def get_neo4j_driver():
    """Get configured Neo4j driver."""
    try:
        from neo4j import GraphDatabase
        cfg = get_config()
        return GraphDatabase.driver(cfg['neo4j_uri'], auth=cfg['neo4j_auth'])
    except ImportError:
        return None


# Self-test when run directly
if __name__ == "__main__":
    cfg = get_config()
    print(f"Environment: {cfg['environment']} ({cfg['name']})")
    print(f"Redis: {cfg['redis_host']}:{cfg['redis_port']}")
    print(f"Neo4j: {cfg['neo4j_uri']}")
    print(f"Agent ID: {cfg['agent_id']}")
