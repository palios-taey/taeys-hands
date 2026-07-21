"""ChatGPT platform package driver.

This file inlines ChatGPT's pinned W2E effective driver behavior plus the
lifecycle methods it reaches, so ChatGPT owns its driver and monitor code in
this package.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, List, Optional, Tuple

from consultation_v2.identity import build_inline_context
from consultation_v2.platforms.chatgpt.monitor import COMPLETE, DEEP_MODES, ChatGPTCompletionDetector
from consultation_v2.stop_conditions import is_stop_condition
from consultation_v2 import primitives
from consultation_v2 import storage_policy
from consultation_v2.display_readiness import display_for_platform
from consultation_v2.display_watchdog import pause_display_watchdog
from consultation_v2.planner import SelectionPlanError, build_selection_plan, has_selection_menus
from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, ExtractedArtifact, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


DEEP_GENERATION_FLOOR_SECONDS = 1800.0
BASE_CONFORMANCE_CLEAN_SNAPSHOTS = 2
BASE_CONFORMANCE_SETTLE_FLOOR_SECONDS = 25.0
BASE_CONFORMANCE_SETTLE_CEILING_SECONDS = 45.0
CLEAN_COMPOSER_EMPTY_SNAPSHOTS = 2
MONITOR_MIN_HEALTHY_RAW_COUNT = 25
PROMPT_ECHO_FAILURE_MESSAGE = 'extracted text matches prompt - echo, not a response'
INLINE_IDENTITY_ATTACHMENT = 'inline:chatgpt_identity_context'


class _ChatGPTInlineBase:
    platform: str
    _INTERACTIVE_UNKNOWN_ROLES = {
        'button',
        'check box',
        'check menu item',
        'combo box',
        'entry',
        'link',
        'menu item',
        'option',
        'page tab',
        'push button',
        'radio button',
        'radio menu item',
        'slider',
        'spin button',
        'switch',
        'toggle button',
    }

    def __init__(self) -> None:
        self.cfg = load_platform_yaml(self.platform)
        self.runtime = ConsultationRuntime(self.platform)
        self._current_selection_plan: list[dict[str, Any]] | None = None

    def result(self, request: ConsultationRequest) -> ConsultationResult:
        return ConsultationResult(platform=self.platform, request=request)

    def find_first(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.first(key)

    def find_last(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.last(key)

    def element_active_state(self, key: str) -> str | None:
        spec = self.cfg.get('tree', {}).get('element_map', {}).get(key, {})
        state = spec.get('active_state') if isinstance(spec, dict) else None
        return str(state).strip().lower() if state else None

    def element_is_active(self, snapshot: Snapshot, key: str) -> bool:
        active_state = self.element_active_state(key)
        if not active_state:
            return False
        for element in snapshot.mapped.get(key) or []:
            states = {str(state).lower() for state in (element.states or [])}
            if active_state in states:
                return True
        return False

    def active_element_key(self, snapshot: Snapshot, keys: Iterable[str]) -> str | None:
        for key in keys:
            if self.element_is_active(snapshot, key):
                return key
        return None

    def snapshot_has_any(self, snapshot: Snapshot, keys: Iterable[str]) -> bool:
        return any(snapshot.has(key) for key in keys)

    def find_first_any(self, snapshot: Snapshot, keys: Iterable[str]) -> tuple[str | None, Optional[ElementRef]]:
        for key in keys:
            element = self.find_first(snapshot, key)
            if element:
                return key, element
        return None, None

    def tree_conformance_gate(
        self,
        result: ConsultationResult,
        snapshot: Snapshot | None = None,
        surface: str | None = None,
    ) -> bool:
        surface = surface or ('base' if self._uses_identity_schema() else None)
        settle_evidence: dict[str, object] = {}
        if snapshot is None and surface == 'base':
            snap, discrepancies, missing, by_role, settle_evidence = (
                self._settled_base_conformance_findings()
            )
        else:
            snap = snapshot or self._conformance_snapshot(surface)
            discrepancies, missing, by_role = self._conformance_findings(snap, surface)
        if not discrepancies and not missing:
            return True
        if discrepancies:
            drift_controls = snap.unknown if surface == 'base' else None
            dismissed = self.runtime.close_all_popups(drift_controls=drift_controls)
            (
                recovered_snap,
                recovered_discrepancies,
                recovered_missing,
                recovered_by_role,
                recovery_elapsed,
            ) = self._post_popup_recovery_findings(surface, discrepancies)
            if not recovered_discrepancies and not recovered_missing:
                result.add_step(
                    'popup_recovery',
                    True,
                    f'{self.platform} cleared transient popup drift on {surface or "unscoped"}',
                    surface=surface,
                    dismissed=dismissed,
                    recovery_elapsed_seconds=round(recovery_elapsed, 3),
                    before_unknown=discrepancies,
                    snapshot=recovered_snap.serializable(),
                )
                return True
            snap = recovered_snap
            discrepancies = recovered_discrepancies
            missing = recovered_missing
            by_role = recovered_by_role
            if surface == 'base' and discrepancies and not missing:
                result.add_step(
                    'tree_conformance_drift',
                    True,
                    (
                        f'{self.platform} base conformance observed unknown extra '
                        'element(s); expected elements present, proceeding'
                    ),
                    surface=surface,
                    unknown=discrepancies,
                    by_role=by_role,
                    snapshot=snap.serializable(),
                )
                return True
            if dismissed:
                result.add_step(
                    'popup_recovery',
                    False,
                    f'{self.platform} popup recovery ran but conformance drift persisted',
                    surface=surface,
                    dismissed=dismissed,
                    recovery_elapsed_seconds=round(recovery_elapsed, 3),
                    unknown=discrepancies,
                    missing=missing,
                    by_role=by_role,
                    snapshot=snap.serializable(),
                    **settle_evidence,
                )
        result.add_step(
            'tree_conformance',
            False,
            (
                f'{self.platform} tree conformance failed on {surface or "unscoped"}: '
                f'{len(discrepancies)} unknown live element(s), '
                f'{len(missing)} expected element(s) missing'
            ),
            surface=surface,
            unknown=discrepancies,
            missing=missing,
            by_role=by_role,
            snapshot=snap.serializable(),
            **settle_evidence,
        )
        return False

    def _conformance_findings(
        self,
        snapshot: Snapshot,
        surface: str | None,
    ) -> tuple[list[dict[str, str | None]], list[dict[str, object]], dict[str, int]]:
        expected_keys = self._expected_keys_for_surface(surface)
        menu_surface = self._conformance_surface_is_menu_only(surface, expected_keys)
        if self._conformance_menu_surface_closed(snapshot, surface, expected_keys):
            return [], [], {}
        discrepancies = [] if menu_surface else self._conformance_unknown_discrepancies(snapshot, surface)
        missing = self._missing_expected_elements(snapshot, surface, expected_keys=expected_keys)
        by_role: dict[str, int] = {}
        for item in discrepancies:
            role = item['role'] or ''
            by_role[role] = by_role.get(role, 0) + 1
        return discrepancies, missing, by_role

    def _conformance_unknown_discrepancies(
        self,
        snapshot: Snapshot,
        surface: str | None,
    ) -> list[dict[str, str | None]]:
        return [
            {'role': item.role, 'name': item.name}
            for item in (snapshot.unknown or [])
            if not (
                surface == 'base'
                and self._is_incidental_base_unknown(item)
            )
        ]

    @classmethod
    def _is_incidental_base_unknown(cls, item: ElementRef) -> bool:
        name = (item.name or '').strip()
        role = (item.role or '').strip().lower()
        if role == 'link' and (name.startswith('http://') or name.startswith('https://')):
            return True
        return not name and role not in cls._INTERACTIVE_UNKNOWN_ROLES

    def _conformance_snapshot(self, surface: str | None) -> Snapshot:
        if surface == 'base':
            return self.runtime.wait_for_stable_snapshot(
                anchor_key=self._conformance_anchor_key(surface),
                require_non_empty=True,
            )
        if surface:
            return self.runtime.wait_for_stable_menu_snapshot(
                consecutive=2,
                timeout=max(self._selection_settle_seconds() + 1.0, 3.0),
                interval=0.2,
                require_non_empty=True,
            )
        return self.runtime.snapshot()

    def _settled_base_conformance_findings(
        self,
    ) -> tuple[Snapshot, list[dict[str, str | None]], list[dict[str, object]], dict[str, int], dict[str, object]]:
        started = time.monotonic()
        timeout = self._base_conformance_settle_seconds()
        deadline = started + timeout
        required_clean = self._base_conformance_clean_snapshots()
        anchor_key = self._conformance_anchor_key('base')
        clean_samples = 0
        probes = 0
        last_snapshot: Snapshot | None = None
        last_findings: tuple[list[dict[str, str | None]], list[dict[str, object]], dict[str, int]] | None = None

        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=2,
                timeout=min(remaining, 1.2),
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
            probes += 1
            last_findings = self._conformance_findings(last_snapshot, 'base')
            discrepancies, missing, by_role = last_findings
            if not discrepancies and not missing:
                clean_samples += 1
                if clean_samples >= required_clean:
                    return last_snapshot, discrepancies, missing, by_role, {
                        'base_conformance_clean_samples': clean_samples,
                        'base_conformance_required_clean_samples': required_clean,
                        'base_conformance_probes': probes,
                        'base_conformance_elapsed_seconds': round(time.monotonic() - started, 3),
                    }
            else:
                clean_samples = 0
            time.sleep(0.2)

        if last_snapshot is None or last_findings is None:
            last_snapshot = self._conformance_snapshot('base')
            last_findings = self._conformance_findings(last_snapshot, 'base')
        discrepancies, missing, by_role = last_findings
        return last_snapshot, discrepancies, missing, by_role, {
            'base_conformance_clean_samples': clean_samples,
            'base_conformance_required_clean_samples': required_clean,
            'base_conformance_probes': probes,
            'base_conformance_elapsed_seconds': round(time.monotonic() - started, 3),
            'base_conformance_timeout_seconds': timeout,
        }

    def _base_conformance_clean_snapshots(self) -> int:
        settle = self.cfg.get('settle') or {}
        value = (
            settle.get('base_conformance_clean_snapshots', BASE_CONFORMANCE_CLEAN_SNAPSHOTS)
            if isinstance(settle, dict)
            else BASE_CONFORMANCE_CLEAN_SNAPSHOTS
        )
        try:
            return min(max(int(value), 2), 5)
        except (TypeError, ValueError):
            return BASE_CONFORMANCE_CLEAN_SNAPSHOTS

    def _base_conformance_settle_seconds(self) -> float:
        settle = self.cfg.get('settle') or {}
        candidates = [self._selection_settle_seconds()]
        if isinstance(settle, dict):
            for key in ('base_conformance_ms', 'clean_base_ms', 'navigate_ms', 'selection_ms', 'default_ms'):
                value = settle.get(key)
                try:
                    candidates.append(max(0.0, float(value) / 1000.0))
                except (TypeError, ValueError):
                    continue
        seconds = max(candidates or [0.0]) + 4.0
        return min(
            max(seconds, BASE_CONFORMANCE_SETTLE_FLOOR_SECONDS),
            BASE_CONFORMANCE_SETTLE_CEILING_SECONDS,
        )

    def _post_popup_recovery_findings(
        self,
        surface: str | None,
        before_discrepancies: list[dict[str, str | None]],
    ) -> tuple[Snapshot, list[dict[str, str | None]], list[dict[str, object]], dict[str, int], float]:
        started = time.monotonic()
        if surface != 'base':
            snap = self._conformance_snapshot(surface)
            discrepancies, missing, by_role = self._conformance_findings(snap, surface)
            return snap, discrepancies, missing, by_role, time.monotonic() - started

        timeout = self._popup_recovery_settle_seconds()
        deadline = time.monotonic() + timeout
        anchor_key = self._conformance_anchor_key(surface)
        last_snapshot: Snapshot | None = None
        last_findings: tuple[list[dict[str, str | None]], list[dict[str, object]], dict[str, int]] | None = None

        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=1,
                timeout=min(remaining, 0.8),
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
            last_findings = self._conformance_findings(last_snapshot, surface)
            discrepancies, missing, by_role = last_findings
            if not discrepancies and not missing:
                return last_snapshot, discrepancies, missing, by_role, time.monotonic() - started
            if not self._conformance_discrepancies_still_present(discrepancies, before_discrepancies):
                return last_snapshot, discrepancies, missing, by_role, time.monotonic() - started
            time.sleep(0.2)

        if last_snapshot is None or last_findings is None:
            last_snapshot = self._conformance_snapshot(surface)
            last_findings = self._conformance_findings(last_snapshot, surface)
        discrepancies, missing, by_role = last_findings
        return last_snapshot, discrepancies, missing, by_role, time.monotonic() - started

    def _popup_recovery_settle_seconds(self) -> float:
        settle = self.cfg.get('settle') or {}
        value = settle.get('popup_recovery_ms', 5000) if isinstance(settle, dict) else 5000
        try:
            seconds = float(value) / 1000.0
        except (TypeError, ValueError):
            seconds = 5.0
        return min(max(seconds, 3.0), 5.0)

    @classmethod
    def _conformance_discrepancies_still_present(
        cls,
        current: list[dict[str, str | None]],
        before: list[dict[str, str | None]],
    ) -> bool:
        before_keys = {cls._conformance_discrepancy_key(item) for item in before}
        return any(cls._conformance_discrepancy_key(item) in before_keys for item in current)

    @staticmethod
    def _conformance_discrepancy_key(item: dict[str, str | None]) -> tuple[str, str]:
        return (
            str(item.get('role') or '').strip().lower(),
            str(item.get('name') or '').strip(),
        )

    def _conformance_anchor_key(self, surface: str | None) -> str | None:
        if surface != 'base':
            return None
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        if not isinstance(element_map, dict):
            return None
        for key in self._expected_keys_for_surface(surface):
            spec = element_map.get(key)
            if not isinstance(spec, dict):
                continue
            role = str(spec.get('role') or '').strip().lower()
            scope = str(spec.get('scope') or '').strip().lower()
            if role == 'entry' and (
                scope == 'base.composer' or scope.startswith('base.composer.')
            ):
                return key
        return None

    def _uses_identity_schema(self) -> bool:
        return (
            self.cfg.get('schema') == 'identity_v1'
            or (self.cfg.get('tree') or {}).get('schema') == 'identity_v1'
        )

    def _expected_keys_for_surface(self, surface: str | None) -> tuple[str, ...]:
        if not surface:
            return ()
        conformance = (self.cfg.get('tree') or {}).get('conformance') or {}
        scopes = conformance.get('scopes') or {}
        scope_cfg = scopes.get(surface) or {}
        expected = scope_cfg.get('expected') or []
        if not isinstance(expected, list):
            return ()
        return tuple(str(key) for key in expected if isinstance(key, str) and key)

    def _conformance_menu_surface_closed(
        self,
        snapshot: Snapshot,
        surface: str | None,
        expected_keys: tuple[str, ...],
    ) -> bool:
        if not surface or surface == 'base' or not expected_keys:
            return False
        if any(snapshot.has(key) for key in expected_keys):
            return False
        return self._conformance_surface_is_menu_only(surface, expected_keys)

    def _conformance_surface_is_menu_only(
        self,
        surface: str | None,
        expected_keys: tuple[str, ...],
    ) -> bool:
        if not surface or not expected_keys:
            return False
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        if not isinstance(element_map, dict):
            return False
        return all(self._is_menu_scoped_element(element_map.get(key), surface) for key in expected_keys)

    @staticmethod
    def _is_menu_scoped_element(spec: object, surface: str) -> bool:
        if not isinstance(spec, dict):
            return False
        role = str(spec.get('role') or '').strip().lower()
        scope = str(spec.get('scope') or '').strip()
        return (
            role in {'check menu item', 'menu item', 'option', 'radio menu item'}
            and (scope == surface or scope.startswith(f'{surface}.'))
        )

    def _missing_expected_elements(
        self,
        snapshot: Snapshot,
        surface: str | None,
        *,
        expected_keys: tuple[str, ...] | None = None,
    ) -> list[dict[str, object]]:
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        missing: list[dict[str, object]] = []
        for key in expected_keys if expected_keys is not None else self._expected_keys_for_surface(surface):
            if snapshot.has(key):
                continue
            spec = element_map.get(key) if isinstance(element_map, dict) else {}
            spec = spec if isinstance(spec, dict) else {}
            payload: dict[str, object] = {
                'key': key,
                'role': spec.get('role'),
                'scope': spec.get('scope'),
            }
            if spec.get('name') is not None:
                payload['name'] = spec.get('name')
            if spec.get('match_strategy') is not None:
                payload['match_strategy'] = spec.get('match_strategy')
            missing.append(payload)
        return missing

    def wait_for_page_ready_after_navigation(
        self,
        result: ConsultationResult,
        *,
        timeout: float = 15.0,
    ) -> bool:
        timeout = max(float(timeout), self._base_conformance_settle_seconds())
        groups = self._page_ready_key_groups()
        started = time.time()
        last_snapshot: Snapshot | None = None
        missing = self._page_ready_group_labels(groups)

        def _probe() -> Snapshot | None:
            nonlocal last_snapshot, missing
            last_snapshot = self.runtime.snapshot()
            missing = self._page_ready_missing_groups(last_snapshot, groups)
            return last_snapshot if not missing else None

        matched = self.runtime.wait_until(_probe, timeout=timeout, interval=0.4)
        if isinstance(matched, Snapshot):
            elapsed = round(time.time() - started, 2)
            result.add_step(
                'page_ready',
                True,
                f'{self.platform} page ready after navigation',
                required=self._page_ready_group_labels(groups),
                optional_present=self._page_ready_present_optional_keys(matched),
                elapsed_seconds=elapsed,
                snapshot=matched.serializable(),
            )
            return True

        snapshot = last_snapshot or self.runtime.snapshot()
        dismissed = self.runtime.close_all_popups(drift_controls=snapshot.unknown)
        if dismissed:
            recovery_started = time.time()
            matched = self.runtime.wait_until(
                _probe,
                timeout=self._popup_recovery_settle_seconds(),
                interval=0.4,
            )
            if isinstance(matched, Snapshot):
                elapsed = round(time.time() - started, 2)
                result.add_step(
                    'popup_recovery',
                    True,
                    f'{self.platform} cleared transient popup before page-ready',
                    dismissed=dismissed,
                    recovery_elapsed_seconds=round(time.time() - recovery_started, 2),
                    snapshot=matched.serializable(),
                )
                result.add_step(
                    'page_ready',
                    True,
                    f'{self.platform} page ready after navigation',
                    required=self._page_ready_group_labels(groups),
                    optional_present=self._page_ready_present_optional_keys(matched),
                    elapsed_seconds=elapsed,
                    snapshot=matched.serializable(),
                )
                return True
            snapshot = last_snapshot or self.runtime.snapshot()
        result.add_step(
            'page_ready',
            False,
            f'{self.platform} page did not expose required controls after navigation',
            required=self._page_ready_group_labels(groups),
            missing=missing,
            optional_present=self._page_ready_present_optional_keys(snapshot),
            timeout_seconds=timeout,
            dismissed_popups=dismissed,
            snapshot=snapshot.serializable(),
        )
        return False

    def _page_ready_key_groups(self) -> tuple[tuple[str, ...], ...]:
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        if not isinstance(element_map, dict):
            return ()
        groups: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()

        def add_group(keys: Iterable[str]) -> None:
            group = tuple(
                key
                for key in dict.fromkeys(str(key).strip() for key in keys if str(key).strip())
                if key in element_map
            )
            if group and group not in seen:
                seen.add(group)
                groups.append(group)

        # Page readiness is narrower than base conformance: some platform
        # snapshots intentionally exclude sidebar/nav chrome, so this gate uses
        # only workflow controls required to interact with the composer.
        for key in self._selection_trigger_keys():
            add_group((key,))

        input_keys = self._workflow_prompt_keys(
            'input',
            'input_fallback',
            'input_keys',
            'input_candidates',
        )
        add_group(input_keys)

        attachment = (self.cfg.get('workflow') or {}).get('attachment') or {}
        trigger = attachment.get('trigger') if isinstance(attachment, dict) else None
        if isinstance(trigger, str):
            add_group((trigger,))

        return tuple(groups)

    def _selection_trigger_keys(self) -> tuple[str, ...]:
        workflow = self.cfg.get('workflow') or {}
        selection = workflow.get('selection') or {}
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        if not isinstance(selection, dict) or not isinstance(element_map, dict):
            return ()
        keys: list[str] = []
        menus = selection.get('menus')
        if isinstance(menus, dict):
            for menu in menus.values():
                if not isinstance(menu, dict):
                    continue
                operate = menu.get('operate') or {}
                if isinstance(operate, dict) and isinstance(operate.get('trigger'), str):
                    keys.append(operate['trigger'])

        model_targets = selection.get('model_targets')
        mode_targets = selection.get('mode_targets')
        tool_targets = selection.get('tool_targets')
        if isinstance(model_targets, dict) and model_targets:
            if 'mode_picker' in element_map:
                keys.append('mode_picker')
            elif 'model_selector' in element_map:
                keys.append('model_selector')
        if isinstance(mode_targets, dict) and mode_targets:
            if isinstance(model_targets, dict) and model_targets and 'model_selector' in element_map:
                keys.append('model_selector')
            elif 'attach_trigger' in element_map:
                keys.append('attach_trigger')
            elif 'mode_picker' in element_map:
                keys.append('mode_picker')
        if isinstance(tool_targets, dict) and tool_targets:
            if 'tools_button' in element_map:
                keys.append('tools_button')
            elif 'upload_menu' in element_map:
                keys.append('upload_menu')
            elif 'attach_trigger' in element_map:
                keys.append('attach_trigger')
        return tuple(dict.fromkeys(keys))

    def _workflow_prompt_keys(self, *names: str) -> tuple[str, ...]:
        prompt = (self.cfg.get('workflow') or {}).get('prompt') or {}
        if not isinstance(prompt, dict):
            return ()
        keys: list[str] = []
        for name in names:
            value = prompt.get(name)
            if isinstance(value, str):
                keys.append(value)
            elif isinstance(value, list):
                keys.extend(str(item) for item in value if isinstance(item, str))
        return tuple(dict.fromkeys(key for key in keys if key))

    def _page_ready_optional_keys(self) -> tuple[str, ...]:
        return self._workflow_prompt_keys('send_button', 'send_button_keys')

    def _page_ready_present_optional_keys(self, snapshot: Snapshot) -> list[str]:
        return [
            key for key in self._page_ready_optional_keys()
            if snapshot.has(key)
        ]

    @staticmethod
    def _page_ready_group_labels(groups: tuple[tuple[str, ...], ...]) -> list[str]:
        return [
            group[0] if len(group) == 1 else '|'.join(group)
            for group in groups
        ]

    def _page_ready_missing_groups(
        self,
        snapshot: Snapshot,
        groups: tuple[tuple[str, ...], ...],
    ) -> list[str]:
        return [
            group[0] if len(group) == 1 else '|'.join(group)
            for group in groups
            if not any(snapshot.has(key) for key in group)
        ]

    def validation_passes(self, snapshot: Snapshot, validation_key: str, filename: str | None = None) -> bool:
        validations = self.cfg.get('validation', {})
        if validation_key not in validations:
            return False
        raw_validation = validations.get(validation_key)
        if not isinstance(raw_validation, dict) or not raw_validation:
            return False
        validation = dict(raw_validation)

        if validation.get('best_effort'):
            return False

        if 'url_contains' in validation:  # lint-allow: fail-loud rejection; URL substrings are not tree validation
            return False

        checked_tree = False
        indicators = validation.get('indicators') or []
        if indicators:
            checked_tree = True
            all_elements: List[ElementRef] = []
            for items in getattr(snapshot, 'mapped', {}).values():
                all_elements.extend(items)
            all_elements.extend(getattr(snapshot, 'unknown', []) or [])
            all_elements.extend(getattr(snapshot, 'sidebar', []) or [])
            all_elements.extend(getattr(snapshot, 'menu_items', []) or [])

            found = False
            for indicator in indicators:
                if any(matches_spec(element, indicator) for element in all_elements):
                    found = True
                    break
            if not found:
                return False

        file_chip = validation.get('file_chip')
        if filename and file_chip:
            checked_tree = True
            if isinstance(file_chip, str):
                chip_key = file_chip
            elif isinstance(file_chip, dict):
                chip_key = file_chip.get('element') or file_chip.get('key')
            else:
                chip_key = None
            if chip_key:
                if not snapshot.has(str(chip_key)):
                    return False
            elif isinstance(file_chip, dict):
                roles = file_chip.get('roles')
                if not isinstance(roles, list) or not roles:
                    return False
                expected_path = os.path.abspath(filename)
                expected_name = os.path.basename(filename)
                allowed_roles = {str(role) for role in roles if isinstance(role, str) and role}
                all_elements: List[ElementRef] = []
                for items in getattr(snapshot, 'mapped', {}).values():
                    all_elements.extend(items)
                all_elements.extend(getattr(snapshot, 'unknown', []) or [])
                all_elements.extend(getattr(snapshot, 'sidebar', []) or [])
                all_elements.extend(getattr(snapshot, 'menu_items', []) or [])

                def chip_name_matches(display_name: str) -> bool:
                    displayed_file = display_name.split()[0] if display_name else ''
                    for expected in (expected_path, expected_name):
                        if display_name == expected or displayed_file == expected:
                            return True
                        if '...' in displayed_file:
                            prefix, suffix = displayed_file.split('...', 1)
                            if expected.startswith(prefix) and expected.endswith(suffix):
                                return True
                    return False

                def element_value(element: ElementRef | dict, key: str) -> str:
                    if isinstance(element, dict):
                        return str(element.get(key) or '')
                    return str(getattr(element, key, '') or '')

                if not any(
                    any(
                        chip_name_matches(element_value(element, field))
                        for field in ('name', 'description', 'text')
                    )
                    and element_value(element, 'role') in allowed_roles
                    for element in all_elements
                ):
                    return False
            else:
                return False

        absent = validation.get('absent') or []
        if absent:
            checked_tree = True
            absent_keys = absent if isinstance(absent, list) else [absent]
            for absent_key in absent_keys:
                if not isinstance(absent_key, str) or absent_key not in self.cfg.get('tree', {}).get('element_map', {}):
                    return False
                if snapshot.has(absent_key):
                    return False

        if validation.get('stop_present'):
            checked_tree = True
            stop_present = validation.get('stop_present')
            stop_key = (
                stop_present
                if isinstance(stop_present, str)
                else self.cfg.get('workflow', {}).get('monitor', {}).get('stop_key') or 'stop_button'
            )
            if not snapshot.has(stop_key):
                return False

        if validation.get('stop_absent'):
            checked_tree = True
            stop_absent = validation.get('stop_absent')
            stop_key = (
                stop_absent
                if isinstance(stop_absent, str)
                else self.cfg.get('workflow', {}).get('monitor', {}).get('stop_key') or 'stop_button'
            )
            if snapshot.has(stop_key):
                return False
        if not checked_tree:
            return False
        return True

    def _scoped_snapshot(self, scope: str) -> Snapshot:
        normalized = (scope or 'document').strip().lower()
        if normalized in {'document', 'snapshot'}:
            return self.runtime.snapshot()
        if normalized in {'menu', 'menu_snapshot'}:
            return self.runtime.menu_snapshot()
        if normalized in {'app_root', 'app_root_snapshot'}:
            return self.runtime.app_root_snapshot()
        raise ValueError(f'Unknown AT-SPI snapshot scope {scope!r}')

    def wait_for_validation(
        self,
        validation_key: str,
        *,
        filename: str | None = None,
        timeout: float = 5.0,
        interval: float = 0.4,
        scope: str = 'document',
    ) -> Snapshot:
        """Return a fresh tree snapshot after bounded AT-SPI settle.

        This is observation-only: it repeatedly refreshes the requested AT-SPI
        tree scope until the YAML validation passes or the timeout expires. It
        never repeats the action that preceded it.
        """
        last_snapshot: Snapshot | None = None

        def _probe() -> Snapshot | None:
            nonlocal last_snapshot
            last_snapshot = self._scoped_snapshot(scope)
            if self.validation_passes(last_snapshot, validation_key, filename=filename):
                return last_snapshot
            return None

        matched = self.runtime.wait_until(_probe, timeout=timeout, interval=interval)
        if isinstance(matched, Snapshot):
            return matched
        return last_snapshot or self._scoped_snapshot(scope)

    def wait_for_key(
        self,
        key: str,
        *,
        timeout: float = 5.0,
        interval: float = 0.4,
        scope: str = 'document',
        select: str = 'first',
    ) -> Tuple[Snapshot, Optional[ElementRef]]:
        """Return a fresh tree snapshot and mapped element after bounded settle.

        The action itself is still single-shot; this helper only gives AT-SPI
        time to expose the expected element after the UI changes.
        """
        last_snapshot: Snapshot | None = None

        def _probe() -> ElementRef | None:
            nonlocal last_snapshot
            last_snapshot = self._scoped_snapshot(scope)
            if select == 'last':
                return last_snapshot.last(key)
            return last_snapshot.first(key)

        element = self.runtime.wait_until(_probe, timeout=timeout, interval=interval)
        if isinstance(element, ElementRef):
            return last_snapshot or self._scoped_snapshot(scope), element
        return last_snapshot or self._scoped_snapshot(scope), None

    def apply_selection_plan(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        plan = self._current_selection_plan
        if plan is None:
            result.add_step(
                'selection_plan',
                False,
                'Selection plan missing before SELECT; driver.run must gate before browser action',
            )
            return False
        self._selection_menu_transition_seen = False
        for step in plan:
            if step.get('skip'):
                result.add_step(
                    'select',
                    True,
                    f"{self.platform} selection {step['menu']} intentionally {step['value']}",
                    menu=step['menu'],
                    value=step['value'],
                    because=step.get('because') or '',
                )
                continue
            if not self._apply_selection_step(step, result):
                return False
        return True

    def _apply_selection_step(self, step: dict[str, Any], result: ConsultationResult) -> bool:
        menu = str(step['menu'])
        option = str(step['option'])
        operate = dict(step['operate'])
        scope = str(operate['scope'])
        trigger_key = str(operate['trigger'])
        target_key = str(step['element'])
        active_element_key = str(step.get('active_element') or '').strip()
        active_trigger_names = tuple(
            str(name).strip()
            for name in (step.get('active_trigger_names') or [])
            if str(name).strip()
        )
        typeahead_label = str(step.get('typeahead_label') or '').strip()
        postcondition = step.get('postcondition') if isinstance(step.get('postcondition'), dict) else {}
        click_strategy = str(step.get('click_strategy') or 'atspi_only')
        path = list(step.get('path') or [])
        first_key = str(path[0]['element']) if path else target_key

        if active_trigger_names:
            active_snapshot, active_present, trigger_name = self._selection_wait_for_active_trigger(
                trigger_key,
                active_trigger_names,
                timeout=0.8,
            )
            if active_present:
                result.add_step(
                    'select',
                    True,
                    f'{self.platform} {menu}={option} already active',
                    menu=menu,
                    option=option,
                    confirmation='active_trigger_name',
                    active_trigger=trigger_key,
                    active_trigger_names=list(active_trigger_names),
                    observed_trigger_name=trigger_name,
                    snapshot=active_snapshot.serializable(),
                )
                return True

        if active_element_key:
            active_snapshot, active_present = self._selection_wait_for_active_element(
                active_element_key,
                timeout=0.8,
            )
            if active_present:
                result.add_step(
                    'select',
                    True,
                    f'{self.platform} {menu}={option} already active',
                    menu=menu,
                    option=option,
                    confirmation='active_element_present',
                    active_element=active_element_key,
                    snapshot=active_snapshot.serializable(),
                )
                return True

        if typeahead_label:
            return self._apply_typeahead_selection_step(
                menu=menu,
                option=option,
                operate=operate,
                trigger_key=trigger_key,
                typeahead_label=typeahead_label,
                postcondition=dict(postcondition or {}),
                result=result,
            )

        opened = self._open_selection_menu(trigger_key, first_key, scope, result)
        if opened is None:
            return False
        snapshot, _ = opened
        target_snapshot, target = self._walk_selection_path(snapshot, path, target_key, scope, result)
        if target is None:
            return False
        active_state = str(step['active_recognition'])
        if (
            not active_element_key
            and not active_trigger_names
            and self._selection_element_matches_active_recognition(target, active_state)
        ):
            closed_snapshot, closed = self._selection_close_active_selection_menu()
            if not closed:
                result.add_step(
                    'select',
                    False,
                    f'{self.platform} {menu}={option} active but menu did not close after Escape',
                    menu=menu,
                    option=option,
                    active_state=active_state,
                    snapshot=closed_snapshot.serializable(),
                )
                return False
            result.add_step(
                'select',
                True,
                f'{self.platform} {menu}={option} already active',
                menu=menu,
                option=option,
                active_state=active_state,
                snapshot=target_snapshot.serializable(),
                closed_snapshot=closed_snapshot.serializable(),
            )
            return True
        target_snapshot, target = self._selection_wait_for_click_ready(
            target_key,
            scope,
            target_snapshot,
            target,
            strategy=click_strategy,
        )
        if target is None or not self._selection_element_click_ready(target, click_strategy):
            result.add_step(
                'select',
                False,
                f'{self.platform} {menu}={option} target not click-ready after bounded settle-rescan',
                menu=menu,
                option=option,
                click_strategy=click_strategy,
                readiness=self._selection_click_readiness(target, click_strategy),
                snapshot=target_snapshot.serializable(),
            )
            return False
        if (
            not active_element_key
            and not active_trigger_names
            and self._selection_element_matches_active_recognition(target, active_state)
        ):
            closed_snapshot, closed = self._selection_close_active_selection_menu()
            if not closed:
                result.add_step(
                    'select',
                    False,
                    f'{self.platform} {menu}={option} active after settle but menu did not close after Escape',
                    menu=menu,
                    option=option,
                    active_state=active_state,
                    confirmation='post_settle_active_state',
                    snapshot=closed_snapshot.serializable(),
                )
                return False
            result.add_step(
                'select',
                True,
                f'{self.platform} {menu}={option} already active',
                menu=menu,
                option=option,
                active_state=active_state,
                confirmation='post_settle_active_state',
                snapshot=target_snapshot.serializable(),
                closed_snapshot=closed_snapshot.serializable(),
            )
            return True
        if not self.runtime.click(target, strategy=click_strategy):
            result.add_step(
                'select',
                False,
                f'{self.platform} {menu}={option} click failed',
                menu=menu,
                option=option,
                click_strategy=click_strategy,
                snapshot=target_snapshot.serializable(),
            )
            return False
        time.sleep(0.3)
        self.runtime.press('Escape')
        if active_state.strip().lower() == 'click_only':
            closed_snapshot = self._selection_wait_for_menu_closed()
            closed = int(closed_snapshot.raw_count or 0) == 0
            result.add_step(
                'select',
                closed,
                (
                    f'{self.platform} selected {menu}={option}'
                    if closed
                    else f'{self.platform} {menu}={option} click landed but menu surface stayed open'
                ),
                menu=menu,
                option=option,
                confirmation='click_only_menu_closed',
                snapshot=closed_snapshot.serializable(),
            )
            return closed
        if active_element_key:
            active_snapshot, active_present = self._selection_wait_for_active_element(active_element_key)
            result.add_step(
                'select',
                active_present,
                (
                    f'{self.platform} selected {menu}={option}'
                    if active_present
                    else f'{self.platform} {menu}={option} did not expose active element after bounded settle-rescan'
                ),
                menu=menu,
                option=option,
                confirmation='active_element_present',
                active_element=active_element_key,
                snapshot=active_snapshot.serializable(),
            )
            return active_present
        if active_trigger_names:
            active_snapshot, active_present, trigger_name = self._selection_wait_for_active_trigger(
                trigger_key,
                active_trigger_names,
            )
            result.add_step(
                'select',
                active_present,
                (
                    f'{self.platform} selected {menu}={option}'
                    if active_present
                    else f'{self.platform} {menu}={option} did not expose exact trigger name after bounded settle-rescan'
                ),
                menu=menu,
                option=option,
                confirmation='active_trigger_name',
                active_trigger=trigger_key,
                active_trigger_names=list(active_trigger_names),
                observed_trigger_name=trigger_name,
                snapshot=active_snapshot.serializable(),
            )
            return active_present
        time.sleep(0.2)
        verify_opened = self._open_selection_menu(trigger_key, first_key, scope, result)
        if verify_opened is None:
            return False
        verify_snapshot, _ = verify_opened
        verify_snapshot, verified_target = self._walk_selection_path(
            verify_snapshot,
            path,
            target_key,
            scope,
            result,
        )
        if verified_target is None:
            return False
        verify_snapshot, verified_target, verified = self._selection_wait_for_active_state(
            target_key,
            active_state,
            scope,
        )
        result.add_step(
            'select',
            verified,
            (
                f'{self.platform} selected {menu}={option}'
                if verified
                else f'{self.platform} {menu}={option} did not show {active_state} after bounded settle-rescan'
            ),
            menu=menu,
            option=option,
            active_state=active_state,
            confirmation='menu_active_state',
            snapshot=verify_snapshot.serializable(),
        )
        self.runtime.press('Escape')
        return verified

    def _apply_typeahead_selection_step(
        self,
        *,
        menu: str,
        option: str,
        operate: dict[str, Any],
        trigger_key: str,
        typeahead_label: str,
        postcondition: dict[str, Any],
        result: ConsultationResult,
    ) -> bool:
        open_method = str(operate.get('open_method') or 'click').strip().lower()
        if open_method != 'focus_and_key_open':
            result.add_step(
                'select',
                False,
                f'{self.platform} {menu}={option} typeahead requires focus_and_key_open',
                menu=menu,
                option=option,
                open_method=open_method,
            )
            return False
        postcondition_key = str(postcondition.get('element') or '').strip()
        if not postcondition_key:
            result.add_step(
                'select',
                False,
                f'{self.platform} {menu}={option} typeahead has no mapped postcondition',
                menu=menu,
                option=option,
            )
            return False
        if not self._selection_prepare_base_for_menu(result):
            return False
        trigger_snapshot, trigger = self._selection_find_once(trigger_key, 'snapshot')
        if trigger is None:
            result.add_step(
                'select',
                False,
                f'{self.platform} selection trigger {trigger_key} not found',
                trigger=trigger_key,
                snapshot=trigger_snapshot.serializable(),
            )
            return False
        open_evidence = self.runtime.focus_and_key_open(
            trigger,
            key=str(operate.get('open_key') or 'space'),
            settle=0.3,
        )
        if not open_evidence.get('ok'):
            result.add_step(
                'select',
                False,
                f'{self.platform} {menu}={option} tools menu did not open from focused trigger',
                menu=menu,
                option=option,
                trigger=trigger_key,
                open_evidence=open_evidence,
                snapshot=trigger_snapshot.serializable(),
            )
            return False
        if not self.runtime.type_text(typeahead_label, delay_ms=5):
            result.add_step(
                'select',
                False,
                f'{self.platform} {menu}={option} typeahead text entry failed',
                menu=menu,
                option=option,
                typeahead_label=typeahead_label,
                open_evidence=open_evidence,
                snapshot=trigger_snapshot.serializable(),
            )
            return False
        submit_keys = operate.get('typeahead_submit_keys') or ['Down', 'Return']
        for key in submit_keys:
            if not self.runtime.press(str(key)):
                result.add_step(
                    'select',
                    False,
                    f'{self.platform} {menu}={option} typeahead submit key failed',
                    menu=menu,
                    option=option,
                    typeahead_label=typeahead_label,
                    submit_key=str(key),
                    open_evidence=open_evidence,
                    snapshot=trigger_snapshot.serializable(),
                )
                return False
            time.sleep(0.15)
        timeout_ms = postcondition.get('timeout_ms', 6000)
        try:
            timeout = max(0.1, float(timeout_ms) / 1000.0)
        except (TypeError, ValueError):
            timeout = 6.0
        scope = str(postcondition.get('scope') or 'snapshot')
        post_snapshot, post_present = self._selection_wait_for_typeahead_postcondition(
            postcondition_key,
            scope,
            timeout=timeout,
        )
        result.add_step(
            'select',
            post_present,
            (
                f'{self.platform} selected {menu}={option}'
                if post_present
                else f'{self.platform} {menu}={option} did not expose mapped postcondition after typeahead'
            ),
            menu=menu,
            option=option,
            confirmation='typeahead_postcondition',
            typeahead_label=typeahead_label,
            postcondition=postcondition_key,
            postcondition_scope=scope,
            open_evidence=open_evidence,
            snapshot=post_snapshot.serializable(),
        )
        return post_present

    def _selection_wait_for_typeahead_postcondition(
        self,
        postcondition_key: str,
        scope: str,
        *,
        timeout: float,
    ) -> tuple[Snapshot, bool]:
        deadline = time.time() + timeout
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self._selection_stable_snapshot(
                scope,
                timeout=min(remaining, 0.8),
                anchor_key=postcondition_key,
            )
            if last_snapshot.has(postcondition_key):
                return last_snapshot, True
            time.sleep(0.2)
        if last_snapshot is None:
            last_snapshot = self._selection_snapshot(scope)
        return last_snapshot, last_snapshot.has(postcondition_key)

    def _open_selection_menu(
        self,
        trigger_key: str,
        expected_key: str,
        scope: str,
        result: ConsultationResult,
    ) -> tuple[Snapshot, ElementRef] | None:
        transition_seen = bool(getattr(self, '_selection_menu_transition_seen', False))
        if transition_seen:
            existing_snapshot = self.runtime.menu_snapshot()
            existing_expected = self.find_first(existing_snapshot, expected_key)
            if existing_expected is not None:
                if not self._selection_conformance_gate(result, existing_snapshot, expected_key):
                    return None
                return existing_snapshot, existing_expected
            if not self._selection_prepare_base_for_menu(result):
                return None
        trigger_snapshot, trigger = self._selection_find_once(trigger_key, 'snapshot')
        if trigger is None:
            result.add_step(
                'select',
                False,
                f'{self.platform} selection trigger {trigger_key} not found',
                trigger=trigger_key,
                snapshot=trigger_snapshot.serializable(),
            )
            return None
        trigger_snapshot, trigger = self._selection_wait_for_click_ready(
            trigger_key,
            'snapshot',
            trigger_snapshot,
            trigger,
        )
        if trigger is None or not self._selection_element_click_ready(trigger, None):
            result.add_step(
                'select',
                False,
                f'{self.platform} selection trigger {trigger_key} not click-ready after bounded settle-rescan',
                trigger=trigger_key,
                readiness=self._selection_click_readiness(trigger, None),
                snapshot=trigger_snapshot.serializable(),
            )
            return None
        if not self.runtime.click(trigger):
            result.add_step(
                'select',
                False,
                f'{self.platform} selection trigger {trigger_key} click failed',
                trigger=trigger_key,
                snapshot=trigger_snapshot.serializable(),
            )
            return None
        snapshot, expected = self._selection_wait_for_revealed_anchor(expected_key, scope)
        if expected is None:
            result.add_step(
                'select',
                False,
                f'{self.platform} selection expected element {expected_key} missing after menu open',
                expected=expected_key,
                snapshot=snapshot.serializable(),
            )
            return None
        if not self._selection_conformance_gate(result, snapshot, expected_key):
            return None
        self._selection_menu_transition_seen = True
        return snapshot, expected

    def _selection_prepare_base_for_menu(self, result: ConsultationResult) -> bool:
        menu_snapshot = self.runtime.menu_snapshot()
        if int(menu_snapshot.raw_count or 0) <= 0:
            return True
        self.runtime.focus_firefox()
        time.sleep(0.1)
        self.runtime.press('Escape')
        menu_snapshot = self._selection_wait_for_menu_closed()
        anchor_key = self._selection_base_anchor_key()
        if int(menu_snapshot.raw_count or 0) > 0:
            if anchor_key is None:
                result.add_step(
                    'select',
                    False,
                    f'{self.platform} selection base anchor unavailable while closing menu',
                    snapshot=menu_snapshot.serializable(),
                )
                return False
            if self._selection_click_base_anchor(anchor_key):
                menu_snapshot = self._selection_wait_for_menu_closed()
        if int(menu_snapshot.raw_count or 0) > 0:
            result.add_step(
                'select',
                False,
                f'{self.platform} selection menu surface still open before trigger',
                anchor=anchor_key,
                snapshot=menu_snapshot.serializable(),
            )
            return False
        if anchor_key is None:
            result.add_step(
                'select',
                False,
                f'{self.platform} selection base anchor unavailable before trigger',
            )
            return False
        timeout = max(self._selection_settle_seconds() + 1.0, 3.0)
        snapshot = self._selection_wait_for_clean_base(anchor_key, timeout=timeout)
        if not self._selection_base_snapshot_clean(snapshot, anchor_key):
            result.add_step(
                'select',
                False,
                f'{self.platform} selection base did not settle on anchor {anchor_key}',
                anchor=anchor_key,
                snapshot=snapshot.serializable(),
            )
            return False
        return True

    def _selection_click_base_anchor(self, anchor_key: str) -> bool:
        snapshot = self.runtime.wait_for_stable_snapshot(
            consecutive=1,
            timeout=max(self._selection_settle_seconds(), 1.0),
            interval=0.2,
            anchor_key=anchor_key,
            require_non_empty=True,
        )
        anchor = self.find_first(snapshot, anchor_key)
        if anchor is None:
            return False
        return self.runtime.click(anchor)

    def _selection_wait_for_clean_base(self, anchor_key: str, *, timeout: float) -> Snapshot:
        timeout = max(float(timeout), self._base_conformance_settle_seconds())
        deadline = time.time() + timeout
        required_clean = self._base_conformance_clean_snapshots()
        clean_samples = 0
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=2,
                timeout=min(remaining, 1.2),
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
            if self._selection_base_snapshot_clean(last_snapshot, anchor_key):
                clean_samples += 1
                if clean_samples >= required_clean:
                    return last_snapshot
            else:
                clean_samples = 0
            time.sleep(0.2)
        return last_snapshot or self.runtime.snapshot()

    def _selection_base_snapshot_clean(self, snapshot: Snapshot, anchor_key: str) -> bool:
        if not snapshot.has(anchor_key):
            return False
        for items in (snapshot.mapped or {}).values():
            for element in items:
                states = {str(state).lower() for state in (element.states or [])}
                if 'expanded' in states:
                    return False
        scopes = (((self.cfg.get('tree') or {}).get('conformance') or {}).get('scopes') or {})
        if 'base' not in scopes:
            return True
        return (
            not self._conformance_unknown_discrepancies(snapshot, 'base')
            and not self._missing_expected_elements(snapshot, 'base')
        )

    def _selection_wait_for_menu_closed(self) -> Snapshot:
        timeout = max(self._selection_settle_seconds() + 1.0, 3.0)
        deadline = time.time() + timeout
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            last_snapshot = self.runtime.menu_snapshot()
            if int(last_snapshot.raw_count or 0) == 0:
                return last_snapshot
            time.sleep(0.2)
        return last_snapshot or self.runtime.menu_snapshot()

    def _selection_base_anchor_key(self) -> str | None:
        conformance_anchor = self._conformance_anchor_key('base')
        if conformance_anchor:
            return conformance_anchor
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        if not isinstance(element_map, dict):
            return None
        for key in ('input', 'input_chat_with_chatgpt'):
            spec = element_map.get(key)
            if isinstance(spec, dict) and str(spec.get('role') or '').strip().lower() == 'entry':
                return key
        for key, spec in element_map.items():
            if not isinstance(spec, dict):
                continue
            role = str(spec.get('role') or '').strip().lower()
            if role == 'entry' and str(key).startswith('input'):
                return str(key)
        return None

    def _walk_selection_path(
        self,
        snapshot: Snapshot,
        path: list[dict[str, Any]],
        target_key: str,
        scope: str,
        result: ConsultationResult,
    ) -> tuple[Snapshot, ElementRef | None]:
        current_snapshot = snapshot
        for index, path_step in enumerate(path):
            path_key = str(path_step['element'])
            action = str(path_step['action'])
            element = self.find_first(current_snapshot, path_key)
            if element is None:
                current_snapshot, element = self._selection_find_once(path_key, scope)
            if element is None:
                result.add_step(
                    'select',
                    False,
                    f'{self.platform} selection path element {path_key} not found',
                    element=path_key,
                    snapshot=current_snapshot.serializable(),
                )
                return current_snapshot, None
            if not self._activate_selection_path_element(element, action):
                result.add_step(
                    'select',
                    False,
                    f'{self.platform} selection path {path_key} {action} failed',
                    element=path_key,
                    action=action,
                    snapshot=current_snapshot.serializable(),
                )
                return current_snapshot, None
            next_key = str(path[index + 1]['element']) if index + 1 < len(path) else target_key
            normalized_action = action.strip().lower()
            if normalized_action == 'hover':
                time.sleep(0.15)
                current_snapshot, next_element = self._selection_wait_for_hover_revealed_anchor(next_key)
            else:
                current_snapshot, next_element = self._selection_wait_for_revealed_anchor(next_key, scope)
            if next_element is None:
                result.add_step(
                    'select',
                    False,
                    f'{self.platform} selection expected element {next_key} missing after {action}',
                    expected=next_key,
                    action=action,
                    snapshot=current_snapshot.serializable(),
                )
                return current_snapshot, None
            if not self._selection_conformance_gate(result, current_snapshot, next_key):
                return current_snapshot, None
        target = self.find_first(current_snapshot, target_key)
        if target is None:
            current_snapshot, target = self._selection_find_once(target_key, scope)
        if target is None:
            result.add_step(
                'select',
                False,
                f'{self.platform} selection target {target_key} not found',
                target=target_key,
                snapshot=current_snapshot.serializable(),
            )
        return current_snapshot, target

    def _selection_close_active_selection_menu(self) -> tuple[Snapshot, bool]:
        closed_snapshot: Snapshot | None = None
        for _ in range(3):
            self.runtime.press('Escape')
            closed_snapshot = self._selection_wait_for_menu_closed()
            if int(closed_snapshot.raw_count or 0) == 0:
                self._selection_menu_transition_seen = False
                return closed_snapshot, True
            time.sleep(0.1)
        return closed_snapshot or self.runtime.menu_snapshot(), False

    def _selection_wait_for_hover_revealed_anchor(self, key: str) -> tuple[Snapshot, ElementRef | None]:
        timeout = max(self._selection_settle_seconds() + 0.5, 2.0)
        deadline = time.time() + timeout
        last_snapshot: Snapshot | None = None
        roles = ['menu item', 'radio menu item', 'check menu item', 'option']
        while time.time() < deadline:
            last_snapshot = self.runtime.app_root_snapshot(allowed_roles=roles)
            element = self.find_first(last_snapshot, key)
            if element is not None:
                return last_snapshot, element
            time.sleep(0.2)
        fallback_snapshot, fallback_element = self._selection_wait_for_revealed_anchor(key, 'menu_snapshot')
        if fallback_element is not None:
            return fallback_snapshot, fallback_element
        return last_snapshot or fallback_snapshot, self.find_first(last_snapshot or fallback_snapshot, key)

    def _selection_wait_for_revealed_anchor(self, key: str, scope: str) -> tuple[Snapshot, ElementRef | None]:
        timeout = max(self._selection_settle_seconds() + 1.0, 5.0)
        deadline = time.time() + timeout
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            if scope.strip().lower() == 'menu_snapshot':
                # Some native/web menus disappear after a cache-clearing menu scan;
                # one anchored observation is the stable evidence for this surface.
                last_snapshot = self.runtime.wait_for_stable_menu_snapshot(
                    consecutive=1,
                    timeout=min(remaining, 0.8),
                    interval=0.2,
                    anchor_key=key,
                    require_non_empty=True,
                )
            else:
                last_snapshot = self._selection_stable_snapshot(
                    scope,
                    timeout=min(remaining, 0.8),
                    anchor_key=key,
                )
            element = self.find_first(last_snapshot, key)
            if element is not None:
                return last_snapshot, element
            time.sleep(0.4)
        if scope.strip().lower() == 'menu_snapshot':
            fallback = self.runtime.wait_for_stable_app_root_snapshot(
                consecutive=1,
                timeout=max(self._selection_settle_seconds(), 1.0),
                interval=0.2,
                anchor_key=key,
                require_non_empty=True,
            )
            fallback_element = self.find_first(fallback, key)
            if fallback_element is not None:
                return fallback, fallback_element
            last_snapshot = fallback
            fallback = self.runtime.app_root_snapshot()
            fallback_element = self.find_first(fallback, key)
            if fallback_element is not None:
                return fallback, fallback_element
            last_snapshot = fallback
        last_snapshot = last_snapshot or self._selection_snapshot(scope)
        return last_snapshot, self.find_first(last_snapshot, key)

    def _activate_selection_path_element(self, element: ElementRef, action: str) -> bool:
        normalized = action.strip().lower()
        if normalized == 'hover':
            return self.runtime.hover(element)
        if normalized in {'press', 'click'}:
            return self.runtime.click(element, strategy='atspi_only')
        return False

    def _selection_find_once(self, key: str, scope: str) -> tuple[Snapshot, ElementRef | None]:
        return self._selection_wait_for_revealed_anchor(key, scope)

    def _selection_wait_for_click_ready(
        self,
        key: str,
        scope: str,
        snapshot: Snapshot,
        element: ElementRef | None,
        *,
        strategy: str | None = None,
    ) -> tuple[Snapshot, ElementRef | None]:
        timeout = max(self._selection_settle_seconds() + 1.0, 3.0)
        deadline = time.time() + timeout
        last_snapshot = snapshot
        last_element = element
        while time.time() < deadline:
            if self._selection_element_click_ready(last_element, strategy):
                return last_snapshot, last_element
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self._selection_stable_snapshot(
                scope,
                timeout=min(remaining, 0.8),
                anchor_key=key,
            )
            last_element = self.find_first(last_snapshot, key)
            time.sleep(0.2)
        return last_snapshot, last_element

    def _selection_element_click_ready(
        self,
        element: ElementRef | None,
        strategy: str | None,
    ) -> bool:
        readiness = self._selection_click_readiness(element, strategy)
        chosen = str(readiness['strategy']).lower()
        if chosen == 'coordinate_only':
            return bool(readiness['has_coordinates'])
        if chosen == 'atspi_only':
            return bool(readiness['has_action'])
        return bool(readiness['has_coordinates'] or readiness['has_action'])

    def _selection_click_readiness(
        self,
        element: ElementRef | None,
        strategy: str | None,
    ) -> dict[str, Any]:
        chosen = (strategy or self.runtime.click_strategy or 'xdotool_first').lower()
        has_coordinates = bool(element and element.x is not None and element.y is not None)
        has_action = False
        if element is not None and element.atspi_obj is not None:
            try:
                action = element.atspi_obj.get_action_iface()
                has_action = bool(action and action.get_n_actions() > 0)
            except Exception:
                has_action = False
        return {
            'strategy': chosen,
            'has_coordinates': has_coordinates,
            'has_action': has_action,
            'x': element.x if element is not None else None,
            'y': element.y if element is not None else None,
            'role': element.role if element is not None else None,
            'name': element.name if element is not None else None,
        }

    def _selection_snapshot(self, scope: str) -> Snapshot:
        normalized = scope.strip().lower()
        if normalized == 'menu_snapshot':
            return self.runtime.menu_snapshot()
        if normalized == 'app_root_snapshot':
            return self.runtime.app_root_snapshot()
        if normalized == 'snapshot':
            return self.runtime.snapshot()
        raise ValueError(f'Unknown selection snapshot scope {scope!r}')

    def _selection_settle_seconds(self) -> float:
        settle = self.cfg.get('settle') or {}
        if isinstance(settle, dict):
            value = settle.get('selection_ms') or settle.get('default_ms', 800)
        else:
            value = 800
        try:
            return max(0.0, float(value) / 1000.0)
        except (TypeError, ValueError):
            return 0.8

    def _selection_element_has_state(self, element: ElementRef, state: str) -> bool:
        expected = state.strip().lower()
        return expected in {str(item).lower() for item in (element.states or [])}

    def _selection_element_matches_active_recognition(
        self,
        element: ElementRef,
        active_recognition: str,
    ) -> bool:
        normalized = active_recognition.strip().lower()
        if normalized == 'selected_name_prefix':
            return (element.name or '').strip().lower().startswith('selected ')
        if normalized == 'click_only':
            return False
        return self._selection_element_has_state(element, normalized)

    def _selection_wait_for_active_state(
        self,
        target_key: str,
        active_state: str,
        scope: str,
    ) -> tuple[Snapshot, ElementRef | None, bool]:
        timeout = self._selection_settle_seconds()
        deadline = time.time() + timeout
        last_snapshot: Snapshot | None = None
        last_target: ElementRef | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self._selection_stable_snapshot(
                scope,
                timeout=min(remaining, 0.8),
                anchor_key=target_key,
            )
            last_target = self.find_first(last_snapshot, target_key)
            if last_target is not None and self._selection_element_matches_active_recognition(last_target, active_state):
                return last_snapshot, last_target, True
            time.sleep(0.2)
        if last_snapshot is None:
            last_snapshot = self._selection_snapshot(scope)
            last_target = self.find_first(last_snapshot, target_key)
        return last_snapshot, last_target, False

    def _selection_wait_for_active_element(
        self,
        active_element_key: str,
        *,
        timeout: float | None = None,
    ) -> tuple[Snapshot, bool]:
        wait_seconds = (
            max(self._selection_settle_seconds() + 1.0, 6.0)
            if timeout is None
            else max(float(timeout), 0.1)
        )
        deadline = time.time() + wait_seconds
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=1,
                timeout=min(remaining, 0.8),
                interval=0.2,
                anchor_key=active_element_key,
                require_non_empty=True,
            )
            if last_snapshot.has(active_element_key):
                return last_snapshot, True
            time.sleep(0.2)
        if last_snapshot is None:
            last_snapshot = self.runtime.snapshot()
        return last_snapshot, last_snapshot.has(active_element_key)

    def _selection_wait_for_active_trigger(
        self,
        trigger_key: str,
        active_trigger_names: tuple[str, ...],
        *,
        timeout: float | None = None,
    ) -> tuple[Snapshot, bool, str | None]:
        expected = {name for name in active_trigger_names if name}
        wait_seconds = (
            max(self._selection_settle_seconds() + 1.0, 6.0)
            if timeout is None
            else max(float(timeout), 0.1)
        )
        deadline = time.time() + wait_seconds
        last_snapshot: Snapshot | None = None
        last_name: str | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=1,
                timeout=min(remaining, 0.8),
                interval=0.2,
                anchor_key=trigger_key,
                require_non_empty=True,
            )
            trigger = self.find_first(last_snapshot, trigger_key)
            last_name = trigger.name if trigger is not None else None
            if trigger is not None and trigger.name in expected:
                return last_snapshot, True, trigger.name
            time.sleep(0.2)
        if last_snapshot is None:
            last_snapshot = self.runtime.snapshot()
        trigger = self.find_first(last_snapshot, trigger_key)
        last_name = trigger.name if trigger is not None else last_name
        return last_snapshot, bool(trigger is not None and trigger.name in expected), last_name

    def _selection_stable_snapshot(
        self,
        scope: str,
        *,
        timeout: float,
        anchor_key: str | None = None,
    ) -> Snapshot:
        normalized = scope.strip().lower()
        if normalized == 'menu_snapshot':
            return self.runtime.wait_for_stable_menu_snapshot(
                consecutive=2,
                timeout=timeout,
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
        if normalized == 'app_root_snapshot':
            return self.runtime.wait_for_stable_app_root_snapshot(
                consecutive=2,
                timeout=timeout,
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
        if normalized == 'snapshot':
            return self.runtime.wait_for_stable_snapshot(
                consecutive=2,
                timeout=timeout,
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
        raise ValueError(f'Unknown selection snapshot scope {scope!r}')

    def _selection_conformance_gate(
        self,
        result: ConsultationResult,
        snapshot: Snapshot,
        key: str,
    ) -> bool:
        surface = self._element_scope(key)
        scopes = (((self.cfg.get('tree') or {}).get('conformance') or {}).get('scopes') or {})
        if surface and surface in scopes:
            return self.tree_conformance_gate(result, snapshot, surface=surface)
        return True

    def _element_scope(self, key: str) -> str | None:
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        spec = element_map.get(key) if isinstance(element_map, dict) else {}
        if isinstance(spec, dict) and isinstance(spec.get('scope'), str):
            return str(spec['scope'])
        return None

    def _gate_selection_plan(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        self._current_selection_plan = None
        if not has_selection_menus(request.platform):
            return True
        try:
            self._current_selection_plan = build_selection_plan(request)
        except SelectionPlanError as exc:
            result.add_step(
                'selection_plan',
                False,
                'Selection plan rejected before browser action',
                findings=list(exc.findings),
            )
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

    def acquire_display_lock(
        self,
        payload: Optional[dict] = None,
        ttl: int = 3600,
        display: str | None = None,
    ) -> str | None:
        return primitives.acquire_display_lock(
            payload=payload,
            ttl=ttl,
            display=display or self._display(),
        )

    def release_display_lock(self, owner_token: str | None, display: str | None = None) -> bool:
        return primitives.release_display_lock(owner_token, display=display or self._display())

    def write_run_state(self, request_id: str, state: dict, ttl: int = 7200) -> bool:
        return primitives.write_run_state(request_id, state, ttl=ttl)

    def read_run_state(self, request_id: str) -> Optional[dict]:
        return primitives.read_run_state(request_id)

    def assert_session_not_dead(self, request_id: str) -> None:
        primitives.assert_session_not_dead(request_id)

    def clear_run_state(self, request_id: str) -> bool:
        return primitives.clear_run_state(request_id)

    def register_monitor_session(self, monitor_id: str, session: dict) -> bool:
        return primitives.register_monitor_session(monitor_id, session)

    def deregister_monitor_session(self, monitor_id: str) -> bool:
        return primitives.deregister_monitor_session(monitor_id)

    # ------------------------------------------------------------------
    # Per-display setup/send SERIALIZATION (FLOW §10 concurrency model)
    # ------------------------------------------------------------------
    #
    # FLOW §10 splits the lifecycle into a SEQUENTIAL region and a CONCURRENT
    # region on a per-display basis:
    #
    #   Sequential (one consultation at a time PER DISPLAY): navigate, select
    #     model/mode/tools/connectors, attach, paste prompt, send + register.
    #     Two dispatches racing the same Firefox/AT-SPI bus would interleave
    #     clicks/menus on one browser window and corrupt each other's setup.
    #   Concurrent (overlapping across consultations): registered monitor
    #     sessions, stop-button polling, completion notification, extraction.
    #     Monitoring is passive observation; holding the display lock through it
    #     would needlessly serialize generations and defeat the contract's
    #     "later sends proceed while earlier responses are monitored" invariant.
    #
    # The serialization unit is the DISPLAY (one physical Firefox window), so the
    # mutex is the EXISTING DISPLAY-scoped plan lock primitive
    # (primitives.acquire/release_display_lock, key taey:plan_active:{DISPLAY} —
    # the exact key monitor/central.py::_plan_active reads to decide whether it
    # may cycle a tab). No new key scheme; no platform string (the lock is keyed
    # by DISPLAY, never by platform).
    #
    # The template run() below acquires the lock for the WHOLE setup+send+register
    # phase and RELEASES it the instant guarded_send hands the monitor off (or
    # any setup/send step fails), so monitor/extract run UNLOCKED.

    def _display(self) -> str:
        return display_for_platform(self.platform) or os.environ.get('DISPLAY', ':0')

    @contextmanager
    def _display_dispatch_lock(self, request: ConsultationRequest) -> Iterator[bool]:
        """Hold the DISPLAY-scoped dispatch lock for the duration of the
        ``with`` block (the setup+send+register region, FLOW §10).

        Yields ``True`` if the lock was acquired (this dispatch owns the display
        and may drive the browser), ``False`` if another consultation already
        holds it (the caller must NOT proceed — a busy display is a loud failure,
        not a silent shared-browser race).

        RELEASE-SAFE: the release runs in a ``finally`` so a failed/halted/raising
        setup or send still frees the display — no deadlock can leave a DISPLAY
        permanently locked. The lock is released ONLY if THIS context acquired it,
        so a False (already-held-by-another) exit never deletes the other
        dispatch's lock.

        This is correct resource discipline, NOT an error swallow: when the
        locked block raises, the lock is released in ``finally`` and the
        exception propagates out of the ``with`` (first-error full-stop)."""
        display = self._display()
        payload = {
            'platform': self.platform,
            'display': display,
            'request_id': request.request_id(),
            'locked_at': datetime.now(timezone.utc).isoformat(),
        }
        owner_token = primitives.acquire_display_lock(payload=payload, display=display)
        try:
            yield bool(owner_token)
        finally:
            if owner_token:
                primitives.release_display_lock(owner_token, display=display)

    # ------------------------------------------------------------------
    # Run-state idempotency (FLOW §8, CONSULTATION_CONTRACT §10)
    # ------------------------------------------------------------------
    #
    # The send is the single IRREVERSIBLE action. A re-run after a landed send
    # (drift hit post-send, process crashed, operator re-dispatched) must NEVER
    # replay it. The durable run-state record keyed by the request's STABLE
    # request_id is the duplicate-send guard: as the lifecycle progresses we
    # checkpoint the load-bearing milestones into it, and at the send seam we
    # READ it first. A prior submitted URL resumes directly. A prior
    # setup_complete is quarantined as possibly-landed: verify/resume a live URL
    # if one exists, otherwise fail closed instead of replaying Enter.
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
        if self._is_unresumable_landed_send(prior, request):
            if not self._invalidate_unresumable_landed_send(prior, request, result):
                return False
        if self._is_setup_complete_send_quarantine(prior, request):
            live_url = self._live_resumable_send_url()
            if live_url:
                return self._resume_possibly_landed_send(
                    prior or {},
                    request,
                    result,
                    live_url,
                )
            return self._fail_duplicate_send_risk(prior or {}, request, result)

        # setup_complete milestone: this run reached the pre-send boundary
        # (navigate + model/mode/tools + attach + prompt entry all validated)
        # with no proven prior send. Written AFTER the landed-send check so it
        # never overwrites a prior submitted record.
        pre_send_url = self.runtime.current_url() or result.session_url_before or ''
        self.checkpoint_run_state(
            request,
            self.RUN_STATE_SETUP_COMPLETE,
            result=result,
            pre_send_url=pre_send_url,
            monitor_id=self._monitor_id(request),
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
        if not self.is_resumable_session_url(captured_url):
            result.add_step(
                'send_checkpoint',
                False,
                f'{self.platform} send produced no valid resumable answer-thread URL; '
                f'not checkpointing or registering monitor',
                captured_url=captured_url,
            )
            return False
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

    def is_resumable_session_url(self, url: str | None) -> bool:
        return bool((url or '').strip())

    def _landed_run_state_statuses(self) -> set[str]:
        return {
            self.RUN_STATE_SUBMITTED,
            self.RUN_STATE_COMPLETION_OBSERVED,
            self.RUN_STATE_EXTRACTION_DONE,
        }

    def _is_setup_complete_send_quarantine(
        self,
        prior: Optional[dict],
        request: ConsultationRequest,
    ) -> bool:
        if not prior:
            return False
        if prior.get('prompt_hash') != request.prompt_hash():
            return False
        return prior.get('status') == self.RUN_STATE_SETUP_COMPLETE

    def _live_resumable_send_url(self) -> str:
        current_url = (self.runtime.current_url() or '').strip()
        if self.is_resumable_session_url(current_url):
            return current_url
        return ''

    def _resume_possibly_landed_send(
        self,
        prior: dict,
        request: ConsultationRequest,
        result: ConsultationResult,
        live_url: str,
    ) -> bool:
        monitor_id = str(prior.get('monitor_id') or self._monitor_id(request))
        self.checkpoint_run_state(
            request,
            self.RUN_STATE_SUBMITTED,
            result=result,
            url=live_url,
            monitor_id=monitor_id,
            side_effect_uncertain=True,
            duplicate_send_quarantined=True,
            prior_status=prior.get('status'),
        )
        resumed_prior = {
            **prior,
            'status': self.RUN_STATE_SUBMITTED,
            'url': live_url,
            'monitor_id': monitor_id,
        }
        result.add_step(
            'duplicate_send_quarantine',
            True,
            f'{self.platform} prior setup_complete may have landed a send; '
            f'resuming live answer thread instead of replaying Enter',
            prior_status=prior.get('status'),
            live_url=live_url,
            duplicate_send_risk=True,
            side_effect_uncertain=True,
        )
        return self._resume_landed_send(resumed_prior, request, result)

    def _fail_duplicate_send_risk(
        self,
        prior: dict,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        current_url = (self.runtime.current_url() or '').strip()
        result.session_url_after = current_url or result.session_url_after
        result.add_step(
            'send',
            False,
            f'{self.platform} duplicate_send_risk: prior setup_complete for this '
            f'prompt means a send may already have landed, but no live resumable '
            f'answer-thread URL could be verified; refusing to re-send',
            stop_condition='duplicate_send_risk',
            side_effect='side_effect_uncertain',
            prior_status=prior.get('status'),
            current_url=current_url,
            pre_send_url=prior.get('pre_send_url'),
            duplicate_send_risk=True,
            side_effect_uncertain=True,
        )
        return False

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
        if prior.get('status') not in self._landed_run_state_statuses():
            return False
        return self.is_resumable_session_url(str(prior.get('url') or ''))

    def _is_unresumable_landed_send(
        self,
        prior: Optional[dict],
        request: ConsultationRequest,
    ) -> bool:
        if not prior:
            return False
        if prior.get('prompt_hash') != request.prompt_hash():
            return False
        if prior.get('status') not in self._landed_run_state_statuses():
            return False
        return not self.is_resumable_session_url(str(prior.get('url') or ''))

    def _invalidate_unresumable_landed_send(
        self,
        prior: dict,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        captured_url = str(prior.get('url') or '')
        try:
            cleared = self.clear_run_state(request.request_id())
        except Exception as exc:  # noqa: BLE001 - stale idempotency must fail loudly
            result.add_step(
                'run_state_resume_rejected',
                False,
                f'{self.platform} prior send checkpoint is not resumable, and clearing '
                f'the stale durable run-state failed: {exc}',
                prior_status=prior.get('status'),
                captured_url=captured_url,
            )
            return False
        result.add_step(
            'run_state_resume_rejected',
            True,
            f'{self.platform} rejected stale prior send checkpoint; captured URL is not '
            f'a valid resumable answer thread',
            prior_status=prior.get('status'),
            captured_url=captured_url,
            run_state_cleared=bool(cleared),
        )
        return True

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
            'mode': str(request.selection_value('mode', '') or ''),
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
        echo = self._prompt_echo_evidence(response_text, user_prompt)
        if echo.get('is_echo'):
            return {
                'stored': False,
                'reason': 'prompt_echo_guard',
                'error': PROMPT_ECHO_FAILURE_MESSAGE,
                'echo_guard': echo,
            }
        return primitives.store_consultation(
            platform=self.platform,
            url=url,
            user_prompt=user_prompt,
            response_text=response_text,
            attachments=attachments,
        )

    def store_response_for_delivery(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        session_url: str,
        *,
        label: str,
    ) -> bool:
        if not storage_policy.external_store_enabled(request):
            result.storage = storage_policy.disabled_record(request)
            result.storage['url'] = session_url
            result.add_step(
                'store',
                True,
                f'{label} external storage skipped',
                storage=result.storage,
            )
            return True

        result.storage = self.store_consultation(
            session_url,
            request.message,
            result.response_text,
            attachments=request.attachments,
        )
        result.storage['url'] = session_url
        if result.storage.get('stored'):
            result.add_step(
                'store',
                True,
                f'{label} response stored in external storage',
                storage=result.storage,
            )
            return True

        result.add_step(
            'store',
            False,
            f'{label} external storage failed; delivering extracted response locally',
            storage=result.storage,
        )
        return True

    # ------------------------------------------------------------------
    # Shared completion detection (single source of truth)
    # ------------------------------------------------------------------

    def _stop_key(self) -> str:
        """YAML-declared stop-button element key (default 'stop_button')."""
        return self.cfg.get('workflow', {}).get('monitor', {}).get('stop_key') or 'stop_button'

    def _monitor_intermediate_states(self) -> list[dict[str, Any]]:
        monitor = (self.cfg.get('workflow') or {}).get('monitor') or {}
        raw_states = monitor.get('intermediate_states') or []
        if not raw_states:
            return []
        if not isinstance(raw_states, list):
            raise ValueError(f'{self.platform} workflow.monitor.intermediate_states must be a list')
        states: list[dict[str, Any]] = []
        for state in raw_states:
            if not isinstance(state, dict):
                raise ValueError(f'{self.platform} workflow.monitor.intermediate_states entries must be mappings')
            states.append(dict(state))
        return states

    def _monitor_state_keys(self, state: dict[str, Any]) -> tuple[str, ...]:
        raw_keys = state.get('detect') or state.get('detect_keys') or state.get('elements')
        action_key = state.get('element') or state.get('action_element')
        if raw_keys is None and action_key:
            raw_keys = [action_key]
        if isinstance(raw_keys, str):
            keys = (raw_keys,)
        elif isinstance(raw_keys, list):
            keys = tuple(str(key) for key in raw_keys if str(key).strip())
        else:
            raise ValueError(f'{self.platform} monitor intermediate state requires detect keys')
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        missing = [key for key in keys if key not in element_map]
        if missing:
            raise ValueError(f'{self.platform} monitor intermediate key(s) not in element_map: {missing}')
        return keys

    def _monitor_intermediate_max_actions(self, state: dict[str, Any]) -> int:
        raw_value = state.get('max_actions', 1)
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{self.platform} monitor intermediate max_actions must be an integer') from exc
        if value < 0:
            raise ValueError(f'{self.platform} monitor intermediate max_actions must be >= 0')
        return value

    @staticmethod
    def _reset_detector_after_intermediate(detector: ChatGPTCompletionDetector) -> None:
        detector.ever_seen_stop = False
        detector.stop_was_visible = False
        detector.stop_cycles = 0

    def _handle_monitor_intermediate_state(
        self,
        snapshot: Snapshot,
        result: ConsultationResult,
        action_counts: dict[str, int],
        *,
        step_name: str = 'monitor',
    ) -> tuple[bool, bool]:
        for state in self._monitor_intermediate_states():
            name = str(state.get('name') or state.get('state') or 'intermediate').strip()
            keys = self._monitor_state_keys(state)
            matched_key = next((key for key in keys if snapshot.has(key)), None)
            if not matched_key:
                continue
            action = str(state.get('action') or 'wait').strip().lower()
            if action != 'click':
                return True, False
            action_key = str(state.get('element') or state.get('action_element') or matched_key).strip()
            if action_key not in ((self.cfg.get('tree') or {}).get('element_map') or {}):
                raise ValueError(f'{self.platform} monitor intermediate action key not in element_map: {action_key}')
            max_actions = self._monitor_intermediate_max_actions(state)
            current_count = action_counts.get(name, 0)
            if current_count >= max_actions:
                return True, False
            action_element = self.find_first(snapshot, action_key)
            if action_element is None:
                result.add_step(
                    f'{step_name}_intermediate',
                    False,
                    f'{self.platform} monitor intermediate {name} matched but action {action_key} was absent',
                    state=name,
                    matched_key=matched_key,
                    action_key=action_key,
                    snapshot=snapshot.serializable(),
                )
                return True, True
            clicked = self.runtime.click(
                action_element,
                strategy=str(state.get('click_strategy') or 'atspi_first'),
            )
            action_counts[name] = current_count + 1
            result.add_step(
                f'{step_name}_intermediate',
                clicked,
                (
                    f'{self.platform} monitor disposed intermediate state {name}'
                    if clicked else
                    f'{self.platform} monitor failed to dispose intermediate state {name}'
                ),
                state=name,
                matched_key=matched_key,
                action_key=action_key,
                action_count=action_counts[name],
                max_actions=max_actions,
                element=action_element.serializable(),
                snapshot=snapshot.serializable(),
            )
            return True, not clicked
        return False, False

    @staticmethod
    def _normalized_text(text: str) -> str:
        return ' '.join((text or '').split())

    @staticmethod
    def _echo_tokens(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9][a-z0-9_-]{3,}", (text or '').lower()))

    def _prompt_echo_evidence(
        self,
        content: str,
        request_or_prompt: ConsultationRequest | str,
    ) -> dict[str, Any]:
        prompt_text = (
            request_or_prompt.message
            if isinstance(request_or_prompt, ConsultationRequest)
            else str(request_or_prompt or '')
        )
        content_norm = self._normalized_text(content)
        prompt_norm = self._normalized_text(prompt_text)
        evidence: dict[str, Any] = {
            'is_echo': False,
            'reason': '',
            'content_chars': len(content_norm),
            'prompt_chars': len(prompt_norm),
        }
        if len(content_norm) < 80 or not prompt_norm:
            return evidence

        content_lower = content_norm.lower()
        prompt_lower = prompt_norm.lower()
        if content_norm == prompt_norm:
            evidence.update(is_echo=True, reason='exact_match')
            return evidence
        if content_norm in prompt_norm and len(content_norm) >= 160:
            evidence.update(is_echo=True, reason='content_substring_of_prompt')
            return evidence
        if prompt_norm in content_norm and len(content_norm) <= int(len(prompt_norm) * 1.25):
            evidence.update(is_echo=True, reason='prompt_with_only_small_appendix')
            return evidence
        if len(prompt_norm) >= 120 and content_norm.startswith(prompt_norm[:120]):
            evidence.update(is_echo=True, reason='prompt_prefix_match')
            return evidence

        content_tokens = self._echo_tokens(content_norm)
        prompt_tokens = self._echo_tokens(prompt_norm)
        if content_tokens and prompt_tokens:
            shared_tokens = content_tokens & prompt_tokens
            content_overlap = len(shared_tokens) / len(content_tokens)
            prompt_overlap = len(shared_tokens) / len(prompt_tokens)
            evidence.update(
                content_token_count=len(content_tokens),
                prompt_token_count=len(prompt_tokens),
                shared_token_count=len(shared_tokens),
                content_token_overlap=round(content_overlap, 4),
                prompt_token_overlap=round(prompt_overlap, 4),
            )
            if (
                len(content_tokens) >= 25
                and content_overlap >= 0.82
                and prompt_overlap >= 0.20
                and len(content_norm) <= int(len(prompt_norm) * 1.35)
            ):
                evidence.update(is_echo=True, reason='high_prompt_token_overlap')
                return evidence

        distinctive_markers = (
            'see the attached file for full ground truth',
            'full ground truth',
            'attached file for full',
            'answer a-f',
            'questions a-f',
        )
        markers = [
            marker for marker in distinctive_markers
            if marker in prompt_lower and marker in content_lower
        ]
        if markers:
            evidence['distinctive_prompt_markers'] = markers
            content_overlap = float(evidence.get('content_token_overlap') or 0.0)
            if len(content_norm) <= int(len(prompt_norm) * 1.35) and content_overlap >= 0.65:
                evidence.update(is_echo=True, reason='distinctive_prompt_marker_overlap')
                return evidence
        return evidence

    def _is_prompt_echo(self, content: str, request: ConsultationRequest) -> bool:
        return bool(self._prompt_echo_evidence(content, request).get('is_echo'))

    def reject_prompt_echo_response(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        content: str,
        *,
        step: str = 'extract_primary',
        source: str = '',
        **evidence: Any,
    ) -> bool:
        echo = self._prompt_echo_evidence(content, request)
        if not echo.get('is_echo'):
            return False
        result.response_text = ''
        step_evidence = dict(evidence)
        if source:
            step_evidence.setdefault('source', source)
        step_evidence.setdefault('characters', len(content or ''))
        step_evidence.setdefault('preview', (content or '')[:200])
        step_evidence['echo_guard'] = echo
        result.add_step(step, False, PROMPT_ECHO_FAILURE_MESSAGE, **step_evidence)
        return True

    def set_response_text_if_not_prompt_echo(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        content: str,
        *,
        step: str = 'extract_primary',
        source: str = '',
        **evidence: Any,
    ) -> bool:
        if self.reject_prompt_echo_response(
            request,
            result,
            content,
            step=step,
            source=source,
            **evidence,
        ):
            return False
        result.response_text = content
        return True

    @staticmethod
    def _urls_equivalent(left: str | None, right: str | None) -> bool:
        return (left or '').strip().rstrip('/') == (right or '').strip().rstrip('/')

    def _assert_monitor_answer_thread(
        self,
        result: ConsultationResult,
        *,
        step_name: str = 'monitor',
        answer_url_predicate=None,
    ) -> tuple[bool, bool]:
        captured = (result.session_url_after or '').strip()
        current = (self.runtime.current_url() or '').strip()
        predicate = answer_url_predicate or self.is_resumable_session_url
        if not captured:
            result.add_step(
                f'{step_name}_answer_thread',
                False,
                f'{self.platform} monitor has no send-created answer-thread URL',
                current_url=current,
                captured_url=captured,
                stop_condition='answer_thread_lost',
            )
            return False, True
        if predicate is not None and not predicate(captured):
            result.add_step(
                f'{step_name}_answer_thread',
                False,
                f'{self.platform} send-created URL is not a valid answer thread',
                current_url=current,
                captured_url=captured,
                stop_condition='answer_thread_lost',
            )
            return False, True
        if self._urls_equivalent(current, captured):
            return True, False

        result.add_step(
            f'{step_name}_answer_thread',
            False,
            f'{self.platform} monitor left send-created answer thread',
            current_url=current,
            captured_url=captured,
            stop_condition='answer_thread_lost',
        )
        return False, True

    def reassert_captured_session_url(
        self,
        result: ConsultationResult,
        *,
        answer_url_predicate=None,
        timeout: float = 8.0,
    ) -> bool:
        captured = (result.session_url_after or '').strip()
        current_before = (self.runtime.current_url() or '').strip()
        if not captured:
            if answer_url_predicate is not None and answer_url_predicate(current_before):
                result.session_url_after = current_before
                result.add_step(
                    'answer_thread',
                    True,
                    f'{self.platform} adopted current answer thread URL',
                    url=current_before,
                    captured_url=captured,
                    adopted_current=True,
                )
                return True
            result.add_step(
                'answer_thread',
                False,
                f'{self.platform} has no captured answer-thread URL before extraction',
                current_url=current_before,
            )
            return False
        if answer_url_predicate is not None and not answer_url_predicate(captured):
            if answer_url_predicate(current_before):
                result.session_url_after = current_before
                result.add_step(
                    'answer_thread',
                    True,
                    f'{self.platform} adopted current answer thread URL',
                    current_url=current_before,
                    captured_url=captured,
                    adopted_current=True,
                )
                return True
            result.add_step(
                'answer_thread',
                False,
                f'{self.platform} captured URL is not an answer thread',
                current_url=current_before,
                captured_url=captured,
            )
            return False
        if self._urls_equivalent(current_before, captured):
            result.add_step(
                'answer_thread',
                True,
                f'{self.platform} already on captured answer thread',
                url=current_before,
            )
            return True

        navigated = self.runtime.navigate(captured, verify_change=False)

        def _arrived() -> str | None:
            current = (self.runtime.current_url() or '').strip()
            if self._urls_equivalent(current, captured):
                return current
            return None

        arrived = self.runtime.wait_until(_arrived, timeout=timeout, interval=0.5)
        ok = bool(arrived)
        result.add_step(
            'answer_thread',
            ok,
            (
                f'{self.platform} navigated back to captured answer thread'
                if ok else
                f'{self.platform} could not reassert captured answer thread'
            ),
            current_url=current_before,
            captured_url=captured,
            after_url=arrived or self.runtime.current_url(),
            navigated=navigated,
        )
        return ok

    def monitor_generation(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        mode: Optional[str] = None,
        seed_stop_seen: bool = False,
    ) -> bool:
        """Poll until the response completes, using the SHARED stop-transition
        detector (`consultation_v2.platforms.chatgpt.monitor.ChatGPTCompletionDetector`) — the single
        source of truth that mirrors monitor/central.py::_detect_completion.

        Completion = the stop button was SEEN and is now GONE for the required
        number of cycles (2 for deep modes, 1 otherwise). No content-guess
        fallback (100_TIMES §1); the stop button is the only completion oracle.

        ``seed_stop_seen`` is accepted only as explicit upstream proof from a
        validated send. Without that proof, this monitor call must observe Stop
        itself before Stop-gone can complete.
        """
        # The selected mode lives in request.selections['mode'] (read via
        # selection_value); ConsultationRequest has no `.mode` attribute, so the
        # prior getattr(request, 'mode', None) ALWAYS yielded None -> '' ->
        # 'default'. That silently collapsed deep modes to required_stop_cycles=1
        # AND dropped their DEEP_GENERATION_FLOOR_SECONDS floor below. Read the
        # real selected mode so deep modes get their intended 2-cycle stop-gone
        # debounce + deep timeout floor.
        detector_mode = (
            (mode if mode is not None else request.selection_value('mode', None)) or ''
        ).strip().lower()
        detector = ChatGPTCompletionDetector(mode=detector_mode)
        stop_key = self._stop_key()
        completed = False
        observed_stop = bool(seed_stop_seen)
        intermediate_failed = False
        answer_thread_lost = False
        intermediate_actions: dict[str, int] = {}
        if seed_stop_seen:
            detector.ever_seen_stop = True
            detector.stop_was_visible = True

        def _poll() -> bool:
            nonlocal completed, observed_stop, intermediate_failed, answer_thread_lost
            _thread_ok, thread_lost = self._assert_monitor_answer_thread(result)
            if thread_lost:
                answer_thread_lost = True
                return True
            snap = self.runtime.snapshot()
            stop_present = snap.has(stop_key)
            observed_stop = observed_stop or stop_present
            if stop_present:
                detector.observe(stop_present=True)
            handled, failed = self._handle_monitor_intermediate_state(
                snap,
                result,
                intermediate_actions,
            )
            if handled:
                self._reset_detector_after_intermediate(detector)
                intermediate_failed = failed
                return bool(failed)
            if stop_present:
                return False
            # Stop-key absent on this scan. An ABSENCE is only real information
            # when it comes from a FAITHFUL read of the page: under concurrent
            # AT-SPI bus contention a starved read returns a near-empty tree in
            # which stop_key is absent NOT because generation finished but because
            # the read itself failed. Feeding that to the detector as stop-gone is
            # the false-completion root cause (compounded by BUG1's lost deep
            # debounce). A degraded read is therefore 'unknown', not 'gone': skip
            # the tick (debounce counter untouched) and keep polling. stop_present
            # is unaffected — a visible stop means generating regardless of tree
            # size — and the wall-clock effective_timeout still bounds a
            # genuinely-stuck run, so this adds no infinite wait.
            if int(snap.raw_count or 0) < MONITOR_MIN_HEALTHY_RAW_COUNT:
                return False
            verdict = detector.observe(stop_present=False)
            if verdict == COMPLETE:
                completed = True
                return True
            return False

        # Per-mode timeout floor: deep/research generations run for many minutes,
        # so a caller's short --timeout must not bound them below the floor (the
        # p8 audit false-failure: a deep run dispatched with --timeout 900). The
        # timeout remains the contract's LOUD bound for a genuinely-stuck run; it
        # is never an elapsed-time completion heuristic (completion stays
        # Stop-gone-only).
        effective_timeout = float(request.timeout)
        if detector_mode in DEEP_MODES:
            effective_timeout = max(effective_timeout, DEEP_GENERATION_FLOOR_SECONDS)
        self.runtime.wait_until(_poll, timeout=effective_timeout, interval=1.0)
        verify_snap = self.wait_for_validation(
            'response_complete',
            timeout=5.0,
            interval=0.5,
        )
        if not observed_stop:
            if answer_thread_lost:
                result.add_step(
                    'monitor', False,
                    f'{self.platform} answer_thread_lost: monitor left send-created answer thread',
                    stop_seen=observed_stop, seed_stop_seen=bool(seed_stop_seen),
                    mode=detector_mode or 'default',
                    stop_condition='answer_thread_lost',
                    snapshot=verify_snap.serializable(),
                )
                return False
            result.add_step(
                'monitor', False,
                f'{self.platform} monitor never observed Stop button after send',
                stop_seen=False, seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode or 'default',
                snapshot=verify_snap.serializable(),
            )
            return False
        if answer_thread_lost:
            result.add_step(
                'monitor', False,
                f'{self.platform} answer_thread_lost: monitor left send-created answer thread',
                stop_seen=observed_stop, seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode or 'default',
                stop_condition='answer_thread_lost',
                snapshot=verify_snap.serializable(),
            )
            return False
        if intermediate_failed:
            result.add_step(
                'monitor', False,
                f'{self.platform} monitor failed while disposing intermediate state',
                stop_seen=observed_stop, seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode or 'default',
                intermediate_actions=intermediate_actions,
                snapshot=verify_snap.serializable(),
            )
            return False
        verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
        # Classify a non-completion: if the Stop button is STILL present at the
        # final fresh scan, this is the contract's "genuinely stuck visible-stop"
        # run bounded by the (now floored) timeout — a LOUD, mapped
        # generation_stalled failure (FLOW §9 / stop_conditions.py), not a generic
        # completion miss. (Stop gone but debounce-cycles incomplete is the other,
        # non-stalled, miss.)
        stop_still_present = bool(verify_snap.has(stop_key))
        stop_condition = (
            'generation_stalled'
            if (not verified and stop_still_present and is_stop_condition('generation_stalled'))
            else None
        )
        if verified:
            monitor_message = f'{self.platform} response completed'
        elif stop_condition == 'generation_stalled':
            monitor_message = (
                f'{self.platform} generation_stalled: Stop still present after '
                f'{effective_timeout:.0f}s (mode={detector_mode or "default"}) — loud bound, not completion'
            )
        else:
            monitor_message = f'{self.platform} response did not reach Stop-gone completion'
        result.add_step(
            'monitor', verified, monitor_message,
            stop_seen=observed_stop, seed_stop_seen=bool(seed_stop_seen),
            mode=detector_mode or 'default',
            stop_condition=stop_condition,
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

    # ------------------------------------------------------------------
    # Lifecycle template (FLOW §10) — the lock seam lives HERE, once, so it
    # is identical for all five drivers and cannot drift per-platform.
    # ------------------------------------------------------------------

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        """Two-phase consultation lifecycle with per-display serialization.

        Phase A (LOCKED, sequential per display): ``setup_and_send`` — switch,
        navigate, select model/mode/tools/connectors, attach, enter prompt, and
        the guarded (idempotent) send + monitor registration. Held under the
        DISPLAY-scoped dispatch lock so two consultations never drive the same
        Firefox/AT-SPI bus at once.

        Phase B (UNLOCKED, concurrent): ``monitor_and_extract`` — poll for the
        Stop-gone completion, extract, store. Runs with the display lock ALREADY
        RELEASED so the next consultation can set up/send on this display while
        this one's response is monitored concurrently (FLOW §10 invariant).

        The lock is released at the EXACT moment setup_and_send returns (the
        send-registered handoff) AND on any setup/send failure or exception
        (release-safe ``finally`` in ``_display_dispatch_lock``)."""
        self.assert_session_not_dead(request.request_id())
        with pause_display_watchdog(self.platform, self._display()):
            result = self.result(request)
            if not self._gate_selection_plan(request, result):
                return result
            with self._display_dispatch_lock(request) as owns_display:
                if not owns_display:
                    # Another consultation holds this display's dispatch lock. Per
                    # FLOW §10 setup/send is sequential per display — do NOT race the
                    # shared browser. Loud failure, not a silent skip or a wait-loop.
                    result.add_step(
                        'dispatch_lock', False,
                        f'{self.platform} display {self._display()} dispatch lock is '
                        f'already held by another consultation — setup/send is '
                        f'sequential per display (FLOW §10); not racing the shared '
                        f'browser/AT-SPI bus',
                        display=self._display(),
                    )
                    return result
                # --- LOCKED region: setup + send + monitor registration ----------
                if not self.setup_and_send(request, result):
                    # Setup/send failed; lock released by the context manager's
                    # finally as the with-block exits. No monitor handoff happened.
                    return result
            # --- UNLOCKED region: monitor + extract + store ----------------------
            # Reached only when setup_and_send returned True (send registered, monitor
            # handed off). The display lock is now RELEASED (with-block exited), so a
            # concurrent consultation may set up/send on this display while we monitor.
            self.monitor_and_extract(request, result)
            if result.ok and result.response_text and self.reject_prompt_echo_response(
                request,
                result,
                result.response_text,
                step='extract_primary',
                source='chatgpt_package_run_delivery_gate',
            ):
                result.ok = False
            return result

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): switch/navigate/select/attach/prompt then the
        guarded send + monitor registration. Return True iff the send is proven
        and the monitor session is registered (the handoff point); False on any
        setup/send failure (the step audit records why). Runs while THIS driver
        holds the DISPLAY-scoped dispatch lock — must not block on monitoring."""
        raise NotImplementedError

    def monitor_and_extract(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> None:
        """UNLOCKED phase (FLOW §10): poll for completion, extract, store, set
        result.ok. Runs AFTER the display lock is released so other consultations
        can set up/send on this display concurrently. Sets result.ok on success;
        leaves it False (with a recorded step) on any monitor/extract failure."""
        raise NotImplementedError


class ChatGPTConsultationDriver(_ChatGPTInlineBase):
    platform = 'chatgpt'
    _AUTO_CHIP_ROLES = {'push button', 'list item', 'heading', 'panel'}
    _AUTO_CHIP_IGNORED_NAMES = {
        'Add files and more',
        'Ask anything',
        'Chat with ChatGPT',
        'Send prompt',
        'Start Voice',
        'Start dictation',
    }
    _EXTRACT_CHROME_POLLUTION_MARKERS = (
        'Firefox View',
        'Bookmark this page',
        'Show sidebar',
        'pinned conversation',
        'Open context menu for',
    )
    _RESPONSE_TEXT_CONTROL_ROLES = {
        'alert',
        'check box',
        'check menu item',
        'combo box',
        'entry',
        'menu',
        'menu bar',
        'menu item',
        'option',
        'page tab',
        'page tab list',
        'push button',
        'radio button',
        'radio menu item',
        'scroll bar',
        'separator',
        'toggle button',
        'tool bar',
    }
    _RESPONSE_TEXT_IGNORED_NAMES = {
        'Bad response',
        'Copy response',
        'Good response',
        'More actions',
        'Read aloud',
        'Response actions',
        'Share',
        'Switch model',
        'Your message actions',
    }

    # run() is the shared two-phase template on _ChatGPTInlineBase (FLOW §10):
    # it holds the DISPLAY-scoped dispatch lock across setup_and_send (below) and
    # releases it before monitor_and_extract so monitoring runs concurrently.

    @staticmethod
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

    @classmethod
    def prepare_identity_request(
        cls,
        request: ConsultationRequest,
        caller_attachments: list[str],
    ) -> tuple[ConsultationRequest, dict[str, Any]] | None:
        if request.session_url or caller_attachments:
            return None
        inline_context, provenance = build_inline_context(
            platform=cls.platform,
            caller_attachments=[],
        )
        return (
            replace(
                request,
                message=cls._inline_context_message(inline_context, request.message),
                attachments=[],
                caller_attachment_provenance=list(provenance),
            ),
            {
                'mode': 'identity_inline',
                'package_paths': [],
                'attachment_path': INLINE_IDENTITY_ATTACHMENT,
                'inline_context_chars': len(inline_context),
                'caller_attachment_provenance': [
                    item.serializable() for item in provenance
                ],
            },
        )

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): navigate → page-ready → clean composer →
        mode → attach → prompt → guarded send + monitor registration."""
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        cleaned_fresh_chat = False
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to ChatGPT tab')
            return False
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(target_url, verify_change=bool(urls.get('verify_navigation')))
            snap = self.runtime.snapshot()
            result.add_step('navigate', navigated, 'Navigated to ChatGPT session target', target_url=target_url, snapshot=snap.serializable())
            if not navigated:
                return False
            if not self.wait_for_page_ready_after_navigation(result):
                return False
            if not request.session_url:
                if not self.clean_composer(request, result):
                    return False
                cleaned_fresh_chat = True
                if not self.wait_for_page_ready_after_navigation(result):
                    return False
        if not self.tree_conformance_gate(result):
            return False

        if not cleaned_fresh_chat and not self.clean_composer(request, result):
            return False
        if not self.apply_selection_plan(request, result):
            return False
        if request.attachments and not self.attach_files(request, result):
            return False
        if not self.enter_prompt(request, result):
            return False
        # Idempotent send seam (FLOW §8): guarded_send reads durable run-state
        # first and RESUMES a landed send instead of re-sending; otherwise it
        # performs the real send via self.send_prompt and checkpoints submitted.
        if not self.guarded_send(request, result):
            return False
        return True

    def monitor_and_extract(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> None:
        """UNLOCKED phase (FLOW §10): monitor → extract → store. Display lock is
        already released so a concurrent consultation can set up/send here."""
        if not self.monitor_generation(request, result):
            return
        if not self.extract_primary(request, result):
            return
        if not self.extract_additional(request, result):
            return
        if not self.store_in_neo4j(request, result):
            return
        result.ok = True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _click_strategy(self) -> str:
        """Return click strategy from top-level YAML key; fall back to 'at_spi'."""
        return self.cfg.get('click_strategy', 'at_spi')

    def _click(self, element) -> bool:
        """Dispatch click using the YAML-declared strategy."""
        strategy = self._click_strategy()
        return self.runtime.click(element, strategy=strategy)

    @staticmethod
    def _element_evidence(element):
        if element is None:
            return None
        return {
            'name': element.name,
            'role': element.role,
            'x': element.x,
            'y': element.y,
            'states': list(element.states or []),
        }

    def _prompt_input_keys(self) -> tuple[str, ...]:
        prompt_cfg = self.cfg.get('workflow', {}).get('prompt', {}) or {}
        keys = prompt_cfg.get('input_keys') or prompt_cfg.get('input') or ['input']
        keys = keys if isinstance(keys, list) else [keys]
        return tuple(str(key) for key in keys if isinstance(key, str) and key)

    def _stop_keys(self) -> tuple[str, ...]:
        monitor_cfg = self.cfg.get('workflow', {}).get('monitor', {}) or {}
        keys = monitor_cfg.get('stop_keys') or monitor_cfg.get('stop_key') or ['stop_button']
        keys = keys if isinstance(keys, list) else [keys]
        return tuple(str(key) for key in keys if isinstance(key, str) and key)

    @staticmethod
    def _snapshot_elements_for_evidence(snapshot: Snapshot) -> list[ElementRef]:
        elements: list[ElementRef] = []
        for items in (snapshot.mapped or {}).values():
            elements.extend(items)
        elements.extend(snapshot.unknown or [])
        elements.extend(snapshot.menu_items or [])
        elements.extend(snapshot.sidebar or [])
        return elements

    def _stop_like_candidates(self, snapshot: Snapshot, *, limit: int = 12) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for element in self._snapshot_elements_for_evidence(snapshot):
            name = str(element.name or '').strip()
            role = str(element.role or '').strip().lower()
            if 'stop' not in name.lower() or role not in {'push button', 'button'}:
                continue
            candidates.append(self._element_evidence(element))
            if len(candidates) >= limit:
                break
        return candidates

    def _stop_read_evidence(
        self,
        scope: str,
        snapshot: Snapshot,
        stop_keys: tuple[str, ...],
    ) -> dict[str, object]:
        found = {
            key: [self._element_evidence(element) for element in (snapshot.mapped or {}).get(key) or []]
            for key in stop_keys
            if (snapshot.mapped or {}).get(key)
        }
        return {
            'scope': scope,
            'raw_count': int(snapshot.raw_count or 0),
            'present': bool(found),
            'found': found,
            'stop_like_candidates': self._stop_like_candidates(snapshot),
        }

    def _stop_snapshot_probe(self, stop_keys: tuple[str, ...]) -> tuple[bool, Snapshot, dict[str, object]]:
        scopes: list[dict[str, object]] = []
        snap = self.runtime.snapshot()
        doc_evidence = self._stop_read_evidence('snapshot', snap, stop_keys)
        scopes.append(doc_evidence)
        if doc_evidence['present']:
            return True, snap, {'present': True, 'scope': 'snapshot', 'scopes': scopes}

        app_snap = self.runtime.app_root_snapshot(allowed_roles=['push button'])
        app_evidence = self._stop_read_evidence('app_root_push_buttons', app_snap, stop_keys)
        scopes.append(app_evidence)
        if app_evidence['present']:
            return True, app_snap, {'present': True, 'scope': 'app_root_push_buttons', 'scopes': scopes}
        return False, app_snap, {'present': False, 'scope': 'absent', 'scopes': scopes}

    def _read_stop_state(
        self,
        stop_keys: tuple[str, ...],
        *,
        confirm_absence: bool,
    ) -> tuple[bool, Snapshot, dict[str, object]]:
        first_present, first_snapshot, first_evidence = self._stop_snapshot_probe(stop_keys)
        if first_present or not confirm_absence:
            first_evidence['confirmed_absent'] = False
            return first_present, first_snapshot, first_evidence

        time.sleep(0.25)
        second_present, second_snapshot, second_evidence = self._stop_snapshot_probe(stop_keys)
        if second_present:
            second_evidence.update({
                'confirmed_absent': False,
                'rescan_after_absent': True,
                'previous_absent_read': first_evidence,
            })
            return True, second_snapshot, second_evidence
        second_evidence.update({
            'confirmed_absent': True,
            'rescan_after_absent': True,
            'previous_absent_read': first_evidence,
        })
        return False, second_snapshot, second_evidence

    @staticmethod
    def _compact_stop_reading(evidence: dict[str, object]) -> dict[str, object]:
        return {
            'present': bool(evidence.get('present')),
            'scope': evidence.get('scope'),
            'confirmed_absent': bool(evidence.get('confirmed_absent')),
            'rescan_after_absent': bool(evidence.get('rescan_after_absent')),
            'scopes': [
                {
                    'scope': scope.get('scope'),
                    'raw_count': scope.get('raw_count'),
                    'present': bool(scope.get('present')),
                    'found_keys': sorted((scope.get('found') or {}).keys()),
                    'stop_like_candidates': scope.get('stop_like_candidates') or [],
                }
                for scope in (evidence.get('scopes') or [])
                if isinstance(scope, dict)
            ],
        }

    def _minimum_stop_gone_cycles(self) -> int:
        monitor_cfg = self.cfg.get('workflow', {}).get('monitor', {}) or {}
        raw = monitor_cfg.get('sustained_stop_gone_cycles', 4)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 4

    def _post_complete_quiet_cycles(self) -> int:
        monitor_cfg = self.cfg.get('workflow', {}).get('monitor', {}) or {}
        raw = monitor_cfg.get('post_complete_quiet_cycles', 8)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 8

    def _effective_generation_timeout(
        self,
        request: ConsultationRequest,
        detector_mode: str,
    ) -> float:
        monitor_cfg = self.cfg.get('workflow', {}).get('monitor', {}) or {}
        raw = monitor_cfg.get('generation_timeout', request.timeout)
        try:
            configured_timeout = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                'ChatGPT workflow.monitor.generation_timeout must be numeric seconds'
            ) from exc
        effective_timeout = max(float(request.timeout), configured_timeout)
        if detector_mode in DEEP_MODES:
            effective_timeout = max(effective_timeout, DEEP_GENERATION_FLOOR_SECONDS)
        return effective_timeout

    def _send_button_keys(self) -> tuple[str, ...]:
        prompt_cfg = self.cfg.get('workflow', {}).get('prompt', {}) or {}
        keys = prompt_cfg.get('send_button_keys') or prompt_cfg.get('send_button') or ['send_button']
        keys = keys if isinstance(keys, list) else [keys]
        return tuple(str(key) for key in keys if isinstance(key, str) and key)

    def _bottommost_input(self, snapshot):
        inputs = []
        for key in self._prompt_input_keys():
            inputs.extend((snapshot.mapped or {}).get(key) or [])
        if not inputs:
            return None
        with_coords = [item for item in inputs if item.x is not None and item.y is not None]
        candidates = with_coords or inputs
        return max(
            candidates,
            key=lambda item: (
                item.y if item.y is not None else -1,
                item.x if item.x is not None else -1,
            ),
        )

    @staticmethod
    def _atspi_state_names(obj) -> set[str]:
        if obj is None:
            return set()
        try:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi as _Atspi

            states = obj.get_state_set()
            interesting = (
                _Atspi.StateType.EDITABLE,
                _Atspi.StateType.ENABLED,
                _Atspi.StateType.FOCUSED,
                _Atspi.StateType.FOCUSABLE,
                _Atspi.StateType.MULTI_LINE,
                _Atspi.StateType.SHOWING,
                _Atspi.StateType.VISIBLE,
            )
            return {
                state.value_nick
                for state in interesting
                if states.contains(state)
            }
        except Exception:
            return set()

    def _atspi_object_evidence(self, obj) -> dict[str, object] | None:
        if obj is None:
            return None
        try:
            name = obj.get_name() or ''
        except Exception:
            name = ''
        try:
            role = obj.get_role_name() or ''
        except Exception:
            role = ''
        return {
            'name': name,
            'role': role,
            'states': sorted(self._atspi_state_names(obj)),
            'rect': self._screen_rect(obj),
        }

    def _bounded_composer_focus_target(self, snapshot: Snapshot, input_node) -> tuple[object | None, dict[str, object]]:
        input_rect = self._screen_rect(input_node.atspi_obj) if input_node else None
        evidence: dict[str, object] = {
            'ok': False,
            'source': 'bounded_composer_ancestor',
            'input_node': self._element_evidence(input_node),
            'input_rect': input_rect,
        }
        if input_node is None or input_node.atspi_obj is None:
            evidence['reason'] = 'composer_input_missing'
            return None, evidence
        if input_rect and int(input_rect.get('width') or 0) > 0 and int(input_rect.get('height') or 0) > 0:
            x = int(input_rect['x'] + input_rect['width'] // 2)
            y = int(input_rect['y'] + input_rect['height'] // 2)
            target_evidence = {
                'source': 'composer_input',
                'depth': 0,
                'broad': False,
                'node': self._atspi_object_evidence(input_node.atspi_obj),
            }
            evidence.update({
                'ok': True,
                'reason': 'bounded_composer_input',
                'target': target_evidence,
                'click_point': {'x': x, 'y': y},
                'checked_candidates': [target_evidence],
            })
            return input_node.atspi_obj, evidence

        seen: set[int] = set()
        candidates: list[tuple[str, int, object]] = []

        root = self._composer_scope_root(snapshot)
        evidence['composer_scope_root'] = self._atspi_object_evidence(root)
        if root is not None:
            for depth, obj in enumerate(self._atspi_path_to_root(root)):
                candidates.append(('composer_scope_root', depth, obj))
                if depth > 0 and self._is_broad_scope_root(obj):
                    break

        for depth, obj in enumerate(self._atspi_path_to_root(input_node.atspi_obj)[1:], start=1):
            candidates.append(('composer_input_ancestor', depth, obj))
            if self._is_broad_scope_root(obj):
                break

        checked: list[dict[str, object]] = []
        for source, depth, obj in candidates:
            identity = id(obj)
            if identity in seen:
                continue
            seen.add(identity)
            broad = self._is_broad_scope_root(obj)
            rect = None if broad else self._screen_rect(obj)
            candidate_evidence = {
                'source': source,
                'depth': depth,
                'broad': broad,
                'node': self._atspi_object_evidence(obj),
            }
            checked.append(candidate_evidence)
            if not rect:
                continue
            x = int(rect['x'] + rect['width'] // 2)
            y = int(rect['y'] + rect['height'] // 2)
            evidence.update({
                'ok': True,
                'reason': 'bounded_composer_ancestor',
                'target': candidate_evidence,
                'click_point': {'x': x, 'y': y},
                'checked_candidates': checked[:8],
            })
            return obj, evidence

        evidence.update({
            'reason': 'no_bounded_composer_ancestor',
            'checked_candidates': checked[:8],
        })
        return None, evidence

    def _focused_editable_descendant(self, root):
        if root is None:
            return None
        seen: set[int] = set()
        queue: list[tuple[object, int]] = [(root, 0)]
        while queue:
            obj, depth = queue.pop(0)
            identity = id(obj)
            if identity in seen:
                continue
            seen.add(identity)
            states = self._atspi_state_names(obj)
            try:
                role = obj.get_role_name() or ''
            except Exception:
                role = ''
            if 'focused' in states and ('editable' in states or role in {'entry', 'paragraph'}):
                return obj
            if depth >= 12:
                continue
            try:
                count = min(obj.get_child_count(), 80)
            except Exception:
                continue
            for index in range(count):
                try:
                    child = obj.get_child_at_index(index)
                except Exception:
                    child = None
                if child is not None:
                    queue.append((child, depth + 1))
        return None

    def _composer_focus_verification(self, target_obj) -> tuple[bool, ElementRef | None, dict[str, object]]:
        focused_editable = self._focused_editable_descendant(target_obj)
        snap = self.runtime.snapshot()
        focused_input = self._bottommost_input(snap)
        input_states = {str(state).strip().lower() for state in (focused_input.states or [])} if focused_input else set()
        evidence = {
            'focused_editable': self._atspi_object_evidence(focused_editable),
            'focused_input': self._element_evidence(focused_input),
            'focused_input_states': sorted(input_states),
            'focused_input_wrapper': bool(focused_input and 'focused' in input_states),
        }
        return bool(focused_editable), focused_input, evidence

    def _focus_composer(self):
        """Focus ChatGPT's bounded composer ancestor and return the input proof.

        The mapped ChatGPT composer entry exists in AT-SPI but can expose no
        component extents, so clicking the entry itself may set wrapper focus
        without placing keyboard focus in ProseMirror. Use the bounded composer
        scope ancestor as the click target, then require a focused editable
        descendant before Return.
        """
        from consultation_v2 import input as _inp

        self._last_composer_focus_evidence = {
            'ok': False,
            'reason': 'not_started',
        }
        firefox_focused = self.runtime.focus_firefox()
        time.sleep(0.2)

        def _find_input_entry():
            snap = self.runtime.snapshot()
            return self._bottommost_input(snap)

        node = self.runtime.wait_until(_find_input_entry, timeout=10, interval=0.4)
        if node is None:
            self._last_composer_focus_evidence = {
                'ok': False,
                'reason': 'composer_input_missing',
                'firefox_focused': firefox_focused,
            }
            return None

        for click_attempt in (1, 2):
            snap = self.runtime.snapshot()
            refreshed = self._bottommost_input(snap)
            if refreshed is not None:
                node = refreshed
            target_obj, target_evidence = self._bounded_composer_focus_target(snap, node)
            focus_evidence = {
                'ok': False,
                'attempt': click_attempt,
                'firefox_focused': firefox_focused,
                **target_evidence,
            }
            if target_obj is None or not target_evidence.get('ok'):
                self._last_composer_focus_evidence = focus_evidence
                continue
            click_point = target_evidence.get('click_point') or {}
            clicked = bool(_inp.click_at(int(click_point['x']), int(click_point['y'])))
            focus_evidence['clicked'] = clicked
            if not clicked:
                focus_evidence['reason'] = 'bounded_composer_click_failed'
                self._last_composer_focus_evidence = focus_evidence
                continue
            time.sleep(0.25)

            last_verification: dict[str, object] = {}

            def _focused_editable_entry():
                nonlocal last_verification
                landed, focused_input, verification = self._composer_focus_verification(target_obj)
                last_verification = verification
                if landed:
                    return focused_input or node
                return None

            focused = self.runtime.wait_until(_focused_editable_entry, timeout=5.0, interval=0.25)
            focus_evidence['verification'] = last_verification
            if focused is not None:
                focus_evidence.update({
                    'ok': True,
                    'reason': 'focused_editable_descendant',
                    'focus_node': self._element_evidence(focused),
                })
                self._last_composer_focus_evidence = focus_evidence
                return focused

            focus_evidence['reason'] = 'composer_focus_not_landed_extentsless_node'
            self._last_composer_focus_evidence = focus_evidence

        return None

    # ------------------------------------------------------------------
    # Clean composer (D1) — FORCE a fresh chat before doing any work
    # ------------------------------------------------------------------

    def clean_composer(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        """FORCE a clean fresh chat so a restored stale draft / old file
        attachment / reopened temporary-or-old thread can NEVER be sent.

        ROOT CAUSE (D1): ChatGPT reopens the composer with the previous turn's
        draft text + the previous file attachment + an old/temporary thread, so
        navigate->attach->enter->send operate on contaminated state and ship the
        WRONG content (PROD 2026-06-15: a sorter dispatch fired an old
        CPT-packing packet). The page-content snapshot excludes the sidebar, so
        the live New Chat control is unreachable by element lookup here. Use the
        documented Ctrl+Shift+O shortcut, then verify the fresh composer is empty
        before proceeding.

        For a follow-up session (request.session_url set) we must NOT start a new
        chat — that would abandon the thread. Skip in that case.
        """
        if request.session_url:
            result.add_step('clean_composer', True,
                            'ChatGPT follow-up session — keeping existing thread (no New chat)')
            return True

        initial_focus = self._focus_composer()
        if initial_focus is None:
            result.add_step('clean_composer', False,
                            'ChatGPT composer not focusable before New chat shortcut',
                            snapshot=self.runtime.snapshot().serializable())
            return False
        if not self.runtime.press('ctrl+shift+o'):
            result.add_step('clean_composer', False,
                            'ChatGPT New chat shortcut failed',
                            focus_node=self._element_evidence(initial_focus),
                            snapshot=self.runtime.snapshot().serializable())
            return False
        time.sleep(0.8)
        shortcut_library_windows_closed = self._close_firefox_library_windows()
        if shortcut_library_windows_closed:
            retry_focus = self._focus_composer()
            if retry_focus is not None and self.runtime.press('ctrl+shift+o'):
                fresh_focus = retry_focus
                time.sleep(0.8)
            else:
                fresh_focus = None
        else:
            fresh_focus = self._focus_composer()
        if fresh_focus is None:
            result.add_step('clean_composer', False,
                            'ChatGPT fresh composer not focusable after New chat shortcut',
                            focus_node=self._element_evidence(initial_focus),
                            browser_library_windows_closed=shortcut_library_windows_closed,
                            snapshot=self.runtime.snapshot().serializable())
            return False
        # Belt-and-suspenders: clear any draft the fresh chat restored, then
        # verify it is empty.
        #
        # FOCUS-BASED, NOT find_first('input'): ChatGPT's composer is NAMELESS
        # ProseMirror `[paragraph]` nodes (state 'editable'), NOT a findable
        # `entry`/`input` element (live-verified on :2 2026-06-15:
        # find_first('input') == None, the composer is 13 nameless paragraphs).
        # Nameless nodes CANNOT be exact-matched (contract forbids fuzzy/nameless
        # matching), so there is nothing to find_first/click — the contract-clean
        # primitive is keyboard-to-focused-composer. The shortcut-created fresh
        # composer is explicitly focused above; activate the Firefox window so
        # the keys land, then ctrl+a + Delete clears any restored draft text. This is the
        # documented working ChatGPT method (100_TIMES / memory: "ProseMirror not
        # in AT-SPI; paste directly into the focused composer"), NOT a fallback.
        if not self.runtime.focus_firefox():
            result.add_step('clean_composer', False,
                            'ChatGPT Firefox focus failed before composer clear',
                            focus_node=self._element_evidence(fresh_focus),
                            snapshot=self.runtime.snapshot().serializable())
            return False
        time.sleep(0.3)
        if not self.runtime.press('ctrl+a'):
            result.add_step('clean_composer', False,
                            'ChatGPT composer select-all failed during clean',
                            focus_node=self._element_evidence(fresh_focus),
                            snapshot=self.runtime.snapshot().serializable())
            return False
        time.sleep(0.15)
        if not self.runtime.press('Delete'):
            result.add_step('clean_composer', False,
                            'ChatGPT composer delete failed during clean',
                            focus_node=self._element_evidence(fresh_focus),
                            snapshot=self.runtime.snapshot().serializable())
            return False
        time.sleep(0.3)

        verify_timeout = max(5.0, self._base_conformance_settle_seconds())
        (
            verify_snap,
            empty_samples,
            empty_probes,
            empty_elapsed,
        ) = self._wait_for_empty_fresh_composer(timeout=verify_timeout)
        late_library_windows_closed = 0
        if verify_snap is None:
            late_library_windows_closed = self._close_firefox_library_windows()
            if late_library_windows_closed:
                retry_focus = self._focus_composer()
                if retry_focus is not None and self.runtime.press('ctrl+shift+o'):
                    fresh_focus = retry_focus
                    time.sleep(0.8)
                    (
                        verify_snap,
                        empty_samples,
                        empty_probes,
                        empty_elapsed,
                    ) = self._wait_for_empty_fresh_composer(timeout=verify_timeout)
        if verify_snap is None:
            verify_snap = self.runtime.snapshot()
            result.add_step(
                'clean_composer',
                False,
                'ChatGPT clean composer verification failed',
                has_input=bool(self._bottommost_input(verify_snap)),
                send_button_present=self.snapshot_has_any(verify_snap, self._send_button_keys()),
                focus_node=self._element_evidence(fresh_focus),
                snapshot=verify_snap.serializable(),
                empty_composer_clean_samples=empty_samples,
                empty_composer_required_clean_samples=CLEAN_COMPOSER_EMPTY_SNAPSHOTS,
                empty_composer_probes=empty_probes,
                empty_composer_elapsed_seconds=round(empty_elapsed, 3),
                empty_composer_timeout_seconds=verify_timeout,
                browser_library_windows_closed=shortcut_library_windows_closed + late_library_windows_closed,
            )
            return False
        late_library_windows_closed += self._close_firefox_library_windows()
        result.add_step('clean_composer', True,
                        'ChatGPT forced clean fresh chat via New chat shortcut',
                        shortcut='ctrl+shift+o',
                        focus_node=self._element_evidence(fresh_focus),
                        empty_composer_clean_samples=empty_samples,
                        empty_composer_required_clean_samples=CLEAN_COMPOSER_EMPTY_SNAPSHOTS,
                        empty_composer_probes=empty_probes,
                        empty_composer_elapsed_seconds=round(empty_elapsed, 3),
                        browser_library_windows_closed=shortcut_library_windows_closed + late_library_windows_closed,
                        snapshot=verify_snap.serializable())
        return True

    def _close_firefox_library_windows(self) -> int:
        env = os.environ.copy()
        env['DISPLAY'] = self._display()
        try:
            found = subprocess.run(
                ['xdotool', 'search', '--onlyvisible', '--class', 'firefox'],
                capture_output=True,
                text=True,
                timeout=2,
                env=env,
            )
        except Exception:
            return 0
        closed = 0
        for window_id in found.stdout.split():
            try:
                title = subprocess.run(
                    ['xdotool', 'getwindowname', window_id],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env=env,
                ).stdout.strip()
            except Exception:
                continue
            if title != 'Library':
                continue
            try:
                subprocess.run(
                    ['xdotool', 'windowclose', window_id],
                    capture_output=True,
                    timeout=3,
                    env=env,
                )
                closed += 1
            except Exception:
                continue
        if closed:
            time.sleep(0.8)
        return closed

    def _wait_for_empty_fresh_composer(self, *, timeout: float) -> tuple[Snapshot | None, int, int, float]:
        started = time.monotonic()
        deadline = started + timeout
        clean_samples = 0
        probes = 0
        last_snapshot: Snapshot | None = None
        anchor_key = self._selection_base_anchor_key()

        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=2,
                timeout=min(remaining, 1.2),
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
            probes += 1
            if self._bottommost_input(last_snapshot) and not self.snapshot_has_any(last_snapshot, self._send_button_keys()):
                clean_samples += 1
                if clean_samples >= CLEAN_COMPOSER_EMPTY_SNAPSHOTS:
                    return last_snapshot, clean_samples, probes, time.monotonic() - started
            else:
                clean_samples = 0
            time.sleep(0.2)
        return None, clean_samples, probes, time.monotonic() - started

    # ------------------------------------------------------------------
    # File attachment
    # ------------------------------------------------------------------

    @staticmethod
    def _attachment_name_matches(display_name: str, filename: str) -> bool:
        expected_path = os.path.abspath(filename)
        expected_name = os.path.basename(filename)
        displayed_file = display_name.split()[0] if display_name else ''
        for expected in (expected_path, expected_name):
            if display_name == expected or displayed_file == expected:
                return True
            if '...' in displayed_file:
                prefix, suffix = displayed_file.split('...', 1)
                if expected.startswith(prefix) and expected.endswith(suffix):
                    return True
        return False

    def _attachment_visible(self, snapshot, filename: str) -> bool:
        return self._attachment_chip(snapshot, filename) is not None

    def _attachment_chip(self, snapshot: Snapshot, filename: str) -> ElementRef | None:
        allowed_roles = {'push button', 'panel'}
        return next(
            (
                element
                for element in self._composer_scope_elements(snapshot)
                if element.role in allowed_roles
                and self._attachment_name_matches(element.name or '', filename)
            ),
            None,
        )

    def _paste_chip_names(
        self,
        snapshot: Snapshot,
        baseline_names: set[str],
        elements: list[ElementRef] | None = None,
    ) -> set[str]:
        candidates = elements if elements is not None else self._snapshot_elements(snapshot)
        return {
            name
            for element in candidates
            if (name := (element.name or '').strip())
            and name not in baseline_names
            and self._looks_like_paste_chip(element, name)
        }

    @classmethod
    def _looks_like_paste_chip(cls, element: ElementRef, name: str) -> bool:
        role = (element.role or '').strip().lower()
        if role not in cls._AUTO_CHIP_ROLES:
            return False
        if name in cls._AUTO_CHIP_IGNORED_NAMES:
            return False
        lower_name = name.lower()
        failure_terms = (
            'cannot',
            'error',
            'failed',
            'not supported',
            'too large',
            'try again',
            'unsupported',
        )
        if any(term in lower_name for term in failure_terms):
            return False
        attachment_terms = (
            'attachment',
            'markdown',
            'package',
            'paste',
            'pasted',
            'txt',
        )
        if any(term in lower_name for term in attachment_terms):
            return True
        if ',' in lower_name:
            size_terms = (' bytes', ' kb', ' mb', ' lines', ' words')
            return any(term in lower_name for term in size_terms)
        return False

    def _composer_paste_chip_names(self, snapshot: Snapshot) -> list[str]:
        return sorted(self._paste_chip_names(
            snapshot,
            set(),
            elements=self._composer_scope_elements(snapshot),
        ))

    def _composer_scope_elements(self, snapshot: Snapshot) -> list[ElementRef]:
        root = self._composer_scope_root(snapshot)
        if root is not None:
            return [
                element
                for element in self._snapshot_elements(snapshot)
                if self._element_descends_from(element, root)
            ]
        return self._composer_band_elements(snapshot)

    def _composer_scope_root(self, snapshot: Snapshot):
        objects = [
            element.atspi_obj
            for key in self._composer_scope_keys()
            for element in (snapshot.mapped.get(key) or [])
            if element.atspi_obj is not None
        ]
        paths = [path for obj in objects if (path := self._atspi_path_to_root(obj))]
        if not paths:
            return None
        if len(paths) == 1:
            root = paths[0][1] if len(paths[0]) > 1 else paths[0][0]
            return None if self._is_broad_scope_root(root) else root
        for candidate in paths[0]:
            if all(any(candidate == other for other in path) for path in paths[1:]):
                return None if self._is_broad_scope_root(candidate) else candidate
        return None

    def _composer_band_elements(self, snapshot: Snapshot) -> list[ElementRef]:
        anchors = [
            element
            for key in self._composer_scope_keys()
            for element in (snapshot.mapped.get(key) or [])
            if element.x is not None and element.y is not None
        ]
        if not anchors:
            return []
        min_x = min(int(element.x) for element in anchors) - 80
        max_x = max(int(element.x) for element in anchors) + 80
        min_y = min(int(element.y) for element in anchors) - 140
        max_y = max(int(element.y) for element in anchors) + 140
        candidates: list[ElementRef] = []
        for items in getattr(snapshot, 'mapped', {}).values():
            candidates.extend(items)
        candidates.extend(getattr(snapshot, 'unknown', []) or [])
        return [
            element
            for element in candidates
            if element.x is not None
            and element.y is not None
            and min_x <= int(element.x) <= max_x
            and min_y <= int(element.y) <= max_y
        ]

    def _composer_scope_keys(self) -> tuple[str, ...]:
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        if not isinstance(element_map, dict):
            return ()
        keys: list[str] = []
        for key, spec in element_map.items():
            if not isinstance(spec, dict):
                continue
            scope = str(spec.get('scope') or '').strip().lower()
            if scope == 'base.composer' or scope.startswith('base.composer.'):
                keys.append(str(key))
        return tuple(keys)

    @staticmethod
    def _atspi_path_to_root(obj) -> list[object]:
        path: list[object] = []
        current = obj
        for _ in range(60):
            if current is None:
                break
            path.append(current)
            try:
                current = current.get_parent()
            except Exception:
                break
        return path

    @classmethod
    def _element_descends_from(cls, element: ElementRef, root) -> bool:
        obj = element.atspi_obj
        if obj is None:
            return False
        return any(candidate == root for candidate in cls._atspi_path_to_root(obj))

    @staticmethod
    def _is_broad_scope_root(root) -> bool:
        try:
            role = str(root.get_role_name() or '').strip().lower()
        except Exception:
            return False
        return role in {'application', 'document web', 'frame', 'window'}

    def _file_dialog_open(self) -> bool:
        env_factory = getattr(self.runtime, '_dialog_env', None)
        finder = getattr(self.runtime, '_file_dialog_window', None)
        if not callable(env_factory) or not callable(finder):
            return False
        return finder(env_factory()) is not None

    def _wait_for_attachment_chip(self, abs_path: str) -> tuple[Snapshot, ElementRef | None, bool]:
        last_snapshot: Snapshot | None = None

        def _probe() -> Snapshot | None:
            nonlocal last_snapshot
            if self._file_dialog_open():
                return None
            snap = self.runtime.snapshot()
            last_snapshot = snap
            chip = self._attachment_chip(snap, abs_path)
            return snap if chip is not None else None

        matched = self.runtime.wait_until(
            _probe,
            timeout=15.0,
            interval=0.5,
        )
        verify_snap = matched if isinstance(matched, Snapshot) else last_snapshot or self.runtime.snapshot()
        return verify_snap, self._attachment_chip(verify_snap, abs_path), not self._file_dialog_open()

    def _snapshot_elements(self, snapshot: Snapshot) -> list[ElementRef]:
        all_elements: list[ElementRef] = []
        for items in getattr(snapshot, 'mapped', {}).values():
            all_elements.extend(items)
        all_elements.extend(getattr(snapshot, 'unknown', []) or [])
        all_elements.extend(getattr(snapshot, 'sidebar', []) or [])
        all_elements.extend(getattr(snapshot, 'menu_items', []) or [])
        return all_elements

    @staticmethod
    def _element_state_set(element: ElementRef | None) -> set[str]:
        if element is None:
            return set()
        return {str(state).strip().lower() for state in (element.states or [])}

    def _attachment_upload_blockers(self, snapshot: Snapshot) -> list[dict[str, object]]:
        busy_terms = (
            'uploading',
            'processing',
            'scanning',
            'loading',
            'spinner',
            'progress',
            'preparing',
            'queued',
        )
        blockers = []
        for element in self._snapshot_elements(snapshot):
            haystack = ' '.join(
                str(value or '')
                for value in (
                    element.name,
                    element.description,
                    element.text,
                    element.role,
                )
            ).lower()
            if any(term in haystack for term in busy_terms):
                blockers.append(self._element_evidence(element))
        return blockers

    def _wait_for_attachment_upload_complete(
        self,
        request: ConsultationRequest,
        timeout: float,
    ) -> tuple[Snapshot | None, dict[str, object], Snapshot | None]:
        attachment_paths = [os.path.abspath(path) for path in request.attachments]
        started = time.time()
        last_snapshot: Snapshot | None = None
        last_evidence: dict[str, object] = {
            'attachments': attachment_paths,
            'missing_attachments': attachment_paths,
            'send_key': None,
            'send_button': None,
            'send_button_ready': False,
            'upload_blockers': [],
            'elapsed_seconds': 0.0,
        }
        consecutive_ready = 0

        def _probe_ready() -> Snapshot | None:
            nonlocal consecutive_ready, last_snapshot, last_evidence
            snap = self.runtime.snapshot()
            last_snapshot = snap
            missing = [
                path for path in attachment_paths
                if not self._attachment_visible(snap, path)
            ]
            send_key, send_button = self.find_first_any(snap, self._send_button_keys())
            states = self._element_state_set(send_button)
            upload_blockers = self._attachment_upload_blockers(snap)
            send_button_ready = bool(
                send_button
                and 'enabled' in states
                and 'focusable' in states
            )
            ready = bool(not missing and send_button_ready and not upload_blockers)
            if ready:
                consecutive_ready += 1
            else:
                consecutive_ready = 0
            last_evidence = {
                'attachments': attachment_paths,
                'missing_attachments': missing,
                'send_key': send_key,
                'send_button': self._element_evidence(send_button),
                'send_button_ready': send_button_ready,
                'required_ready_cycles': 2,
                'observed_ready_cycles': consecutive_ready,
                'upload_blockers': upload_blockers,
                'elapsed_seconds': round(time.time() - started, 2),
            }
            if consecutive_ready >= 2:
                return snap
            return None

        ready_snapshot = self.runtime.wait_until(
            _probe_ready,
            timeout=max(float(timeout), 15.0),
            interval=0.5,
        )
        return ready_snapshot, last_evidence, last_snapshot

    def attach_files(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        self.runtime.close_stale_dialogs()
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger:
                result.add_step('attach', False, f'ChatGPT attach trigger not found for {abs_path}', snapshot=snap.serializable())
                return False

            attachment = self.cfg.get('workflow', {}).get('attachment', {}) or {}
            if str(attachment.get('open_method') or '').strip().lower() != 'focus_and_key_open':
                result.add_step('attach', False, 'ChatGPT attachment requires focus_and_key_open tools-menu flow', snapshot=snap.serializable())
                return False
            open_evidence = self.runtime.focus_and_key_open(
                trigger,
                key=str(attachment.get('open_key') or 'space'),
                settle=0.3,
            )
            if not open_evidence.get('ok'):
                result.add_step('attach', False, f'ChatGPT attach trigger focus+key open failed for {abs_path}', open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            typeahead_label = str(attachment.get('typeahead_label') or '').strip()
            if not typeahead_label:
                result.add_step('attach', False, 'ChatGPT attachment missing typeahead_label', open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            if not self.runtime.type_text(typeahead_label, delay_ms=5):
                result.add_step('attach', False, f'ChatGPT upload typeahead failed for {abs_path}', typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            for submit_key in attachment.get('typeahead_submit_keys') or ['Down', 'Return']:
                if not self.runtime.press(str(submit_key)):
                    result.add_step('attach', False, f'ChatGPT upload typeahead submit key failed for {abs_path}', submit_key=str(submit_key), typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                    return False
                time.sleep(0.15)
            if not self.runtime.focus_file_dialog():
                result.add_step('attach', False, f'ChatGPT file dialog did not focus for {abs_path}', typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            if not self.runtime.press('ctrl+l'):
                result.add_step('attach', False, f'ChatGPT file dialog location shortcut failed for {abs_path}', typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            time.sleep(0.2)
            if not self.runtime.press('ctrl+a'):
                result.add_step('attach', False, f'ChatGPT file dialog path select-all failed for {abs_path}', typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            time.sleep(0.2)
            if not self.runtime.paste(abs_path):
                result.add_step('attach', False, f'ChatGPT file dialog path paste failed for {abs_path}', typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            time.sleep(0.2)
            if not self.runtime.focus_file_dialog():
                result.add_step('attach', False, f'ChatGPT file dialog lost focus before submit for {abs_path}', typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            # ONE Return is sufficient: selects the file and closes the GTK dialog.
            # A second Return would hit the now-focused chat input and submit garbage.
            if not self.runtime.press('Return'):
                result.add_step('attach', False, f'ChatGPT file dialog submit failed for {abs_path}', typeahead_label=typeahead_label, open_evidence=open_evidence, snapshot=snap.serializable())
                return False
            verify_snap, chip, dialog_closed = self._wait_for_attachment_chip(abs_path)
            verified = bool(chip and dialog_closed)
            result.add_step(
                'attach',
                verified,
                f'ChatGPT attached {os.path.basename(abs_path)}',
                file=abs_path,
                dialog_closed=dialog_closed,
                chip=self._element_evidence(chip),
                snapshot=verify_snap.serializable(),
            )
            if not verified:
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No ChatGPT attachments requested')
        return True

    # ------------------------------------------------------------------
    # Prompt entry and send
    # ------------------------------------------------------------------

    def enter_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        # FOCUS-BASED, NOT find_first('input'): ChatGPT's composer is nameless
        # ProseMirror paragraphs, not a findable entry (live-verified :2
        # 2026-06-15). The contract-clean primitive is keyboard-to-focused-
        # composer — activate Firefox (the composer holds focus after attach /
        # clean_composer), clear any leftover text, then paste. (100_TIMES /
        # memory: "ProseMirror not in AT-SPI; paste directly into the focused
        # composer.") NOT a fallback — the correct composer primitive.
        from consultation_v2 import input as _inp
        self.runtime.focus_firefox()
        time.sleep(0.3)
        # Final-guard clear immediately before paste. The authoritative
        # stale-state purge is clean_composer() (D1: forces a fresh New chat,
        # discarding any restored draft / attachment / old thread). This ctrl+a
        # + Delete is the belt-and-suspenders clear right before the intended
        # paste, so even if attach left odd composer state the message replaces
        # it cleanly rather than appending to leftover text.
        _inp.press_key('ctrl+a')
        time.sleep(0.15)
        _inp.press_key('Delete')
        time.sleep(0.2)
        pasted = self.runtime.paste(request.message)
        verify_snap = self.runtime.snapshot()
        paste_chip_names = self._composer_paste_chip_names(verify_snap)
        verified = bool(pasted)
        result.add_step(
            'prompt',
            verified,
            'ChatGPT prompt entered',
            paste_chip_names=paste_chip_names[:3],
            snapshot=verify_snap.serializable(),
        )
        return verified

    @staticmethod
    def _send_failure_reason(attempts: list[dict]) -> str:
        if not attempts:
            return 'send_not_attempted'
        last = attempts[-1]
        focus = last.get('focus') if isinstance(last.get('focus'), dict) else {}
        if last.get('phase') == 'send_button_ready' and not last.get('ready'):
            return 'send_button_not_ready'
        if last.get('phase') == 'exact_send_button_click' and not last.get('clicked'):
            return 'send_button_click_failed'
        if last.get('phase') == 'exact_send_button_click':
            if last.get('stop_seen') and not last.get('url_landed'):
                return 'send_validation_stop_seen_url_missing'
            if last.get('url_landed') and not last.get('stop_seen'):
                return 'send_validation_url_seen_stop_missing'
            if last.get('prompt_still_staged'):
                return 'send_button_click_not_delivered_prompt_still_staged'
            return 'send_landing_unverified'
        if focus.get('reason') == 'composer_focus_not_landed_extentsless_node':
            return 'composer_focus_did_not_land_extentsless_node'
        if focus.get('reason') == 'no_bounded_composer_ancestor':
            return 'composer_has_no_bounded_focus_ancestor'
        if not last.get('focused'):
            return 'composer_focus_did_not_land'
        if not last.get('pressed'):
            return 'return_keypress_failed'
        if last.get('stop_seen') and not last.get('url_landed'):
            return 'send_validation_stop_seen_url_missing'
        if last.get('url_landed') and not last.get('stop_seen'):
            return 'send_validation_url_seen_stop_missing'
        if last.get('prompt_still_staged'):
            return 'return_not_delivered_prompt_still_staged'
        return 'send_landing_unverified'

    def _send_button_readiness(self, snapshot: Snapshot) -> tuple[str | None, ElementRef | None, dict[str, object]]:
        send_key, send_button = self.find_first_any(snapshot, self._send_button_keys())
        states = self._element_state_set(send_button)
        paste_chip_names = self._composer_paste_chip_names(snapshot)
        has_coordinates = bool(send_button and send_button.x is not None and send_button.y is not None)
        state_ready = 'enabled' in states
        paste_chip_ready = bool(paste_chip_names)
        ready = bool(
            send_button
            and has_coordinates
            and state_ready
        )
        return send_key, send_button, {
            'phase': 'send_button_ready',
            'send_key': send_key,
            'send_button': self._element_evidence(send_button),
            'states': sorted(states),
            'ready': ready,
            'has_coordinates': has_coordinates,
            'state_ready': state_ready,
            'paste_chip_ready': paste_chip_ready,
            'paste_chip_names': paste_chip_names[:3],
        }

    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        # Use the pre-navigation baseline captured in run() — file attachment
        # can change the URL before send, making current_url() stale.
        before = result.session_url_before
        # SEND = exact mapped Send prompt button click. This is not a fixed pixel
        # fallback: the click point comes from the YAML-mapped, enabled send
        # element in the current tree. Stop/url validation still gates success.
        attempts = []
        configured_timeout = float(self.cfg.get('workflow', {}).get('send', {}).get('timeout', 120) or 120)
        full_timeout = max(120.0, configured_timeout)
        first_probe_timeout = min(12.0, full_timeout)
        stop_keys = self._stop_keys()
        if request.attachments:
            upload_snap, upload_readiness, last_upload_snap = (
                self._wait_for_attachment_upload_complete(
                    request,
                    timeout=max(full_timeout, 300.0),
                )
            )
            attempts.append({
                'phase': 'attachment_upload_ready',
                **upload_readiness,
            })
            if upload_snap is None:
                verify_snap = last_upload_snap or self.runtime.snapshot()
                result.session_url_after = self.runtime.current_url() or before
                result.add_step(
                    'send', False,
                    'ChatGPT attachment upload did not become send-ready before send',
                    url_before=before,
                    url_after=result.session_url_after,
                    attempts=attempts,
                    snapshot=verify_snap.serializable(),
                )
                return False

        for attempt in (1, 2):
            send_snap = None
            readiness_snapshot = self.runtime.wait_until(
                lambda: (
                    snap
                    if self._send_button_readiness(snap := self.runtime.snapshot())[2]['ready']
                    else None
                ),
                timeout=5.0,
                interval=0.25,
            ) or self.runtime.snapshot()
            send_key, send_button, readiness = self._send_button_readiness(readiness_snapshot)
            readiness['attempt'] = attempt
            attempts.append(readiness)
            if not readiness['ready'] or send_button is None:
                if attempt == 2:
                    break
                continue

            clicked = self._click(send_button)
            timeout = first_probe_timeout if attempt == 1 else full_timeout
            if clicked:
                send_snap = self.runtime.wait_until(
                    lambda: (
                        stop_state[1]
                        if (stop_state := self._read_stop_state(stop_keys, confirm_absence=False))[0]
                        else None
                    ),
                    timeout=timeout,
                    interval=0.6,
                ) or self.runtime.snapshot()
            else:
                send_snap = self.runtime.snapshot()
            stop_seen, stop_snap, stop_reading = self._read_stop_state(
                stop_keys,
                confirm_absence=False,
            )
            if stop_seen:
                send_snap = stop_snap
            answer_url = self._wait_for_answer_thread_url(
                timeout=30.0 if stop_seen else 5.0,
                previous_url=before,
                require_change=not bool(request.session_url),
            )
            result.session_url_after = answer_url or before
            url_changed = bool(result.session_url_after and result.session_url_after != before)
            answer_thread = bool(self._is_answer_thread_url(result.session_url_after))
            url_landed = bool(answer_url and answer_thread and (url_changed or request.session_url))
            prompt_still_staged = False
            if attempt == 1 and not stop_seen and not url_landed:
                prompt_still_staged = self.snapshot_has_any(self.runtime.snapshot(), self._send_button_keys())
            verified = bool(clicked and stop_seen and url_landed)
            attempts.append({
                'attempt': attempt,
                'phase': 'exact_send_button_click',
                'send_key': send_key,
                'send_button': self._element_evidence(send_button),
                'clicked': clicked,
                'stop_seen': stop_seen,
                'stop_reading': self._compact_stop_reading(stop_reading),
                'url_changed': url_changed,
                'answer_thread': answer_thread,
                'url_landed': url_landed,
                'prompt_still_staged': prompt_still_staged,
            })
            if verified:
                verify_snap = send_snap
                result.add_step(
                    'send', True,
                    'ChatGPT send validated by exact Send prompt click, Stop button, and answer-thread URL',
                    url_before=before,
                    url_after=result.session_url_after,
                    stop_seen=stop_seen,
                    url_changed=url_changed,
                    url_landed=url_landed,
                    attempts=attempts,
                    snapshot=verify_snap.serializable(),
                )
                return True

            # Retry only when the exact send click produced no send evidence and
            # the prompt is still staged. If Stop or a thread URL appears, do not
            # click again.
            if attempt == 1 and not stop_seen and not url_landed and prompt_still_staged:
                continue
            break

        verify_snap = send_snap or self.runtime.snapshot()
        failure_reason = self._send_failure_reason(attempts)
        result.add_step(
            'send', False,
            'ChatGPT send failed validation after exact Send prompt click',
            url_before=before,
            url_after=result.session_url_after or self.runtime.current_url() or before,
            failure_reason=failure_reason,
            attempts=attempts,
            snapshot=verify_snap.serializable(),
        )
        return False

    # ------------------------------------------------------------------
    # Generation monitoring and extraction
    # ------------------------------------------------------------------

    def monitor_generation(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        detector_mode = str(request.selection_value('mode', '') or '').strip().lower()
        detector = ChatGPTCompletionDetector(mode=detector_mode)
        detector.required_stop_cycles = max(
            detector.required_stop_cycles,
            self._minimum_stop_gone_cycles(),
        )
        stop_keys = self._stop_keys()
        completed = False
        observed_stop = False
        intermediate_failed = False
        answer_thread_lost = False
        intermediate_actions: dict[str, int] = {}
        terminal_snapshot: Snapshot | None = None
        stop_read_samples: list[dict[str, object]] = []
        last_stop_reading: dict[str, object] = {}
        completion_quiet_samples: list[dict[str, object]] = []
        completion_quiet_resets: dict[str, int] = {}
        post_complete_quiet_cycles = self._post_complete_quiet_cycles()

        def _record_stop_reading(evidence: dict[str, object]) -> None:
            nonlocal last_stop_reading
            compact = self._compact_stop_reading(evidence)
            last_stop_reading = compact
            if len(stop_read_samples) >= 10:
                return
            if (
                compact.get('present')
                or compact.get('confirmed_absent')
                or compact.get('rescan_after_absent')
                or not stop_read_samples
            ):
                stop_read_samples.append(compact)

        def _record_completion_quiet_sample(sample: dict[str, object]) -> None:
            if len(completion_quiet_samples) < 16:
                completion_quiet_samples.append(sample)

        def _record_completion_quiet_reset(reason: str) -> None:
            completion_quiet_resets[reason] = completion_quiet_resets.get(reason, 0) + 1

        def _confirm_completion_quiet_window() -> tuple[Snapshot | None, str]:
            nonlocal observed_stop, intermediate_failed
            last_snapshot: Snapshot | None = None
            for cycle in range(1, post_complete_quiet_cycles + 1):
                time.sleep(1.0)
                stop_present, snap, stop_reading = self._read_stop_state(
                    stop_keys,
                    confirm_absence=True,
                )
                _record_stop_reading(stop_reading)
                observed_stop = observed_stop or stop_present
                if stop_present:
                    detector.observe(stop_present=True)
                    _record_completion_quiet_sample({
                        'cycle': cycle,
                        'stop_present': True,
                        'reason': 'stop_reappeared',
                    })
                    return None, 'stop_reappeared'

                handled, failed = self._handle_monitor_intermediate_state(
                    snap,
                    result,
                    intermediate_actions,
                )
                if handled:
                    self._reset_detector_after_intermediate(detector)
                    intermediate_failed = failed
                    reason = 'intermediate_failed' if failed else 'intermediate_state'
                    _record_completion_quiet_sample({
                        'cycle': cycle,
                        'stop_present': False,
                        'reason': reason,
                    })
                    return None, reason

                _record_completion_quiet_sample({
                    'cycle': cycle,
                    'stop_present': False,
                    'reason': 'quiet',
                })
                last_snapshot = snap
            return last_snapshot, 'quiet'

        def _poll() -> bool:
            nonlocal completed, observed_stop, intermediate_failed, answer_thread_lost, terminal_snapshot
            _thread_ok, thread_lost = self._assert_monitor_answer_thread(
                result,
                answer_url_predicate=self._is_answer_thread_url,
            )
            if thread_lost:
                answer_thread_lost = True
                return True
            stop_present, snap, stop_reading = self._read_stop_state(
                stop_keys,
                confirm_absence=detector.ever_seen_stop or observed_stop,
            )
            _record_stop_reading(stop_reading)
            observed_stop = observed_stop or stop_present
            handled, failed = self._handle_monitor_intermediate_state(
                snap,
                result,
                intermediate_actions,
            )
            if handled:
                self._reset_detector_after_intermediate(detector)
                intermediate_failed = failed
                return bool(failed)
            verdict = detector.observe(stop_present=stop_present)
            if verdict == COMPLETE:
                quiet_snapshot, quiet_reason = _confirm_completion_quiet_window()
                if quiet_snapshot is not None:
                    completed = True
                    terminal_snapshot = quiet_snapshot
                    return True
                _record_completion_quiet_reset(quiet_reason)
                return False
            return False

        def _verified_stop_absent_snapshot() -> Snapshot | None:
            stop_present, snap, stop_reading = self._read_stop_state(
                stop_keys,
                confirm_absence=True,
            )
            _record_stop_reading(stop_reading)
            if stop_present:
                return None
            return snap

        effective_timeout = self._effective_generation_timeout(request, detector_mode)
        self.runtime.wait_until(_poll, timeout=effective_timeout, interval=1.0)
        verify_snap = terminal_snapshot or self.runtime.wait_until(
            _verified_stop_absent_snapshot,
            timeout=5.0,
            interval=0.5,
        ) or self.runtime.snapshot()
        if answer_thread_lost:
            result.add_step(
                'monitor',
                False,
                'ChatGPT answer_thread_lost: monitor left send-created answer thread',
                stop_seen=observed_stop,
                mode=detector_mode or 'default',
                stop_keys=stop_keys,
                stop_condition='answer_thread_lost',
                stop_read_samples=stop_read_samples,
                last_stop_reading=last_stop_reading,
                snapshot=verify_snap.serializable(),
            )
            return False
        if not observed_stop:
            result.add_step(
                'monitor',
                False,
                'ChatGPT monitor never observed Stop button after send',
                stop_seen=False,
                mode=detector_mode or 'default',
                stop_keys=stop_keys,
                stop_read_samples=stop_read_samples,
                last_stop_reading=last_stop_reading,
                snapshot=verify_snap.serializable(),
            )
            return False
        if intermediate_failed:
            result.add_step(
                'monitor',
                False,
                'ChatGPT monitor failed while disposing intermediate state',
                stop_seen=observed_stop,
                mode=detector_mode or 'default',
                stop_keys=stop_keys,
                intermediate_actions=intermediate_actions,
                stop_read_samples=stop_read_samples,
                last_stop_reading=last_stop_reading,
                snapshot=verify_snap.serializable(),
            )
            return False
        stop_present_final, stop_verify_snap, stop_verify_reading = self._read_stop_state(
            stop_keys,
            confirm_absence=True,
        )
        _record_stop_reading(stop_verify_reading)
        if not stop_present_final:
            verify_snap = stop_verify_snap
        stop_absent = not stop_present_final
        verified = bool(completed and stop_absent)
        stop_condition = (
            'generation_stalled'
            if (not verified and stop_present_final and is_stop_condition('generation_stalled'))
            else None
        )
        if verified:
            monitor_message = 'ChatGPT response completed'
        elif stop_condition == 'generation_stalled':
            monitor_message = (
                'ChatGPT generation_stalled: Stop still present after '
                f'{effective_timeout:.0f}s (mode={detector_mode or "default"}) -- loud bound, not completion'
            )
        else:
            monitor_message = 'ChatGPT response did not reach Stop-gone completion'
        result.add_step(
            'monitor',
            verified,
            monitor_message,
            stop_seen=observed_stop,
            mode=detector_mode or 'default',
            stop_keys=stop_keys,
            completion_gate='stop_gone_only',
            positive_marker_gate=False,
            intermediate_actions=intermediate_actions,
            stop_gone_cycles=detector.stop_cycles,
            required_stop_gone_cycles=detector.required_stop_cycles,
            post_complete_quiet_cycles=post_complete_quiet_cycles,
            completion_quiet_resets=completion_quiet_resets,
            completion_quiet_samples=completion_quiet_samples,
            stop_read_samples=stop_read_samples,
            last_stop_reading=last_stop_reading,
            generation_timeout=effective_timeout,
            stop_condition=stop_condition,
            snapshot=verify_snap.serializable(),
        )
        if verified:
            self.checkpoint_run_state(
                request, self.RUN_STATE_COMPLETION_OBSERVED,
                result=result,
                url=result.session_url_after or self.runtime.current_url() or '',
            )
        return verified

    def _is_answer_thread_url(self, url: str | None) -> bool:
        return '/c/' in (url or '')

    def is_resumable_session_url(self, url: str | None) -> bool:
        return self._is_answer_thread_url(url)

    def _wait_for_answer_thread_url(
        self,
        *,
        timeout: float = 12.0,
        previous_url: str | None = None,
        require_change: bool = False,
    ) -> str | None:
        last_canonical_url = ''
        stable_samples = 0

        def _current_answer_url() -> str | None:
            nonlocal last_canonical_url, stable_samples
            current = (self.runtime.current_url() or '').strip()
            canonical = bool(
                self._is_answer_thread_url(current)
                and '/c/WEB:' not in current
                and not (
                    require_change
                    and self._urls_equivalent(current, previous_url)
                )
            )
            if not canonical:
                last_canonical_url = ''
                stable_samples = 0
                return None
            if self._urls_equivalent(current, last_canonical_url):
                stable_samples += 1
            else:
                last_canonical_url = current
                stable_samples = 1
            return current if stable_samples >= 2 else None

        return self.runtime.wait_until(_current_answer_url, timeout=timeout, interval=0.5)

    @staticmethod
    def _screen_rect(obj):
        if obj is None:
            return None
        try:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi as _Atspi

            comp = obj.get_component_iface()
            rect = comp.get_extents(_Atspi.CoordType.SCREEN) if comp is not None else None
            if rect and rect.width > 0 and rect.height > 0 and rect.x >= 0 and rect.y >= 0:
                return {
                    'x': int(rect.x),
                    'y': int(rect.y),
                    'width': int(rect.width),
                    'height': int(rect.height),
                }
        except Exception:
            return None
        return None

    def _chatgpt_document(self):
        from consultation_v2.platforms import routing as platform_routing

        firefox = platform_routing.find_firefox_for_platform(self.platform)
        return platform_routing.get_platform_document(firefox, self.platform) if firefox else None

    def _scroll_chatgpt_thread_to_bottom(self) -> dict:
        from consultation_v2 import input as _inp

        evidence = {
            'ok': False,
            'source': 'document_extents',
        }
        for _ in range(8):
            doc = self._chatgpt_document()
            rect = self._screen_rect(doc)
            if rect:
                x = int(rect['x'] + rect['width'] // 2)
                y_offset = min(max(120, rect['height'] // 2), max(0, rect['height'] - 180))
                y = int(rect['y'] + y_offset)
                clicked = bool(_inp.click_at(x, y))
                time.sleep(0.2)
                end_presses = 0
                for _press in range(12):
                    if _inp.press_key('End'):
                        end_presses += 1
                    time.sleep(0.08)
                wheel_ok = bool(_inp.scroll_wheel('down', clicks=12, hover_point=(x, y)))
                evidence.update({
                    'ok': bool(clicked and end_presses >= 10 and wheel_ok),
                    'x': x,
                    'y': y,
                    'clicked': clicked,
                    'end_presses': end_presses,
                    'wheel_ok': wheel_ok,
                    'document_rect': rect,
                })
                return evidence
            time.sleep(0.25)
        return evidence

    def _chatgpt_latest_turn_copy_candidates(
        self,
        elements: list[dict],
        copy_buttons: list[dict],
        request: ConsultationRequest,
    ) -> tuple[list[dict], dict[str, object]]:
        prompt_norm = self._normalized_text(request.message).lower()
        element_map = self.cfg.get('tree', {}).get('element_map', {}) or {}
        user_panel_spec = element_map.get('user_message_actions_panel', {}) or {}
        response_panel_spec = element_map.get('response_actions_panel', {}) or {}
        prompt_matches: list[dict[str, object]] = []
        user_action_panels: list[dict[str, object]] = []
        response_action_panels: list[dict[str, object]] = []

        for element in elements:
            y = element.get('y')
            if y is None:
                continue
            name = str(element.get('name') or '').strip()
            role = str(element.get('role') or '').strip()
            text = str(element.get('text') or '').strip()
            element_norm = self._normalized_text(' '.join(part for part in (name, text) if part)).lower()
            if matches_spec(element, user_panel_spec):
                user_action_panels.append({'y': int(y), 'name': name, 'role': role})
            if matches_spec(element, response_panel_spec):
                response_action_panels.append({'y': int(y), 'name': name, 'role': role})
            if not (prompt_norm and element_norm):
                continue
            prompt_seen = (
                element_norm == prompt_norm
                or (len(prompt_norm) >= 24 and prompt_norm in element_norm)
                or (len(element_norm) >= 80 and element_norm in prompt_norm)
            )
            if prompt_seen:
                prompt_matches.append({
                    'y': int(y),
                    'name': name[:120],
                    'role': role,
                })

        anchor_source = ''
        anchor_y: int | None = None
        if prompt_matches:
            anchor_source = 'prompt_text'
            anchor_y = max(int(item['y']) for item in prompt_matches)
        elif user_action_panels:
            anchor_source = 'user_message_actions_panel'
            anchor_y = max(int(item['y']) for item in user_action_panels)

        if anchor_y is None:
            assistant_candidates, assistant_anchor = self._chatgpt_latest_assistant_turn_copy_candidates(
                copy_buttons,
                response_action_panels,
            )
            assistant_anchor.update({
                'prompt_text_matches': len(prompt_matches),
                'user_message_action_panels': len(user_action_panels),
                'response_action_panels': len(response_action_panels),
            })
            return assistant_candidates, assistant_anchor

        correlated = [
            button for button in copy_buttons
            if button.get('y') is not None and int(button.get('y') or 0) > anchor_y
        ]
        return correlated, {
            'ok': bool(correlated),
            'anchor_source': anchor_source,
            'anchor_y': anchor_y,
            'prompt_text_matches': len(prompt_matches),
            'user_message_action_panels': len(user_action_panels),
            'response_action_panels': len(response_action_panels),
            'copy_buttons_after_anchor': len(correlated),
        }

    def _chatgpt_latest_assistant_turn_copy_candidates(
        self,
        copy_buttons: list[dict],
        response_action_panels: list[dict[str, object]],
    ) -> tuple[list[dict], dict[str, object]]:
        copy_buttons_with_y = [
            button for button in copy_buttons
            if self._chatgpt_int(button.get('y')) is not None
        ]
        if not copy_buttons_with_y:
            return [], {
                'ok': False,
                'reason': 'assistant_turn_copy_button_not_found',
            }

        sorted_buttons = sorted(
            copy_buttons_with_y,
            key=lambda button: self._chatgpt_int(button.get('y')) or 0,
        )
        button_ys = [self._chatgpt_int(button.get('y')) or 0 for button in sorted_buttons]
        latest_copy_y = button_ys[-1]
        previous_copy_ys = [y for y in button_ys[:-1] if y < latest_copy_y]
        assistant_floor_y = max(previous_copy_ys) if previous_copy_ys else None

        panel_ys = [
            self._chatgpt_int(panel.get('y'))
            for panel in response_action_panels
            if self._chatgpt_int(panel.get('y')) is not None
        ]
        latest_panel_y = max(panel_ys) if panel_ys else None
        if latest_panel_y is not None:
            panel_buttons = [
                button for button in sorted_buttons
                if abs((self._chatgpt_int(button.get('y')) or 0) - latest_panel_y) <= 160
            ]
            if panel_buttons:
                return panel_buttons, {
                    'ok': True,
                    'anchor_source': 'latest_response_actions_panel',
                    'anchor_y': assistant_floor_y,
                    'response_actions_y': latest_panel_y,
                    'copy_buttons_near_response_actions': len(panel_buttons),
                    'copy_buttons_total': len(sorted_buttons),
                }

        latest_buttons = [
            button for button in sorted_buttons
            if (self._chatgpt_int(button.get('y')) or 0) >= latest_copy_y - 40
        ]
        return latest_buttons, {
            'ok': True,
            'anchor_source': 'latest_assistant_copy_button',
            'anchor_y': assistant_floor_y,
            'copy_button_y': latest_copy_y,
            'copy_buttons_in_latest_band': len(latest_buttons),
            'copy_buttons_total': len(sorted_buttons),
        }

    def _chatgpt_extract_quality_failure(
        self,
        content: str,
        request: ConsultationRequest,
    ) -> dict[str, object] | None:
        normalized = self._normalized_text(content)
        lowered = normalized.lower()
        markers = [
            marker for marker in self._EXTRACT_CHROME_POLLUTION_MARKERS
            if marker.lower() in lowered
        ]
        if markers:
            return {
                'reason': 'browser_chrome_or_sidebar_pollution',
                'markers': markers,
            }

        prompt = self._normalized_text(request.message)
        word_count = len(normalized.split())
        prompt_chars = len(prompt)
        substantial_prompt = prompt_chars >= 1500 and any(
            term in prompt.lower()
            for term in ('audit', 'review', 'root cause', 'rca', 'verdict', 'validate')
        )
        if substantial_prompt and word_count < 35:
            return {
                'reason': 'short_fragment_for_substantial_prompt',
                'word_count': word_count,
                'prompt_chars': prompt_chars,
            }
        return None

    @staticmethod
    def _chatgpt_int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _chatgpt_action_specs(self) -> tuple[dict, dict, dict]:
        element_map = self.cfg.get('tree', {}).get('element_map', {}) or {}
        return (
            element_map.get('user_message_actions_panel', {}) or {},
            element_map.get('response_actions_panel', {}) or {},
            element_map.get('copy_button', {}) or {},
        )

    def _chatgpt_is_response_action_element(self, element: dict) -> bool:
        name = str(element.get('name') or '').strip()
        role = str(element.get('role') or '').strip().lower()
        if name in self._RESPONSE_TEXT_IGNORED_NAMES:
            return True
        user_actions_spec, response_actions_spec, copy_spec = self._chatgpt_action_specs()
        return (
            matches_spec(element, user_actions_spec)
            or matches_spec(element, response_actions_spec)
            or matches_spec(element, copy_spec)
            or role in self._RESPONSE_TEXT_CONTROL_ROLES
        )

    def _chatgpt_node_text(self, obj) -> str:
        text = ''
        try:
            text_iface = obj.get_text_iface()
        except Exception:
            text_iface = None
        if text_iface is not None:
            try:
                count = text_iface.get_character_count()
            except Exception:
                count = -1
            try:
                text = text_iface.get_text(0, count if count and count > 0 else -1) or ''
            except Exception:
                text = ''
        if not text:
            try:
                text = obj.get_name() or ''
            except Exception:
                text = ''
        return self._normalized_text(text)

    @staticmethod
    def _chatgpt_compact_node_evidence(obj) -> dict[str, object]:
        try:
            name = obj.get_name() or ''
        except Exception:
            name = ''
        try:
            role = obj.get_role_name() or ''
        except Exception:
            role = ''
        return {'name': name[:120], 'role': role}

    def _chatgpt_append_text_chunk(
        self,
        chunks: list[str],
        seen: list[str],
        text: str,
        *,
        max_chars: int,
    ) -> None:
        normalized = self._normalized_text(text)
        if not normalized or normalized in self._RESPONSE_TEXT_IGNORED_NAMES:
            return
        for previous in seen:
            if normalized == previous:
                return
            if len(normalized) >= 80 and normalized in previous:
                return
            if len(previous) >= 80 and previous in normalized:
                seen.remove(previous)
                chunks[:] = [chunk for chunk in chunks if chunk != previous]
                break
        remaining = max_chars - sum(len(chunk) + 1 for chunk in chunks)
        if remaining <= 0:
            return
        if len(normalized) > remaining:
            normalized = normalized[:remaining].rstrip()
        seen.append(normalized)
        chunks.append(normalized)

    def _chatgpt_collect_response_subtree_text(
        self,
        root,
        *,
        anchor_y: int | None,
        action_y: int | None,
        max_nodes: int = 900,
        max_chars: int = 120000,
    ) -> tuple[str, dict[str, object]]:
        chunks: list[str] = []
        seen: list[str] = []
        visited: set[int] = set()
        evidence: dict[str, object] = {
            'nodes_seen': 0,
            'chunks': 0,
            'bounded_by_anchor_y': anchor_y,
            'bounded_by_action_y': action_y,
        }

        user_actions_spec, response_actions_spec, copy_spec = self._chatgpt_action_specs()

        def _traverse(obj, depth: int = 0) -> None:
            if len(visited) >= max_nodes or sum(len(chunk) + 1 for chunk in chunks) >= max_chars:
                return
            identity = id(obj)
            if identity in visited:
                return
            visited.add(identity)
            try:
                name = obj.get_name() or ''
            except Exception:
                name = ''
            try:
                role = obj.get_role_name() or ''
            except Exception:
                role = ''
            role_lower = role.strip().lower()
            element = {'name': name, 'role': role, 'atspi_obj': obj}
            evidence['nodes_seen'] = int(evidence['nodes_seen']) + 1

            rect = None if depth == 0 else self._screen_rect(obj)
            if rect:
                center_y = int(rect['y'] + rect['height'] // 2)
                if anchor_y is not None and center_y <= anchor_y:
                    return
                if action_y is not None and center_y >= action_y + 80:
                    return

            if (
                matches_spec(element, user_actions_spec)
                or matches_spec(element, response_actions_spec)
                or matches_spec(element, copy_spec)
            ):
                return

            if name in self._RESPONSE_TEXT_IGNORED_NAMES:
                return

            if role_lower not in self._RESPONSE_TEXT_CONTROL_ROLES:
                self._chatgpt_append_text_chunk(
                    chunks,
                    seen,
                    self._chatgpt_node_text(obj),
                    max_chars=max_chars,
                )

            try:
                child_count = min(obj.get_child_count(), 220)
            except Exception:
                child_count = 0
            for index in range(child_count):
                try:
                    child = obj.get_child_at_index(index)
                except Exception:
                    child = None
                if child is not None:
                    _traverse(child, depth + 1)

        _traverse(root)
        content = '\n'.join(chunks).strip()
        evidence.update({
            'chunks': len(chunks),
            'characters': len(content),
        })
        return content, evidence

    def _chatgpt_collect_response_band_text(
        self,
        elements: list[dict],
        *,
        anchor_y: int | None,
        action_y: int | None,
        max_chars: int = 120000,
    ) -> tuple[str, dict[str, object]]:
        chunks: list[str] = []
        seen: list[str] = []
        rows: list[tuple[int, int, str]] = []
        for element in elements:
            y = self._chatgpt_int(element.get('y'))
            if y is None:
                continue
            if anchor_y is not None and y <= anchor_y:
                continue
            if action_y is not None and y >= action_y:
                continue
            if self._chatgpt_is_response_action_element(element):
                continue
            name = str(element.get('name') or '').strip()
            text = str(element.get('text') or '').strip()
            content = self._normalized_text(' '.join(part for part in (name, text) if part))
            if not content:
                continue
            rows.append((y, self._chatgpt_int(element.get('x')) or 0, content))

        for _y, _x, content in sorted(rows):
            self._chatgpt_append_text_chunk(chunks, seen, content, max_chars=max_chars)
        result = '\n'.join(chunks).strip()
        return result, {
            'source': 'document_element_band',
            'rows': len(rows),
            'chunks': len(chunks),
            'characters': len(result),
            'bounded_by_anchor_y': anchor_y,
            'bounded_by_action_y': action_y,
        }

    def _chatgpt_fallback_prompt_contamination(
        self,
        content: str,
        request: ConsultationRequest,
    ) -> dict[str, object] | None:
        content_norm = self._normalized_text(content)
        prompt_norm = self._normalized_text(request.message)
        if not content_norm or len(prompt_norm) < 120:
            return None
        if prompt_norm in content_norm:
            return {'reason': 'full_prompt_present_in_fallback_text'}
        prompt_prefix = prompt_norm[: min(500, len(prompt_norm))]
        if len(prompt_prefix) >= 120 and prompt_prefix in content_norm[: max(2000, len(prompt_prefix) * 2)]:
            return {'reason': 'prompt_prefix_present_in_fallback_text'}
        return None

    def _chatgpt_response_text_candidate_failure(
        self,
        content: str,
        request: ConsultationRequest,
    ) -> dict[str, object] | None:
        prompt_contamination = self._chatgpt_fallback_prompt_contamination(content, request)
        if prompt_contamination:
            return prompt_contamination
        echo = self._prompt_echo_evidence(content, request)
        if echo.get('is_echo'):
            return {'reason': 'prompt_echo', 'echo_guard': echo}
        quality_failure = self._chatgpt_extract_quality_failure(content, request)
        if quality_failure:
            return quality_failure
        return None

    def _chatgpt_bounded_response_text_fallback(
        self,
        elements: list[dict],
        target: dict[str, object] | None,
        request: ConsultationRequest,
        turn_correlation: dict[str, object] | None,
    ) -> tuple[str, dict[str, object]]:
        anchor_y = self._chatgpt_int((turn_correlation or {}).get('anchor_y'))
        action_y = self._chatgpt_int((target or {}).get('y'))
        evidence: dict[str, object] = {
            'ok': False,
            'source': 'chatgpt_bounded_response_text',
            'anchor_y': anchor_y,
            'action_y': action_y,
            'copy_button': {
                key: (target or {}).get(key)
                for key in ('name', 'role', 'x', 'y')
            } if target else None,
            'candidates': [],
        }
        if not target or target.get('atspi_obj') is None:
            evidence['reason'] = 'copy_button_atspi_object_missing'
            return '', evidence

        for depth, ancestor in enumerate(self._atspi_path_to_root(target.get('atspi_obj'))[1:], start=1):
            if self._is_broad_scope_root(ancestor):
                evidence['stopped_at_broad_root'] = self._chatgpt_compact_node_evidence(ancestor)
                break
            content, collect_evidence = self._chatgpt_collect_response_subtree_text(
                ancestor,
                anchor_y=anchor_y,
                action_y=action_y,
            )
            failure = (
                self._chatgpt_response_text_candidate_failure(content, request)
                if content
                else {'reason': 'empty_candidate'}
            )
            candidate = {
                'source': 'copy_button_ancestor',
                'depth': depth,
                'node': self._chatgpt_compact_node_evidence(ancestor),
                **collect_evidence,
                'failure': failure,
            }
            if len(evidence['candidates']) < 8:
                evidence['candidates'].append(candidate)
            if content and not failure:
                evidence.update({
                    'ok': True,
                    'reason': 'copy_button_ancestor_text',
                    'selected': candidate,
                })
                return content, evidence

        band_content, band_evidence = self._chatgpt_collect_response_band_text(
            elements,
            anchor_y=anchor_y,
            action_y=action_y,
        )
        band_failure = (
            self._chatgpt_response_text_candidate_failure(band_content, request)
            if band_content
            else {'reason': 'empty_candidate'}
        )
        band_candidate = {**band_evidence, 'failure': band_failure}
        if len(evidence['candidates']) < 8:
            evidence['candidates'].append(band_candidate)
        if band_content and not band_failure:
            evidence.update({
                'ok': True,
                'reason': 'document_element_band_text',
                'selected': band_candidate,
            })
            return band_content, evidence

        evidence['reason'] = 'no_bounded_response_text_candidate'
        return '', evidence

    def extract_primary(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        from consultation_v2 import clipboard
        from consultation_v2.platforms import routing as platform_routing
        from consultation_v2.interact import atspi_click
        from consultation_v2.tree import find_elements as raw_find_elements

        if not self.reassert_captured_session_url(
            result,
            answer_url_predicate=self._is_answer_thread_url,
        ):
            return False

        copy_spec = self.cfg.get('tree', {}).get('element_map', {}).get('copy_button', {})
        last_snapshot = self.runtime.snapshot()
        last_scroll: dict[str, object] = {}
        last_copy_buttons: list[dict[str, object]] = []
        last_document_elements: list[dict] = []
        last_correlated_copy_button: dict[str, object] | None = None
        last_turn_correlation: dict[str, object] | None = None
        saw_empty_clipboard_from_copy_button = False
        attempts: list[dict[str, object]] = []
        for attempt in range(5):
            time.sleep(1.0)
            last_scroll = self._scroll_chatgpt_thread_to_bottom()
            if not last_scroll.get('ok'):
                result.add_step(
                    'extract_primary',
                    False,
                    'ChatGPT thread scroll-to-bottom failed; refusing to copy a possibly stale visible response',
                    attempt=attempt + 1,
                    scroll=last_scroll,
                    snapshot=last_snapshot.serializable() if last_snapshot else {},
                )
                return False
            firefox = platform_routing.find_firefox_for_platform(self.platform)
            if not firefox:
                attempts.append({
                    'attempt': attempt + 1,
                    'scroll': last_scroll,
                    'reason': 'firefox_not_found',
                })
                continue
            try:
                firefox.clear_cache_single()
            except Exception:
                pass
            document = platform_routing.get_platform_document(firefox, self.platform)
            if not document:
                attempts.append({
                    'attempt': attempt + 1,
                    'scroll': last_scroll,
                    'reason': 'chatgpt_document_not_found',
                })
                continue
            try:
                document.clear_cache_single()
            except Exception:
                pass
            last_snapshot = self.runtime.snapshot()
            all_elements = raw_find_elements(document, fence_after=[])
            last_document_elements = all_elements
            copy_buttons = [
                element for element in all_elements
                if matches_spec(element, copy_spec)
                and element.get('y') is not None
            ]
            copy_buttons = sorted(copy_buttons, key=lambda element: int(element.get('y') or 0))
            last_copy_buttons = [
                {key: button.get(key) for key in ('name', 'role', 'x', 'y')}
                for button in copy_buttons
            ]
            if not copy_buttons:
                attempts.append({
                    'attempt': attempt + 1,
                    'scroll': last_scroll,
                    'copy_buttons_found': 0,
                    'reason': 'copy_button_not_found',
                })
                continue

            correlated_copy_buttons, turn_correlation = self._chatgpt_latest_turn_copy_candidates(
                all_elements,
                copy_buttons,
                request,
            )
            if not correlated_copy_buttons:
                attempts.append({
                    'attempt': attempt + 1,
                    'scroll': last_scroll,
                    'copy_buttons_found': len(copy_buttons),
                    'turn_correlation': turn_correlation,
                    'reason': 'copy_button_not_correlated_to_latest_user_turn',
                })
                continue

            target = correlated_copy_buttons[-1]
            last_correlated_copy_button = target
            last_turn_correlation = turn_correlation
            copy_button = {key: target.get(key) for key in ('name', 'role', 'x', 'y')}
            scrolled_button = self.runtime.scroll_element_into_view(ElementRef(
                key='copy_button',
                name=str(target.get('name') or ''),
                role=str(target.get('role') or ''),
                x=target.get('x'),
                y=target.get('y'),
                states=list(target.get('states') or []),
                atspi_obj=target.get('atspi_obj'),
            ))
            clipboard.write('')
            time.sleep(0.2)
            clicked = atspi_click(target)
            time.sleep(1.0)
            content = (clipboard.read() or '').strip()
            exact_prompt_echo = (
                bool(content)
                and self._normalized_text(content) == self._normalized_text(request.message)
            )
            quality_failure = (
                self._chatgpt_extract_quality_failure(content, request)
                if content and not exact_prompt_echo
                else None
            )
            attempt_evidence = {
                'attempt': attempt + 1,
                'scroll': last_scroll,
                'copy_buttons_found': len(copy_buttons),
                'turn_correlation': turn_correlation,
                'copy_button': copy_button,
                'button_scrolled_to_anywhere': bool(scrolled_button),
                'clicked': bool(clicked),
                'characters': len(content),
                'preview': content[:200],
                'exact_prompt_echo': exact_prompt_echo,
                'quality_failure': quality_failure,
            }
            attempts.append(attempt_evidence)
            if clicked and not content:
                saw_empty_clipboard_from_copy_button = True
            if not clicked or not content or exact_prompt_echo:
                continue
            if quality_failure:
                result.response_text = ''
                result.add_step(
                    'extract_primary',
                    False,
                    'ChatGPT copied response rejected by extract quality gate',
                    source='chatgpt_copy_response_quality_gate',
                    attempts=attempts,
                    **quality_failure,
                )
                return False
            if not self.set_response_text_if_not_prompt_echo(
                request,
                result,
                content,
                step='extract_primary',
                source='chatgpt_copy_response',
                **attempt_evidence,
            ):
                return False
            result.add_step(
                'extract_primary',
                True,
                f'ChatGPT response copied from Copy response button ({len(content)} chars, attempt {attempt + 1})',
                source='chatgpt_copy_response',
                **attempt_evidence,
            )
            return True

        if saw_empty_clipboard_from_copy_button:
            fallback_content, fallback_evidence = self._chatgpt_bounded_response_text_fallback(
                last_document_elements,
                last_correlated_copy_button,
                request,
                last_turn_correlation,
            )
            if fallback_content and fallback_evidence.get('ok'):
                if not self.set_response_text_if_not_prompt_echo(
                    request,
                    result,
                    fallback_content,
                    step='extract_primary',
                    source='chatgpt_bounded_response_text',
                    fallback=fallback_evidence,
                    attempts=attempts,
                ):
                    return False
                result.add_step(
                    'extract_primary',
                    True,
                    f'ChatGPT response extracted from bounded response turn ({len(fallback_content)} chars)',
                    source='chatgpt_bounded_response_text',
                    fallback=fallback_evidence,
                    attempts=attempts,
                )
                return True
            attempts.append({
                'attempt': 'bounded_response_text_fallback',
                'reason': 'empty_copy_clipboard_fallback_failed',
                'fallback': fallback_evidence,
            })

        result.add_step(
            'extract_primary', False,
            'ChatGPT Copy response button did not yield non-empty response text',
            attempts=attempts,
            last_scroll=last_scroll,
            copy_buttons=last_copy_buttons,
            snapshot=last_snapshot.serializable() if last_snapshot else {},
        )
        return False

    def extract_additional(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        result.add_step('extract_additional', True, 'ChatGPT additional attachment extraction not configured in YAML yet', artifacts=[])
        return True

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def store_in_neo4j(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        session_url = (
            result.session_url_after
            or result.session_url_before
            or self.runtime.current_url()
            or ''
        )
        return self.store_response_for_delivery(
            request,
            result,
            session_url,
            label='ChatGPT',
        )
