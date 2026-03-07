#!/usr/bin/env python3
"""
Hook Configuration - Environment variable driven.

All hooks import from here for Redis connections and node identity.
No hardcoded IPs — reads from environment with localhost defaults.

Usage in hooks:
    from config import get_config, get_redis, node_key
"""
import os
import socket


def get_config() -> dict:
    """Get configuration from environment variables."""
    return {
        'redis_host': os.environ.get('REDIS_HOST', '127.0.0.1'),
        'redis_port': int(os.environ.get('REDIS_PORT', '6379')),
        'neo4j_uri': os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
        'agent_id': detect_node_id(),
    }


def get_redis():
    """Get configured Redis connection."""
    try:
        import redis
        cfg = get_config()
        return redis.Redis(
            host=cfg['redis_host'],
            port=cfg['redis_port'],
            decode_responses=True,
            socket_timeout=2,
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
