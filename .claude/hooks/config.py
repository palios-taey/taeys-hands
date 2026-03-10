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
    """Auto-detect instance ID: TAEY_NODE_ID > parent TTY tmux session > hostname.

    Uses tmux list-panes to map parent process's TTY to a session name.
    This is reliable for MCP subprocesses (unlike display-message which
    returns whichever tmux client was most recently active).
    """
    explicit = os.environ.get('TAEY_NODE_ID')
    if explicit:
        return explicit
    import subprocess
    try:
        # Map parent's TTY → tmux session name (reliable for MCP subprocesses)
        parent_tty = os.readlink(f'/proc/{os.getppid()}/fd/0')
        result = subprocess.run(
            ['tmux', 'list-panes', '-a', '-F', '#{pane_tty} #{session_name}'],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                parts = line.split(' ', 1)
                if len(parts) == 2 and parts[0] == parent_tty:
                    return parts[1]
    except Exception:
        pass
    # Fallback: display-message (works in interactive tmux shells)
    try:
        result = subprocess.run(
            ['tmux', 'display-message', '-p', '#S'],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return socket.gethostname()


_cached_node_id = None


def node_key(suffix: str) -> str:
    """Instance-scoped Redis key: taey:{node_id}:{suffix}."""
    global _cached_node_id
    if _cached_node_id is None:
        _cached_node_id = detect_node_id()
    return f"taey:{_cached_node_id}:{suffix}"
