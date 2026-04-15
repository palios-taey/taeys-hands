#!/usr/bin/env python3
"""consultation_v2/store.py — Neo4j storage for consultations.

Stores consultation requests, responses, and metadata in Neo4j.
Every consultation gets a permanent record: what was asked, to whom,
with what settings, and what came back.

Usage:
    from consultation_v2.store import store_consultation, store_response

    # After consult.py dispatches:
    consultation_id = store_consultation(
        platform='gemini',
        prompt='Your prompt here',
        mode='pro',
        tools=['deep_think'],
        attachments=['/path/to/file.md'],
        url='https://gemini.google.com/app/abc123',
    )

    # After extraction:
    store_response(consultation_id, response_text, url='https://...')
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    model: str | None = None,
) -> str:
    """Store a consultation request in Neo4j. Returns the consultation UUID."""
    consultation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    driver = _get_driver()
    try:
        with driver.session() as session:
            session.run("""
                MERGE (p:Platform {name: $platform})
                CREATE (c:Consultation {
                    uuid: $uuid,
                    platform: $platform,
                    prompt: $prompt,
                    mode: $mode,
                    tools: $tools,
                    attachments: $attachments,
                    url: $url,
                    model: $model,
                    status: 'dispatched',
                    created_at: $created_at
                })
                CREATE (c)-[:ON_PLATFORM]->(p)
            """, uuid=consultation_id, platform=platform, prompt=prompt,
                mode=mode, tools=json.dumps(tools or []),
                attachments=json.dumps(attachments or []),
                url=url, model=model, created_at=now)
    finally:
        driver.close()

    return consultation_id


def store_response(
    consultation_id: str,
    response_text: str,
    url: str | None = None,
    extraction_method: str = 'copy_button',
) -> str:
    """Store a consultation response in Neo4j. Returns the response UUID."""
    response_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    driver = _get_driver()
    try:
        with driver.session() as session:
            session.run("""
                MATCH (c:Consultation {uuid: $consultation_id})
                CREATE (r:ConsultationResponse {
                    uuid: $response_id,
                    text: $text,
                    url: $url,
                    extraction_method: $extraction_method,
                    extracted_at: $extracted_at,
                    char_count: $char_count
                })
                CREATE (c)-[:HAS_RESPONSE]->(r)
                SET c.status = 'complete',
                    c.completed_at = $extracted_at,
                    c.response_url = $url
            """, consultation_id=consultation_id, response_id=response_id,
                text=response_text, url=url, extraction_method=extraction_method,
                extracted_at=now, char_count=len(response_text))
    finally:
        driver.close()

    return response_id


def store_monitor_event(
    consultation_id: str,
    event_type: str,
    elapsed: float,
    url: str | None = None,
    method: str | None = None,
):
    """Store a monitor completion/timeout event against a consultation."""
    now = datetime.now(timezone.utc).isoformat()

    driver = _get_driver()
    try:
        with driver.session() as session:
            session.run("""
                MATCH (c:Consultation {uuid: $consultation_id})
                SET c.monitor_event = $event_type,
                    c.monitor_elapsed = $elapsed,
                    c.monitor_method = $method,
                    c.monitor_url = $url,
                    c.monitor_at = $now
            """, consultation_id=consultation_id, event_type=event_type,
                elapsed=elapsed, method=method, url=url, now=now)
    finally:
        driver.close()


def get_consultation(consultation_id: str) -> dict | None:
    """Retrieve a consultation and its response by UUID."""
    driver = _get_driver()
    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Consultation {uuid: $uuid})
                OPTIONAL MATCH (c)-[:HAS_RESPONSE]->(r:ConsultationResponse)
                RETURN c {.*} AS consultation,
                       r {.*} AS response
            """, uuid=consultation_id)
            record = result.single()
            if not record:
                return None
            return {
                'consultation': dict(record['consultation']),
                'response': dict(record['response']) if record['response'] else None,
            }
    finally:
        driver.close()


def list_consultations(platform: str | None = None, limit: int = 20) -> list[dict]:
    """List recent consultations, optionally filtered by platform."""
    driver = _get_driver()
    try:
        with driver.session() as session:
            if platform:
                result = session.run("""
                    MATCH (c:Consultation {platform: $platform})
                    OPTIONAL MATCH (c)-[:HAS_RESPONSE]->(r:ConsultationResponse)
                    RETURN c {.*} AS consultation, r.char_count AS response_chars
                    ORDER BY c.created_at DESC
                    LIMIT $limit
                """, platform=platform, limit=limit)
            else:
                result = session.run("""
                    MATCH (c:Consultation)
                    OPTIONAL MATCH (c)-[:HAS_RESPONSE]->(r:ConsultationResponse)
                    RETURN c {.*} AS consultation, r.char_count AS response_chars
                    ORDER BY c.created_at DESC
                    LIMIT $limit
                """, limit=limit)
            return [{'consultation': dict(r['consultation']),
                     'response_chars': r['response_chars']} for r in result]
    finally:
        driver.close()
