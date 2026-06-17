from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Iterable, List, Optional

from consultation_v2.completion import (
    COMPLETE,
    HANG_SUSPECTED,
    CompletionDetector,
)
from consultation_v2 import primitives
from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, ExtractedArtifact, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


class BaseConsultationDriver(ABC):
    platform: str

    def __init__(self) -> None:
        self.cfg = load_platform_yaml(self.platform)
        self.runtime = ConsultationRuntime(self.platform)

    def result(self, request: ConsultationRequest) -> ConsultationResult:
        return ConsultationResult(platform=self.platform, request=request)

    def find_first(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.first(key)

    def find_last(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.last(key)

    def validation_passes(self, snapshot: Snapshot, validation_key: str, filename: str | None = None) -> bool:
        validation = dict(self.cfg.get('validation', {}).get(validation_key, {}))
        if not validation and not filename:
            # If the validation key is missing, we assume it's NOT active
            return False

        if validation.get('url_contains'):
            probe = str(validation['url_contains']).lower()
            if probe not in (snapshot.url or '').lower():
                return False

        indicators = validation.get('indicators') or []
        if indicators:
            all_elements: List[ElementRef] = []
            for items in snapshot.mapped.values():
                all_elements.extend(items)
            all_elements.extend(snapshot.unknown)
            all_elements.extend(snapshot.sidebar)

            found = False
            for indicator in indicators:
                if any(matches_spec(element, indicator) for element in all_elements):
                    found = True
                    break
            if not found:
                return False

        file_chip = dict(validation.get('file_chip', {}))
        if filename and file_chip:
            probes = []
            base = filename.split('/')[-1]
            probes.append(base.lower())
            stem = base.rsplit('.', 1)[0].lower() if '.' in base else base.lower()
            probes.append(stem)
            if stem.startswith('taey_package_'):
                probes.append(stem.rsplit('_', 1)[0])
                probes.append('taey_package_')
            
            all_elements: List[ElementRef] = []
            for items in snapshot.mapped.values():
                all_elements.extend(items)
            all_elements.extend(snapshot.unknown)
            
            role_set = {str(role).lower() for role in file_chip.get('roles', [])}
            matched_chip = False
            for element in all_elements:
                if role_set and element.role.lower() not in role_set:
                    continue
                name = element.name.lower()
                if any(probe and probe in name for probe in probes):
                    matched_chip = True
                    break
            if not matched_chip:
                return False

        if validation.get('stop_absent'):
            stop_key = self.cfg.get('workflow', {}).get('monitor', {}).get('stop_key') or 'stop_button'
            if snapshot.has(stop_key):
                return False
        return True

    def serialize_artifacts(self, artifacts: Iterable[ExtractedArtifact]) -> List[str]:
        return [json.dumps(artifact.serializable(), sort_keys=True) for artifact in artifacts]

    # ------------------------------------------------------------------
    # Shared state primitives (FLOW §7) — locks / run-state / monitor
    # registration / storage. These delegate to consultation_v2.primitives,
    # the single shared-primitive surface, so a driver never imports the
    # legacy platform-driving modules (tools/send.py, monitor/central.py) for
    # state. They carry NO platform knowledge: the driver passes its own
    # ``self.platform`` (opaque data), request ids, and monitor ids.
    # ------------------------------------------------------------------

    def acquire_display_lock(self, payload: Optional[dict] = None, ttl: int = 3600) -> bool:
        return primitives.acquire_display_lock(payload=payload, ttl=ttl)

    def release_display_lock(self) -> bool:
        return primitives.release_display_lock()

    def write_run_state(self, request_id: str, state: dict, ttl: int = 7200) -> bool:
        return primitives.write_run_state(request_id, state, ttl=ttl)

    def read_run_state(self, request_id: str) -> Optional[dict]:
        return primitives.read_run_state(request_id)

    def clear_run_state(self, request_id: str) -> bool:
        return primitives.clear_run_state(request_id)

    def register_monitor_session(self, monitor_id: str, session: dict) -> bool:
        return primitives.register_monitor_session(monitor_id, session)

    def deregister_monitor_session(self, monitor_id: str) -> bool:
        return primitives.deregister_monitor_session(monitor_id)

    # ------------------------------------------------------------------
    # Run-state idempotency (FLOW §8, CONSULTATION_CONTRACT §10)
    # ------------------------------------------------------------------
    #
    # The send is the single IRREVERSIBLE action. A re-run after a landed send
    # (drift hit post-send, process crashed, operator re-dispatched) must NEVER
    # replay it. The durable run-state record keyed by the request's STABLE
    # request_id is the duplicate-send guard: as the lifecycle progresses we
    # checkpoint the load-bearing milestones into it, and at the send seam we
    # READ it first — if a prior run already captured a submitted-URL, we RESUME
    # (re-attach to the existing chat URL) instead of sending again.
    #
    # This lives in the base driver, called from ONE seam in each platform
    # driver's run() (``guarded_send`` replaces the direct ``send_prompt`` call),
    # so the guard is identical for all five platforms and cannot drift per
    # driver. ``self.platform`` is opaque DATA stamped into the record, never a
    # control-flow branch.

    # Checkpoint milestone STATUS values written to run-state['status'].
    RUN_STATE_SETUP_COMPLETE = 'setup_complete'
    RUN_STATE_SUBMITTED = 'submitted'
    RUN_STATE_COMPLETION_OBSERVED = 'completion_observed'
    RUN_STATE_EXTRACTION_DONE = 'extraction_done'

    def _monitor_id(self, request: ConsultationRequest) -> str:
        """Deterministic monitor/session id for this consultation. Derived from
        the same stable request_id so a resumed run re-registers/looks up the
        SAME monitor session rather than spawning a duplicate."""
        return f'{self.platform}:{request.request_id()}'

    def checkpoint_run_state(
        self,
        request: ConsultationRequest,
        status: str,
        result: Optional[ConsultationResult] = None,
        **fields: object,
    ) -> None:
        """Merge a milestone checkpoint into the durable run-state record for
        this consultation (FLOW §8). ``status`` is the milestone reached;
        ``fields`` are the milestone-specific values (e.g. ``url=...``,
        ``monitor_id=...``) that are PERSISTED into the run-state record.

        ``result`` is an OUT-OF-BAND handle used only to record a failed-step
        audit entry if the checkpoint cannot be written — it is a named
        parameter, NOT part of ``fields``, so it is never serialized into the
        record. (Root cause: previously the result was smuggled through
        ``fields['_result']`` and then spread via ``**fields`` into the
        json.dumps'd state, which raised "Object of type ConsultationResult is
        not JSON serializable" on EVERY checkpoint — silently defeating the
        duplicate-send guard because no ``submitted`` record ever persisted.)

        Run-state is a durable idempotency CONVENIENCE, not the system of record
        (that is the Neo4j plan/message rows on success). If Redis is
        unreachable the checkpoint write raises out of the primitive; we do NOT
        let that abort a consultation whose irreversible work may already be in
        flight — we surface it loudly via the step audit and continue. This is
        NOT a silent swallow: the failure is recorded as a visible failed step,
        and the send guard below treats an unreadable run-state as
        "cannot prove a prior send" (it still gates on the live URL/Stop tree)."""
        try:
            self.write_run_state(
                request.request_id(),
                {
                    'status': status,
                    'platform': self.platform,
                    'prompt_hash': request.prompt_hash(),
                    'session_target': request.session_url or 'new',
                    **fields,
                },
            )
        except Exception as exc:  # noqa: BLE001 - surfaced loudly, never swallowed
            if result is not None:
                result.add_step(
                    'run_state_checkpoint', False,
                    f'{self.platform} run-state checkpoint {status!r} failed: {exc}',
                    status=status,
                )

    def guarded_send(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        """Idempotent send seam (FLOW §8). Replaces a driver's direct
        ``self.send_prompt(...)`` call in run().

        1. READ durable run-state for this consultation's stable request_id.
        2. If a prior run reached ``submitted`` (the send landed) AND captured a
           chat URL, RESUME: do NOT re-send. Re-attach to the captured URL,
           seed the result's session URL, register the monitor against it, and
           return True so run() proceeds to monitor/extract the EXISTING turn.
        3. Otherwise perform the real (irreversible) send via the platform
           driver's ``send_prompt``. On success, checkpoint
           ``submitted`` + URL + prompt-hash + monitor-id and register the
           monitor session so the run is observably in-flight.

        A send that the driver could not prove succeeded (``send_prompt``
        returns False) is NOT checkpointed as submitted and NOT registered — per
        FLOW §8 an unproven send must not be treated as monitored."""
        # READ prior run-state FIRST — before writing any checkpoint — so a
        # landed-send record from an earlier run is detected, never clobbered.
        prior = None
        try:
            prior = self.read_run_state(request.request_id())
        except Exception as exc:  # noqa: BLE001 - cannot prove prior, gate on live tree
            result.add_step(
                'run_state_read', False,
                f'{self.platform} run-state read failed ({exc}); '
                f'treating as no prior send and gating on the live URL/Stop tree',
            )

        if self._is_landed_send(prior, request):
            return self._resume_landed_send(prior, request, result)

        # setup_complete milestone: this run reached the pre-send boundary
        # (navigate + model/mode/tools + attach + prompt entry all validated)
        # with no proven prior send. Written AFTER the landed-send check so it
        # never overwrites a prior submitted record.
        self.checkpoint_run_state(
            request, self.RUN_STATE_SETUP_COMPLETE, result=result,
        )

        # No proven prior send → perform the real irreversible send.
        sent = self.send_prompt(request, result)
        if not sent:
            # Unproven send: do not checkpoint submitted, do not register a
            # monitor. run() will return on the False send step.
            return False

        captured_url = (
            result.session_url_after
            or self.runtime.current_url()
            or result.session_url_before
            or ''
        )
        monitor_id = self._monitor_id(request)
        self.checkpoint_run_state(
            request,
            self.RUN_STATE_SUBMITTED,
            result=result,
            url=captured_url,
            monitor_id=monitor_id,
        )
        self._register_monitor(request, result, monitor_id, captured_url)
        return True

    def _is_landed_send(
        self,
        prior: Optional[dict],
        request: ConsultationRequest,
    ) -> bool:
        """True iff the run-state record proves a send for THIS prompt already
        landed (status at/after ``submitted`` AND a captured chat URL).

        The prompt-hash match is required: a stale record whose prompt differs
        (request_id collision is cryptographically improbable, but the field is
        checked anyway) is NOT treated as a landed send for this prompt."""
        if not prior:
            return False
        if prior.get('prompt_hash') != request.prompt_hash():
            return False
        landed_statuses = {
            self.RUN_STATE_SUBMITTED,
            self.RUN_STATE_COMPLETION_OBSERVED,
            self.RUN_STATE_EXTRACTION_DONE,
        }
        if prior.get('status') not in landed_statuses:
            return False
        return bool(prior.get('url'))

    def _resume_landed_send(
        self,
        prior: dict,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        """RESUME a consultation whose send already landed: re-attach to the
        captured chat URL WITHOUT re-sending, re-register the monitor, and let
        run() proceed to monitor/extract the existing turn."""
        captured_url = str(prior.get('url') or '')
        monitor_id = str(prior.get('monitor_id') or self._monitor_id(request))
        # Navigate the existing tab to the captured chat URL so monitor/extract
        # operate on the real in-flight/completed turn. This is navigation, not a
        # send — it produces no new irreversible turn.
        navigated = self.runtime.navigate(captured_url) if captured_url else False
        result.session_url_after = captured_url
        self._register_monitor(request, result, monitor_id, captured_url)
        result.add_step(
            'send', True,
            f'{self.platform} send RESUMED from durable run-state — prior send '
            f'already landed at {captured_url!r}; NOT re-sending (duplicate-send '
            f'guard, FLOW §8 / CONTRACT §10)',
            resumed=True,
            url_after=captured_url,
            prior_status=prior.get('status'),
            navigated=navigated,
        )
        return True

    def _register_monitor(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        monitor_id: str,
        url: str,
    ) -> None:
        """Register (idempotently) the in-flight monitor session for this
        consultation. Registration failure is a loud step (FLOW §8: a dispatch
        that cannot be registered must not be silently treated as monitored),
        but it does not undo a landed send — the run continues so the response
        is still observed/extracted in-process."""
        session = {
            'platform': self.platform,
            'url': url,
            'requester': request.requester or 'unknown',
            'mode': request.mode or '',
            'timeout': request.timeout,
            'request_id': request.request_id(),
            'prompt_hash': request.prompt_hash(),
            'purpose': request.purpose or '',
        }
        try:
            self.register_monitor_session(monitor_id, session)
            result.add_step(
                'monitor_register', True,
                f'{self.platform} monitor session {monitor_id!r} registered',
                monitor_id=monitor_id, url=url,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced loudly, never swallowed
            result.add_step(
                'monitor_register', False,
                f'{self.platform} monitor session registration FAILED: {exc} '
                f'(send landed; run continues in-process)',
                monitor_id=monitor_id,
            )

    def store_consultation(
        self,
        url: str,
        user_prompt: str,
        response_text: str,
        attachments: Optional[List[str]] = None,
    ) -> dict:
        return primitives.store_consultation(
            platform=self.platform,
            url=url,
            user_prompt=user_prompt,
            response_text=response_text,
            attachments=attachments,
        )

    # ------------------------------------------------------------------
    # Shared completion detection (single source of truth)
    # ------------------------------------------------------------------

    def _stop_key(self) -> str:
        """YAML-declared stop-button element key (default 'stop_button')."""
        return self.cfg.get('workflow', {}).get('monitor', {}).get('stop_key') or 'stop_button'

    @staticmethod
    def _snapshot_content_count(snapshot: Snapshot) -> int:
        """Rendered-element count, mirroring runtime.scroll_to_bottom's metric.
        Used by the shared completion detector for hang detection."""
        return sum(len(v) for v in snapshot.mapped.values()) + len(snapshot.unknown)

    def monitor_generation(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        mode: Optional[str] = None,
        seed_stop_seen: bool = False,
    ) -> bool:
        """Poll until the response completes, using the SHARED stop-transition
        detector (consultation_v2.completion.CompletionDetector) — the single
        source of truth that mirrors monitor/central.py::_detect_completion.

        Completion = the stop button was SEEN and is now GONE for the required
        number of cycles (2 for deep modes, 1 otherwise). No content-guess
        fallback (100_TIMES §1). Hang (stop present + content frozen) is logged
        as evidence but never auto-completes.

        ``seed_stop_seen`` lets a driver whose send step already observed the
        stop button mark ever_seen_stop up front, so a sub-second generation
        whose stop button was only visible during send still completes (it is an
        OBSERVATION carried forward, not a content fallback).
        """
        detector_mode = (
            (mode if mode is not None else request.mode) or ''
        ).strip().lower()
        detector = CompletionDetector(mode=detector_mode)
        if seed_stop_seen:
            detector.ever_seen_stop = True
            detector.stop_was_visible = True
        stop_key = self._stop_key()
        hang_logged = False
        completed = False

        def _poll() -> bool:
            nonlocal completed, hang_logged
            snap = self.runtime.snapshot()
            verdict = detector.observe(
                stop_present=snap.has(stop_key),
                content_count=self._snapshot_content_count(snap),
            )
            if verdict == COMPLETE:
                completed = True
                return True
            if verdict == HANG_SUSPECTED and not hang_logged:
                hang_logged = True
                result.add_step(
                    'monitor_hang', False,
                    f'{self.platform} generation SUSPECTED hung '
                    f'(stop present, content frozen >= {detector.frozen_ticks} ticks)',
                    frozen_ticks=detector.frozen_ticks,
                )
            return False

        self.runtime.wait_until(_poll, timeout=float(request.timeout), interval=1.0)
        verify_snap = self.runtime.snapshot()
        verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
        result.add_step(
            'monitor', verified, f'{self.platform} response completed',
            stop_seen=detector.ever_seen_stop, mode=detector_mode or 'default',
            snapshot=verify_snap.serializable(),
        )
        if verified:
            # completion_observed milestone: the Stop button was seen then gone
            # for the required cycles (FLOW §9). Checkpointed so a re-run after a
            # crash between completion and extraction resumes at the captured URL
            # and re-extracts rather than re-sending.
            self.checkpoint_run_state(
                request, self.RUN_STATE_COMPLETION_OBSERVED,
                result=result,
                url=result.session_url_after or self.runtime.current_url() or '',
            )
        return verified

    @abstractmethod
    def run(self, request: ConsultationRequest) -> ConsultationResult:
        raise NotImplementedError
