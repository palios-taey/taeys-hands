"""
LVP Task Router

Hybrid routing: coordinator decomposes tasks, agents self-claim via LVP scoring.
Ported from v4 isma/coordination.py (LocalVotingProtocol).

Scoring function (Grok's mathematically-optimal, validated convergent):
  S(a,t) = 0.40 * cos(C_a, R_t) + 0.35 * min(1, w_a/s_t) + 0.25 * 1/(1+L_a)

Where:
  C_a = agent capability vector
  R_t = task requirement vector
  w_a = agent context window
  s_t = estimated tokens for task
  L_a = agent current load
"""

import math
from typing import List, Optional, Tuple

from .registry import AgentInfo, AgentRole, AgentStatus
from .task_queue import TaskMessage


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


# Scoring weights (Grok-validated, alpha+beta+gamma = 1.0)
ALPHA = 0.40  # Capability match
BETA = 0.35   # Context fit
GAMMA = 0.25  # Load balance


def score_agent_for_task(agent: AgentInfo, task: TaskMessage) -> float:
    """
    Score an agent's suitability for a task using Grok's optimal function.

    Returns score in [0, 1] range. Higher = better fit.
    """
    # Skip dead/stopping agents
    if agent.status in (AgentStatus.DEAD, AgentStatus.STOPPING):
        return 0.0

    # Coordinators don't claim tasks - they assign them
    if agent.role == AgentRole.COORDINATOR:
        return 0.0

    # Shared resources (Gemini CLI, Codex CLI) don't self-claim.
    # Coordinator routes one task at a time to these single-threaded executors.
    if agent.role == AgentRole.SHARED:
        return 0.0

    # Build task requirement vector from capability tags
    task_req = _tags_to_vector(task.capability_tags)
    agent_cap = agent.capabilities.to_vector()

    # Component 1: Capability match (cosine similarity)
    cap_match = cosine_similarity(agent_cap, task_req)

    # Component 2: Context fit (can the agent hold the task's tokens?)
    if agent.context_window > 0 and task.estimated_tokens > 0:
        context_fit = min(1.0, agent.context_window / task.estimated_tokens)
    elif agent.context_window == 0:
        # Perplexity/remote agents - penalize for token-heavy tasks
        context_fit = 0.1 if task.estimated_tokens > 10_000 else 0.5
    else:
        context_fit = 1.0

    # Component 3: Load balance (prefer less loaded agents)
    load_balance = 1.0 / (1.0 + agent.current_load)

    return ALPHA * cap_match + BETA * context_fit + GAMMA * load_balance


def rank_agents_for_task(
    agents: List[AgentInfo],
    task: TaskMessage,
) -> List[Tuple[AgentInfo, float]]:
    """
    Rank all agents for a task by LVP score.

    Returns list of (agent, score) sorted by score descending.
    Deterministic tie-break by agent_id for consistency.
    """
    scored = []
    for agent in agents:
        score = score_agent_for_task(agent, task)
        if score > 0:
            scored.append((agent, score))

    # Sort by score desc, then agent_id asc for deterministic tie-break
    scored.sort(key=lambda x: (-x[1], x[0].agent_id))
    return scored


def select_best_agent(
    agents: List[AgentInfo],
    task: TaskMessage,
    min_score: float = 0.1,
) -> Optional[AgentInfo]:
    """Select the best agent for a task, or None if no agent qualifies."""
    ranked = rank_agents_for_task(agents, task)
    if ranked and ranked[0][1] >= min_score:
        return ranked[0][0]
    return None


# --- Capability tag mapping ---

# Maps capability tags to vector positions
# [reasoning, codegen, research, privacy, review]
TAG_VECTORS = {
    "architecture": [1.0, 0.5, 0.3, 0.0, 0.8],
    "reasoning": [1.0, 0.3, 0.3, 0.0, 0.5],
    "codegen": [0.3, 1.0, 0.1, 0.0, 0.3],
    "testing": [0.4, 0.8, 0.1, 0.0, 0.5],
    "research": [0.3, 0.1, 1.0, 0.0, 0.3],
    "security": [0.5, 0.5, 0.3, 0.8, 0.7],
    "review": [0.7, 0.5, 0.3, 0.0, 1.0],
    "large_context": [0.5, 0.5, 0.5, 0.0, 0.8],
    "privacy": [0.3, 0.3, 0.1, 1.0, 0.3],
    "multi_file": [0.7, 0.8, 0.2, 0.0, 0.6],
}


def _tags_to_vector(tags: List[str]) -> List[float]:
    """Convert capability tags to a requirement vector by averaging."""
    if not tags:
        return [0.5, 0.5, 0.5, 0.5, 0.5]  # Neutral - any agent fits

    vectors = [TAG_VECTORS.get(tag, [0.5] * 5) for tag in tags]
    dim = len(vectors[0])
    avg = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    return avg
