"""Consultation V2 orchestrator — 4-phase consultation lifecycle.

Phase 1: Consolidate attachments (FAMILY_KERNEL + platform identity + caller files)
Phase 2: Create Plan record in Neo4j (pre-flight)
Phase 3: Run the platform driver (navigate → mode → attach → send → monitor → extract → store)
Phase 4: Complete Plan record + notify requester + ingest into ISMA
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace

from consultation_v2.identity import consolidate_attachments
from consultation_v2.notify import push_notification
from consultation_v2.types import ConsultationRequest, ConsultationResult
from consultation_v2.drivers.chatgpt import ChatGPTConsultationDriver
from consultation_v2.drivers.claude import ClaudeConsultationDriver
from consultation_v2.drivers.gemini import GeminiConsultationDriver
from consultation_v2.drivers.grok import GrokConsultationDriver
from consultation_v2.drivers.perplexity import PerplexityConsultationDriver

logger = logging.getLogger(__name__)

_REGISTRY = {
    'chatgpt': ChatGPTConsultationDriver,
    'claude': ClaudeConsultationDriver,
    'gemini': GeminiConsultationDriver,
    'grok': GrokConsultationDriver,
    'perplexity': PerplexityConsultationDriver,
}


def run_consultation(request: ConsultationRequest) -> ConsultationResult:
    if request.platform not in _REGISTRY:
        raise ValueError(f'Unsupported platform: {request.platform}')

    # --- Phase 1: Identity consolidation ---
    consolidated_path = None
    try:
        consolidated_path = consolidate_attachments(
            platform=request.platform,
            caller_attachments=list(request.attachments),
        )
    except Exception as exc:
        logger.error("Identity consolidation failed: %s", exc)

    if consolidated_path:
        request = replace(request, attachments=[consolidated_path])

    # --- Phase 2: Create Plan in Neo4j ---
    plan_id = None
    if not request.no_neo4j:
        try:
            from storage import neo4j_client
            plan_id = neo4j_client.create_plan(
                platform=request.platform,
                model=request.model or '',
                mode=request.mode or '',
                tools=list(request.tools),
                message=request.message,
                attachment_path=consolidated_path or '',
                session=request.session_url or 'new',
                requester=request.requester or 'unknown',
            )
        except Exception as exc:
            logger.error("Plan creation failed: %s", exc)

    # --- Phase 3: Run driver ---
    try:
        driver = _REGISTRY[request.platform]()
        result = driver.run(request)
    except Exception as exc:
        logger.exception("Driver crashed with unhandled exception")
        result = ConsultationResult(platform=request.platform, request=request)
        result.add_step("driver_run", False, f"Driver crashed: {exc}")

    # --- Phase 4: Complete Plan + notify + ingest ---
    if plan_id and not request.no_neo4j:
        try:
            from storage import neo4j_client
            status = 'completed' if result.ok else 'failed'
            step_audit = json.dumps([s.serializable() for s in result.steps],
                                     default=str)
            neo4j_client.complete_plan(
                plan_id=plan_id,
                response_text=result.response_text or '',
                extraction_method=_extraction_method(result),
                status=status,
                step_audit=step_audit,
            )
            if result.storage.get('session_id'):
                neo4j_client.link_plan_to_session(plan_id, result.storage['session_id'])
        except Exception as exc:
            logger.error("Plan completion failed: %s", exc)

    # Notify requester
    if request.requester:
        try:
            push_notification(
                requester=request.requester,
                platform=request.platform,
                status='completed' if result.ok else 'failed',
                plan_id=plan_id or 'unknown',
                preview=(result.response_text or '')[:200],
            )
        except Exception as exc:
            logger.error("Notification failed: %s", exc)

    # ISMA ingestion (non-blocking)
    if result.ok and result.response_text:
        try:
            from core.ingest import auto_ingest
            auto_ingest(
                platform=request.platform,
                content=result.response_text,
                url=result.session_url_after,
                session_id=result.storage.get('session_id'),
            )
            if plan_id:
                from storage import neo4j_client
                neo4j_client.mark_plan_ingested(plan_id)
        except Exception as exc:
            logger.error("ISMA ingestion failed: %s", exc)

    return result


def _extraction_method(result: ConsultationResult) -> str:
    """Extract the method used from the step audit."""
    for step in result.steps:
        if step.step == 'extract_primary' and step.success:
            return step.message
    return 'unknown'
