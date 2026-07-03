from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, List, Optional, Tuple

from consultation_v2.completion import (
    COMPLETE,
    CompletionDetector,
    DEEP_MODES,
)
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


# Deep/research generations legitimately run for many minutes. A caller that
# under-sets --timeout (e.g. a quick-chat default) must not be able to bound a
# deep generation below this floor — the monitor floors the effective wait for
# deep modes so a long-but-healthy run completes instead of false-failing.
# (FLOW Monitor Contract: stop-present = generating; the timeout is the LOUD
# bound for a genuinely-stuck run, never a content/elapsed completion heuristic.)
DEEP_GENERATION_FLOOR_SECONDS = 1800.0
# Minimum raw AT-SPI node count for a document snapshot to be a FAITHFUL read of
# the page (and therefore for a stop-ABSENT observation drawn from it to be
# trustworthy). A loaded consultation page — nav, sidebar history, composer,
# toolbar, rendered response — always scans into the hundreds of raw nodes; a
# starved/degraded read under concurrent AT-SPI bus contention returns a
# near-empty tree (zero / single-digit nodes). This floor sits in the wide empty
# gap between the two, so it never clips a real generating-or-complete page while
# always catching a degenerate read. It bounds only the absence interpretation:
# a degraded tick is treated as 'unknown' (skipped, debounce not advanced), never
# as stop-gone. Because the monitor's wall-clock effective_timeout still bounds
# the loop, an over-conservative misfire can only degrade to a LOUD timeout —
# never a silent false-complete and never an infinite wait.
MONITOR_MIN_HEALTHY_RAW_COUNT = 25
PROMPT_ECHO_FAILURE_MESSAGE = 'extracted text matches prompt — echo, not a response'


class BaseConsultationDriver(ABC):
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
        timeout = max(float(timeout), 15.0)
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
        if normalized == 'document':
            return self.runtime.snapshot()
        if normalized == 'menu':
            return self.runtime.menu_snapshot()
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
        deadline = time.time() + timeout
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=2,
                timeout=min(remaining, 0.8),
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
            if self._selection_base_snapshot_clean(last_snapshot, anchor_key):
                return last_snapshot
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
    def _reset_detector_after_intermediate(detector: CompletionDetector) -> None:
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
        detector (consultation_v2.completion.CompletionDetector) — the single
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
        detector = CompletionDetector(mode=detector_mode)
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
            return result

    @abstractmethod
    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): switch/navigate/select/attach/prompt then the
        guarded send + monitor registration. Return True iff the send is proven
        and the monitor session is registered (the handoff point); False on any
        setup/send failure (the step audit records why). Runs while THIS driver
        holds the DISPLAY-scoped dispatch lock — must not block on monitoring."""
        raise NotImplementedError

    @abstractmethod
    def monitor_and_extract(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> None:
        """UNLOCKED phase (FLOW §10): poll for completion, extract, store, set
        result.ok. Runs AFTER the display lock is released so other consultations
        can set up/send on this display concurrently. Sets result.ok on success;
        leaves it False (with a recorded step) on any monitor/extract failure."""
        raise NotImplementedError
