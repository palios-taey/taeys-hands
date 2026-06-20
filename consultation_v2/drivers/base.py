from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, List, Optional, Tuple

from consultation_v2.completion import (
    COMPLETE,
    CompletionDetector,
)
from consultation_v2 import primitives
from consultation_v2.planner import SelectionPlanError, build_selection_plan, has_selection_menus
from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, ExtractedArtifact, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


class BaseConsultationDriver(ABC):
    platform: str

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
            dismissed = self.runtime.close_all_popups()
            recovered_snap = self._conformance_snapshot(surface)
            recovered_discrepancies, recovered_missing, recovered_by_role = (
                self._conformance_findings(recovered_snap, surface)
            )
            if not recovered_discrepancies and not recovered_missing:
                result.add_step(
                    'popup_recovery',
                    True,
                    f'{self.platform} cleared transient popup drift on {surface or "unscoped"}',
                    surface=surface,
                    dismissed=dismissed,
                    before_unknown=discrepancies,
                    snapshot=recovered_snap.serializable(),
                )
                return True
            snap = recovered_snap
            discrepancies = recovered_discrepancies
            missing = recovered_missing
            by_role = recovered_by_role
            if dismissed:
                result.add_step(
                    'popup_recovery',
                    False,
                    f'{self.platform} popup recovery ran but conformance drift persisted',
                    surface=surface,
                    dismissed=dismissed,
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
        discrepancies = [
            {'role': item.role, 'name': item.name}
            for item in (snapshot.unknown or [])
        ]
        missing = self._missing_expected_elements(snapshot, surface)
        by_role: dict[str, int] = {}
        for item in discrepancies:
            role = item['role'] or ''
            by_role[role] = by_role.get(role, 0) + 1
        return discrepancies, missing, by_role

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

    def _missing_expected_elements(self, snapshot: Snapshot, surface: str | None) -> list[dict[str, object]]:
        element_map = (self.cfg.get('tree') or {}).get('element_map') or {}
        missing: list[dict[str, object]] = []
        for key in self._expected_keys_for_surface(surface):
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
        path = list(step.get('path') or [])
        first_key = str(path[0]['element']) if path else target_key

        opened = self._open_selection_menu(trigger_key, first_key, scope, result)
        if opened is None:
            return False
        snapshot, _ = opened
        target_snapshot, target = self._walk_selection_path(snapshot, path, target_key, scope, result)
        if target is None:
            return False
        active_state = str(step['active_recognition'])
        if self._selection_element_has_state(target, active_state):
            self.runtime.press('Escape')
            result.add_step(
                'select',
                True,
                f'{self.platform} {menu}={option} already active',
                menu=menu,
                option=option,
                active_state=active_state,
                snapshot=target_snapshot.serializable(),
            )
            return True
        if not self.runtime.click(target, strategy='atspi_only'):
            result.add_step(
                'select',
                False,
                f'{self.platform} {menu}={option} click failed',
                menu=menu,
                option=option,
                snapshot=target_snapshot.serializable(),
            )
            return False
        time.sleep(0.3)
        self.runtime.press('Escape')
        persistent_snapshot, persistent_verified, persistent_labels = (
            self._selection_persistent_trigger_matches(trigger_key, option, target)
        )
        if persistent_verified:
            result.add_step(
                'select',
                True,
                f'{self.platform} selected {menu}={option}',
                menu=menu,
                option=option,
                active_state=active_state,
                confirmation='persistent_trigger_label',
                expected_labels=sorted(persistent_labels),
                snapshot=persistent_snapshot.serializable(),
            )
            return True
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
        if int(menu_snapshot.raw_count or 0) > 0:
            result.add_step(
                'select',
                False,
                f'{self.platform} selection menu surface still open before trigger',
                snapshot=menu_snapshot.serializable(),
            )
            return False
        anchor_key = self._selection_base_anchor_key()
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
        return not (snapshot.unknown or []) and not self._missing_expected_elements(snapshot, 'base')

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

    def _selection_wait_for_revealed_anchor(self, key: str, scope: str) -> tuple[Snapshot, ElementRef | None]:
        timeout = max(self._selection_settle_seconds() + 1.0, 3.0)
        snapshot = self._selection_stable_snapshot(
            scope,
            timeout=timeout,
            anchor_key=key,
        )
        return snapshot, self.find_first(snapshot, key)

    def _activate_selection_path_element(self, element: ElementRef, action: str) -> bool:
        normalized = action.strip().lower()
        if normalized == 'hover':
            return self.runtime.hover(element)
        if normalized in {'press', 'click'}:
            return self.runtime.click(element, strategy='atspi_only')
        return False

    def _selection_find_once(self, key: str, scope: str) -> tuple[Snapshot, ElementRef | None]:
        return self._selection_wait_for_revealed_anchor(key, scope)

    def _selection_snapshot(self, scope: str) -> Snapshot:
        normalized = scope.strip().lower()
        if normalized == 'menu_snapshot':
            return self.runtime.menu_snapshot()
        if normalized == 'snapshot':
            return self.runtime.snapshot()
        raise ValueError(f'Unknown selection snapshot scope {scope!r}')

    def _selection_settle_seconds(self) -> float:
        settle = self.cfg.get('settle') or {}
        value = settle.get('default_ms', 800) if isinstance(settle, dict) else 800
        try:
            return max(0.0, float(value) / 1000.0)
        except (TypeError, ValueError):
            return 0.8

    def _selection_element_has_state(self, element: ElementRef, state: str) -> bool:
        expected = state.strip().lower()
        return expected in {str(item).lower() for item in (element.states or [])}

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
            if last_target is not None and self._selection_element_has_state(last_target, active_state):
                return last_snapshot, last_target, True
            time.sleep(0.2)
        if last_snapshot is None:
            last_snapshot = self._selection_snapshot(scope)
            last_target = self.find_first(last_snapshot, target_key)
        return last_snapshot, last_target, False

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
        if normalized == 'snapshot':
            return self.runtime.wait_for_stable_snapshot(
                consecutive=2,
                timeout=timeout,
                interval=0.2,
                anchor_key=anchor_key,
                require_non_empty=True,
            )
        raise ValueError(f'Unknown selection snapshot scope {scope!r}')

    def _selection_persistent_trigger_matches(
        self,
        trigger_key: str,
        option: str,
        selected_target: ElementRef,
    ) -> tuple[Snapshot, bool, set[str]]:
        labels = self._selection_persistent_labels(option, selected_target)
        if trigger_key != 'model_selector' or not labels:
            snapshot = self.runtime.snapshot()
            return snapshot, False, labels
        timeout = self._selection_settle_seconds()
        deadline = time.time() + timeout
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            last_snapshot = self.runtime.wait_for_stable_snapshot(
                consecutive=2,
                timeout=min(remaining, 0.8),
                interval=0.2,
                require_non_empty=True,
            )
            trigger = self.find_first(last_snapshot, trigger_key)
            if trigger is not None and trigger.name.strip() in labels:
                return last_snapshot, True, labels
            time.sleep(0.2)
        return last_snapshot or self.runtime.snapshot(), False, labels

    def _selection_persistent_labels(self, option: str, selected_target: ElementRef) -> set[str]:
        labels = {selected_target.name.strip()} if selected_target.name and selected_target.name.strip() else set()
        if option:
            labels.add(' '.join(part.capitalize() for part in option.split('_') if part))
        return labels

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

    def acquire_display_lock(self, payload: Optional[dict] = None, ttl: int = 3600) -> str | None:
        return primitives.acquire_display_lock(payload=payload, ttl=ttl)

    def release_display_lock(self, owner_token: str | None) -> bool:
        return primitives.release_display_lock(owner_token)

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
        return os.environ.get('DISPLAY', ':0')

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
        payload = {
            'platform': self.platform,
            'display': self._display(),
            'request_id': request.request_id(),
            'locked_at': datetime.now(timezone.utc).isoformat(),
        }
        owner_token = primitives.acquire_display_lock(payload=payload)
        try:
            yield bool(owner_token)
        finally:
            if owner_token:
                primitives.release_display_lock(owner_token)

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
        if self._is_unresumable_landed_send(prior, request):
            if not self._invalidate_unresumable_landed_send(prior, request, result):
                return False

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
    def _normalized_text(text: str) -> str:
        return ' '.join((text or '').split())

    def _is_prompt_echo(self, content: str, request: ConsultationRequest) -> bool:
        content_norm = self._normalized_text(content)
        prompt_norm = self._normalized_text(request.message)
        if len(content_norm) < 80 or not prompt_norm:
            return False
        if content_norm == prompt_norm:
            return True
        if content_norm in prompt_norm and len(content_norm) >= 160:
            return True
        if prompt_norm in content_norm and len(content_norm) <= int(len(prompt_norm) * 1.25):
            return True
        if len(prompt_norm) >= 120 and content_norm.startswith(prompt_norm[:120]):
            return True
        return False

    @staticmethod
    def _urls_equivalent(left: str | None, right: str | None) -> bool:
        return (left or '').strip().rstrip('/') == (right or '').strip().rstrip('/')

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

        ``seed_stop_seen`` lets a driver whose send step already observed the
        stop button mark ever_seen_stop up front, so a sub-second generation
        whose stop button was only visible during send still completes (it is an
        OBSERVATION carried forward, not a content fallback).
        """
        detector_mode = (
            (mode if mode is not None else getattr(request, 'mode', None)) or ''
        ).strip().lower()
        detector = CompletionDetector(mode=detector_mode)
        if seed_stop_seen:
            detector.ever_seen_stop = True
            detector.stop_was_visible = True
        stop_key = self._stop_key()
        completed = False

        def _poll() -> bool:
            nonlocal completed
            snap = self.runtime.snapshot()
            verdict = detector.observe(stop_present=snap.has(stop_key))
            if verdict == COMPLETE:
                completed = True
                return True
            return False

        self.runtime.wait_until(_poll, timeout=float(request.timeout), interval=1.0)
        verify_snap = self.wait_for_validation(
            'response_complete',
            timeout=5.0,
            interval=0.5,
        )
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
