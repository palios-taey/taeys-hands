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
from consultation_v2 import storage_policy
from consultation_v2.identity import (
    IdentityError,
    build_inline_context,
    consolidate_attachments,
    validate_caller_attachments,
)
from consultation_v2.notify import (
    NotificationDelivery,
    push_notification,
    write_notification_local_log,
)
from consultation_v2.planner import (
    SelectionPlanError,
    build_selection_plan,
    has_selection_menus,
    selection_plan_record,
)
from consultation_v2.stop_conditions import is_stop_condition
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


def _inline_context_message(context: str, message: str) -> str:
    return (
        "Read the following identity/context packet before answering. It replaces "
        "the usual ChatGPT attachment for this run.\n\n"
        "<TAEY_INLINE_CONTEXT>\n"
        f"{context}\n"
        "</TAEY_INLINE_CONTEXT>\n\n"
        "User request:\n"
        f"{message}"
    )


def run_consultation(request: ConsultationRequest) -> ConsultationResult:
    if request.platform not in _REGISTRY:
        raise ValueError(f'Unsupported platform: {request.platform}')

    external_store_enabled = storage_policy.external_store_enabled(request)
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

    # --- Phase 1: Identity consolidation / explicit caller-only attachment mode ---
    # FAIL-LOUD (FLOW §4 / CONSULTATION_CONTRACT): a missing/unreadable
    # FAMILY_KERNEL.md or the required platform IDENTITY file raises
    # IdentityError out of consolidate_attachments. We do NOT catch it — a
    # consultation without complete identity must HALT, never proceed on a
    # partial/empty packet. consolidate_attachments now returns a
    # ConsolidatedPackage (always complete) or raises; there is no None case.
    caller_attachments = list(request.attachments)
    consolidated_path = ''
    package_paths = []
    identity_mode = 'identity_consolidated'
    if request.no_identity:
        if not caller_attachments:
            raise IdentityError(
                '--no-identity requires at least one --attach file; refusing to '
                'send an empty packet without FAMILY_KERNEL/IDENTITY overlay.'
            )
        provenance = validate_caller_attachments(caller_attachments)
        identity_mode = 'caller_only'
        request = replace(
            request,
            attachments=caller_attachments,
            caller_attachment_provenance=provenance,
        )
    else:
        if request.platform == 'chatgpt' and not request.session_url and not caller_attachments:
            inline_context, provenance = build_inline_context(
                platform=request.platform,
                caller_attachments=[],
            )
            identity_mode = 'identity_inline'
            consolidated_path = 'inline:chatgpt_identity_context'
            request = replace(
                request,
                message=_inline_context_message(inline_context, request.message),
                attachments=[],
                caller_attachment_provenance=list(provenance),
            )
        else:
            package = consolidate_attachments(
                platform=request.platform,
                caller_attachments=caller_attachments,
            )
            package_paths = package.attachment_paths()
            consolidated_path = '\n'.join(package_paths)
            # Provenance survives consolidation: stamp the caller-attachment path+hashes
            # onto the request (FLOW §3) and write them to durable run-state via the
            # shared-primitive surface so the audit trail records what the caller sent
            # even though the browser receives the merged package file(s).
            request = replace(
                request,
                attachments=package_paths,
                caller_attachment_provenance=list(package.caller_provenance),
            )
    if request.caller_attachment_provenance:
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
                    'identity_mode': identity_mode,
                    'attachment_hashes': [
                        prov.serializable() for prov in request.caller_attachment_provenance
                    ],
                    'package_paths': list(request.attachments),
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
    plan_create_error = None
    if external_store_enabled:
        try:
            from storage import neo4j_client
            plan_id = storage_policy.run_bounded_store_call(
                'Neo4j plan creation',
                lambda: neo4j_client.create_plan(
                    platform=request.platform,
                    model='',
                    mode='',
                    tools=[],
                    selections={
                        'choices': request.serializable_selections(),
                        'plan': selection_record,
                    },
                    message=request.message,
                    attachment_path=consolidated_path or '\n'.join(request.attachments),
                    session=request.session_url or 'new',
                    requester=request.requester or 'unknown',
                ),
            )
        except Exception as exc:
            plan_create_error = str(exc)
            logger.error("Plan creation failed: %s", exc)

    # --- Phase 3: Run driver ---
    driver = _REGISTRY[request.platform]()
    result = driver.run(request)
    if plan_create_error:
        result.add_step(
            'plan_store',
            False,
            'Neo4j plan creation failed; consultation continued',
            error=plan_create_error,
        )
    if result.ok and result.response_text and driver.reject_prompt_echo_response(
        request,
        result,
        result.response_text,
        step='extract_primary',
        source='orchestrator_delivery_gate',
    ):
        result.ok = False
        logger.error(
            'Prompt echo blocked at orchestrator delivery gate for %s purpose=%r',
            request.platform,
            request.purpose,
        )

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
    if plan_id and external_store_enabled:
        try:
            from storage import neo4j_client
            status = 'completed' if result.ok else 'failed'
            step_audit = json.dumps([s.serializable() for s in result.steps],
                                     default=str)
            storage_policy.run_bounded_store_call(
                'Neo4j plan completion',
                lambda: neo4j_client.complete_plan(
                    plan_id=plan_id,
                    response_text=result.response_text or '',
                    extraction_method=_extraction_method(result),
                    status=status,
                    step_audit=step_audit,
                ),
            )
            if result.storage.get('session_id'):
                storage_policy.run_bounded_store_call(
                    'Neo4j plan-session link',
                    lambda: neo4j_client.link_plan_to_session(
                        plan_id,
                        result.storage['session_id'],
                    ),
                )
        except Exception as exc:
            logger.error("Plan completion failed: %s", exc)
            result.add_step(
                'plan_store',
                False,
                'Neo4j plan completion failed; consultation result still delivered locally',
                error=str(exc),
            )

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
            notification_delivery = _push_notification_step(
                result,
                requester=request.requester,
                recipient=None,
                platform=request.platform,
                status='completed',
                plan_id=plan_id or 'unknown',
                response_text=result.response_text or '',
                source_file=request.output_path,
                output_path=request.output_path,
                purpose=request.purpose,
                step_name='notify_requester',
            )
            notification_delivered = bool(notification_delivery)
            if notification_delivered:
                _write_notification_evidence(
                    request,
                    delivery=notification_delivery,
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
                    delivery=notification_delivery,
                )
                _push_notification_step(
                    result,
                    requester=request.requester,
                    recipient=operator,
                    platform=request.platform,
                    status='failed',
                    plan_id=plan_id or 'unknown',
                    response_text=result.response_text or '',
                    source_file=request.output_path,
                    output_path=request.output_path,
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
                delivery=None,
            )
            _push_notification_step(
                result,
                requester='unknown',
                recipient=operator,
                platform=request.platform,
                status='failed',
                plan_id=plan_id or 'unknown',
                response_text=result.response_text or '',
                source_file=request.output_path,
                output_path=request.output_path,
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
            response_text=result.response_text or '',
            source_file=request.output_path,
            output_path=request.output_path,
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
                delivery=operator_notified,
            )

    # ISMA ingestion (non-blocking)
    if result.ok and result.response_text:
        try:
            from consultation_v2.ingest import auto_ingest
            ingest_result = auto_ingest(
                platform=request.platform,
                content=result.response_text,
                url=result.session_url_after,
                session_id=result.storage.get('session_id'),
                external_store_enabled=external_store_enabled,
            )
            result.add_step(
                'ingest',
                True,
                'Consult response persisted locally; external ingest handled by storage policy',
                ingest=ingest_result,
            )
            if plan_id and external_store_enabled and ingest_result.get('isma_triggered'):
                from storage import neo4j_client
                storage_policy.run_bounded_store_call(
                    'Neo4j mark plan ingested',
                    lambda: neo4j_client.mark_plan_ingested(plan_id),
                )
        except Exception as exc:
            logger.error("ISMA ingestion failed: %s", exc)
            result.add_step(
                'isma_ingest',
                False,
                'ISMA ingestion failed; consultation result still delivered locally',
                error=str(exc),
            )

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
    response_text: str,
    source_file: str | None,
    output_path: str | None,
    purpose: str | None,
    step_name: str,
) -> NotificationDelivery:
    target = recipient or requester
    try:
        delivery = push_notification(
            requester=requester,
            platform=platform,
            status=status,
            plan_id=plan_id,
            response_text=response_text,
            purpose=purpose,
            recipient=recipient,
            source_file=source_file,
            output_path=output_path,
        )
    except Exception as exc:
        delivery = NotificationDelivery(
            surfaced=False,
            queued=False,
            acked=False,
            notification_id='',
            recipient=target,
            queue_key=f'taey:{target}:notifications',
            ack_key='',
            attempts=0,
            error=str(exc),
        )
        result.add_step(
            step_name,
            False,
            f'Notification delivery to {target!r} raised: {exc}',
            recipient=target,
            status=status,
            plan_id=plan_id,
            stop_condition='notification_ack_missing',
            notification_delivery=delivery.as_evidence(),
        )
        logger.error("Notification delivery to %s raised: %s", target, exc)
        return delivery
    success = bool(delivery)
    evidence = delivery.as_evidence()
    stop_condition = (
        'notification_ack_missing'
        if (not success and is_stop_condition('notification_ack_missing'))
        else None
    )
    step_evidence = {
        'recipient': target,
        'status': status,
        'plan_id': plan_id,
        'response_chars': len(response_text or ''),
        'source_file': source_file or '',
        'output_path': output_path or '',
        'notification_delivery': evidence,
    }
    if stop_condition:
        step_evidence['stop_condition'] = stop_condition
    result.add_step(
        step_name,
        success,
        (
            f'Notification surfaced by {target!r}'
            if success else f'Notification delivery to {target!r} missing ACK'
        ),
        **step_evidence,
    )
    return delivery


def _write_notification_evidence(
    request: ConsultationRequest,
    *,
    delivery: NotificationDelivery,
    recipient: str,
    plan_id: str,
) -> None:
    try:
        primitives.write_run_state(
            request_id=request.request_id(),
            state={
                'status': 'extraction_done',
                'notification_evidence': {
                    'delivered': bool(delivery),
                    'surface_ack': bool(delivery),
                    'recipient': recipient,
                    'plan_id': plan_id,
                    'notification_id': delivery.notification_id,
                    'ack_key': delivery.ack_key,
                    'attempts': delivery.attempts,
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
    delivery: NotificationDelivery | None = None,
) -> None:
    delivery_evidence = delivery.as_evidence() if delivery is not None else {}
    stop_condition = 'notification_ack_missing' if delivery is not None else None
    local_log_path = _write_notification_attention_record(
        request,
        result,
        recipient=recipient,
        plan_id=plan_id,
        reason=reason,
        delivery=delivery,
    )
    state = {
        'notification_evidence': {
            'delivered': False,
            'surface_ack': False,
            'recipient': recipient,
            'plan_id': plan_id,
            'reason': reason,
            'local_log_path': local_log_path,
            'delivery': delivery_evidence,
        },
        'needs_attention': True,
        'parked_reason': reason,
        'parked_local_log_path': local_log_path,
    }
    if stop_condition:
        state['notification_evidence']['stop_condition'] = stop_condition
        state['parked_stop_condition'] = stop_condition
    if preserve_extraction_done:
        state['status'] = 'extraction_done'
    try:
        primitives.write_run_state(
            request_id=request.request_id(),
            state=state,
        )
    except Exception as exc:
        logger.error("Run-state notification failure park failed: %s", exc)
    step_evidence = {
        'recipient': recipient,
        'plan_id': plan_id,
        'local_log_path': local_log_path,
        'notification_delivery': delivery_evidence,
    }
    if stop_condition:
        step_evidence['stop_condition'] = stop_condition
    result.add_step(
        'notification_parked',
        False,
        f'Notification failure parked for attention: {reason}',
        **step_evidence,
    )


def _write_notification_attention_record(
    request: ConsultationRequest,
    result: ConsultationResult,
    *,
    recipient: str | None,
    plan_id: str,
    reason: str,
    delivery: NotificationDelivery | None,
) -> str:
    try:
        stop_condition = 'notification_ack_missing' if delivery is not None else None
        record = {
            'kind': (
                'notification_ack_missing'
                if delivery is not None else 'notification_needs_attention'
            ),
            'request_id': request.request_id(),
            'platform': request.platform,
            'requester': request.requester,
            'recipient': recipient,
            'purpose': request.purpose,
            'plan_id': plan_id,
            'reason': reason,
            'needs_attention': True,
            'response_chars': len(result.response_text or ''),
            'source_file': request.output_path or '',
            'output_path': request.output_path or '',
            'session_url_after': result.session_url_after,
            'delivery': delivery.as_evidence() if delivery is not None else {},
        }
        if stop_condition:
            record['stop_condition'] = stop_condition
        return write_notification_local_log(record)
    except Exception as exc:
        logger.error("Local notification attention log failed: %s", exc)
        return ''
