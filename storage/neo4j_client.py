"""
Neo4j client for session and message persistence.

Provides CRUD operations for chat sessions and messages.
Uses the NCCL fabric network for high-speed access.

Sessions and messages form a graph:
  (ChatSession)-[:HAS_MESSAGE]->(Message)
  (Message)-[:RESPONDS_TO]->(Message)
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Neo4j configuration - no auth, NCCL network
NEO4J_URI = "bolt://192.168.100.10:7689"

_driver = None


class Neo4jJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for Neo4j temporal types."""
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return str(obj)
        return super().default(obj)


def get_driver():
    """Get or create the Neo4j driver (singleton)."""
    global _driver
    if _driver is None:
        try:
            from neo4j import GraphDatabase
            _driver = GraphDatabase.driver(NEO4J_URI, auth=None)
            _driver.verify_connectivity()
            logger.info("Neo4j connected")
        except Exception as e:
            logger.warning(f"Neo4j connection failed: {e}")
            _driver = None
    return _driver


def create_session(platform: str, url: str,
                   session_type: str = None,
                   purpose: str = None) -> Optional[str]:
    """Create a new chat session.

    Returns:
        Session ID string, or None on failure.
    """
    driver = get_driver()
    if not driver:
        return None

    session_id = str(uuid.uuid4())[:12]
    try:
        with driver.session() as s:
            s.run("""
                CREATE (sess:ChatSession {
                    session_id: $session_id,
                    platform: $platform,
                    url: $url,
                    session_type: $session_type,
                    purpose: $purpose,
                    created_at: datetime(),
                    last_activity: datetime(),
                    message_count: 0
                })
            """, session_id=session_id, platform=platform, url=url,
                 session_type=session_type, purpose=purpose)
        return session_id
    except Exception as e:
        logger.error(f"Create session failed: {e}")
        return None


def get_or_create_session(platform: str, url: str) -> Optional[str]:
    """Get existing session by URL or create new one.

    Returns:
        Session ID string, or None on failure.
    """
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
    """Add a message to a session.

    Args:
        session_id: Parent session ID.
        role: 'user' or 'assistant'.
        content: Message text.
        attachments: List of attached file paths.

    Returns:
        Message ID string, or None on failure.
    """
    driver = get_driver()
    if not driver:
        return None

    message_id = str(uuid.uuid4())[:12]
    try:
        with driver.session() as s:
            s.run("""
                MATCH (sess:ChatSession {session_id: $session_id})
                CREATE (msg:Message {
                    message_id: $message_id,
                    role: $role,
                    content: $content,
                    attachments: $attachments,
                    created_at: datetime(),
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
    except Exception as e:
        logger.error(f"Add message failed: {e}")
        return None


def update_session(session_id: str, updates: Dict[str, Any]) -> bool:
    """Update session properties.

    Args:
        session_id: Session to update.
        updates: Dict of property names to new values.

    Returns:
        True on success.
    """
    driver = get_driver()
    if not driver:
        return False

    try:
        with driver.session() as s:
            set_clauses = ', '.join(f's.{k} = ${k}' for k in updates)
            s.run(
                f"MATCH (s:ChatSession {{session_id: $session_id}}) SET {set_clauses}",
                session_id=session_id, **updates,
            )
        return True
    except Exception as e:
        logger.error(f"Update session failed: {e}")
        return False


def get_active_sessions(platform: str = None) -> List[Dict]:
    """Get active sessions, optionally filtered by platform.

    Returns:
        List of session dicts with metadata.
    """
    driver = get_driver()
    if not driver:
        return []

    try:
        with driver.session() as s:
            if platform:
                result = s.run("""
                    MATCH (sess:ChatSession {platform: $platform})
                    RETURN sess
                    ORDER BY sess.last_activity DESC
                    LIMIT 20
                """, platform=platform)
            else:
                result = s.run("""
                    MATCH (sess:ChatSession)
                    RETURN sess
                    ORDER BY sess.last_activity DESC
                    LIMIT 50
                """)
            return [dict(record['sess']) for record in result]
    except Exception as e:
        logger.error(f"Get sessions failed: {e}")
        return []


def mark_message_handled(message_id: str) -> bool:
    """Mark a message as handled (response processed).

    Returns:
        True on success.
    """
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
