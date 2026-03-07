#!/usr/bin/env python3
"""
Orchestration Stop Gate

BLOCKS Claude from stopping if there are incomplete orchestration tasks
assigned to this agent. Queries both Neo4j (OrchTask nodes) and Redis
(orch:task:* claims).

Ported from v4 stop_gate.py, adapted for orchestration layer.
"""
import json
import sys
import os
import subprocess

# Add hooks directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, detect_node_id


# Orchestration Neo4j config (separate from memory infra)
ORCH_NEO4J_URI = os.environ.get("ORCH_NEO4J_URI", "bolt://192.168.100.10:7687")
ORCH_NEO4J_DB = os.environ.get("ORCH_NEO4J_DB", "neo4j")


def block(reason: str):
    """Block stop and inject continue prompt."""
    _inject_continue()
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def allow(reason: str):
    """Allow stop."""
    print(json.dumps({"decision": "approve", "reason": reason}))
    sys.exit(0)


def _inject_continue():
    """Inject continue prompt to this agent's tmux window."""
    try:
        node_id = detect_node_id()
        msg = "Continue working on pending orchestration tasks."
        tmp_file = "/tmp/orch_continue_msg.txt"
        with open(tmp_file, "w") as f:
            f.write(msg)

        for cmd in [
            f"tmux load-buffer {tmp_file}",
            f"tmux paste-buffer -t {node_id}:0",
            f"tmux send-keys -t {node_id}:0 Enter",
        ]:
            subprocess.run(cmd, shell=True, capture_output=True, timeout=5)
    except Exception:
        pass


def get_orch_tasks_neo4j(agent_id: str) -> list:
    """Query Neo4j orchestration labels for incomplete tasks."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(ORCH_NEO4J_URI, auth=None)
        driver.verify_connectivity()

        with driver.session(database=ORCH_NEO4J_DB) as session:
            result = session.run("""
                MATCH (t:OrchTask)
                WHERE t.owner = $agent_id
                  AND t.status IN ['pending', 'in_progress']
                RETURN t.id AS id, t.description AS description, t.status AS status
                ORDER BY t.priority DESC
                LIMIT 10
            """, agent_id=agent_id)

            tasks = [
                {"id": r.get("id"), "description": r.get("description", ""), "status": r.get("status")}
                for r in result
            ]

        driver.close()
        return tasks
    except Exception:
        return []


def get_orch_tasks_redis(agent_id: str) -> list:
    """Check Redis for active task claims by this agent."""
    r = get_redis()
    if not r:
        return []

    try:
        tasks = []
        for k in r.scan_iter("orch:task:*:claimed"):
            owner = r.get(k)
            if owner == agent_id:
                # Extract task_id from key
                parts = k.split(":")
                if len(parts) >= 3:
                    task_id = parts[2]
                    tasks.append({"id": task_id, "description": "Active claim", "status": "claimed"})
        return tasks
    except Exception:
        return []


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        allow("JSON parse error - allowing stop")
        return

    # Detect this agent's ID
    agent_id = detect_node_id()

    # Check Neo4j orchestration tasks
    neo4j_tasks = get_orch_tasks_neo4j(agent_id)

    # Check Redis claims
    redis_tasks = get_orch_tasks_redis(agent_id)

    # Combine and deduplicate
    all_tasks = neo4j_tasks + redis_tasks
    seen = set()
    unique = []
    for t in all_tasks:
        tid = t.get("id", str(t))
        if tid not in seen:
            seen.add(tid)
            unique.append(t)

    if unique:
        task_list = "\n".join(
            f"  - [{t.get('status', '?')}] {t.get('description', t.get('id', '?'))}"
            for t in unique[:5]
        )
        block(f"Orchestration tasks pending:\n{task_list}\n\nComplete tasks before stopping.")

    allow("No orchestration tasks pending")


if __name__ == "__main__":
    main()
