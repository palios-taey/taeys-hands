import hashlib
import json
import uuid

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

    def store(self, platform, content, session_id, monitor_id, redis_client):
        if not content:
            return None
        pending = self._pending(platform, redis_client)
        session_id = session_id or pending.get("session_id") or str(uuid.uuid4())[:12]
        message_id = str(uuid.uuid4())[:12]
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        url = pending.get("session_url", "")
        with self.driver.session() as session:
            session.run(
                """
                MERGE (s:ChatSession {session_id: $session_id})
                ON CREATE SET s.platform = $platform, s.url = $url, s.created_at = datetime()
                SET s.last_activity = datetime()
                CREATE (m:Message {
                  message_id: $message_id, role: 'assistant', content: $content,
                  content_hash: $content_hash, monitor_id: $monitor_id, created_at: datetime()
                })
                MERGE (s)-[:HAS_MESSAGE]->(m)
                WITH s
                SET s.message_count = size([(s)-[:HAS_MESSAGE]->(:Message) | 1])
                """,
                session_id=session_id,
                platform=platform,
                url=url,
                message_id=message_id,
                content=content,
                content_hash=content_hash,
                monitor_id=monitor_id,
            )
        return content_hash
