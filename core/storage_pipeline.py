import hashlib
import json
import uuid
from datetime import datetime, timezone

from neo4j import GraphDatabase

from storage.redis_pool import node_key


class StoragePipeline:
    def __init__(self):
        self.driver = GraphDatabase.driver("bolt://localhost:7689", auth=None)

    def _pending(self, platform, redis_client):
        if not redis_client:
            return {}
        raw = redis_client.get(node_key(f"pending_prompt:{platform}"))
        if not raw:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}

    def store(self, platform, content, session_id, monitor_id, redis_client, source="monitor"):
        if not content:
            return None
        pending = self._pending(platform, redis_client)
        session_id = session_id or pending.get("session_id") or str(uuid.uuid4())[:12]
        message_id = str(uuid.uuid4())[:12]
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        url = pending.get("session_url", "")
        created_at = datetime.now(timezone.utc)
        with self.driver.session() as session:
            session.run(
                """
                MERGE (s:ChatSession {session_id: $session_id})
                ON CREATE SET
                  s.platform = $platform,
                  s.source = $source,
                  s.url = $url,
                  s.created_at = $created_at
                SET s.last_activity = $created_at
                CREATE (m:Message {
                  message_id: $message_id, role: 'assistant', content: $content,
                  content_hash: $content_hash, monitor_id: $monitor_id, created_at: $created_at
                })
                MERGE (s)-[:HAS_MESSAGE]->(m)
                WITH s
                SET s.message_count = size([(s)-[:HAS_MESSAGE]->(:Message) | 1])
                """,
                session_id=session_id,
                platform=platform,
                source=source,
                url=url,
                created_at=created_at,
                message_id=message_id,
                content=content,
                content_hash=content_hash,
                monitor_id=monitor_id,
            )
        return content_hash
