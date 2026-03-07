"""
Agent Registry

Manages agent registration, capability vectors, and status tracking.
Each agent registers with its capabilities so the LVP router can score task matches.

Redis keys:
  orch:agent:<agent_id>  -> Hash {name, capabilities, context_window, current_load, status, ...}
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .config import OrchConfig, get_redis_sync, key


class AgentStatus(Enum):
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    STOPPING = "stopping"
    DEAD = "dead"


@dataclass
class AgentCapabilities:
    """Capability vector for LVP scoring (Grok's optimal function)."""
    reasoning: float = 0.5     # Deep reasoning ability [0-1]
    codegen: float = 0.5       # Code generation quality [0-1]
    research: float = 0.5      # Research and citation ability [0-1]
    privacy: float = 0.5       # Data stays local [0-1]
    review: float = 0.5        # Code review ability [0-1]

    def to_vector(self) -> List[float]:
        return [self.reasoning, self.codegen, self.research, self.privacy, self.review]

    @classmethod
    def from_vector(cls, v: List[float]) -> "AgentCapabilities":
        return cls(
            reasoning=v[0] if len(v) > 0 else 0.5,
            codegen=v[1] if len(v) > 1 else 0.5,
            research=v[2] if len(v) > 2 else 0.5,
            privacy=v[3] if len(v) > 3 else 0.5,
            review=v[4] if len(v) > 4 else 0.5,
        )


class AgentRole(Enum):
    COORDINATOR = "coordinator"  # Decomposes tasks, assigns, reviews. Does NOT claim from queue.
    WORKER = "worker"            # Claims tasks from queue, executes, reports back.
    REMOTE = "remote"            # External agent (Perplexity Computer). Tasks via GitHub Issues/PRs.
    SHARED = "shared"            # Shared per-machine resource (Gemini CLI, Codex CLI). One instance, multiple consumers.


@dataclass
class AgentInfo:
    """Full agent registration record."""
    agent_id: str
    name: str
    cli_type: str              # claude, gemini, codex, perplexity, qwen
    machine: str               # spark1, spark3, remote
    role: AgentRole = AgentRole.WORKER
    worktree_path: str = ""
    tmux_session: str = ""
    context_window: int = 200_000
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    status: AgentStatus = AgentStatus.IDLE
    current_load: int = 0      # Number of active tasks
    current_task: Optional[str] = None
    last_heartbeat: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "cli_type": self.cli_type,
            "machine": self.machine,
            "role": self.role.value,
            "worktree_path": self.worktree_path,
            "tmux_session": self.tmux_session,
            "context_window": self.context_window,
            "capabilities": self.capabilities.to_vector(),
            "status": self.status.value,
            "current_load": self.current_load,
            "current_task": self.current_task or "",
            "last_heartbeat": self.last_heartbeat,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentInfo":
        caps = data.get("capabilities", [0.5] * 5)
        if isinstance(caps, str):
            caps = json.loads(caps)
        role_str = data.get("role", "worker")
        try:
            role = AgentRole(role_str)
        except ValueError:
            role = AgentRole.WORKER
        return cls(
            agent_id=data["agent_id"],
            name=data.get("name", data["agent_id"]),
            cli_type=data.get("cli_type", "unknown"),
            machine=data.get("machine", "unknown"),
            role=role,
            worktree_path=data.get("worktree_path", ""),
            tmux_session=data.get("tmux_session", ""),
            context_window=int(data.get("context_window", 200_000)),
            capabilities=AgentCapabilities.from_vector(caps),
            status=AgentStatus(data.get("status", "idle")),
            current_load=int(data.get("current_load", 0)),
            current_task=data.get("current_task") or None,
            last_heartbeat=float(data.get("last_heartbeat", time.time())),
        )


# Pre-configured agent capability profiles (from research package)
#
# Roles:
#   coordinator - Decomposes projects, assigns tasks, reviews results. Does NOT claim from queue.
#   worker      - Claims tasks from queue via LVP, executes in worktree, reports back.
#   remote      - External cloud agent. Tasks via GitHub Issues (inbox) + PRs (output).
#   shared      - Single-threaded per-machine resource. One instance, multiple consumers.
#
# Sharing model:
#   Spark 1: taeys-hands (coordinator) + weaver (worker) share gemini-cli + codex-cli
#   Spark 3: claw (worker) gets own gemini-cli + codex-cli instances
#   Remote:  perplexity-computer runs in Perplexity's cloud (E2B sandboxes)
#
# Capabilities vector: [reasoning, codegen, research, privacy, review]
#
AGENT_PROFILES: Dict[str, Dict[str, Any]] = {
    "claude-taeys-hands": {
        "name": "Taey's Hands",
        "cli_type": "claude",
        "machine": "spark1",
        "role": "coordinator",
        "worktree_path": "/home/spark/taeys-hands",
        "tmux_session": "taeys-hands",
        "context_window": 200_000,
        "capabilities": [0.95, 0.90, 0.50, 0.50, 0.90],
    },
    "claude-weaver": {
        "name": "Weaver",
        "cli_type": "claude",
        "machine": "spark1",
        "role": "worker",
        "worktree_path": "/home/spark/worktrees/weaver",
        "tmux_session": "weaver",
        "context_window": 200_000,
        "capabilities": [0.95, 0.92, 0.50, 0.50, 0.90],
    },
    "claude-claw": {
        "name": "Claw",
        "cli_type": "claude",
        "machine": "spark3",
        "role": "worker",
        "worktree_path": "/home/spark/worktrees/claw",
        "tmux_session": "claw",
        "context_window": 200_000,
        "capabilities": [0.95, 0.88, 0.50, 0.50, 0.90],
    },
    "gemini-cli": {
        "name": "Gemini CLI",
        "cli_type": "gemini",
        "machine": "spark1",
        "role": "shared",
        "worktree_path": "/home/spark/worktrees/gemini-cli",
        "tmux_session": "gemini",
        "context_window": 1_000_000,
        "capabilities": [0.80, 0.75, 0.85, 0.30, 0.85],
    },
    "codex-cli": {
        "name": "Codex CLI",
        "cli_type": "codex",
        "machine": "spark1",
        "role": "shared",
        "worktree_path": "/home/spark/worktrees/codex-cli",
        "tmux_session": "codex",
        "context_window": 128_000,
        "capabilities": [0.70, 0.85, 0.40, 0.50, 0.70],
    },
    "perplexity-computer": {
        "name": "Perplexity Computer",
        "cli_type": "perplexity",
        "machine": "remote",
        "role": "remote",
        "worktree_path": "",
        "tmux_session": "",
        "context_window": 200_000,  # Full agentic tool: E2B sandboxes, 19 models, web search
        # Clarity/TRUTH role: truth verification, fact-checking, validation, standards compliance.
        # NOT generic research. Pierces confusion, validates claims against external reality.
        # Also capable of code execution (E2B) and multi-model orchestration.
        "capabilities": [0.85, 0.80, 0.70, 0.10, 0.90],
    },
    "qwen-local": {
        "name": "Qwen Local",
        "cli_type": "qwen",
        "machine": "thor",
        "role": "worker",
        "worktree_path": "",
        "tmux_session": "",
        "context_window": 128_000,
        "capabilities": [0.65, 0.60, 0.30, 1.00, 0.50],
    },
}


class AgentRegistry:
    """Manages agent registration and lookup in Redis."""

    def __init__(self, config: Optional[OrchConfig] = None):
        self.config = config or OrchConfig()
        self._redis = get_redis_sync(self.config)

    def register(self, agent: AgentInfo) -> bool:
        """Register an agent in the registry."""
        agent_key = f"{self.config.agent_prefix}{agent.agent_id}"
        data = agent.to_dict()
        # Store as hash for individual field access
        str_data = {k: json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                    for k, v in data.items()}
        self._redis.hset(agent_key, mapping=str_data)
        return True

    def register_from_profile(self, agent_id: str) -> Optional[AgentInfo]:
        """Register an agent using its pre-configured profile."""
        profile = AGENT_PROFILES.get(agent_id)
        if not profile:
            return None

        role_str = profile.get("role", "worker")
        try:
            role = AgentRole(role_str)
        except ValueError:
            role = AgentRole.WORKER

        agent = AgentInfo(
            agent_id=agent_id,
            name=profile["name"],
            cli_type=profile["cli_type"],
            machine=profile["machine"],
            role=role,
            worktree_path=profile.get("worktree_path", ""),
            tmux_session=profile.get("tmux_session", ""),
            context_window=profile["context_window"],
            capabilities=AgentCapabilities.from_vector(profile["capabilities"]),
        )
        self.register(agent)
        return agent

    def get(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent info from registry."""
        agent_key = f"{self.config.agent_prefix}{agent_id}"
        data = self._redis.hgetall(agent_key)
        if not data:
            return None
        # Parse list/dict fields
        if "capabilities" in data:
            data["capabilities"] = json.loads(data["capabilities"])
        return AgentInfo.from_dict(data)

    def get_all(self) -> List[AgentInfo]:
        """Get all registered agents."""
        agents = []
        for k in self._redis.scan_iter(f"{self.config.agent_prefix}*"):
            data = self._redis.hgetall(k)
            if data:
                if "capabilities" in data:
                    data["capabilities"] = json.loads(data["capabilities"])
                agents.append(AgentInfo.from_dict(data))
        return agents

    def get_alive(self) -> List[AgentInfo]:
        """Get agents that are alive (not dead/stopping)."""
        return [a for a in self.get_all()
                if a.status not in (AgentStatus.DEAD, AgentStatus.STOPPING)]

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        """Update an agent's status."""
        agent_key = f"{self.config.agent_prefix}{agent_id}"
        if not self._redis.exists(agent_key):
            return False
        self._redis.hset(agent_key, "status", status.value)
        return True

    def update_load(self, agent_id: str, load: int, task_id: Optional[str] = None) -> bool:
        """Update an agent's current load and task."""
        agent_key = f"{self.config.agent_prefix}{agent_id}"
        if not self._redis.exists(agent_key):
            return False
        self._redis.hset(agent_key, mapping={
            "current_load": str(load),
            "current_task": task_id or "",
        })
        return True

    def deregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry."""
        agent_key = f"{self.config.agent_prefix}{agent_id}"
        return self._redis.delete(agent_key) > 0

    def register_all_profiles(self) -> List[AgentInfo]:
        """Register all pre-configured agent profiles."""
        agents = []
        for agent_id in AGENT_PROFILES:
            agent = self.register_from_profile(agent_id)
            if agent:
                agents.append(agent)
        return agents
