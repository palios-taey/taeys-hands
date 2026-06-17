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
        return verified

    @abstractmethod
    def run(self, request: ConsultationRequest) -> ConsultationResult:
        raise NotImplementedError
