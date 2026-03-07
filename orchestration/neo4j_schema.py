"""
Neo4j Orchestration Schema

Creates task DAG schema in the neo4j database with Orch-prefixed labels
to isolate from memory infrastructure (ISMA, HMM, Weaviate).

Label convention: OrchProject, OrchPhase, OrchTask, OrchFileOwnership
(memory labels: ISMAExchange, HMMTile, HMMMotif, Message, ChatSession)
"""

from typing import Any, Dict, List, Optional

from .config import OrchConfig, get_neo4j_driver


SCHEMA_CONSTRAINTS = [
    "CREATE CONSTRAINT orch_task_id IF NOT EXISTS FOR (t:OrchTask) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT orch_project_id IF NOT EXISTS FOR (p:OrchProject) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT orch_phase_id IF NOT EXISTS FOR (ph:OrchPhase) REQUIRE ph.id IS UNIQUE",
]

SCHEMA_INDEXES = [
    "CREATE INDEX orch_task_status IF NOT EXISTS FOR (t:OrchTask) ON (t.status)",
    "CREATE INDEX orch_task_owner IF NOT EXISTS FOR (t:OrchTask) ON (t.owner)",
    "CREATE INDEX orch_file_path IF NOT EXISTS FOR (f:OrchFileOwnership) ON (f.path)",
]


def init_schema(config: Optional[OrchConfig] = None) -> Dict[str, Any]:
    """Create orchestration schema (constraints + indexes). Idempotent."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    results = {"constraints": [], "indexes": [], "errors": []}

    try:
        with driver.session(database=cfg.neo4j_db) as session:
            for stmt in SCHEMA_CONSTRAINTS:
                try:
                    session.run(stmt)
                    results["constraints"].append(stmt.split("FOR")[0].strip())
                except Exception as e:
                    results["errors"].append(f"{stmt[:60]}: {e}")

            for stmt in SCHEMA_INDEXES:
                try:
                    session.run(stmt)
                    results["indexes"].append(stmt.split("FOR")[0].strip())
                except Exception as e:
                    results["errors"].append(f"{stmt[:60]}: {e}")
    finally:
        driver.close()

    return results


def create_project(project_id: str, name: str, description: str = "",
                   config: Optional[OrchConfig] = None) -> str:
    """Create an OrchProject node."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    try:
        with driver.session(database=cfg.neo4j_db) as session:
            result = session.run("""
                MERGE (p:OrchProject {id: $id})
                SET p.name = $name, p.description = $description,
                    p.created_at = datetime(), p.status = 'active'
                RETURN p.id AS id
            """, id=project_id, name=name, description=description)
            return result.single()["id"]
    finally:
        driver.close()


def create_phase(project_id: str, phase_id: str, name: str,
                 order: int = 0, config: Optional[OrchConfig] = None) -> str:
    """Create an OrchPhase linked to a project."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    try:
        with driver.session(database=cfg.neo4j_db) as session:
            result = session.run("""
                MATCH (p:OrchProject {id: $project_id})
                MERGE (ph:OrchPhase {id: $phase_id})
                SET ph.name = $name, ph.order = $order, ph.status = 'pending'
                MERGE (p)-[:HAS_PHASE]->(ph)
                RETURN ph.id AS id
            """, project_id=project_id, phase_id=phase_id, name=name, order=order)
            return result.single()["id"]
    finally:
        driver.close()


def create_task(
    phase_id: str,
    task_id: str,
    description: str,
    priority: int = 50,
    capability_tags: Optional[List[str]] = None,
    file_blast_radius: Optional[List[str]] = None,
    estimated_tokens: int = 50_000,
    config: Optional[OrchConfig] = None,
) -> str:
    """Create an OrchTask linked to a phase."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    try:
        with driver.session(database=cfg.neo4j_db) as session:
            result = session.run("""
                MATCH (ph:OrchPhase {id: $phase_id})
                MERGE (t:OrchTask {id: $task_id})
                SET t.description = $description,
                    t.priority = $priority,
                    t.capability_tags = $capability_tags,
                    t.file_blast_radius = $file_blast_radius,
                    t.estimated_tokens = $estimated_tokens,
                    t.status = 'pending',
                    t.owner = '',
                    t.created_at = datetime()
                MERGE (ph)-[:HAS_TASK]->(t)
                RETURN t.id AS id
            """,
                task_id=task_id,
                phase_id=phase_id,
                description=description,
                priority=priority,
                capability_tags=capability_tags or [],
                file_blast_radius=file_blast_radius or [],
                estimated_tokens=estimated_tokens,
            )
            return result.single()["id"]
    finally:
        driver.close()


def add_dependency(task_id: str, depends_on_id: str,
                   config: Optional[OrchConfig] = None) -> bool:
    """Create DEPENDS_ON relationship between tasks."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    try:
        with driver.session(database=cfg.neo4j_db) as session:
            session.run("""
                MATCH (t:OrchTask {id: $task_id})
                MATCH (dep:OrchTask {id: $depends_on_id})
                MERGE (t)-[:DEPENDS_ON]->(dep)
            """, task_id=task_id, depends_on_id=depends_on_id)
            return True
    finally:
        driver.close()


def get_ready_tasks(config: Optional[OrchConfig] = None) -> List[Dict[str, Any]]:
    """Get tasks that are pending with all dependencies satisfied."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    try:
        with driver.session(database=cfg.neo4j_db) as session:
            result = session.run("""
                MATCH (t:OrchTask {status: 'pending'})
                WHERE NOT EXISTS {
                    MATCH (t)-[:DEPENDS_ON]->(dep:OrchTask)
                    WHERE dep.status <> 'completed'
                }
                RETURN t.id AS id, t.description AS description,
                       t.priority AS priority, t.capability_tags AS capability_tags,
                       t.file_blast_radius AS file_blast_radius,
                       t.estimated_tokens AS estimated_tokens
                ORDER BY t.priority DESC
            """)
            return [dict(r) for r in result]
    finally:
        driver.close()


def update_task_status(task_id: str, status: str, owner: str = "",
                       config: Optional[OrchConfig] = None) -> bool:
    """Update task status and owner."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    try:
        with driver.session(database=cfg.neo4j_db) as session:
            result = session.run("""
                MATCH (t:OrchTask {id: $task_id})
                SET t.status = $status, t.owner = $owner,
                    t.updated_at = datetime()
                RETURN t.id AS id
            """, task_id=task_id, status=status, owner=owner)
            return result.single() is not None
    finally:
        driver.close()


def get_agent_tasks(agent_id: str, config: Optional[OrchConfig] = None) -> List[Dict[str, Any]]:
    """Get tasks owned by an agent."""
    cfg = config or OrchConfig()
    driver = get_neo4j_driver(cfg)
    try:
        with driver.session(database=cfg.neo4j_db) as session:
            result = session.run("""
                MATCH (t:OrchTask)
                WHERE t.owner = $agent_id
                  AND t.status IN ['pending', 'in_progress']
                RETURN t.id AS id, t.description AS description,
                       t.status AS status, t.priority AS priority
                ORDER BY t.priority DESC
                LIMIT 10
            """, agent_id=agent_id)
            return [dict(r) for r in result]
    finally:
        driver.close()
