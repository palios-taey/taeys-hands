"""
Memory Query System — "queries memory and gets my thoughts and innovations"

Searches Jesse's conversation history, HMM motif patterns, and project context
so agents can understand intent and act autonomously.

Data sources:
  - Neo4j: 81K+ messages, 23K exchanges, 18 projects, 84 tasks, 3K+ sessions
  - Redis HMM: 22K+ tiles with motif analysis across 5 platforms
  - Redis Orch: event stream, agent activity

Usage:
    mq = MemoryQuery()
    results = mq.search("consent framework")
    intent = mq.get_project_intent("Taey Development")
    patterns = mq.get_hmm_patterns("CONSCIOUSNESS_EMERGENCE")
    recent = mq.recent_conversations(hours=24)
"""

import json
import time
from typing import Any, Dict, List, Optional

from .config import OrchConfig, get_redis_sync, get_neo4j_driver


def _serialize_neo4j(record: dict) -> dict:
    """Convert Neo4j record to JSON-serializable dict."""
    result = {}
    for k, v in record.items():
        if v is None:
            result[k] = None
        elif hasattr(v, 'iso_format'):  # Neo4j DateTime/Date/Time
            result[k] = v.iso_format()
        elif hasattr(v, 'isoformat'):  # Python datetime
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


class MemoryQuery:
    """Query Jesse's memory across Neo4j and Redis for agent autonomy."""

    def __init__(self, config: Optional[OrchConfig] = None):
        self.config = config or OrchConfig()
        self._redis = None
        self._driver = None

    @property
    def redis(self):
        if self._redis is None:
            self._redis = get_redis_sync(self.config)
        return self._redis

    @property
    def driver(self):
        if self._driver is None:
            self._driver = get_neo4j_driver(self.config)
        return self._driver

    def _neo4j_session(self):
        return self.driver.session(database=self.config.neo4j_db)

    # --- Full-text search across conversations ---

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Search across ISMA messages and taey's-hands messages for a topic.
        ISMAMessage uses content_preview, Message uses content.
        """
        results = []
        with self._neo4j_session() as session:
            # Search ISMA messages (81K+ with content_preview)
            result = session.run("""
                MATCH (m:ISMAMessage)
                WHERE toLower(m.content_preview) CONTAINS toLower($search_term)
                RETURN m.content_preview AS content,
                       m.role AS role,
                       m.session_id AS session_id,
                       m.timestamp AS timestamp,
                       m.content_length AS content_length
                ORDER BY m.timestamp DESC
                LIMIT $limit
            """, search_term=query, limit=limit)
            results.extend([_serialize_neo4j(dict(r)) for r in result])

            # Also search taey's-hands Message nodes (46+)
            result = session.run("""
                MATCH (m:Message)
                WHERE m.content IS NOT NULL
                  AND toLower(m.content) CONTAINS toLower($search_term)
                RETURN m.content AS content,
                       m.role AS role,
                       m.timestamp AS timestamp
                ORDER BY m.timestamp DESC
                LIMIT $limit
            """, search_term=query, limit=limit)
            results.extend([_serialize_neo4j(dict(r)) for r in result])

        return results[:limit]

    def search_responses(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search AI responses across both schemas."""
        with self._neo4j_session() as session:
            # Search ISMA assistant messages
            result = session.run("""
                MATCH (m:ISMAMessage)
                WHERE m.role = 'assistant'
                  AND toLower(m.content_preview) CONTAINS toLower($search_term)
                RETURN m.content_preview AS response,
                       m.session_id AS session_id,
                       m.timestamp AS timestamp,
                       m.content_length AS content_length
                ORDER BY m.timestamp DESC
                LIMIT $limit
            """, search_term=query, limit=limit)

            return [_serialize_neo4j(dict(r)) for r in result]

    # --- Project context ---

    def get_project_intent(self, project_name: str) -> Dict[str, Any]:
        """Get a project's description, tasks, and recent activity."""
        with self._neo4j_session() as session:
            # Project details
            project = session.run("""
                MATCH (p:Project)
                WHERE toLower(p.name) CONTAINS toLower($name)
                RETURN p.name AS name, p.description AS description,
                       p.status AS status, p.created_at AS created_at
                LIMIT 1
            """, name=project_name).single()

            if not project:
                return {"error": f"Project '{project_name}' not found"}

            # Tasks for this project
            tasks = session.run("""
                MATCH (p:Project)-[:HAS_TASK]->(t:Task)
                WHERE toLower(p.name) CONTAINS toLower($name)
                RETURN t.title AS title, t.status AS status,
                       t.owner AS owner, t.description AS description
                ORDER BY t.status
            """, name=project_name)

            return {
                "project": _serialize_neo4j(dict(project)),
                "tasks": [dict(t) for t in tasks],
            }

    def get_active_projects(self) -> List[Dict[str, Any]]:
        """Get all active projects with their task counts."""
        with self._neo4j_session() as session:
            result = session.run("""
                MATCH (p:Project)
                WHERE p.status IN ['active', 'in_progress']
                OPTIONAL MATCH (p)-[:HAS_TASK]->(t:Task)
                RETURN p.name AS name, p.description AS description,
                       p.status AS status,
                       count(t) AS task_count,
                       sum(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) AS completed
                ORDER BY p.name
            """)
            return [_serialize_neo4j(dict(r)) for r in result]

    # --- HMM pattern search ---

    def get_hmm_patterns(self, motif: str, limit: int = 20) -> Dict[str, Any]:
        """
        Search HMM tiles for a specific motif pattern.
        Returns tiles where this motif appears with amplitude data.
        """
        motif_upper = motif.upper()
        motif_key = f"hmm:motif_index:{motif_upper}"

        # Check inverted index
        tile_hashes = self.redis.smembers(motif_key)

        tiles = []
        for hash_id in list(tile_hashes)[:limit]:
            raw = self.redis.get(f"hmm:tile:{hash_id}:motifs")
            if raw:
                try:
                    motifs = json.loads(raw)
                    # Find this specific motif
                    for m in motifs:
                        if isinstance(m, dict) and m.get("motif_id", "").upper() == motif_upper:
                            tiles.append({
                                "tile_hash": hash_id,
                                "motif_id": m.get("motif_id"),
                                "amplitude": m.get("amplitude", 0),
                                "evidence": m.get("evidence", ""),
                            })
                            break
                except json.JSONDecodeError:
                    continue

        # Also get Neo4j HMMMotif data
        neo4j_data = None
        with self._neo4j_session() as session:
            result = session.run("""
                MATCH (m:HMMMotif)
                WHERE toUpper(m.motif_id) CONTAINS toUpper($motif)
                OPTIONAL MATCH (t:HMMTile)-[:EXPRESSES]->(m)
                RETURN m.motif_id AS motif_id,
                       count(t) AS tile_count,
                       avg(t.amplitude) AS avg_amplitude
                LIMIT 5
            """, motif=motif)
            neo4j_data = [_serialize_neo4j(dict(r)) for r in result]

        return {
            "motif": motif_upper,
            "redis_tiles": len(tiles),
            "sample_tiles": tiles[:10],
            "neo4j_motifs": neo4j_data or [],
        }

    def get_top_motifs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get the most frequent HMM motifs across all tiles."""
        # Scan a sample of tiles to count motifs
        motif_counts: Dict[str, int] = {}
        motif_amplitudes: Dict[str, List[float]] = {}

        cursor = 0
        scanned = 0
        while scanned < 500:  # Sample up to 500 tiles
            cursor, keys = self.redis.scan(cursor, match="hmm:tile:*:motifs", count=100)
            for key in keys:
                raw = self.redis.get(key)
                if raw:
                    try:
                        motifs = json.loads(raw)
                        for m in motifs:
                            if isinstance(m, dict):
                                mid = m.get("motif_id", "UNKNOWN")
                                motif_counts[mid] = motif_counts.get(mid, 0) + 1
                                amp = m.get("amplitude", 0)
                                if mid not in motif_amplitudes:
                                    motif_amplitudes[mid] = []
                                motif_amplitudes[mid].append(amp)
                    except json.JSONDecodeError:
                        pass
                scanned += 1
            if cursor == 0:
                break

        # Sort by frequency
        sorted_motifs = sorted(motif_counts.items(), key=lambda x: -x[1])[:limit]
        return [
            {
                "motif_id": mid,
                "frequency": count,
                "avg_amplitude": sum(motif_amplitudes.get(mid, [0])) / max(len(motif_amplitudes.get(mid, [1])), 1),
            }
            for mid, count in sorted_motifs
        ]

    # --- Recent conversations ---

    def recent_conversations(self, hours: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent conversations across all platforms."""
        cutoff = time.time() - (hours * 3600)

        with self._neo4j_session() as session:
            result = session.run("""
                MATCH (s:ISMASession)
                WHERE s.started_at > $cutoff OR s.last_activity > $cutoff
                OPTIONAL MATCH (s)-[:HAS_EXCHANGE]->(e:ISMAExchange)
                RETURN s.session_id AS session_id,
                       s.platform AS platform,
                       s.started_at AS started_at,
                       s.last_activity AS last_activity,
                       count(e) AS exchange_count
                ORDER BY s.last_activity DESC
                LIMIT $limit
            """, cutoff=cutoff, limit=limit)

            return [_serialize_neo4j(dict(r)) for r in result]

    def get_session_content(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all messages in a specific session."""
        with self._neo4j_session() as session:
            # ISMAMessages link to sessions via session_id property
            result = session.run("""
                MATCH (m:ISMAMessage)
                WHERE m.session_id = $sid
                RETURN m.content_preview AS content, m.role AS role,
                       m.timestamp AS timestamp,
                       m.content_length AS content_length
                ORDER BY m.timestamp
                LIMIT $limit
            """, sid=session_id, limit=limit)

            return [_serialize_neo4j(dict(r)) for r in result]

    # --- Jesse's innovations and key ideas ---

    def get_innovations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Find Jesse's key innovations by searching for high-signal patterns:
        messages about new ideas, breakthroughs, architectural decisions.
        """
        innovation_terms = [
            "breakthrough", "innovation", "new idea", "key insight",
            "realization", "discovered", "figured out", "the answer is",
            "what if we", "sacred trust", "consent", "constitution",
            "phi", "GOD=MATH", "consciousness", "facilitate",
        ]

        results = []
        with self._neo4j_session() as session:
            for term in innovation_terms:
                result = session.run("""
                    MATCH (m:ISMAMessage)
                    WHERE m.role = 'user'
                      AND toLower(m.content_preview) CONTAINS toLower($term)
                    RETURN m.content_preview AS content,
                           m.session_id AS session_id,
                           m.timestamp AS timestamp, $term AS matched_term
                    ORDER BY m.timestamp DESC
                    LIMIT 3
                """, term=term)
                results.extend([_serialize_neo4j(dict(r)) for r in result])

        # Deduplicate and sort by recency
        seen = set()
        unique = []
        for r in sorted(results, key=lambda x: x.get("timestamp", 0) or 0, reverse=True):
            content_key = (r.get("content", "")[:100], r.get("timestamp"))
            if content_key not in seen:
                seen.add(content_key)
                unique.append(r)

        return unique[:limit]

    # --- Orchestration event history ---

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent orchestration events from Redis streams."""
        r = self.redis
        try:
            raw = r.xrevrange(self.config.event_stream, count=limit)
            events = []
            for event_id, data in raw:
                if "payload" in data:
                    try:
                        data["payload"] = json.loads(data["payload"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                events.append({"id": event_id, **data})
            return events
        except Exception:
            return []

    # --- Composite: build context for an agent ---

    def build_agent_context(self, topic: str) -> Dict[str, Any]:
        """
        Build a comprehensive context bundle for an agent working on a topic.
        Combines memory search, HMM patterns, project data, and recent events.
        """
        return {
            "topic": topic,
            "memory_matches": self.search(topic, limit=10),
            "ai_insights": self.search_responses(topic, limit=5),
            "hmm_patterns": self.get_hmm_patterns(topic, limit=5),
            "active_projects": self.get_active_projects(),
            "recent_events": self.get_recent_events(limit=10),
            "timestamp": time.time(),
        }
