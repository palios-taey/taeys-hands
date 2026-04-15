#!/usr/bin/env python3
"""consultation_v2/store.py — Neo4j storage for consultations.

Uses existing ChatSession/Message schema:
  ChatSession -[:HAS_MESSAGE]-> Message (role: user)
  ChatSession -[:HAS_MESSAGE]-> Message (role: assistant)

ChatSession properties: session_id, platform, purpose, url, session_type,
  mode, tools, created_at, last_activity, message_count, status
Message properties: message_id, role, content, attachments, created_at

Usage:
    from consultation_v2.store import store_consultation, store_response

    consultation_id = store_consultation(
        platform='gemini', prompt='Your prompt', mode='pro',
        tools=['deep_think'], attachments=['/path/to/file.md'],
        url='https://gemini.google.com/app/abc123',
    )

    store_response(consultation_id, response_text, url='https://...')
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _get_driver():
    """Get Neo4j driver from env or defaults."""
    from neo4j import GraphDatabase
    uri = os.environ.get('NEO4J_URI', 'bolt://localhost:7689')
    auth = None
    user = os.environ.get('NEO4J_USER')
    password = os.environ.get('NEO4J_PASSWORD')
    if user and password:
        auth = (user, password)
    return GraphDatabase.driver(uri, auth=auth)


def store_consultation(
    platform: str,
    prompt: str,
    mode: str | None = None,
    tools: list[str] | None = None,
    attachments: list[str] | None = None,
    url: str | None = None,
) -> str:
    """Store a consultation as ChatSession + user Message. Returns session_id."""
    session_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    driver = _get_driver()
    try:
        with driver.session() as session:
            session.run("""
                MERGE (p:Platform {name: $platform})
                CREATE (s:ChatSession {
                    session_id: $session_id,
                    platform: $platform,
                    session_type: 'consultation',
                    purpose: $prompt,
                    mode: $mode,
                    tools: $tools,
                    url: $url,
                    status: 'dispatched',
                    message_count: 1,
                    created_at: $now,
                    last_activity: $now
                })
                CREATE (m:Message {
                    message_id: $message_id,
                    role: 'user',
                    content: $prompt,
                    attachments: $attachments,
                    created_at: $now
                })
                CREATE (s)-[:HAS_MESSAGE]->(m)
                CREATE (s)-[:ON_PLATFORM]->(p)
            """, session_id=session_id, platform=platform, prompt=prompt,
                mode=mode, tools=json.dumps(tools or []),
                attachments=json.dumps(attachments or []),
                url=url, message_id=message_id, now=now)
    finally:
        driver.close()

    return session_id


def store_response(
    session_id: str,
    response_text: str,
    url: str | None = None,
    extraction_method: str = 'copy_button',
) -> str:
    """Store a response as assistant Message linked to ChatSession. Returns message_id."""
    message_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    driver = _get_driver()
    try:
        with driver.session() as session:
            session.run("""
                MATCH (s:ChatSession {session_id: $session_id})
                CREATE (m:Message {
                    message_id: $message_id,
                    role: 'assistant',
                    content: $response_text,
                    extraction_method: $extraction_method,
                    char_count: $char_count,
                    created_at: $now
                })
                CREATE (s)-[:HAS_MESSAGE]->(m)
                SET s.status = 'complete',
                    s.last_activity = $now,
                    s.message_count = s.message_count + 1,
                    s.response_url = $url
            """, session_id=session_id, message_id=message_id,
                response_text=response_text, extraction_method=extraction_method,
                char_count=len(response_text), now=now, url=url)
    finally:
        driver.close()

    return message_id


def store_monitor_event(
    session_id: str,
    event_type: str,
    elapsed: float,
    url: str | None = None,
    method: str | None = None,
):
    """Store monitor completion/timeout metadata on the ChatSession."""
    now = datetime.now(timezone.utc).isoformat()

    driver = _get_driver()
    try:
        with driver.session() as session:
            session.run("""
                MATCH (s:ChatSession {session_id: $session_id})
                SET s.monitor_event = $event_type,
                    s.monitor_elapsed = $elapsed,
                    s.monitor_method = $method,
                    s.monitor_url = $url,
                    s.monitor_at = $now
            """, session_id=session_id, event_type=event_type,
                elapsed=elapsed, method=method, url=url, now=now)
    finally:
        driver.close()


def get_consultation(session_id: str) -> dict | None:
    """Retrieve a consultation session with all messages."""
    driver = _get_driver()
    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (s:ChatSession {session_id: $session_id})
                OPTIONAL MATCH (s)-[:HAS_MESSAGE]->(m:Message)
                WITH s, m ORDER BY m.created_at
                WITH s, collect(m {.*}) AS messages
                RETURN s {.*} AS session, messages
            """, session_id=session_id)
            record = result.single()
            if not record:
                return None
            return {
                'session': dict(record['session']),
                'messages': [dict(m) for m in record['messages']],
            }
    finally:
        driver.close()


def list_consultations(platform: str | None = None, limit: int = 20) -> list[dict]:
    """List recent consultation sessions."""
    driver = _get_driver()
    try:
        with driver.session() as session:
            query = """
                MATCH (s:ChatSession {session_type: 'consultation'"""
            if platform:
                query += ", platform: $platform"
            query += """})
                RETURN s {.*} AS session
                ORDER BY s.created_at DESC
                LIMIT $limit
            """
            params = {'limit': limit}
            if platform:
                params['platform'] = platform
            result = session.run(query, **params)
            return [{'session': dict(r['session'])} for r in result]
    finally:
        driver.close()
