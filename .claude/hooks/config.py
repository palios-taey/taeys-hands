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


def _load_project_env():
    """Load .env from project root (same as server.py).

    Hooks inherit Claude Code's env, NOT the MCP server's env.
    MCP server gets REDIS_HOST etc from .mcp.json, but hooks don't see that.
    Loading .env ensures hooks and server use the same config.
    """
    # Walk up from .claude/hooks/ to project root
    hooks_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(hooks_dir))
    env_path = os.path.join(project_root, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    # Don't override explicitly set env vars
                    if key.strip() not in os.environ:
                        os.environ[key.strip()] = val.strip()


# Load .env on import (before any get_config calls)
_load_project_env()


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


def _find_ancestor_tty() -> str:
    """Walk up the process tree to find the nearest ancestor with a real TTY.

    Hooks are spawned as: tmux pane (pts/N) -> claude (pts/N) -> sh (/dev/null) -> python
    The immediate parent's fd/0 is /dev/null, but the grandparent (claude) has
    the real TTY. Walk up until we find one.
    """
    pid = os.getpid()
    for _ in range(10):
        try:
            with open(f'/proc/{pid}/stat') as f:
                stat = f.read()
            # Parse ppid after closing ')' — comm field can contain spaces
            # e.g. "299556 (tmux: server) S 1 ..." → split after ')'
            after_comm = stat[stat.rfind(')') + 2:]
            pid = int(after_comm.split()[1])  # state=0, ppid=1
            if pid <= 1:
                break
            fd0 = os.readlink(f'/proc/{pid}/fd/0')
            if fd0.startswith('/dev/pts/') or fd0.startswith('/dev/tty'):
                return fd0
        except Exception:
            break
    return ''


def detect_node_id() -> str:
    """Auto-detect instance ID: TAEY_NODE_ID > ancestor TTY tmux session > hostname.

    Walks up the process tree to find the nearest ancestor with a real TTY,
    then maps that TTY to a tmux session via list-panes. This works for both
    MCP subprocesses AND hook subprocesses (whose immediate parent has
    /dev/null as stdin).
    """
    explicit = os.environ.get('TAEY_NODE_ID')
    if explicit:
        return explicit
    import subprocess
    try:
        ancestor_tty = _find_ancestor_tty()
        if ancestor_tty:
            result = subprocess.run(
                ['tmux', 'list-panes', '-a', '-F', '#{pane_tty} #{session_name}'],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    parts = line.split(' ', 1)
                    if len(parts) == 2 and parts[0] == ancestor_tty:
                        return parts[1]
    except Exception:
        pass
    # Fallback: display-message (non-deterministic, last resort)
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
