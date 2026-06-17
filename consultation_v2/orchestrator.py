"""Consultation V2 orchestrator — 4-phase consultation lifecycle.

Phase 1: Consolidate attachments (FAMILY_KERNEL + platform identity + caller files)
Phase 2: Create Plan record in Neo4j (pre-flight)
Phase 3: Run the platform driver (navigate → mode → attach → send → monitor → extract → store)
Phase 4: Complete Plan record + notify requester + ingest into ISMA
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import replace

from consultation_v2 import primitives
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
    # FAIL-LOUD (FLOW §4 / CONSULTATION_CONTRACT): a missing/unreadable
    # FAMILY_KERNEL.md or the required platform IDENTITY file raises
    # IdentityError out of consolidate_attachments. We do NOT catch it — a
    # consultation without complete identity must HALT, never proceed on a
    # partial/empty packet. consolidate_attachments now returns a
    # ConsolidatedPackage (always complete) or raises; there is no None case.
    package = consolidate_attachments(
        platform=request.platform,
        caller_attachments=list(request.attachments),
    )
    consolidated_path = package.path
    # Provenance survives consolidation: stamp the caller-attachment path+hashes
    # onto the request (FLOW §3) and write them to durable run-state via the
    # shared-primitive surface so the audit trail records what the caller sent
    # even though the browser only receives the single merged package.
    request = replace(
        request,
        attachments=[consolidated_path],
        caller_attachment_provenance=list(package.caller_provenance),
    )
    if package.caller_provenance:
        try:
            primitives.write_run_state(
                request_id=consolidated_path,
                state={
                    'platform': request.platform,
                    'attachment_hashes': [
                        prov.serializable() for prov in package.caller_provenance
                    ],
                },
            )
        except Exception as exc:
            # Run-state is a durable convenience checkpoint here, not the
            # provenance system of record (that lives on the request +, on
            # success, the Neo4j plan/message records). Redis being down must
            # not abort a consultation whose identity packet is already valid —
            # log loudly and continue. This is NOT a swallow of the fail-loud
            # identity check above; that path already raised if it had to.
            logger.error("Run-state attachment-hash checkpoint failed: %s", exc)

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
    driver = _REGISTRY[request.platform]()
    result = driver.run(request)

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

    # Notify — recipient routed by outcome (Jesse standing directive: requesters
    # receive ONLY successful deliverables; the DRIVER/operator (taeys-hands)
    # receives FAILURES). A success is a real deliverable: result.ok AND a
    # non-empty response_text. Anything else (not ok, or empty response) is a
    # failure and goes to the operator inbox, NEVER the requester — so a failed
    # run / fix-iteration registered with --requester X can never spam X.
    #
    # The original requester + purpose are always stamped INTO the payload
    # (provenance), independent of who RECEIVES it (recipient), so a
    # operator-routed failure still records who the consult was for.
    delivered = bool(result.ok and result.response_text)
    operator = os.environ.get('TAEY_NODE_ID') or 'taeys-hands'
    if delivered:
        # Success → deliver to the requester. With no requester, surface LOUDLY
        # rather than dropping (the GAIA->tutor orphan: result ready, nobody told).
        if request.requester:
            try:
                push_notification(
                    requester=request.requester,
                    platform=request.platform,
                    status='completed',
                    plan_id=plan_id or 'unknown',
                    preview=(result.response_text or '')[:200],
                    purpose=request.purpose,
                )
            except Exception as exc:
                logger.error("Notification failed: %s", exc)
        else:
            logger.warning(
                "ORPHAN RISK: %s consultation (purpose=%r) completed with a result but NO "
                "requester — result will not be routed to any session. Pass --requester.",
                request.platform, request.purpose,
            )
    else:
        # Failure → notify the operator (taeys-hands), NEVER the requester. The
        # original requester (or 'unknown') is stamped into the payload for
        # audit; the queue is the operator's so the driver sees the failure.
        try:
            push_notification(
                requester=request.requester or 'unknown',
                platform=request.platform,
                status='failed',
                plan_id=plan_id or 'unknown',
                preview=(result.response_text or '')[:200],
                purpose=request.purpose,
                recipient=operator,
            )
        except Exception as exc:
            logger.error("Failure notification to operator failed: %s", exc)

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
