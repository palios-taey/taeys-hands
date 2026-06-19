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
from consultation_v2.planner import (
    SelectionPlanError,
    build_selection_plan,
    has_selection_menus,
    selection_plan_record,
)
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

    selection_record = []
    if has_selection_menus(request.platform):
        try:
            planned_selections = build_selection_plan(request)
        except SelectionPlanError as exc:
            result = ConsultationResult(platform=request.platform, request=request)
            result.add_step(
                'selection_plan',
                False,
                'Selection plan rejected before browser action',
                findings=list(exc.findings),
            )
            return result
        selection_record = selection_plan_record(planned_selections)

    # --- Phase 0: Display readiness gate (all chat platforms; validation-only) ---
    # Before ANY interaction, verify the production display is readable and in
    # one-window/one-tab/right-host shape. Not-ready returns a failed result with
    # evidence; checker exceptions are intentionally not caught.
    from consultation_v2 import display_readiness
    readiness = display_readiness.check(request.platform)
    if not readiness['ready']:
        result = ConsultationResult(platform=request.platform, request=request)
        details = '; '.join(readiness.get('issues') or [])
        resolutions = '; '.join(readiness.get('resolutions') or [])
        message = f"display {readiness.get('display')} NOT ready: {details}"
        if resolutions:
            message += f" | resolution: {resolutions}"
        result.add_step('display_readiness', False, message, readiness=readiness)
        logger.error(
            'DISPLAY READINESS GATE FAILED %s %s: issues=%s resolutions=%s',
            request.platform,
            readiness.get('display'),
            readiness.get('issues'),
            readiness.get('resolutions'),
        )
        return result
    logger.info(
        'display readiness OK %s %s (windows=%s tabs=%s url=%s)',
        request.platform,
        readiness.get('display'),
        readiness.get('windows'),
        readiness.get('tabs'),
        readiness.get('url'),
    )

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
            # Key by the STABLE request_id (FLOW §8), NOT the consolidated-package
            # path: the package path is a per-run timestamped temp file, so keying
            # run-state on it would mint a fresh record every re-run and defeat the
            # duplicate-send guard. The driver's send/monitor checkpoints write to
            # this same key, so the attachment hashes merge into the one durable
            # record the resume logic reads.
            primitives.write_run_state(
                request_id=request.request_id(),
                state={
                    'platform': request.platform,
                    'prompt_hash': request.prompt_hash(),
                    'session_target': request.session_url or 'new',
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
                model='',
                mode='',
                tools=[],
                selections={
                    'choices': request.serializable_selections(),
                    'plan': selection_record,
                },
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

    # extraction_done milestone (FLOW §8): the driver returned a real extracted
    # response. Checkpointed so a re-run that crashes between extraction and
    # delivery still sees the send as landed (and resumes/re-extracts rather than
    # re-sending). Written from the orchestrator because extraction success is
    # the per-platform driver's terminal ok-state, surfaced here as result.ok +
    # response_text.
    if result.ok and result.response_text:
        try:
            primitives.write_run_state(
                request_id=request.request_id(),
                state={
                    'status': 'extraction_done',
                    'platform': request.platform,
                    'prompt_hash': request.prompt_hash(),
                    'url': result.session_url_after or '',
                    'response_chars': len(result.response_text),
                },
            )
        except Exception as exc:
            logger.error("Run-state extraction_done checkpoint failed: %s", exc)

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
    notification_delivered = False
    operator = os.environ.get('TAEY_NODE_ID') or 'taeys-hands'
    if delivered:
        # Success → deliver to the requester. With no requester, surface LOUDLY
        # rather than dropping (the GAIA->tutor orphan: result ready, nobody told).
        if request.requester:
            notification_delivered = _push_notification_step(
                result,
                requester=request.requester,
                recipient=None,
                platform=request.platform,
                status='completed',
                plan_id=plan_id or 'unknown',
                preview=(result.response_text or '')[:200],
                purpose=request.purpose,
                step_name='notify_requester',
            )
            if notification_delivered:
                _write_notification_evidence(
                    request,
                    delivered=True,
                    recipient=request.requester,
                    plan_id=plan_id or 'unknown',
                )
            else:
                _park_notification_failure(
                    request,
                    result,
                    recipient=request.requester,
                    plan_id=plan_id or 'unknown',
                    reason='requester notification delivery failed',
                    preserve_extraction_done=True,
                )
                _push_notification_step(
                    result,
                    requester=request.requester,
                    recipient=operator,
                    platform=request.platform,
                    status='failed',
                    plan_id=plan_id or 'unknown',
                    preview='Requester notification failed; result parked for attention.',
                    purpose=request.purpose,
                    step_name='notify_operator_delivery_failure',
                )
        else:
            _park_notification_failure(
                request,
                result,
                recipient=None,
                plan_id=plan_id or 'unknown',
                reason='completed consultation has no requester',
                preserve_extraction_done=True,
            )
            _push_notification_step(
                result,
                requester='unknown',
                recipient=operator,
                platform=request.platform,
                status='failed',
                plan_id=plan_id or 'unknown',
                preview='Completed consultation has no requester; result parked for attention.',
                purpose=request.purpose,
                step_name='notify_operator_orphan_result',
            )
            logger.warning(
                "ORPHAN RISK: %s consultation (purpose=%r) completed with a result but NO "
                "requester — result will not be routed to any session. Pass --requester.",
                request.platform, request.purpose,
            )
    else:
        # Failure → notify the operator (taeys-hands), NEVER the requester. The
        # original requester (or 'unknown') is stamped into the payload for
        # audit; the queue is the operator's so the driver sees the failure.
        operator_notified = _push_notification_step(
            result,
            requester=request.requester or 'unknown',
            recipient=operator,
            platform=request.platform,
            status='failed',
            plan_id=plan_id or 'unknown',
            preview=(result.response_text or '')[:200],
            purpose=request.purpose,
            step_name='notify_operator_failure',
        )
        if not operator_notified:
            _park_notification_failure(
                request,
                result,
                recipient=operator,
                plan_id=plan_id or 'unknown',
                reason='operator failure notification delivery failed',
                preserve_extraction_done=False,
            )

    # ISMA ingestion (non-blocking)
    if result.ok and result.response_text:
        try:
            from consultation_v2.ingest import auto_ingest
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

    # --- Teardown (FLOW §8): a fully-delivered consultation is DONE. Clear the
    # durable run-state and deregister the monitor session so the request_id is
    # free and a later, genuinely-new consultation with the same prompt is not
    # mistaken for the landed one. We clear ONLY on a real delivery (ok +
    # response): a FAILED run KEEPS its run-state so a re-run can RESUME the
    # landed send (resume + re-extract) instead of re-sending the irreversible
    # turn. monitor_id is derived from the same stable request_id the driver
    # used to register, so deregistration targets the right session.
    if delivered and notification_delivered:
        monitor_id = f'{request.platform}:{request.request_id()}'
        try:
            primitives.deregister_monitor_session(monitor_id)
        except Exception as exc:
            logger.error("Monitor deregistration failed: %s", exc)
        try:
            primitives.clear_run_state(request.request_id())
        except Exception as exc:
            logger.error("Run-state clear failed: %s", exc)

    return result


def _extraction_method(result: ConsultationResult) -> str:
    """Extract the method used from the step audit."""
    for step in result.steps:
        if step.step == 'extract_primary' and step.success:
            return step.message
    return 'unknown'


def _push_notification_step(
    result: ConsultationResult,
    *,
    requester: str,
    recipient: str | None,
    platform: str,
    status: str,
    plan_id: str,
    preview: str,
    purpose: str | None,
    step_name: str,
) -> bool:
    target = recipient or requester
    try:
        delivered = push_notification(
            requester=requester,
            platform=platform,
            status=status,
            plan_id=plan_id,
            preview=preview,
            purpose=purpose,
            recipient=recipient,
        )
    except Exception as exc:
        delivered = False
        result.add_step(
            step_name,
            False,
            f'Notification delivery to {target!r} raised: {exc}',
            recipient=target,
            status=status,
            plan_id=plan_id,
        )
        logger.error("Notification delivery to %s raised: %s", target, exc)
        return False
    result.add_step(
        step_name,
        bool(delivered),
        (
            f'Notification delivered to {target!r}'
            if delivered else f'Notification delivery to {target!r} failed'
        ),
        recipient=target,
        status=status,
        plan_id=plan_id,
    )
    return bool(delivered)


def _write_notification_evidence(
    request: ConsultationRequest,
    *,
    delivered: bool,
    recipient: str,
    plan_id: str,
) -> None:
    try:
        primitives.write_run_state(
            request_id=request.request_id(),
            state={
                'status': 'extraction_done',
                'notification_evidence': {
                    'delivered': delivered,
                    'recipient': recipient,
                    'plan_id': plan_id,
                },
                'needs_attention': False,
            },
        )
    except Exception as exc:
        logger.error("Run-state notification evidence checkpoint failed: %s", exc)


def _park_notification_failure(
    request: ConsultationRequest,
    result: ConsultationResult,
    *,
    recipient: str | None,
    plan_id: str,
    reason: str,
    preserve_extraction_done: bool,
) -> None:
    state = {
        'notification_evidence': {
            'delivered': False,
            'recipient': recipient,
            'plan_id': plan_id,
            'reason': reason,
        },
        'needs_attention': True,
        'parked_reason': reason,
    }
    if preserve_extraction_done:
        state['status'] = 'extraction_done'
    try:
        primitives.write_run_state(
            request_id=request.request_id(),
            state=state,
        )
    except Exception as exc:
        logger.error("Run-state notification failure park failed: %s", exc)
    result.add_step(
        'notification_parked',
        False,
        f'Notification failure parked for attention: {reason}',
        recipient=recipient,
        plan_id=plan_id,
    )
