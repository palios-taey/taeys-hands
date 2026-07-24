"""Perplexity platform package driver.

This file inlines Perplexity's current effective driver behavior plus the
lifecycle methods it reaches, so Perplexity owns its driver and monitor code
in this package.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional, Tuple

from consultation_v2.platforms.perplexity.monitor import COMPLETE, DEEP_MODES, PerplexityCompletionDetector
from consultation_v2.stop_conditions import is_stop_condition
from consultation_v2 import primitives
from consultation_v2 import storage_policy
from consultation_v2.display_readiness import _viewable_windows, display_for_platform
from consultation_v2.display_watchdog import pause_display_watchdog
from consultation_v2.planner import SelectionPlanError, build_selection_plan, has_selection_menus
from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, ExtractedArtifact, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


# Deep/research generations legitimately run for many minutes. A caller that
# under-sets --timeout (e.g. a quick-chat default) must not be able to bound a
# deep generation below this floor - the monitor floors the effective wait for
# deep modes so a long-but-healthy run completes instead of false-failing.
# (FLOW Monitor Contract: stop-present = generating; the timeout is the LOUD
# bound for a genuinely-stuck run, never a content/elapsed completion heuristic.)
DEEP_GENERATION_FLOOR_SECONDS = 1800.0
# Minimum raw AT-SPI node count for a document snapshot to be a FAITHFUL read of
# the page (and therefore for a stop-ABSENT observation drawn from it to be
# trustworthy). A loaded consultation page - nav, sidebar history, composer,
# toolbar, rendered response - always scans into the hundreds of raw nodes; a
# starved/degraded read under concurrent AT-SPI bus contention returns a
# near-empty tree (zero / single-digit nodes). This floor sits in the wide empty
# gap between the two, so it never clips a real generating-or-complete page while
# always catching a degenerate read. It bounds only the absence interpretation:
# a degraded tick is treated as 'unknown' (skipped, debounce not advanced), never
# as stop-gone. Because the monitor's wall-clock effective_timeout still bounds
# the loop, an over-conservative misfire can only degrade to a LOUD timeout -
# never a silent false-complete and never an infinite wait.
MONITOR_MIN_HEALTHY_RAW_COUNT = 25
DEEP_RESEARCH_REPORT_CARD_READINESS_SECONDS = 90.0
DEEP_RESEARCH_REPORT_CARD_READINESS_INTERVAL_SECONDS = 1.0
PROMPT_ECHO_FAILURE_MESSAGE = 'extracted text matches prompt - echo, not a response'
SETUP_RENDER_WAIT_FLOOR_SECONDS = 45.0
SETUP_RENDER_WAIT_MULTIPLIER = 6.0
SETUP_RENDER_WAIT_CEILING_SECONDS = 90.0
PERPLEXITY_FILE_DIALOG_TITLE_PATTERNS = (
    'File Upload - Perplexity',
    'File Upload',
    'Open File',
    'Open',
)


class _PerplexityInlineBase:
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
        # A mode-menu trigger button's accessible NAME is the CURRENTLY-selected
        # mode (e.g. "Search" vs "Deep research"), so the trigger key only matches
        # in the default state. When a mode is already selected, the button shows
        # that option's active_element instead. Page-ready must accept EITHER, so
        # each trigger group includes its options' active_elements as alternatives.
        selection = (self.cfg.get('workflow') or {}).get('selection') or {}
        menus = selection.get('menus') if isinstance(selection, dict) else None
        trigger_alternatives: dict[str, tuple[str, ...]] = {}
        if isinstance(menus, dict):
            for menu_cfg in menus.values():
                if not isinstance(menu_cfg, dict):
                    continue
                operate = menu_cfg.get('operate') or {}
                trig = operate.get('trigger') if isinstance(operate, dict) else None
                if not isinstance(trig, str):
                    continue
                alts: list[str] = [trig]
                options = menu_cfg.get('options') or {}
                if isinstance(options, dict):
                    for opt in options.values():
                        active = opt.get('active_element') if isinstance(opt, dict) else None
                        if isinstance(active, str) and active.strip():
                            alts.append(active.strip())
                trigger_alternatives.setdefault(trig, tuple(alts))
        for key in self._selection_trigger_keys():
            add_group(trigger_alternatives.get(key, (key,)))

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
        timeout = self._selection_render_wait_timeout_seconds()
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
        timeout = self._selection_render_wait_timeout_seconds()
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

    def _selection_render_wait_timeout_seconds(self) -> float:
        return min(
            max(
                self._selection_settle_seconds() * SETUP_RENDER_WAIT_MULTIPLIER,
                SETUP_RENDER_WAIT_FLOOR_SECONDS,
            ),
            SETUP_RENDER_WAIT_CEILING_SECONDS,
        )

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
    # Shared state primitives (FLOW Section 7) - locks / run-state / monitor
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
    # Per-display setup/send SERIALIZATION (FLOW Section 10 concurrency model)
    # ------------------------------------------------------------------
    #
    # FLOW Section 10 splits the lifecycle into a SEQUENTIAL region and a CONCURRENT
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
    # (primitives.acquire/release_display_lock, key taey:plan_active:{DISPLAY} -
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
        ``with`` block (the setup+send+register region, FLOW Section 10).

        Yields ``True`` if the lock was acquired (this dispatch owns the display
        and may drive the browser), ``False`` if another consultation already
        holds it (the caller must NOT proceed - a busy display is a loud failure,
        not a silent shared-browser race).

        RELEASE-SAFE: the release runs in a ``finally`` so a failed/halted/raising
        setup or send still frees the display - no deadlock can leave a DISPLAY
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
    # Run-state idempotency (FLOW Section 8, CONSULTATION_CONTRACT Section 10)
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
        this consultation (FLOW Section 8). ``status`` is the milestone reached;
        ``fields`` are the milestone-specific values (e.g. ``url=...``,
        ``monitor_id=...``) that are PERSISTED into the run-state record.

        ``result`` is an OUT-OF-BAND handle used only to record a failed-step
        audit entry if the checkpoint cannot be written - it is a named
        parameter, NOT part of ``fields``, so it is never serialized into the
        record. (Root cause: previously the result was smuggled through
        ``fields['_result']`` and then spread via ``**fields`` into the
        json.dumps'd state, which raised "Object of type ConsultationResult is
        not JSON serializable" on EVERY checkpoint - silently defeating the
        duplicate-send guard because no ``submitted`` record ever persisted.)

        Run-state is a durable idempotency CONVENIENCE, not the system of record
        (that is the Neo4j plan/message rows on success). If Redis is
        unreachable the checkpoint write raises out of the primitive; we do NOT
        let that abort a consultation whose irreversible work may already be in
        flight - we surface it loudly via the step audit and continue. This is
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
        """Idempotent send seam (FLOW Section 8). Replaces a driver's direct
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
        returns False) is NOT checkpointed as submitted and NOT registered - per
        FLOW Section 8 an unproven send must not be treated as monitored."""
        # READ prior run-state FIRST - before writing any checkpoint - so a
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

        # No proven prior send -> perform the real irreversible send.
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
        # send - it produces no new irreversible turn.
        navigated = self.runtime.navigate(captured_url) if captured_url else False
        result.session_url_after = captured_url
        self._register_monitor(request, result, monitor_id, captured_url)
        result.add_step(
            'send', True,
            f'{self.platform} send RESUMED from durable run-state - prior send '
            f'already landed at {captured_url!r}; NOT re-sending (duplicate-send '
            f'guard, FLOW Section 8 / CONTRACT Section 10)',
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
        consultation. Registration failure is a loud step (FLOW Section 8: a dispatch
        that cannot be registered must not be silently treated as monitored),
        but it does not undo a landed send - the run continues so the response
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
    def _reset_detector_after_intermediate(detector: PerplexityCompletionDetector) -> None:
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
        detector (consultation_v2.platforms.perplexity.monitor.PerplexityCompletionDetector) - the single
        source of truth that mirrors monitor/central.py::_detect_completion.

        Completion = the stop button was SEEN and is now GONE for the required
        number of cycles (2 for deep modes, 1 otherwise). No content-guess
        fallback (100_TIMES Section 1); the stop button is the only completion oracle.

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
        detector = PerplexityCompletionDetector(mode=detector_mode)
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
            # is unaffected - a visible stop means generating regardless of tree
            # size - and the wall-clock effective_timeout still bounds a
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
        # run bounded by the (now floored) timeout - a LOUD, mapped
        # generation_stalled failure (FLOW Section 9 / stop_conditions.py), not a generic
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
                f'{effective_timeout:.0f}s (mode={detector_mode or "default"}) - loud bound, not completion'
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
            # for the required cycles (FLOW Section 9). Checkpointed so a re-run after a
            # crash between completion and extraction resumes at the captured URL
            # and re-extracts rather than re-sending.
            self.checkpoint_run_state(
                request, self.RUN_STATE_COMPLETION_OBSERVED,
                result=result,
                url=result.session_url_after or self.runtime.current_url() or '',
            )
        return verified

    # ------------------------------------------------------------------
    # Lifecycle template (FLOW Section 10) - the lock seam lives HERE, once, so it
    # is identical for all five drivers and cannot drift per-platform.
    # ------------------------------------------------------------------

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        """Two-phase consultation lifecycle with per-display serialization.

        Phase A (LOCKED, sequential per display): ``setup_and_send`` - switch,
        navigate, select model/mode/tools/connectors, attach, enter prompt, and
        the guarded (idempotent) send + monitor registration. Held under the
        DISPLAY-scoped dispatch lock so two consultations never drive the same
        Firefox/AT-SPI bus at once.

        Phase B (UNLOCKED, concurrent): ``monitor_and_extract`` - poll for the
        Stop-gone completion, extract, store. Runs with the display lock ALREADY
        RELEASED so the next consultation can set up/send on this display while
        this one's response is monitored concurrently (FLOW Section 10 invariant).

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
                    # FLOW Section 10 setup/send is sequential per display - do NOT race the
                    # shared browser. Loud failure, not a silent skip or a wait-loop.
                    result.add_step(
                        'dispatch_lock', False,
                        f'{self.platform} display {self._display()} dispatch lock is '
                        f'already held by another consultation - setup/send is '
                        f'sequential per display (FLOW Section 10); not racing the shared '
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
                source='perplexity_package_run_delivery_gate',
            ):
                result.ok = False
            return result

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW Section 10): switch/navigate/select/attach/prompt then the
        guarded send + monitor registration. Return True iff the send is proven
        and the monitor session is registered (the handoff point); False on any
        setup/send failure (the step audit records why). Runs while THIS driver
        holds the DISPLAY-scoped dispatch lock - must not block on monitoring."""
        raise NotImplementedError

    def monitor_and_extract(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> None:
        """UNLOCKED phase (FLOW Section 10): poll for completion, extract, store, set
        result.ok. Runs AFTER the display lock is released so other consultations
        can set up/send on this display concurrently. Sets result.ok on success;
        leaves it False (with a recorded step) on any monitor/extract failure."""
        raise NotImplementedError



class PerplexityConsultationDriver(_PerplexityInlineBase):
    platform = 'perplexity'

    def _read_clipboard_until_nonempty(
        self,
        timeout: float = 4.0,
        interval: float = 0.3,
    ) -> tuple[str, dict[str, object]]:
        started = time.monotonic()
        deadline = started + timeout
        reads = 0
        content = ''
        while True:
            reads += 1
            content = (self.runtime.read_clipboard() or '').strip()
            if content:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
        return content, {
            'clipboard_reads': reads,
            'clipboard_wait_seconds': round(time.monotonic() - started, 3),
            'clipboard_timeout_seconds': timeout,
        }

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    # run() is the shared two-phase template on _PerplexityInlineBase (FLOW Section 10):
    # it holds the DISPLAY-scoped dispatch lock across setup_and_send (below) and
    # releases it before monitor_and_extract so monitoring runs concurrently.

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW Section 10): navigate -> mode -> connectors -> attach ->
        prompt -> guarded send + monitor registration."""
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Perplexity tab')
            return False
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(
                target_url,
                verify_change=bool(urls.get('verify_navigation')),
            )
            snap = self.runtime.snapshot()
            result.add_step(
                'navigate', navigated,
                'Navigated to Perplexity session target',
                target_url=target_url,
                snapshot=snap.serializable(),
            )
            if not navigated:
                return False
        if not self._dismiss_computer_onboarding(result):
            return False
        if target_url:
            if not self.wait_for_page_ready_after_navigation(result):
                return False
        if not self._wait_for_prompt_ready(result):
            return False
        if not self.apply_selection_plan(request, result):
            return False
        if not self._dismiss_computer_onboarding(result):
            return False
        if request.selection_list('connectors'):
            if not self.toggle_connectors(request, result):
                return False
        if not self.attach_files(request, result):
            return False
        if not self.enter_prompt(request, result):
            return False
        # Idempotent send seam (FLOW Section 8): guarded_send reads durable run-state
        # first and RESUMES a landed send instead of re-sending; otherwise it
        # performs the real send via self.send_prompt and checkpoints submitted.
        if not self.guarded_send(request, result):
            return False
        return True

    def monitor_and_extract(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> None:
        """UNLOCKED phase (FLOW Section 10): monitor -> extract -> store. Display lock is
        already released so a concurrent consultation can set up/send here."""
        if not self._ensure_answer_thread(result):
            return
        # send_prompt already proves Stop appeared before URL handoff. Carry
        # that observed Stop into the shared detector so fast completions whose
        # Stop button disappears before monitor starts still require the same
        # Stop-gone completion cycles rather than timing out as "never seen".
        if not self.monitor_generation(request, result, seed_stop_seen=True):
            return
        if not self._ensure_answer_thread(result):
            return
        if not self.extract_primary(request, result):
            return
        if not self.extract_additional(request, result):
            return
        if not self.store_in_neo4j(request, result):
            return
        result.ok = True

    def _wait_for_prompt_ready(self, result: ConsultationResult) -> bool:
        input_key = str(self.cfg['workflow']['prompt']['input'])
        snap, input_el = self.wait_for_key(
            input_key,
            timeout=self._prompt_ready_render_wait_timeout_seconds(),
            interval=0.4,
        )
        verified = input_el is not None
        result.add_step(
            'prompt_ready', verified,
            (
                'Perplexity prompt ready before mode selection'
                if verified else
                'Perplexity prompt not ready before mode selection'
            ),
            input_key=input_key,
            snapshot=snap.serializable(),
        )
        return verified

    def _computer_onboarding_cfg(self) -> dict[str, Any]:
        workflow = self.cfg.get('workflow') or {}
        onboarding = workflow.get('onboarding') if isinstance(workflow, dict) else None
        cfg = onboarding.get('computer_setup') if isinstance(onboarding, dict) else None
        if not isinstance(cfg, dict):
            raise ValueError('Perplexity YAML workflow.onboarding.computer_setup is required')
        return cfg

    def _computer_onboarding_keys(self, cfg: dict[str, Any], name: str) -> list[str]:
        raw_keys = cfg.get(name)
        if not isinstance(raw_keys, list) or not raw_keys:
            raise ValueError(
                f'Perplexity YAML workflow.onboarding.computer_setup.{name} '
                'must be a non-empty key list'
            )
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        keys: list[str] = []
        for raw_key in raw_keys:
            key = str(raw_key).strip() if isinstance(raw_key, str) else ''
            if not key:
                continue
            if key not in element_map:
                raise ValueError(
                    f'Perplexity onboarding key {key!r} is not declared in tree.element_map'
                )
            keys.append(key)
        if not keys:
            raise ValueError(
                f'Perplexity YAML workflow.onboarding.computer_setup.{name} '
                'must contain at least one declared element key'
            )
        return keys

    @staticmethod
    def _computer_onboarding_dismiss_keys(cfg: dict[str, Any]) -> list[str]:
        raw_keys = cfg.get('dismiss_keys')
        if not isinstance(raw_keys, list) or not raw_keys:
            raise ValueError(
                'Perplexity YAML workflow.onboarding.computer_setup.dismiss_keys '
                'must be a non-empty key list'
            )
        keys = [
            str(raw_key).strip()
            for raw_key in raw_keys
            if isinstance(raw_key, str) and raw_key.strip()
        ]
        if not keys:
            raise ValueError(
                'Perplexity YAML workflow.onboarding.computer_setup.dismiss_keys '
                'must contain at least one key chord'
            )
        return keys

    @staticmethod
    def _computer_onboarding_timeout_seconds(
        cfg: dict[str, Any],
        name: str,
        default_ms: int,
    ) -> float:
        value = cfg.get(name, default_ms)
        try:
            seconds = float(int(value)) / 1000.0
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f'Perplexity YAML workflow.onboarding.computer_setup.{name} '
                'must be integer milliseconds'
            ) from exc
        return max(seconds, 0.1)

    @staticmethod
    def _snapshot_has_all(snapshot: Snapshot, keys: Iterable[str]) -> bool:
        return all(snapshot.has(key) for key in keys)

    def _dismiss_computer_onboarding(
        self,
        result: ConsultationResult,
        *,
        initial_snapshot: Snapshot | None = None,
    ) -> bool:
        cfg = self._computer_onboarding_cfg()
        marker_keys = self._computer_onboarding_keys(cfg, 'markers')
        standard_keys = self._computer_onboarding_keys(cfg, 'standard_composer')
        dismiss_keys = self._computer_onboarding_dismiss_keys(cfg)
        detect_timeout = self._computer_onboarding_timeout_seconds(
            cfg, 'detect_timeout_ms', 6000
        )
        settle_timeout = self._computer_onboarding_timeout_seconds(
            cfg, 'settle_ms', 8000
        )
        last_snapshot = initial_snapshot

        def classify(snapshot: Snapshot) -> str | None:
            if self.snapshot_has_any(snapshot, marker_keys):
                return 'onboarding'
            if self._snapshot_has_all(snapshot, standard_keys):
                return 'standard'
            return None

        observed = classify(last_snapshot) if last_snapshot is not None else None
        if observed is None:
            def probe() -> str | None:
                nonlocal last_snapshot
                last_snapshot = self.runtime.snapshot()
                return classify(last_snapshot)

            observed = self.runtime.wait_until(
                probe,
                timeout=detect_timeout,
                interval=0.4,
            )
        if observed != 'onboarding':
            return True

        before_snapshot = last_snapshot or self.runtime.snapshot()
        self.runtime.focus_firefox()
        pressed: list[str] = []
        failed: list[str] = []
        for dismiss_key in dismiss_keys:
            if self.runtime.press(dismiss_key):
                pressed.append(dismiss_key)
            else:
                failed.append(dismiss_key)
            time.sleep(0.2)

        final_snapshot: Snapshot | None = None

        def standard_probe() -> Snapshot | None:
            nonlocal final_snapshot
            final_snapshot = self.runtime.snapshot()
            if self._snapshot_has_all(final_snapshot, standard_keys):
                return final_snapshot
            return None

        restored = self.runtime.wait_until(
            standard_probe,
            timeout=settle_timeout,
            interval=0.4,
        )
        snapshot = (
            restored
            if isinstance(restored, Snapshot)
            else (final_snapshot or self.runtime.snapshot())
        )
        verified = isinstance(restored, Snapshot)
        result.add_step(
            'computer_onboarding',
            verified,
            (
                'Dismissed Perplexity Computer onboarding; standard composer restored'
                if verified else
                'Perplexity Computer onboarding did not restore the standard composer'
            ),
            marker_keys=marker_keys,
            standard_keys=standard_keys,
            dismiss_keys=dismiss_keys,
            pressed_keys=pressed,
            failed_keys=failed,
            before_snapshot=before_snapshot.serializable(),
            snapshot=snapshot.serializable(),
        )
        return verified

    def _mode_settle_timeout(self) -> float:
        settle = self.cfg.get('settle') or {}
        if 'default_ms' not in settle:
            raise ValueError('Perplexity YAML settle.default_ms is required for mode validation')
        try:
            return max(float(int(settle['default_ms'])) / 1000.0, 0.1)
        except (TypeError, ValueError) as exc:
            raise ValueError('Perplexity YAML settle.default_ms must be integer milliseconds') from exc

    def _prompt_ready_render_wait_timeout_seconds(self) -> float:
        return min(
            max(
                self._mode_settle_timeout() * SETUP_RENDER_WAIT_MULTIPLIER,
                SETUP_RENDER_WAIT_FLOOR_SECONDS,
            ),
            SETUP_RENDER_WAIT_CEILING_SECONDS,
        )

    # ------------------------------------------------------------------
    # Connector toggles
    # ------------------------------------------------------------------

    def toggle_connectors(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        self.runtime.close_stale_dialogs()
        cfg_connectors = self.cfg['workflow'].get('connectors', {})
        source_targets: dict[str, str] = cfg_connectors.get('source_targets', {})

        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger:
            result.add_step(
                'toggle_connectors', False,
                'Perplexity attach_trigger not found for connector panel',
                snapshot=snap.serializable(),
            )
            return False
        if not self.runtime.click(trigger):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity attach_trigger click failed for connector panel',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(1.5)

        menu_snap = self.runtime.menu_snapshot()
        panel_trigger = self.find_first(menu_snap, 'git_connector_item')
        if not panel_trigger:
            result.add_step(
                'toggle_connectors', False,
                'Perplexity git_connector_item not found in attach dropdown',
                snapshot=menu_snap.serializable(),
            )
            return False
        if not self.runtime.click(panel_trigger):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity git_connector_item click failed',
                snapshot=menu_snap.serializable(),
            )
            return False
        time.sleep(2.0)

        for connector_name in request.selection_list('connectors'):
            normalized = connector_name.strip().lower()
            element_key = source_targets.get(normalized)
            if not element_key:
                result.add_step(
                    'toggle_connectors', False,
                    f'Connector {connector_name!r} not found in source_targets mapping',
                )
                return False

            panel_snap = self.runtime.menu_snapshot()
            search_box = self.find_first(panel_snap, 'search_sources')
            if not search_box:
                result.add_step(
                    'toggle_connectors', False,
                    f'Perplexity search_sources not found in connector panel '
                    f'(needed for {connector_name!r})',
                    snapshot=panel_snap.serializable(),
                )
                return False

            if not self.runtime.click(search_box):
                result.add_step(
                    'toggle_connectors', False,
                    f'Perplexity search_sources click failed for {connector_name!r}',
                    snapshot=panel_snap.serializable(),
                )
                return False
            time.sleep(0.3)
            self.runtime.press('ctrl+a')
            time.sleep(0.1)
            self.runtime.press('Delete')
            time.sleep(0.1)
            self.runtime.type_text(connector_name, delay_ms=40)
            time.sleep(1.5)

            filtered_snap = self.runtime.menu_snapshot()
            item = self.find_first(filtered_snap, element_key)
            if not item:
                result.add_step(
                    'toggle_connectors', False,
                    f'Perplexity connector element {element_key!r} not found in panel '
                    f'after searching for {connector_name!r}',
                    snapshot=filtered_snap.serializable(),
                )
                return False

            already_checked = bool(
                item.states and 'checked' in [s.lower() for s in item.states]
            )
            if already_checked:
                result.add_step(
                    'toggle_connectors', True,
                    f'Connector {connector_name!r} already enabled - skipping',
                )
            else:
                if not self.runtime.click(item):
                    result.add_step(
                        'toggle_connectors', False,
                        f'Perplexity connector click failed for {connector_name!r}',
                        snapshot=filtered_snap.serializable(),
                    )
                    return False
                time.sleep(0.5)
                result.add_step(
                    'toggle_connectors', True,
                    f'Connector {connector_name!r} clicked to enable',
                )

            panel_snap2 = self.runtime.menu_snapshot()
            search_box2 = self.find_first(panel_snap2, 'search_sources')
            if search_box2:
                self.runtime.click(search_box2)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.3)

        self.runtime.press('Escape')
        time.sleep(0.8)

        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger or not self.runtime.click(trigger):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity attach_trigger re-open failed during connector verification',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(1.5)

        menu_snap2 = self.runtime.menu_snapshot()
        panel_trigger2 = self.find_first(menu_snap2, 'git_connector_item')
        if not panel_trigger2 or not self.runtime.click(panel_trigger2):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity git_connector_item re-open failed during connector verification',
                snapshot=menu_snap2.serializable(),
            )
            return False
        time.sleep(2.0)

        all_verified = True
        for connector_name in request.selection_list('connectors'):
            normalized = connector_name.strip().lower()
            element_key = source_targets.get(normalized)
            if not element_key:
                continue

            verify_panel_snap = self.runtime.menu_snapshot()
            search_box = self.find_first(verify_panel_snap, 'search_sources')
            if search_box:
                self.runtime.click(search_box)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.1)
                self.runtime.type_text(connector_name, delay_ms=40)
                time.sleep(1.5)

            verify_panel_snap2 = self.runtime.menu_snapshot()
            verify_item = self.find_first(verify_panel_snap2, element_key)
            is_checked = bool(
                verify_item
                and verify_item.states
                and 'checked' in [s.lower() for s in verify_item.states]
            )
            if not is_checked:
                all_verified = False
            result.add_step(
                'verify_connector', is_checked,
                f'Connector {connector_name!r} verified {"enabled" if is_checked else "NOT enabled"}',
                snapshot=verify_panel_snap2.serializable(),
            )

            verify_panel_snap3 = self.runtime.menu_snapshot()
            search_box3 = self.find_first(verify_panel_snap3, 'search_sources')
            if search_box3:
                self.runtime.click(search_box3)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.3)

        self.runtime.press('Escape')
        time.sleep(0.5)

        result.add_step(
            'toggle_connectors', all_verified,
            'Perplexity connector toggle complete',
            requested=request.selection_list('connectors'),
        )
        return all_verified

    # ------------------------------------------------------------------
    # File attachment
    # ------------------------------------------------------------------

    def _dialog_env(self) -> dict[str, str]:
        env_factory = getattr(self.runtime, '_dialog_env', None)
        if callable(env_factory):
            return env_factory()
        return {**os.environ, 'DISPLAY': self._display()}

    @staticmethod
    def _is_file_dialog_title(title: str) -> bool:
        normalized = title.strip().lower()
        return (
            normalized == 'open'
            or normalized == 'open file'
            or normalized.startswith('file upload')
        )

    @staticmethod
    def _xdotool_search(args: list[str], env: dict[str, str], timeout: int = 2) -> list[str]:
        try:
            result = subprocess.run(
                ['xdotool', 'search', *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except Exception:
            return []
        if result.returncode != 0 or not result.stdout.strip():
            return []
        return [wid for wid in result.stdout.strip().split() if wid]

    @staticmethod
    def _xdotool_window_name(window_id: str, env: dict[str, str]) -> str:
        try:
            result = subprocess.run(
                ['xdotool', 'getwindowname', window_id],
                capture_output=True,
                text=True,
                timeout=2,
                env=env,
            )
        except Exception:
            return ''
        if result.returncode != 0:
            return ''
        return result.stdout.strip()

    @staticmethod
    def _activate_x_window(window_id: str, env: dict[str, str]) -> bool:
        for command in ('windowactivate', 'windowfocus'):
            try:
                result = subprocess.run(
                    ['xdotool', command, window_id],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env,
                )
            except Exception:
                continue
            if result.returncode == 0 and 'error' not in (result.stderr or '').lower():
                time.sleep(0.3)
                return True
        return False

    @staticmethod
    def _x_window_geometry(window_id: str, env: dict[str, str]) -> tuple[int, int] | None:
        try:
            result = subprocess.run(
                ['xwininfo', '-id', window_id],
                capture_output=True,
                text=True,
                timeout=2,
                env=env,
            )
        except Exception:
            return None
        if result.returncode != 0 or 'IsViewable' not in result.stdout:
            return None
        width_match = re.search(r'Width:\s*(\d+)', result.stdout)
        height_match = re.search(r'Height:\s*(\d+)', result.stdout)
        if not width_match or not height_match:
            return None
        width = int(width_match.group(1))
        height = int(height_match.group(1))
        if width <= 100 or height <= 100:
            return None
        return width, height

    def _visible_firefox_windows(self, env: dict[str, str]) -> list[dict[str, object]]:
        windows: list[dict[str, object]] = []
        for window_id in self._xdotool_search(['--class', 'firefox'], env):
            geometry = self._x_window_geometry(window_id, env)
            if geometry is None:
                continue
            width, height = geometry
            windows.append({
                'id': window_id,
                'title': self._xdotool_window_name(window_id, env),
                'width': width,
                'height': height,
                'area': width * height,
            })
        return windows

    def _visible_firefox_window_count(self, env: dict[str, str]) -> int:
        display = env.get('DISPLAY') or self._display()
        try:
            return _viewable_windows(display)
        except Exception:
            return len(self._visible_firefox_windows(env))

    @staticmethod
    def _close_x_window(window_id: str, env: dict[str, str]) -> bool:
        try:
            result = subprocess.run(
                ['xdotool', 'windowclose', window_id],
                capture_output=True,
                text=True,
                timeout=3,
                env=env,
            )
        except Exception:
            return False
        if result.returncode == 0:
            time.sleep(0.3)
            return True
        return False

    def _focus_platform_firefox_for_attach(self, env: dict[str, str]) -> bool:
        window_ids = self._xdotool_search(['--onlyvisible', '--class', 'Firefox'], env)
        for window_id in reversed(window_ids):
            title = self._xdotool_window_name(window_id, env)
            if title.strip().lower() == 'firefox' or self._is_file_dialog_title(title):
                continue
            if self._activate_x_window(window_id, env):
                return True
        return False

    def _find_perplexity_file_dialog_window(self, env: dict[str, str]) -> tuple[str, str] | None:
        seen: set[str] = set()
        for title_pattern in PERPLEXITY_FILE_DIALOG_TITLE_PATTERNS:
            for search_args in (
                ['--onlyvisible', '--name', title_pattern],
                ['--name', title_pattern],
            ):
                for window_id in self._xdotool_search(search_args, env):
                    if window_id in seen:
                        continue
                    seen.add(window_id)
                    title = self._xdotool_window_name(window_id, env) or title_pattern
                    if self._is_file_dialog_title(title):
                        return window_id, title
        return None

    def _wait_for_perplexity_file_dialog_window(
        self,
        env: dict[str, str],
        timeout: float,
        interval: float = 0.25,
    ) -> tuple[tuple[str, str] | None, float]:
        started = time.monotonic()
        deadline = started + max(float(timeout), 0.1)
        while time.monotonic() < deadline:
            found = self._find_perplexity_file_dialog_window(env)
            if found is not None:
                return found, round(time.monotonic() - started, 3)
            time.sleep(interval)
        return None, round(time.monotonic() - started, 3)

    def _focus_perplexity_file_dialog_for_attach(
        self,
        timeout: float = 12.0,
    ) -> tuple[bool, dict[str, object]]:
        env = self._dialog_env()
        firefox_focused = self._focus_platform_firefox_for_attach(env)
        found, waited = self._wait_for_perplexity_file_dialog_window(env, timeout)
        evidence: dict[str, object] = {
            'firefox_focused_before_dialog_wait': firefox_focused,
            'dialog_wait_seconds': waited,
            'dialog_wait_timeout_seconds': timeout,
        }
        if found is None:
            evidence['dialog_found'] = False
            return False, evidence
        window_id, title = found
        activated = self._activate_x_window(window_id, env)
        evidence.update({
            'dialog_found': True,
            'dialog_window_id': window_id,
            'dialog_title': title,
            'dialog_activated': activated,
        })
        if activated:
            return True, evidence
        runtime_focused = self.runtime.focus_file_dialog()
        evidence['runtime_focus_file_dialog'] = runtime_focused
        return runtime_focused, evidence

    def _fail_attach_with_dialog_cleanup(
        self,
        result: ConsultationResult,
        message: str,
        *,
        snapshot: Snapshot | None = None,
        **evidence: object,
    ) -> bool:
        evidence['closed_orphan_file_dialogs'] = self.runtime.close_stale_dialogs()
        if snapshot is not None:
            evidence['snapshot'] = snapshot.serializable()
        result.add_step('attach', False, message, **evidence)
        return False

    def attach_files(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        self.runtime.close_stale_dialogs()
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger:
                result.add_step(
                    'attach', False,
                    f'Perplexity attach trigger missing for {abs_path}',
                    snapshot=snap.serializable(),
                )
                return False
            if not self.runtime.click(trigger):
                result.add_step(
                    'attach', False,
                    f'Perplexity attach trigger click failed for {abs_path}',
                    snapshot=snap.serializable(),
                )
                return False
            # Settle + rescan (DRIVER_CONTRACT Section E): the attach dropdown's
            # "Upload files or images" item renders a beat after the trigger
            # click. A fixed time.sleep(0.7) + one-shot read flaked ("upload
            # item not found") when the menu was slow to render - the item was
            # present moments later. Poll for it (observation only, no re-click)
            # before declaring it missing, same readiness pattern as mode-select.
            menu_snap, upload_item = self.wait_for_key(
                'upload_files_item',
                timeout=10.0,
                interval=0.4,
                scope='menu',
            )
            if not upload_item:
                result.add_step(
                    'attach', False,
                    f'Perplexity upload item not found for {abs_path}',
                    snapshot=menu_snap.serializable(),
                )
                return False
            if not self.runtime.click(upload_item):
                result.add_step(
                    'attach', False,
                    f'Perplexity upload item click failed for {abs_path}',
                    snapshot=menu_snap.serializable(),
                )
                return False
            time.sleep(0.8)
            focused, dialog_evidence = self._focus_perplexity_file_dialog_for_attach()
            if not focused:
                return self._fail_attach_with_dialog_cleanup(
                    result,
                    f'Perplexity file dialog did not focus for {abs_path}',
                    snapshot=menu_snap,
                    **dialog_evidence,
                )
            if not self.runtime.press('ctrl+l'):
                return self._fail_attach_with_dialog_cleanup(
                    result,
                    f'Perplexity file dialog location shortcut failed for {abs_path}',
                    **dialog_evidence,
                )
            time.sleep(0.2)
            if not self.runtime.press('ctrl+a'):
                return self._fail_attach_with_dialog_cleanup(
                    result,
                    f'Perplexity file dialog select-all failed for {abs_path}',
                    **dialog_evidence,
                )
            time.sleep(0.1)
            if not self.runtime.paste(abs_path):
                return self._fail_attach_with_dialog_cleanup(
                    result,
                    f'Perplexity file dialog path paste failed for {abs_path}',
                    **dialog_evidence,
                )
            time.sleep(0.2)
            focused, submit_dialog_evidence = self._focus_perplexity_file_dialog_for_attach()
            if not focused:
                return self._fail_attach_with_dialog_cleanup(
                    result,
                    f'Perplexity file dialog lost focus before submit for {abs_path}',
                    **submit_dialog_evidence,
                )
            if not self.runtime.press('Return'):
                return self._fail_attach_with_dialog_cleanup(
                    result,
                    f'Perplexity file dialog submit failed for {abs_path}',
                    **submit_dialog_evidence,
                )
            time.sleep(1.2)
            verify_snap = self.wait_for_validation(
                'attach_success',
                filename=abs_path,
                timeout=15.0,
                interval=0.5,
            )
            verified = self.validation_passes(verify_snap, 'attach_success', filename=abs_path)
            result.add_step(
                'attach', verified,
                f'Perplexity attached {os.path.basename(abs_path)}',
                file=abs_path,
                snapshot=verify_snap.serializable(),
            )
            if not verified:
                self.runtime.close_stale_dialogs()
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Perplexity attachments requested')
        return True

    # ------------------------------------------------------------------
    # Prompt entry
    # ------------------------------------------------------------------

    def enter_prompt(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        prompt_cfg = self.cfg['workflow']['prompt']
        input_key = str(prompt_cfg['input'])
        last_snap: Snapshot | None = None

        def _input_probe() -> ElementRef | None:
            nonlocal last_snap
            last_snap = self.runtime.snapshot()
            return self.find_first(last_snap, input_key)

        found = self.runtime.wait_until(_input_probe, timeout=12.0, interval=0.5)
        snap = last_snap or self.runtime.snapshot()
        input_el = found
        if not input_el:
            result.add_step(
                'prompt', False,
                'Perplexity input field not found',
                snapshot=snap.serializable(),
                input_key=input_key,
            )
            return False
        if not self.runtime.focus_firefox():
            result.add_step(
                'prompt', False,
                'Perplexity Firefox window focus failed before prompt entry',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(0.2)
        focused = self.runtime.click(input_el)
        if not focused:
            result.add_step(
                'prompt', False,
                'Perplexity input focus failed',
                snapshot=snap.serializable(),
                focused=focused,
            )
            return False
        time.sleep(0.3)
        if not self.runtime.press('ctrl+a'):
            result.add_step(
                'prompt', False,
                'Perplexity prompt stale-draft select-all failed',
                snapshot=self.runtime.snapshot().serializable(),
            )
            return False
        if not self.runtime.press('BackSpace'):
            result.add_step(
                'prompt', False,
                'Perplexity prompt stale-draft clear failed',
                snapshot=self.runtime.snapshot().serializable(),
            )
            return False
        pasted = self.runtime.paste(request.message)
        verify_snap, submit_visible = self.wait_for_key(
            'submit_button',
            timeout=8.0,
            interval=0.4,
            select='last',
        )
        verified = bool(pasted and submit_visible)
        result.add_step(
            'prompt',
            verified,
            (
                'Perplexity prompt entered and Submit button appeared'
                if verified else
                'Perplexity prompt entry failed validation: Submit button did not appear'
            ),
            snapshot=verify_snap.serializable(),
            focused=focused,
            input_key=input_key,
        )
        return verified

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_prompt(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        before = result.session_url_before
        snap, send_button, submit_scope = self._wait_for_submit_button_for_send()
        if send_button:
            # Use atspi_only (direct do_action(0) on the AT-SPI push button) for reliable
            # submit registration. xdotool/coord clicks on the 'Submit' (last_by_y) are
            # proven unreliable for Perplexity even when enabled (message+attach+mode staged
            # but no navigation to /search/<id> thread).
            click_returned = self.runtime.click(send_button, strategy='atspi_only')
            if not click_returned:
                result.add_step(
                    'send', False,
                    'Perplexity submit button click failed',
                    submit_scope=submit_scope,
                    snapshot=snap.serializable(),
                )
                return False
        else:
            result.add_step(
                'send', False,
                'Perplexity submit button not found',
                submit_scope=submit_scope,
                snapshot=snap.serializable(),
            )
            return False

        # VERIFY submit actually fired before declaring success (no silent success on
        # staged-but-not-submitted state). Stop button, answer-thread URL, or composer
        # clear are all landed signals; Deep Research with attachments can surface them
        # after the ordinary DOM settle window.
        submit_timeout = self._submit_fire_timeout(request)
        submit_fired, submit_evidence = self._verify_submit_fired(
            before,
            timeout=submit_timeout,
        )
        if not submit_fired:
            result.add_step(
                'send', False,
                'Perplexity submit did not fire (no Stop button, composer clear, or /search/<id> thread URL within settle)',
                url_before=before,
                url_after=self.runtime.current_url() or '',
                submit_scope=submit_scope,
                click_returned=click_returned,
                submit_verification=submit_evidence,
            )
            return False

        send_timeout = self._send_success_timeout()
        send_snap = self.wait_for_validation(
            'send_success',
            timeout=send_timeout,
            interval=0.6,
        )
        stop_seen = self.validation_passes(send_snap, 'send_success')
        settled_url = self._wait_for_answer_thread_url(timeout=submit_timeout)
        if not settled_url:
            result.add_step(
                'send', False,
                'Perplexity answer thread URL was not captured after submit',
                url_before=before,
                submit_scope=submit_scope,
                click_returned=click_returned,
                answer_thread_timeout=submit_timeout,
                stop_seen=bool(stop_seen),
                snapshot=send_snap.serializable(),
            )
            return False
        result.session_url_after = settled_url
        verify_snap = send_snap
        url_changed = settled_url and settled_url != before
        is_new_session = not request.session_url
        if is_new_session:
            verified = bool(click_returned and stop_seen and url_changed and self._is_answer_thread_url(settled_url))
        else:
            verified = bool(click_returned and stop_seen and self._is_answer_thread_url(settled_url))
        msg = (
            'Perplexity send validated by Stop button appearance and URL capture'
            if verified else
            'Perplexity send failed validation: Stop button did not appear or URL was not captured'
        )
        result.add_step(
            'send', verified,
            msg,
            url_before=before,
            url_after=settled_url,
            submit_scope=submit_scope,
            click_returned=click_returned,
            submit_verification=submit_evidence,
            stop_seen=bool(stop_seen),
            answer_thread=bool(self._is_answer_thread_url(settled_url)),
            snapshot=verify_snap.serializable(),
        )
        return verified

    def _wait_for_submit_button_for_send(self) -> tuple[Snapshot, ElementRef | None, str]:
        last_snapshot: Snapshot | None = None
        last_scope = 'not_found'

        def _probe() -> tuple[Snapshot, ElementRef, str] | None:
            nonlocal last_snapshot, last_scope
            snap, send_button, scope = self._find_submit_button_for_send()
            last_snapshot = snap
            last_scope = scope
            if send_button:
                return snap, send_button, scope
            return None

        found = self.runtime.wait_until(
            _probe,
            timeout=self._mode_settle_timeout(),
            interval=0.4,
        )
        if found:
            return found
        return last_snapshot or self.runtime.snapshot(), None, last_scope

    def _find_submit_button_for_send(self) -> tuple[Snapshot, ElementRef | None, str]:
        snap = self.runtime.snapshot()
        send_button = self.find_last(snap, 'submit_button')
        if send_button:
            # Require ENABLED for the SEND. While a (large) attachment is still
            # uploading, the submit button is PRESENT but DISABLED; clicking the
            # disabled ghost no-ops -> no thread, no answer-thread URL (observed
            # 2026-06-22: ~80KB consolidated attach, submit disabled mid-upload,
            # send false-failed + needed manual recovery). Per CONSULTATION_CONTRACT
            # a disabled control is a DISTINCT state, not a match, so the send
            # wait-loop keeps polling until the upload finishes and submit enables -
            # i.e. the send gates on attach-upload-complete by construction.
            if 'enabled' in set(send_button.states or []):
                return snap, send_button, 'document'
            return snap, None, 'present_but_disabled'
        return snap, None, 'not_found'

    def _is_answer_thread_url(self, url: str | None) -> bool:
        return '/search/' in (url or '')

    def is_resumable_session_url(self, url: str | None) -> bool:
        return self._is_answer_thread_url(url)

    def _wait_for_answer_thread_url(self, *, timeout: float = 8.0) -> str | None:
        def _probe() -> str | None:
            current = self.runtime.current_url()
            return current if self._is_answer_thread_url(current) else None

        found = self.runtime.wait_until(_probe, timeout=timeout, interval=0.5)
        return str(found) if found else None

    def _send_success_timeout(self) -> float:
        raw_timeout = self.cfg.get('validation', {}).get('send_success', {}).get('timeout', 60)
        try:
            return max(float(raw_timeout), self._mode_settle_timeout())
        except (TypeError, ValueError) as exc:
            raise ValueError('Perplexity validation.send_success.timeout must be numeric seconds') from exc

    def _submit_fire_timeout(self, request: ConsultationRequest) -> float:
        timeout = self._mode_settle_timeout()
        settle = self.cfg.get('settle') or {}
        if request.attachments:
            raw_attach_ms = settle.get('attach_ms', 0) if isinstance(settle, dict) else 0
            try:
                timeout += max(float(int(raw_attach_ms)) / 1000.0, 0.0)
            except (TypeError, ValueError) as exc:
                raise ValueError('Perplexity YAML settle.attach_ms must be integer milliseconds') from exc
        default_mode = self.cfg.get('workflow', {}).get('defaults', {}).get('mode')
        selected_mode = str(request.selection_value('mode', default_mode) or '').strip().lower()
        send_timeout = self._send_success_timeout()
        if selected_mode == 'deep_research':
            timeout = max(timeout, send_timeout)
        return min(max(timeout, 1.0), send_timeout)

    def _verify_submit_fired(self, before: str, *, timeout: float) -> tuple[bool, dict[str, object]]:
        """Confirm the submit action registered before entering send_success wait."""
        deadline = time.time() + timeout
        stop_key = self._stop_key()
        last_url = self.runtime.current_url() or ''
        last_signal = 'timeout'
        while time.time() < deadline:
            url = self.runtime.current_url() or ''
            last_url = url
            if self._is_answer_thread_url(url) and url != before:
                return True, {
                    'signal': 'answer_thread_url',
                    'timeout': timeout,
                    'url_after': url,
                    'stop_key': stop_key,
                }
            snap = self.runtime.snapshot()
            if snap.has(stop_key):
                return True, {
                    'signal': 'stop_button',
                    'timeout': timeout,
                    'url_after': url,
                    'stop_key': stop_key,
                }
            btn = self.find_last(snap, 'submit_button')
            if btn is None or 'enabled' not in set(btn.states or []):
                return True, {
                    'signal': 'composer_cleared',
                    'timeout': timeout,
                    'url_after': url,
                    'stop_key': stop_key,
                }
            last_signal = 'composer_still_enabled'
            time.sleep(0.2)
        return False, {
            'signal': last_signal,
            'timeout': timeout,
            'url_after': last_url,
            'stop_key': stop_key,
        }

    def _ensure_answer_thread(self, result: ConsultationResult) -> bool:
        current = self.runtime.current_url()
        if self._is_answer_thread_url(current):
            result.session_url_after = current
            return True
        if self._is_answer_thread_url(result.session_url_after):
            self.runtime.navigate(result.session_url_after, verify_change=False)
            current = self._wait_for_answer_thread_url(timeout=8.0)
            if self._is_answer_thread_url(current):
                result.session_url_after = current
                result.add_step(
                    'answer_thread', True,
                    'Perplexity navigated back to captured answer thread',
                    url=current,
                )
                return True
        result.add_step(
            'answer_thread', False,
            'Perplexity is not on an answer thread; refusing monitor/extract from home',
            current_url=current,
            captured_url=result.session_url_after,
        )
        return False

    # ------------------------------------------------------------------
    # Monitor generation - inherited from _PerplexityInlineBase (the package
    # stop-transition detector). deep_research is a
    # deep mode (2 stop-gone scans) so AT-SPI refresh is debounced before
    # completion is declared.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _is_deep_research(self, request: ConsultationRequest) -> bool:
        """Return True if the current request is a Deep Research mode query."""
        mode = str(request.selection_value('mode', '') or '').strip().lower()
        if mode == 'deep_research':
            return True
        default_mode = (
            self.cfg.get('workflow', {}).get('defaults', {}).get('mode') or ''
        ).strip().lower()
        return default_mode == 'deep_research'

    def _deep_research_copy_target(
        self,
    ) -> tuple[Snapshot, str | None, ElementRef | None, dict[str, object]]:
        started = time.monotonic()
        snap, report_target = self.wait_for_key(
            'copy_contents_button',
            timeout=DEEP_RESEARCH_REPORT_CARD_READINESS_SECONDS,
            interval=DEEP_RESEARCH_REPORT_CARD_READINESS_INTERVAL_SECONDS,
            select='last',
        )
        readiness: dict[str, object] = {
            'waited_for': 'copy_contents_button',
            'timeout_seconds': DEEP_RESEARCH_REPORT_CARD_READINESS_SECONDS,
            'interval_seconds': DEEP_RESEARCH_REPORT_CARD_READINESS_INTERVAL_SECONDS,
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'matched': bool(report_target),
        }
        if report_target:
            readiness['selected'] = 'copy_contents_button'
            return snap, 'copy_contents_button', report_target, readiness
        inline_target = self.find_last(snap, 'copy_button')
        readiness['selected'] = 'copy_button' if inline_target else None
        return snap, 'copy_button' if inline_target else None, inline_target, readiness

    def _accept_extracted_content(
        self,
        content: str,
        request: ConsultationRequest,
        result: ConsultationResult,
        message: str,
        **evidence: object,
    ) -> bool:
        step_evidence = dict(evidence)
        step_evidence.update(
            characters=len(content),
            preview=content[:200],
        )
        if not self.set_response_text_if_not_prompt_echo(
            request,
            result,
            content,
            step='extract_primary',
            source='perplexity_copy_response',
            **step_evidence,
        ):
            return False
        result.add_step(
            'extract_primary', True,
            message,
            **step_evidence,
        )
        return True

    @staticmethod
    def _markdown_download_dirs() -> tuple[Path, ...]:
        paths = [Path.home() / 'Downloads']
        xdg_download = os.environ.get('XDG_DOWNLOAD_DIR')
        if xdg_download:
            paths.append(Path(xdg_download).expanduser())
        unique: list[Path] = []
        seen = set()
        for path in paths:
            marker = str(path)
            if marker not in seen:
                seen.add(marker)
                unique.append(path)
        return tuple(unique)

    def _markdown_download_state(self) -> dict[str, tuple[float, int]]:
        state: dict[str, tuple[float, int]] = {}
        for directory in self._markdown_download_dirs():
            if not directory.exists():
                continue
            for path in directory.glob('*.md'):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                state[str(path)] = (float(stat.st_mtime), int(stat.st_size))
        return state

    def _read_new_markdown_download(
        self,
        before: dict[str, tuple[float, int]],
        *,
        timeout: float = 12.0,
    ) -> tuple[str, dict[str, object]]:
        deadline = time.monotonic() + timeout
        newest: Path | None = None
        while time.monotonic() < deadline:
            changed: list[Path] = []
            for directory in self._markdown_download_dirs():
                if not directory.exists():
                    continue
                for path in directory.glob('*.md'):
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    prior = before.get(str(path))
                    current = (float(stat.st_mtime), int(stat.st_size))
                    if prior != current and current[1] > 0:
                        changed.append(path)
            if changed:
                newest = max(changed, key=lambda item: item.stat().st_mtime)
                try:
                    content = newest.read_text(errors='replace').strip()
                except OSError:
                    content = ''
                if content:
                    return content, {
                        'download_path': str(newest),
                        'download_characters': len(content),
                    }
            time.sleep(0.5)
        return '', {
            'download_path': str(newest) if newest else None,
            'download_timeout': timeout,
        }

    @staticmethod
    def _markdown_download_answer_region(content: str) -> str:
        text = (content or '').strip()
        if not text:
            return ''
        probe = text[:5000].lower()
        if (
            'r2cdn.perplexity.ai/pplx-full-logo' not in probe
            or 'perplexity deep research request' not in probe
            or '## output contract' not in probe
        ):
            return text
        contract_pos = probe.find('## output contract')
        search_start = contract_pos if contract_pos >= 0 else 0
        markers = (
            '\nI now have all the information I need.',
            '\nI have all the information I need.',
            '\nI now have the information I need.',
            '\n***\n\n# ',
        )
        starts = [
            pos + (1 if marker.startswith('\n') else 0)
            for marker in markers
            if (pos := text.find(marker, search_start)) >= 0
        ]
        if not starts:
            return text
        return text[min(starts):].strip()

    @staticmethod
    def _merge_deep_research_sources(
        body: str,
        markdown: str,
    ) -> tuple[str, dict[str, object]]:
        citation_ids = {
            int(value)
            for value in re.findall(r'(?<!\^)\[([0-9]+)\]', body or '')
        }
        sources = {
            int(source_id): url.rstrip()
            for source_id, url in re.findall(
                r'^\[\^([0-9]+)\]:\s+(https?://\S+)\s*$',
                markdown or '',
                flags=re.MULTILINE,
            )
        }
        missing_ids = sorted(citation_ids - sources.keys())
        evidence: dict[str, object] = {
            'citation_ids': sorted(citation_ids),
            'markdown_source_ids': sorted(sources),
            'missing_source_ids': missing_ids,
        }
        if not citation_ids or missing_ids:
            return '', evidence
        source_lines = [f'{source_id}. {sources[source_id]}' for source_id in sorted(citation_ids)]
        merged = f'{body.rstrip()}\n\n## Sources\n\n' + '\n'.join(source_lines)
        evidence['merged_source_urls'] = len(source_lines)
        evidence['merged_characters'] = len(merged)
        return merged, evidence

    def _cleanup_markdown_download_popup(
        self,
        baseline_window_ids: set[str],
        *,
        timeout: float = 3.0,
    ) -> tuple[bool, dict[str, object]]:
        env = self._dialog_env()
        baseline = {str(window_id) for window_id in baseline_window_ids if window_id}
        windows = self._visible_firefox_windows(env)
        evidence: dict[str, object] = {
            'markdown_download_baseline_firefox_window_ids': sorted(baseline),
            'markdown_download_visible_firefox_windows_before_cleanup': len(windows),
            'markdown_download_firefox_windows_before_cleanup': windows,
        }
        if len(windows) > 1:
            candidates = [window for window in windows if str(window.get('id') or '') not in baseline]
            if not candidates:
                keep = max(windows, key=lambda window: int(window.get('area') or 0))
                candidates = [window for window in windows if window is not keep]
            closed: list[str] = []
            failed: list[str] = []
            for window in sorted(candidates, key=lambda item: int(item.get('area') or 0)):
                window_id = str(window.get('id') or '')
                if not window_id:
                    continue
                if self._close_x_window(window_id, env):
                    closed.append(window_id)
                else:
                    failed.append(window_id)
            evidence['markdown_download_popup_closed_window_ids'] = closed
            evidence['markdown_download_popup_close_failed_window_ids'] = failed
        else:
            evidence['markdown_download_popup_closed_window_ids'] = []
            evidence['markdown_download_popup_close_failed_window_ids'] = []

        deadline = time.monotonic() + max(float(timeout), 0.1)
        visible_after = self._visible_firefox_window_count(env)
        while visible_after != 1 and time.monotonic() < deadline:
            time.sleep(0.25)
            visible_after = self._visible_firefox_window_count(env)
        evidence['markdown_download_visible_firefox_windows_after_cleanup'] = visible_after
        evidence['markdown_download_popup_cleanup_timeout_seconds'] = timeout
        return visible_after == 1, evidence

    def _activate_markdown_download_item(
        self,
        trigger_key: str,
        item_key: str,
    ) -> dict[str, object]:
        snap = self.runtime.snapshot()
        trigger = self.find_last(snap, trigger_key)
        evidence: dict[str, object] = {
            'trigger_key': trigger_key,
            'item_key': item_key,
            'trigger_found': bool(trigger),
        }
        if not trigger:
            return evidence
        evidence['trigger'] = {
            'name': trigger.name,
            'role': trigger.role,
            'x': trigger.x,
            'y': trigger.y,
        }
        self.runtime.scroll_element_into_view(trigger)
        time.sleep(0.3)
        evidence['trigger_clicked'] = bool(
            self.runtime.click(trigger, strategy='coordinate_only')
        )
        time.sleep(0.8)
        menu_snap = self.runtime.snapshot()
        item = self.find_last(menu_snap, item_key)
        evidence['item_found'] = bool(item)
        if not item:
            self.runtime.press('Escape')
            time.sleep(0.3)
            return evidence
        evidence['item'] = {
            'name': item.name,
            'role': item.role,
            'x': item.x,
            'y': item.y,
        }
        evidence['item_clicked'] = bool(
            self.runtime.click(item, strategy='coordinate_only')
        )
        if not evidence['item_clicked']:
            self.runtime.press('Escape')
            time.sleep(0.3)
        return evidence

    def _extract_via_markdown_download(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        attempts: list[dict[str, object]],
        *,
        base_content: str | None = None,
    ) -> bool:
        env = self._dialog_env()
        baseline_windows = self._visible_firefox_windows(env)
        baseline_window_ids = {str(window.get('id') or '') for window in baseline_windows}
        before = self._markdown_download_state()
        for trigger_key, item_key in (
            ('more_actions', 'export_markdown_item'),
            ('download_button', 'download_markdown_item'),
        ):
            attempt = self._activate_markdown_download_item(trigger_key, item_key)
            attempts.append(attempt)
            if not attempt.get('item_clicked'):
                continue
            content, download_evidence = self._read_new_markdown_download(before)
            attempt.update(download_evidence)
            cleanup_ok, cleanup_evidence = self._cleanup_markdown_download_popup(
                baseline_window_ids,
            )
            download_evidence.update(cleanup_evidence)
            attempt.update(cleanup_evidence)
            if not cleanup_ok:
                result.add_step(
                    'extract_primary', False,
                    'Perplexity Markdown download left extra visible Firefox windows open',
                    target_key='markdown_download',
                    markdown_download_attempts=attempts,
                    **download_evidence,
                )
                return False
            if not content:
                continue
            answer_region = self._markdown_download_answer_region(content)
            if not answer_region:
                continue
            if answer_region != content:
                download_evidence.update(
                    markdown_download_stripped_echo=True,
                    markdown_download_raw_characters=len(content),
                    markdown_download_answer_characters=len(answer_region),
                )
                attempt.update(download_evidence)
            content = answer_region
            target_key = 'markdown_download'
            message = f'Perplexity response extracted via Markdown download ({len(content)} chars)'
            if base_content is not None:
                content, merge_evidence = self._merge_deep_research_sources(base_content, content)
                download_evidence.update(merge_evidence)
                attempt.update(merge_evidence)
                if not content:
                    continue
                target_key = 'copy_contents_with_markdown_sources'
                message = (
                    'Perplexity report body extracted via Copy contents with '
                    f'Markdown Sources ({len(content)} chars)'
                )
            return self._accept_extracted_content(
                content,
                request,
                result,
                message,
                target_key=target_key,
                markdown_download_attempts=attempts,
                **download_evidence,
            )
        return False

    def extract_primary(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        is_deep_research = self._is_deep_research(request)
        if not is_deep_research:
            # Wait for non-Deep-Research responses to finish exposing their action row.
            time.sleep(2.0)
        if not self._ensure_answer_thread(result):
            return False

        if not is_deep_research:
            self.runtime.scroll_document_to_bottom(clicks=12, rounds=3, settle=0.5)

        # Deep Research renders in one of several mapped output shapes. The report
        # card's Copy contents control carries the full report body but omits its
        # separately rendered Sources widget; Markdown export carries the source map
        # but can omit the detailed report sections.
        # Selection:
        #   - report-card present -> copy_contents_button body + Markdown source map
        #   - inline answer (no report-card) -> copy_button
        # Observed DR sub-shapes:
        #   - Zapier b2a1859e: copy_contents_button never renders; Markdown export
        #     is the extraction path.
        #   - Cursor 92b7d26b: copy_contents_button can render late; during the
        #     90s window copy_button may be present but produce an empty clipboard,
        #     so empty copy_button must continue to Markdown export.
        report_card_readiness: dict[str, object] | None = None
        markdown_download_attempts: list[dict[str, object]] = []
        if is_deep_research:
            snap, target_key, target, report_card_readiness = self._deep_research_copy_target()
        else:
            # Use snapshot (which clears AT-SPI cache via build_snapshot) to find
            # copy buttons. Raw find_elements bypasses cache clearing and misses
            # elements after the long monitor polling phase.
            snap = self.runtime.snapshot()
            target_key = 'copy_button'
            target = self.find_last(snap, target_key)

        if not target:
            if is_deep_research and self._extract_via_markdown_download(
                request,
                result,
                markdown_download_attempts,
            ):
                return True
            result.add_step(
                'extract_primary', False,
                (
                    'Perplexity Deep Research: no mapped extraction control present '
                    '(neither copy_contents_button report-card nor copy_button inline answer)'
                    if is_deep_research
                    else f'Perplexity required extraction target {target_key!r} not found'
                ),
                stop_condition='extraction_failed',
                markdown_download_attempts=markdown_download_attempts,
                report_card_readiness=report_card_readiness,
                snapshot=snap.serializable(),
            )
            return False

        # Perplexity's DR Copy / "Copy contents" returns an EMPTY clipboard if
        # action-clicked while OFF-SCREEN. Make the pre-copy scroll load-bearing
        # for the report control, then rescan so the clicked AT-SPI object is the
        # visible post-scroll element rather than the stale pre-scroll ref.
        scrolled_into_view = bool(self.runtime.scroll_element_into_view(target))
        document_scrolled = False
        refreshed = False
        if target_key == 'copy_contents_button':
            if not scrolled_into_view:
                document_scrolled = bool(
                    self.runtime.scroll_document_to_bottom(clicks=12, rounds=3, settle=0.5)
                )
            post_scroll_snap = self.runtime.snapshot()
            refreshed_target = self.find_last(post_scroll_snap, target_key)
            if refreshed_target:
                target = refreshed_target
                snap = post_scroll_snap
                refreshed = True
            if not (scrolled_into_view or document_scrolled):
                result.add_step(
                    'extract_primary',
                    False,
                    'Perplexity copy_contents_button could not be scrolled into view before copy',
                    stop_condition='extraction_failed',
                    target_key=target_key,
                    scrolled_into_view=scrolled_into_view,
                    document_scrolled=document_scrolled,
                    target_refreshed=refreshed,
                    markdown_download_attempts=markdown_download_attempts,
                    report_card_readiness=report_card_readiness,
                    snapshot=snap.serializable(),
                )
                return False
        time.sleep(0.5)
        # Clear clipboard, click via AT-SPI action, read clipboard
        self.runtime.write_clipboard('')
        time.sleep(0.3)
        clicked = self.runtime.click(target, strategy='atspi_only')
        if not clicked:
            result.add_step(
                'extract_primary', False,
                f'Perplexity copy target click failed (button: {target.name!r})',
                stop_condition='extraction_failed',
                target_key=target_key,
                scrolled_into_view=scrolled_into_view,
                document_scrolled=document_scrolled,
                target_refreshed=refreshed,
                markdown_download_attempts=markdown_download_attempts,
                report_card_readiness=report_card_readiness,
                snapshot=snap.serializable(),
            )
            return False
        content, clipboard_poll = self._read_clipboard_until_nonempty()

        if content:
            if is_deep_research and target_key == 'copy_contents_button':
                step_count_before_markdown = len(result.steps)
                if self._extract_via_markdown_download(
                    request,
                    result,
                    markdown_download_attempts,
                    base_content=content,
                ):
                    return True
                if any(not step.success for step in result.steps[step_count_before_markdown:]):
                    return False
                result.add_step(
                    'extract_primary',
                    False,
                    'Perplexity report body citations could not be resolved to Markdown source URLs',
                    stop_condition='extraction_failed',
                    target_key=target_key,
                    markdown_download_attempts=markdown_download_attempts,
                    report_card_readiness=report_card_readiness,
                    snapshot=snap.serializable(),
                )
                return False
            return self._accept_extracted_content(
                content,
                request,
                result,
                f'Perplexity response extracted via {target.name!r} ({len(content)} chars)',
                target_key=target_key,
                scrolled_into_view=scrolled_into_view,
                document_scrolled=document_scrolled,
                target_refreshed=refreshed,
                markdown_download_attempts=markdown_download_attempts,
                report_card_readiness=report_card_readiness,
                **clipboard_poll,
            )

        if is_deep_research:
            markdown_download_attempts.append({
                'fallback_after_target_key': target_key,
                'fallback_reason': 'empty_clipboard',
                'deep_research_render_shape': (
                    'copy_button_empty_clipboard_after_copy_contents_timeout'
                    if target_key == 'copy_button'
                    else 'copy_contents_empty_clipboard'
                ),
            })
        if is_deep_research and self._extract_via_markdown_download(
            request,
            result,
            markdown_download_attempts,
        ):
            return True

        result.add_step(
            'extract_primary', False,
            f'Perplexity copy target clicked but clipboard empty (button: {target.name!r})',
            stop_condition='extraction_failed',
            target_key=target_key,
            scrolled_into_view=scrolled_into_view,
            document_scrolled=document_scrolled,
            target_refreshed=refreshed,
            clicked=bool(clicked),
            markdown_download_attempts=markdown_download_attempts,
            report_card_readiness=report_card_readiness,
            **clipboard_poll,
            snapshot=snap.serializable(),
        )
        return False

    def extract_additional(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        snap = self.runtime.snapshot()
        copy_contents = self.find_first(snap, 'copy_contents_button')

        if self._is_deep_research(request):
            result.add_step(
                'extract_additional', True,
                'Perplexity Deep Research report already captured by extract_primary',
            )
            return True

        if not copy_contents:
            result.add_step(
                'extract_additional', False,
                'Perplexity copy_contents_button not found',
                snapshot=snap.serializable(),
            )
            return False

        self.runtime.write_clipboard('')
        time.sleep(0.2)

        if not self.runtime.click(copy_contents):
            result.add_step(
                'extract_additional', False,
                'Perplexity copy_contents_button click failed',
                snapshot=snap.serializable(),
            )
            return False
        content, clipboard_poll = self._read_clipboard_until_nonempty()
        if content:
            result.extractions.append(
                ExtractedArtifact(
                    name='perplexity_full_contents.md',
                    content=content,
                    kind='report_export',
                    metadata={'source': 'copy_contents_button'},
                )
            )
            result.add_step(
                'extract_additional', True,
                'Perplexity full contents copied via copy_contents_button',
                characters=len(content),
                preview=content[:200],
                **clipboard_poll,
            )
            return True

        result.add_step(
            'extract_additional', False,
            'Perplexity copy_contents_button clicked but clipboard empty',
            **clipboard_poll,
        )
        return False

    # ------------------------------------------------------------------
    # Neo4j storage
    # ------------------------------------------------------------------

    def store_in_neo4j(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
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
            label='Perplexity',
        )
