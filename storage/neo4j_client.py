"""Neo4j client for session and message persistence."""

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
_driver = None


class Neo4jJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return str(obj)
        return super().default(obj)


def get_driver():
    global _driver
    if _driver is None:
        try:
            from neo4j import GraphDatabase
            _driver = GraphDatabase.driver(NEO4J_URI, auth=None)
            _driver.verify_connectivity()
            logger.info("Neo4j connected")
        except Exception as e:
            _driver = None
            raise ConnectionError(f"Neo4j connection failed: {e}") from e
    return _driver


def create_session(platform: str, url: str,
                   session_type: str = None, purpose: str = None) -> Optional[str]:
    driver = get_driver()
    if not driver:
        return None
    session_id = str(uuid.uuid4())[:12]
    with driver.session() as s:
        s.run("""
            CREATE (sess:ChatSession {
                session_id: $session_id, platform: $platform, url: $url,
                session_type: $session_type, purpose: $purpose,
                created_at: datetime(), last_activity: datetime(), message_count: 0
            })
        """, session_id=session_id, platform=platform, url=url,
             session_type=session_type, purpose=purpose)
    return session_id


def get_or_create_session(platform: str, url: str) -> Optional[str]:
    driver = get_driver()
    if not driver:
        return None
    try:
        with driver.session() as s:
            result = s.run("""
                MATCH (sess:ChatSession {platform: $platform, url: $url})
                RETURN sess.session_id AS session_id
                ORDER BY sess.created_at DESC LIMIT 1
            """, platform=platform, url=url)
            record = result.single()
            if record:
                return record['session_id']
    except Exception as e:
        logger.error(f"Session lookup failed: {e}")
    return create_session(platform, url)


def add_message(session_id: str, role: str, content: str,
                attachments: List[str] = None) -> Optional[str]:
    driver = get_driver()
    if not driver:
        return None
    message_id = str(uuid.uuid4())[:12]
    with driver.session() as s:
        s.run("""
            MATCH (sess:ChatSession {session_id: $session_id})
            CREATE (msg:Message {
                message_id: $message_id, role: $role, content: $content,
                attachments: $attachments, created_at: datetime(),
                handled: $handled
            })
            CREATE (sess)-[:HAS_MESSAGE]->(msg)
            SET sess.message_count = sess.message_count + 1,
                sess.last_activity = datetime()
        """, session_id=session_id, message_id=message_id,
             role=role, content=content,
             attachments=json.dumps(attachments or []),
             handled=(role == 'user'))
    return message_id


_ALLOWED_SESSION_PROPS = {'session_type', 'purpose', 'last_activity'}


def update_session(session_id: str, updates: Dict[str, Any]) -> bool:
    driver = get_driver()
    if not driver:
        return False
    bad_keys = set(updates) - _ALLOWED_SESSION_PROPS
    if bad_keys:
        logger.error(f"Rejecting disallowed session properties: {bad_keys}")
        return False
    try:
        with driver.session() as s:
            clauses = ', '.join(f's.{k} = ${k}' for k in updates)
            s.run(f"MATCH (s:ChatSession {{session_id: $session_id}}) SET {clauses}",
                  session_id=session_id, **updates)
        return True
    except Exception as e:
        logger.error(f"Update session failed: {e}")
        return False


def get_active_sessions(platform: str = None) -> List[Dict]:
    driver = get_driver()
    if not driver:
        return []
    try:
        with driver.session() as s:
            if platform:
                result = s.run("""
                    MATCH (sess:ChatSession {platform: $platform})
                    RETURN sess ORDER BY sess.last_activity DESC LIMIT 20
                """, platform=platform)
            else:
                result = s.run("""
                    MATCH (sess:ChatSession)
                    RETURN sess ORDER BY sess.last_activity DESC LIMIT 50
                """)
            return [dict(record['sess']) for record in result]
    except Exception as e:
        logger.error(f"Get sessions failed: {e}")
        return []


def mark_message_handled(message_id: str) -> bool:
    driver = get_driver()
    if not driver:
        return False
    try:
        with driver.session() as s:
            s.run("""
                MATCH (m:Message {message_id: $message_id})
                SET m.handled = true, m.handled_at = datetime()
            """, message_id=message_id)
        return True
    except Exception as e:
        logger.error(f"Mark handled failed: {e}")
        return False
