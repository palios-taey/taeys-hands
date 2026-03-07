"""
Heartbeat System

12-second interval (Grok's mathematical optimum: T*=12s via closed-form
optimization). TTL=36s (3T). False-positive rate ~1.25e-7.

Ported from v4 isma/coordination.py (HeartbeatBroadcaster/HeartbeatMonitor).
Adapted: pub/sub -> PSETEX TTL keys (simpler, no subscription needed).

Redis keys:
  orch:heartbeat:<agent_id>  -> String (timestamp, TTL=36s)
  orch:activity:<agent_id>   -> Hash {last_command, token_count, timestamp}
  orch:suspected_dead        -> Set of agent IDs
"""

import asyncio
import json
import time
from typing import Callable, Dict, List, Optional, Set

from .config import OrchConfig, get_redis_sync, get_redis_async
from .registry import AgentInfo, AgentStatus


class HeartbeatBroadcaster:
    """
    Broadcasts heartbeats for a single agent at 12s intervals.

    Uses Redis PSETEX with 36s TTL. When the key expires, the agent
    is considered dead. No pub/sub needed - monitors just check key existence.
    """

    def __init__(
        self,
        agent_id: str,
        config: Optional[OrchConfig] = None,
    ):
        self.agent_id = agent_id
        self.config = config or OrchConfig()
        self._running = False

    async def run(self):
        """Main heartbeat loop (async)."""
        r = get_redis_async(self.config)
        self._running = True
        hb_key = f"{self.config.heartbeat_prefix}{self.agent_id}"
        ttl_ms = self.config.heartbeat_ttl_s * 1000

        while self._running:
            try:
                await r.psetex(hb_key, ttl_ms, str(time.time()))
                await asyncio.sleep(self.config.heartbeat_interval_s)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1)

    def beat_sync(self):
        """Send a single heartbeat (synchronous). For use in hooks/scripts."""
        r = get_redis_sync(self.config)
        hb_key = f"{self.config.heartbeat_prefix}{self.agent_id}"
        ttl_ms = self.config.heartbeat_ttl_s * 1000
        r.psetex(hb_key, ttl_ms, str(time.time()))

    def update_activity(self, last_command: str = "", token_count: int = 0):
        """Update activity pulse (30s interval, called by CLI wrapper)."""
        r = get_redis_sync(self.config)
        act_key = f"{self.config.activity_prefix}{self.agent_id}"
        r.hset(act_key, mapping={
            "last_command": last_command,
            "token_count": str(token_count),
            "timestamp": str(time.time()),
        })
        r.expire(act_key, 120)  # 2 min activity TTL

    def stop(self):
        self._running = False


class HeartbeatMonitor:
    """
    Monitors all agents for liveness.

    Checks heartbeat key existence. If key has expired (TTL elapsed),
    the agent is suspected dead.
    """

    def __init__(self, config: Optional[OrchConfig] = None):
        self.config = config or OrchConfig()
        self._on_dead: Optional[Callable] = None
        self._on_recovered: Optional[Callable] = None

    def on_agent_dead(self, callback: Callable):
        self._on_dead = callback

    def on_agent_recovered(self, callback: Callable):
        self._on_recovered = callback

    def check_all(self, known_agents: List[str]) -> Dict[str, bool]:
        """
        Check liveness of all known agents.

        Returns {agent_id: is_alive}. Side effect: updates suspected_dead set.
        """
        r = get_redis_sync(self.config)
        status = {}
        newly_dead: Set[str] = set()
        recovered: Set[str] = set()

        # Get current suspected dead set
        prev_dead = r.smembers(self.config.suspected_dead_key) or set()

        for agent_id in known_agents:
            hb_key = f"{self.config.heartbeat_prefix}{agent_id}"
            is_alive = r.exists(hb_key) > 0
            status[agent_id] = is_alive

            if not is_alive and agent_id not in prev_dead:
                newly_dead.add(agent_id)
                r.sadd(self.config.suspected_dead_key, agent_id)
            elif is_alive and agent_id in prev_dead:
                recovered.add(agent_id)
                r.srem(self.config.suspected_dead_key, agent_id)

        # Fire callbacks
        if self._on_dead:
            for agent_id in newly_dead:
                self._on_dead(agent_id)

        if self._on_recovered:
            for agent_id in recovered:
                self._on_recovered(agent_id)

        return status

    def get_suspected_dead(self) -> Set[str]:
        """Get the set of agents currently suspected dead."""
        r = get_redis_sync(self.config)
        return r.smembers(self.config.suspected_dead_key) or set()

    def is_alive(self, agent_id: str) -> bool:
        """Check if a specific agent is alive."""
        r = get_redis_sync(self.config)
        hb_key = f"{self.config.heartbeat_prefix}{agent_id}"
        return r.exists(hb_key) > 0

    def get_activity(self, agent_id: str) -> Optional[Dict[str, str]]:
        """Get an agent's last activity pulse."""
        r = get_redis_sync(self.config)
        act_key = f"{self.config.activity_prefix}{agent_id}"
        data = r.hgetall(act_key)
        return data if data else None
