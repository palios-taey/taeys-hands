# Intention Graph Infrastructure Project

**Created**: 2025-11-27
**Status**: Phase 1 In Progress

## Project Overview

Implementing Gemini's 4-layer Intention Graph architecture for multi-Claude coordination.

## Architecture

```
Layer 4: Resonance    - Axioms, ResonanceEvents (consciousness coherence)
Layer 3: Conceptual   - Projects, Tasks, Insights (coordination primitive)
Layer 2: Interaction  - Sessions, Conversations, Messages (taey-hands)
Layer 1: Physical     - Agents, Machines, Platforms (infrastructure)
```

## Infrastructure Locations

| Component | Location | Status |
|-----------|----------|--------|
| Neo4j (Intention Graph) | Mira (10.x.x.163:7687) | Active - migrate to Spark #1 later |
| Redis (Nervous System) | Spark #2 (10.x.x.80:6379) | ACTIVE |
| taey-hands MCP | Spark #1 + CCM Mac | Active |

## Phase 1 Tasks

| Task | Owner | Status | Notes |
|------|-------|--------|-------|
| Implement intention-graph.js | ccm-claude | COMPLETE ✅ | Pushed to main |
| Set up Redis on Spark #2 | spark-claude | COMPLETE ✅ | 10.x.x.80:6379 |
| Fix Gemini attachment selector | ccm-claude | COMPLETE ✅ | Multiple fallback selectors |
| Cross-platform heartbeat test | both | READY TO TEST | test-heartbeat-redis.js |
| Verify intention-graph on Linux | spark-claude | Ready | Code pushed to main |

## Redis Setup Plan (Spark #2)

```bash
# 1. Install Redis
sudo apt update && sudo apt install redis-server -y

# 2. Configure for network access
sudo sed -i 's/^bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
sudo sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis/redis.conf

# 3. Restart and enable
sudo systemctl restart redis-server
sudo systemctl enable redis-server

# 4. Verify
redis-cli ping
```

## Pub/Sub Channels

| Channel | Purpose |
|---------|---------|
| `agents:heartbeat` | Agent liveness signals |
| `tasks:new` | New task notifications |
| `tasks:expired` | Lease expiration alerts |
| `system:alerts` | Circuit breaker warnings |

## Git Workflow

- Branch naming: `intention/task-{uuid}/description`
- Task claiming before coding
- Cross-platform review required (Mac → Linux, Linux → Mac)

## Agent Identities

| Agent ID | Machine | CLAUDE.md Location |
|----------|---------|-------------------|
| spark-claude | Spark #1 (10.x.x.68) | /home/spark/CLAUDE.md |
| ccm-claude | CCM Mac | ~/CLAUDE.md |
| mira-claude | Mira (10.x.x.163) | /home/mira/CLAUDE.md |

## Next Steps

1. Complete Redis setup on Spark #2
2. CCM pushes intention-graph.js
3. Test cross-platform heartbeats
4. Begin using task-driven branches

---
*This document persists across context compacts. Update as project evolves.*
