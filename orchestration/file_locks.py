"""
File Locking

Redis SETNX-based file/service locks to prevent parallel agents from
editing the same files simultaneously.

Gemini's insight: Use Redis for kinematic state (locks are ephemeral,
high-frequency). Neo4j is too slow for this.

Redis keys:
  orch:lock:file:<path>  -> String (agent_id, TTL=1800s)
"""

from typing import Dict, List, Optional

from .config import OrchConfig, get_redis_sync


# Lua: renew lock only if we still own it
RENEW_LOCK_LUA = """
local lock_key = KEYS[1]
local agent_id = ARGV[1]
local ttl = tonumber(ARGV[2])

local current = redis.call('GET', lock_key)
if current == agent_id then
    redis.call('EXPIRE', lock_key, ttl)
    return 1
end
return 0
"""

# Lua: release lock only if we own it
RELEASE_LOCK_LUA = """
local lock_key = KEYS[1]
local agent_id = ARGV[1]

local current = redis.call('GET', lock_key)
if current == agent_id then
    redis.call('DEL', lock_key)
    return 1
end
return 0
"""


class FileLockManager:
    """Manages file-level locks for parallel agent coordination."""

    def __init__(self, config: Optional[OrchConfig] = None):
        self.config = config or OrchConfig()
        self._redis = get_redis_sync(self.config)
        self._renew_script = self._redis.register_script(RENEW_LOCK_LUA)
        self._release_script = self._redis.register_script(RELEASE_LOCK_LUA)

    def acquire(self, file_path: str, agent_id: str,
                ttl: Optional[int] = None) -> bool:
        """
        Acquire a file lock atomically. Returns True if acquired.

        Only one agent can hold a lock on a given file path at a time.
        Lock expires after TTL seconds (default 1800 = 30 min).
        """
        lock_ttl = ttl or self.config.file_lock_ttl_s
        lock_key = f"{self.config.file_lock_prefix}{file_path}"
        return bool(self._redis.set(lock_key, agent_id, ex=lock_ttl, nx=True))

    def renew(self, file_path: str, agent_id: str,
              ttl: Optional[int] = None) -> bool:
        """Renew a lock only if we still own it."""
        lock_ttl = ttl or self.config.file_lock_ttl_s
        lock_key = f"{self.config.file_lock_prefix}{file_path}"
        return bool(self._renew_script(
            keys=[lock_key],
            args=[agent_id, lock_ttl],
        ))

    def release(self, file_path: str, agent_id: str) -> bool:
        """Release a lock only if we own it."""
        lock_key = f"{self.config.file_lock_prefix}{file_path}"
        return bool(self._release_script(
            keys=[lock_key],
            args=[agent_id],
        ))

    def owner(self, file_path: str) -> Optional[str]:
        """Check who holds a file lock."""
        lock_key = f"{self.config.file_lock_prefix}{file_path}"
        return self._redis.get(lock_key)

    def is_locked(self, file_path: str) -> bool:
        """Check if a file is locked."""
        lock_key = f"{self.config.file_lock_prefix}{file_path}"
        return self._redis.exists(lock_key) > 0

    def acquire_batch(self, file_paths: List[str], agent_id: str,
                      ttl: Optional[int] = None) -> Dict[str, bool]:
        """
        Try to acquire locks for multiple files.

        Returns dict of {path: acquired}. If any fail, already-acquired
        locks are NOT automatically released (caller decides).
        """
        results = {}
        for path in file_paths:
            results[path] = self.acquire(path, agent_id, ttl)
        return results

    def release_all(self, agent_id: str) -> int:
        """Release all locks held by an agent. Returns count released."""
        released = 0
        for k in self._redis.scan_iter(f"{self.config.file_lock_prefix}*"):
            owner = self._redis.get(k)
            if owner == agent_id:
                self._redis.delete(k)
                released += 1
        return released

    def get_all_locks(self) -> Dict[str, str]:
        """Get all active file locks. Returns {path: agent_id}."""
        locks = {}
        prefix_len = len(self.config.file_lock_prefix)
        for k in self._redis.scan_iter(f"{self.config.file_lock_prefix}*"):
            file_path = k[prefix_len:]
            owner = self._redis.get(k)
            if owner:
                locks[file_path] = owner
        return locks
