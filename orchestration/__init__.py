"""
Multi-CLI Agent Orchestration Layer

Coordinates parallel AI coding agents (Claude, Gemini, Codex, Perplexity Computer)
across the DGX Spark cluster.

ISOLATION: This package is completely separate from memory infrastructure
(ISMA, HMM, Weaviate). All Redis keys use 'orch:' prefix. Neo4j uses
Orch*-prefixed labels in the default database. Zero imports from core/, tools/, storage/.

Architecture (Family consensus, March 2026):
- Control plane: Redis Streams (orch:streams:*)
- Planning plane: Neo4j Orch* labels (task DAGs, gates, file ownership)
- Execution plane: tmux-send adapters per CLI agent
- Code plane: git worktrees + per-task branches + protected dev

Agent Roles:
- COORDINATOR (taeys-hands): Decomposes projects, assigns tasks via LVP,
  reviews results. Does NOT claim tasks from queue.
- WORKER (weaver, claw): Claims tasks via LVP scoring, executes in own
  worktree, reports completion.
- SHARED (gemini-cli, codex-cli): Single-threaded per-machine resources.
  Coordinator routes one task at a time to these.
- REMOTE (perplexity-computer): Cloud agent. Tasks via GitHub Issues (inbox),
  results via PRs (output). 19 models, E2B sandboxes.

Sharing Model:
- Spark 1: taeys-hands (coordinator) + weaver share 1 Gemini CLI + 1 Codex CLI
- Spark 3: claw gets own Gemini CLI + Codex CLI instances
- Remote: Perplexity Computer runs in Perplexity's cloud infrastructure
"""

__version__ = "0.2.0"
