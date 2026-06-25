from __future__ import annotations

import logging
import os
import time
from typing import Optional

from consultation_v2.completion import COMPLETE, CompletionDetector
from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import (
    ConsultationRequest,
    ConsultationResult,
    ElementRef,
    ExtractedArtifact,
    Snapshot,
)

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


logger = logging.getLogger(__name__)


class ChatGPTConsultationDriver(BaseConsultationDriver):
    platform = 'chatgpt'
    _RESPONSE_TEXT_ROLES = {
        'heading',
        'label',
        'link',
        'list item',
        'paragraph',
        'section',
        'static',
        'table cell',
        'text',
    }

    # run() is the shared two-phase template on BaseConsultationDriver (FLOW §10):
    # it holds the DISPLAY-scoped dispatch lock across setup_and_send (below) and
    # releases it before monitor_and_extract so monitoring runs concurrently.

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): navigate → clean composer → mode → attach →
        prompt → guarded send + monitor registration."""
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        cleaned_before_ready = False
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
            if not request.session_url:
                if not self.clean_composer(request, result):
                    return False
                cleaned_before_ready = True
            if not self.wait_for_page_ready_after_navigation(result):
                return False
        if not self.tree_conformance_gate(result):
            return False

        if not cleaned_before_ready and not self.clean_composer(request, result):
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

    def _complete_keys(self) -> tuple[str, ...]:
        monitor_cfg = self.cfg.get('workflow', {}).get('monitor', {}) or {}
        extract_cfg = self.cfg.get('workflow', {}).get('extract', {}) or {}
        keys = monitor_cfg.get('complete_keys') or extract_cfg.get('primary_key') or ['copy_button']
        keys = keys if isinstance(keys, list) else [keys]
        return tuple(str(key) for key in keys if isinstance(key, str) and key)

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

    @staticmethod
    def _element_y(element: ElementRef) -> int | None:
        return int(element.y) if element.y is not None else None

    def _bottom_action_row_y(
        self,
        snapshot: Snapshot,
        action_keys: tuple[str, ...],
    ) -> int | None:
        items = [
            item
            for key in action_keys
            for item in ((snapshot.mapped or {}).get(key) or [])
            if item.y is not None
        ]
        if not items:
            return None
        return max(self._element_y(item) or 0 for item in items)

    def _complete_signal_present(
        self,
        snapshot: Snapshot,
        complete_keys: tuple[str, ...],
        generation_floor_y: int | None,
    ) -> tuple[bool, int | None]:
        row_y = self._bottom_action_row_y(snapshot, complete_keys)
        if row_y is None:
            return False, None
        if generation_floor_y is not None and row_y <= generation_floor_y + 8:
            return False, row_y
        return True, row_y

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
        evidence: dict[str, object] = {
            'ok': False,
            'source': 'bounded_composer_ancestor',
            'input_node': self._element_evidence(input_node),
            'input_rect': self._screen_rect(input_node.atspi_obj) if input_node else None,
        }
        if input_node is None or input_node.atspi_obj is None:
            evidence['reason'] = 'composer_input_missing'
            return None, evidence

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
        fresh_focus = self._focus_composer()
        if fresh_focus is None:
            result.add_step('clean_composer', False,
                            'ChatGPT fresh composer not focusable after New chat shortcut',
                            focus_node=self._element_evidence(initial_focus),
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

        def _empty_fresh_composer():
            snap = self.runtime.snapshot()
            if self._bottommost_input(snap) and not self.snapshot_has_any(snap, self._send_button_keys()):
                return snap
            return None

        verify_snap = self.runtime.wait_until(_empty_fresh_composer, timeout=5.0, interval=0.4)
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
            )
            return False
        result.add_step('clean_composer', True,
                        'ChatGPT forced clean fresh chat via New chat shortcut',
                        shortcut='ctrl+shift+o',
                        focus_node=self._element_evidence(fresh_focus),
                        snapshot=verify_snap.serializable())
        return True

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
            if not self._click(trigger):
                result.add_step('attach', False, f'ChatGPT attach trigger click failed for {abs_path}', snapshot=snap.serializable())
                return False

            attachment = self.cfg.get('workflow', {}).get('attachment', {}) or {}
            upload_key = str(attachment.get('menu_target') or 'tool_upload')
            portal_snap, upload_item = self.wait_for_key(
                upload_key,
                timeout=10.0,
                interval=0.4,
                scope='menu',
            )
            if not upload_item:
                result.add_step('attach', False, f'ChatGPT upload item {upload_key!r} not found for {abs_path}', snapshot=portal_snap.serializable())
                return False
            clicked = self._click(upload_item)
            if not clicked:
                result.add_step('attach', False, f'ChatGPT upload item click failed for {abs_path}', snapshot=portal_snap.serializable())
                return False
            time.sleep(0.8)
            if not self.runtime.focus_file_dialog():
                result.add_step('attach', False, f'ChatGPT file dialog did not focus for {abs_path}', snapshot=portal_snap.serializable())
                return False
            if not self.runtime.press('ctrl+l'):
                result.add_step('attach', False, f'ChatGPT file dialog location shortcut failed for {abs_path}', snapshot=portal_snap.serializable())
                return False
            time.sleep(0.2)
            if not self.runtime.paste(abs_path):
                result.add_step('attach', False, f'ChatGPT file dialog path paste failed for {abs_path}', snapshot=portal_snap.serializable())
                return False
            time.sleep(0.2)
            if not self.runtime.focus_file_dialog():
                result.add_step('attach', False, f'ChatGPT file dialog lost focus before submit for {abs_path}', snapshot=portal_snap.serializable())
                return False
            # ONE Return is sufficient: selects the file and closes the GTK dialog.
            # A second Return would hit the now-focused chat input and submit garbage.
            if not self.runtime.press('Return'):
                result.add_step('attach', False, f'ChatGPT file dialog submit failed for {abs_path}', snapshot=portal_snap.serializable())
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
        verified = bool(pasted)
        result.add_step('prompt', verified, 'ChatGPT prompt entered', snapshot=verify_snap.serializable())
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
        ready = bool(
            send_button
            and send_button.x is not None
            and send_button.y is not None
            and 'enabled' in states
        )
        return send_key, send_button, {
            'phase': 'send_button_ready',
            'send_key': send_key,
            'send_button': self._element_evidence(send_button),
            'states': sorted(states),
            'ready': ready,
            'has_coordinates': bool(send_button and send_button.x is not None and send_button.y is not None),
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
        complete_keys = self._complete_keys()
        self._generating_complete_row_y = None
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
            if stop_seen:
                self._generating_complete_row_y = self._bottom_action_row_y(
                    send_snap,
                    complete_keys,
                )
            answer_url = self._wait_for_answer_thread_url(
                timeout=30.0 if stop_seen else 5.0,
            )
            after = answer_url or self.runtime.wait_for_url_change(
                before,
                timeout=5.0,
                interval=1.0,
            )
            result.session_url_after = after or self.runtime.current_url() or before
            url_changed = bool(result.session_url_after and result.session_url_after != before)
            answer_thread = bool(self._is_answer_thread_url(result.session_url_after))
            url_landed = bool(answer_thread and (url_changed or request.session_url))
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
        detector = CompletionDetector(mode=detector_mode)
        detector.required_stop_cycles = max(
            detector.required_stop_cycles,
            self._minimum_stop_gone_cycles(),
        )
        stop_keys = self._stop_keys()
        complete_keys = self._complete_keys()
        completed = False
        observed_stop = False
        intermediate_failed = False
        answer_thread_lost = False
        intermediate_actions: dict[str, int] = {}
        terminal_snapshot: Snapshot | None = None
        stop_gone_without_complete_signal = 0
        generation_floor_y = getattr(self, '_generating_complete_row_y', None)
        complete_signal_y: int | None = None
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

        def _confirm_completion_quiet_window() -> tuple[Snapshot | None, int | None, str]:
            nonlocal observed_stop, intermediate_failed, generation_floor_y
            last_snapshot: Snapshot | None = None
            last_signal_y: int | None = None
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
                    row_y = self._bottom_action_row_y(snap, complete_keys)
                    if row_y is not None:
                        generation_floor_y = max(generation_floor_y or row_y, row_y)
                    _record_completion_quiet_sample({
                        'cycle': cycle,
                        'stop_present': True,
                        'complete_signal_present': False,
                        'reason': 'stop_reappeared',
                    })
                    return None, None, 'stop_reappeared'

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
                        'complete_signal_present': False,
                        'reason': reason,
                    })
                    return None, None, reason

                complete_signal_present, signal_y = self._complete_signal_present(
                    snap,
                    complete_keys,
                    generation_floor_y,
                )
                _record_completion_quiet_sample({
                    'cycle': cycle,
                    'stop_present': False,
                    'complete_signal_present': bool(complete_signal_present),
                    'complete_signal_y': signal_y,
                    'reason': 'quiet' if complete_signal_present else 'complete_signal_missing',
                })
                if not complete_signal_present:
                    return None, None, 'complete_signal_missing'
                last_snapshot = snap
                last_signal_y = signal_y
            return last_snapshot, last_signal_y, 'quiet'

        def _poll() -> bool:
            nonlocal completed, observed_stop, intermediate_failed, answer_thread_lost, terminal_snapshot
            nonlocal stop_gone_without_complete_signal, generation_floor_y, complete_signal_y
            _thread_ok, thread_lost, thread_restored = self._reassert_monitor_answer_thread(
                result,
                answer_url_predicate=self._is_answer_thread_url,
            )
            if thread_lost:
                answer_thread_lost = True
                return True
            if thread_restored:
                return False
            stop_present, snap, stop_reading = self._read_stop_state(
                stop_keys,
                confirm_absence=detector.ever_seen_stop or observed_stop,
            )
            _record_stop_reading(stop_reading)
            observed_stop = observed_stop or stop_present
            if stop_present:
                row_y = self._bottom_action_row_y(snap, complete_keys)
                if row_y is not None:
                    generation_floor_y = max(generation_floor_y or row_y, row_y)
            handled, failed = self._handle_monitor_intermediate_state(
                snap,
                result,
                intermediate_actions,
            )
            if handled:
                self._reset_detector_after_intermediate(detector)
                intermediate_failed = failed
                return bool(failed)
            complete_signal_present, signal_y = self._complete_signal_present(
                snap,
                complete_keys,
                generation_floor_y,
            )
            verdict = detector.observe(stop_present=stop_present)
            if verdict == COMPLETE and complete_signal_present:
                quiet_snapshot, quiet_signal_y, quiet_reason = _confirm_completion_quiet_window()
                if quiet_snapshot is not None:
                    completed = True
                    terminal_snapshot = quiet_snapshot
                    complete_signal_y = quiet_signal_y
                    return True
                _record_completion_quiet_reset(quiet_reason)
                return False
            if verdict == COMPLETE:
                stop_gone_without_complete_signal += 1
            return False

        def _verified_stop_absent_snapshot() -> Snapshot | None:
            stop_present, snap, stop_reading = self._read_stop_state(
                stop_keys,
                confirm_absence=True,
            )
            _record_stop_reading(stop_reading)
            if stop_present:
                return None
            if not self._complete_signal_present(snap, complete_keys, generation_floor_y)[0]:
                return None
            return snap

        self.runtime.wait_until(_poll, timeout=float(request.timeout), interval=1.0)
        verify_snap = terminal_snapshot or self.runtime.wait_until(
            _verified_stop_absent_snapshot,
            timeout=5.0,
            interval=0.5,
        ) or self.runtime.snapshot()
        if answer_thread_lost:
            result.add_step(
                'monitor',
                False,
                'ChatGPT answer_thread_lost: monitor could not restore pinned answer thread',
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
        complete_signal_seen, final_signal_y = self._complete_signal_present(
            verify_snap,
            complete_keys,
            generation_floor_y,
        )
        complete_signal_y = complete_signal_y if complete_signal_y is not None else final_signal_y
        verified = bool(completed and stop_absent and complete_signal_seen)
        monitor_message = (
            'ChatGPT response completed'
            if verified else
            'ChatGPT response did not reach Stop-gone completion'
        )
        result.add_step(
            'monitor',
            verified,
            monitor_message,
            stop_seen=observed_stop,
            mode=detector_mode or 'default',
            stop_keys=stop_keys,
            complete_keys=complete_keys,
            complete_signal_seen=complete_signal_seen,
            complete_signal_y=complete_signal_y,
            generation_action_row_floor_y=generation_floor_y,
            intermediate_actions=intermediate_actions,
            stop_gone_cycles=detector.stop_cycles,
            required_stop_gone_cycles=detector.required_stop_cycles,
            post_complete_quiet_cycles=post_complete_quiet_cycles,
            completion_quiet_resets=completion_quiet_resets,
            completion_quiet_samples=completion_quiet_samples,
            stop_gone_without_complete_signal=stop_gone_without_complete_signal,
            stop_read_samples=stop_read_samples,
            last_stop_reading=last_stop_reading,
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

    def _wait_for_answer_thread_url(self, *, timeout: float = 12.0) -> str | None:
        def _current_answer_url() -> str | None:
            current = (self.runtime.current_url() or '').strip()
            return current if self._is_answer_thread_url(current) else None

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
        from consultation_v2 import atspi as _atspi

        firefox = _atspi.find_firefox_for_platform(self.platform)
        return _atspi.get_platform_document(firefox, self.platform) if firefox else None

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

    @staticmethod
    def _assistant_message_hover_points(
        document_rect: dict,
        composer_y: int | None,
    ) -> list[dict]:
        doc_x = int(document_rect['x'])
        doc_y = int(document_rect['y'])
        doc_w = int(document_rect['width'])
        doc_h = int(document_rect['height'])
        doc_bottom = doc_y + doc_h
        response_floor = min(int(composer_y or doc_bottom), doc_bottom)
        min_y = doc_y + 120
        max_y = max(min_y, response_floor - 80)
        x_ratios = (0.34, 0.42, 0.50)
        y_specs = (
            ('response_band_076', int(doc_y + doc_h * 0.76)),
            ('composer_minus_140', response_floor - 140),
            ('composer_minus_220', response_floor - 220),
            ('response_band_070', int(doc_y + doc_h * 0.70)),
            ('composer_minus_300', response_floor - 300),
            ('response_band_062', int(doc_y + doc_h * 0.62)),
            ('composer_minus_380', response_floor - 380),
        )
        points: list[dict] = []
        seen: set[tuple[int, int]] = set()
        for y_label, y in y_specs:
            if y < min_y or y > max_y:
                continue
            for x_ratio in x_ratios:
                x = int(doc_x + doc_w * x_ratio)
                key = (x, y)
                if key in seen:
                    continue
                seen.add(key)
                points.append({
                    'x': x,
                    'y': y,
                    'x_ratio': x_ratio,
                    'y_source': y_label,
                })
        return points

    def _hover_assistant_message_for_copy_button(self) -> dict:
        from consultation_v2 import input as _inp
        from consultation_v2.atspi import find_firefox_for_platform
        from consultation_v2.tree import find_elements as raw_find_elements

        evidence = {
            'ok': False,
            'source': 'assistant_message_hover_scan',
        }
        for _ in range(8):
            document = self._chatgpt_document()
            document_rect = self._screen_rect(document)
            if not document_rect:
                time.sleep(0.25)
                continue
            snap = self.runtime.snapshot()
            composer_anchor = (
                self.find_last(snap, 'input_chat_with_chatgpt')
                or self.find_last(snap, 'input_ask_anything')
                or self.find_first(snap, 'input')
            )
            composer_rect = self._screen_rect(composer_anchor.atspi_obj) if composer_anchor else None
            composer_y = int(composer_rect['y']) if composer_rect else None
            points = self._assistant_message_hover_points(document_rect, composer_y)
            attempts = []
            evidence.update({
                'document_rect': document_rect,
                'composer_anchor': composer_anchor.serializable() if composer_anchor else None,
                'composer_rect': composer_rect,
                'candidate_points': points[:12],
                'candidate_count': len(points),
            })
            for point in points:
                x = int(point['x'])
                y = int(point['y'])
                hover_ok = bool(_inp.hover(x, y))
                time.sleep(0.65)
                firefox = find_firefox_for_platform(self.platform)
                copy_buttons = (
                    self._copy_button_candidates(raw_find_elements(firefox, fence_after=[]))
                    if firefox else []
                )
                if not copy_buttons:
                    time.sleep(0.25)
                    firefox = find_firefox_for_platform(self.platform)
                    copy_buttons = (
                        self._copy_button_candidates(raw_find_elements(firefox, fence_after=[]))
                        if firefox else []
                    )
                attempt = {
                    'x': x,
                    'y': y,
                    'x_ratio': point['x_ratio'],
                    'y_source': point['y_source'],
                    'hover_ok': hover_ok,
                    'copy_buttons_found': len(copy_buttons),
                }
                attempts.append(attempt)
                if not (hover_ok and copy_buttons):
                    continue
                evidence.update({
                    **attempt,
                    'copy_buttons': [
                        {key: button.get(key) for key in ('name', 'role', 'x', 'y')}
                        for button in copy_buttons[-3:]
                    ],
                    'attempts': attempts,
                    'ok': True,
                })
                logger.warning(
                    'ChatGPT extract assistant-message hover probe: x=%s y=%s ok=%s '
                    'x_ratio=%s y_source=%s copy_buttons=%s',
                    x,
                    y,
                    evidence['ok'],
                    point['x_ratio'],
                    point['y_source'],
                    len(copy_buttons),
                )
                return evidence
            evidence['attempts'] = attempts
            logger.warning(
                'ChatGPT extract assistant-message hover probe failed: '
                'points=%s document_rect=%s composer_rect=%s',
                len(points),
                document_rect,
                composer_rect,
            )
            return evidence
        logger.warning('ChatGPT extract assistant-message hover probe: no document rect found')
        return evidence

    def _copy_button_names(self) -> tuple[str, ...]:
        extract_cfg = ((self.cfg.get('workflow') or {}).get('extract') or {})
        configured = extract_cfg.get('copy_button_names') or []
        configured = configured if isinstance(configured, list) else [configured]
        names = [
            str(name)
            for name in configured
            if isinstance(name, str) and name.strip()
        ]
        copy_spec = self.cfg.get('tree', {}).get('element_map', {}).get('copy_button', {})
        if isinstance(copy_spec, dict):
            if isinstance(copy_spec.get('name'), str):
                names.append(str(copy_spec['name']))
            names_any = copy_spec.get('names_any_of') or []
            if isinstance(names_any, list):
                names.extend(str(name) for name in names_any if isinstance(name, str) and name.strip())
        return tuple(dict.fromkeys(names))

    def _copy_button_candidates(
        self,
        elements: list[dict],
        copy_spec: dict | None = None,
    ) -> list[dict]:
        spec = copy_spec or self.cfg.get('tree', {}).get('element_map', {}).get('copy_button', {})
        copy_names = set(self._copy_button_names())
        candidates: list[dict] = []
        seen: set[tuple[object, ...]] = set()
        for element in elements:
            if element.get('y') is None:
                continue
            role = str(element.get('role') or '').strip().lower()
            name = str(element.get('name') or '').strip()
            matches_yaml = matches_spec(element, spec)
            matches_configured_copy = role in {'push button', 'button'} and name in copy_names
            if not (matches_yaml or matches_configured_copy):
                continue
            key = (name, role, element.get('x'), element.get('y'), id(element.get('atspi_obj')))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(element)
        return sorted(candidates, key=lambda element: int(element.get('y') or 0))

    def _response_action_panels(self, elements: list[dict]) -> list[dict]:
        spec = self.cfg.get('tree', {}).get('element_map', {}).get('response_actions_panel', {})
        return [
            element for element in elements
            if matches_spec(element, spec)
            and element.get('y') is not None
        ]

    def _user_message_action_panels(self, elements: list[dict]) -> list[dict]:
        spec = self.cfg.get('tree', {}).get('element_map', {}).get('user_message_actions_panel', {})
        return [
            element for element in elements
            if matches_spec(element, spec)
            and element.get('y') is not None
        ]

    @staticmethod
    def _element_tree_text(element: dict) -> str:
        direct = str(element.get('name') or element.get('text') or '').strip()
        if direct:
            return direct
        obj = element.get('atspi_obj')
        if obj is None:
            return ''
        try:
            text_iface = obj.get_text_iface()
            if not text_iface:
                return ''
            return (text_iface.get_text(0, text_iface.get_character_count()) or '').strip()
        except Exception:
            return ''

    @staticmethod
    def _dedupe_direct_text_segments(segments: list[str]) -> list[str]:
        deduped: list[str] = []
        normalized_seen: list[str] = []
        for segment in segments:
            text = segment.strip()
            normalized = ' '.join(text.split())
            if not normalized:
                continue
            if any(normalized == seen or normalized in seen for seen in normalized_seen):
                continue
            keep = [
                (existing, seen)
                for existing, seen in zip(deduped, normalized_seen)
                if seen not in normalized
            ]
            deduped = [existing for existing, _seen in keep]
            normalized_seen = [seen for _existing, seen in keep]
            deduped.append(text)
            normalized_seen.append(normalized)
        return deduped

    def _is_browser_chrome_garbage(self, content: str) -> bool:
        forbidden_markers = [
            "Expedia",
            "Temu",
            "Wikipedia",
            "Switch model",
            "Open context menu",
            "Address and search bar",
            "New Tab",
            "Customize Chrome",
            "Search with Google",
            "View site information",
            "Bookmarks Toolbar",
        ]
        text_lower = content.lower()
        for marker in forbidden_markers:
            if marker.lower() in text_lower:
                return True
        return False

    def _direct_response_text_from_tree(
        self,
        elements: list[dict],
        request: ConsultationRequest,
    ) -> dict:
        doc_element = next((e for e in elements if e.get('role') == 'document web'), None)
        chrome_y = int(doc_element.get('y') or 120) if doc_element else 120

        response_panels = [
            p for p in self._response_action_panels(elements)
            if int(p.get('y') or 0) > chrome_y
        ]
        if not response_panels:
            return {'ok': False, 'reason': 'response_actions_panel_not_found'}
        response_panel = max(response_panels, key=lambda element: int(element.get('y') or 0))
        response_y = int(response_panel.get('y') or 0)
        response_x = int(response_panel.get('x') or 0)
        min_content_x = max(0, response_x - 450)
        max_content_x = response_x + 550
        prior_response_y = max(
            [
                int(element.get('y') or 0)
                for element in response_panels
                if int(element.get('y') or 0) < response_y
            ],
            default=0,
        )
        user_message_panels = [
            u for u in self._user_message_action_panels(elements)
            if int(u.get('y') or 0) > chrome_y
        ]
        user_action_y = max(
            [
                int(element.get('y') or 0)
                for element in user_message_panels
                if int(element.get('y') or 0) < response_y
            ],
            default=0,
        )
        lower_bound_y = max(chrome_y, prior_response_y, user_action_y)
        candidates = [
            element for element in elements
            if lower_bound_y < int(element.get('y') or 0) < response_y
            and min_content_x <= int(element.get('x') or 0) <= max_content_x
            and str(element.get('role') or '').strip() in self._RESPONSE_TEXT_ROLES
        ]
        segments = self._dedupe_direct_text_segments([
            self._element_tree_text(element)
            for element in sorted(candidates, key=lambda item: (int(item.get('y') or 0), int(item.get('x') or 0)))
        ])
        content = '\n'.join(segments).strip()
        copy_buttons_found = len(self._copy_button_candidates(elements))
        evidence = {
            'ok': False,
            'source': 'direct_tree_text',
            'response_actions_y': response_y,
            'response_actions_x': response_x,
            'lower_bound_y': lower_bound_y,
            'min_content_x': min_content_x,
            'max_content_x': max_content_x,
            'text_candidates': len(candidates),
            'segments': len(segments),
            'response_actions_panels': len(response_panels),
            'user_message_action_panels': len(user_message_panels),
            'copy_buttons_found': copy_buttons_found,
        }
        if not content:
            evidence['reason'] = 'no_text_between_action_anchors'
            return evidence
        findings = self._response_content_findings(
            content,
            request,
            copy_buttons_found=copy_buttons_found,
        )
        if findings:
            evidence.update({
                'reason': 'invalid_response_content',
                'findings': findings,
                'characters': len(content),
                'preview': content[:200],
            })
            return evidence
        evidence.update({
            'ok': True,
            'characters': len(content),
            'preview': content[:200],
            'content': content,
        })
        return evidence

    def _response_content_findings(
        self,
        content: str,
        request: ConsultationRequest,
        *,
        copy_buttons_found: int = 0,
    ) -> list[str]:
        findings: list[str] = []
        stripped = (content or '').strip()
        if not stripped:
            return ['empty']
        normalized = self._normalized_text(stripped)
        lowered = normalized.lower()
        if len(stripped) <= len(request.message):
            findings.append('content_shorter_than_prompt')
        if self._is_browser_chrome_garbage(stripped):
            findings.append('contains_browser_chrome_garbage')
        if self._is_prompt_echo(stripped, request):
            findings.append('prompt_echo')
        first_chunk = lowered[:500]
        if (
            lowered.startswith('share | open conversation options')
            or lowered.startswith('share open conversation options')
            or ('open conversation options' in first_chunk and 'share' in first_chunk)
        ):
            findings.append('ui_chrome_extract')
        if copy_buttons_found >= 8 and len(stripped) < 2500:
            findings.append('thin_extract_with_many_copy_buttons')
        if copy_buttons_found >= 2 and self._looks_like_standalone_code_fragment(stripped):
            findings.append('standalone_code_fragment')
        return findings

    @staticmethod
    def _looks_like_standalone_code_fragment(content: str) -> bool:
        stripped = content.strip()
        if not stripped or '```' in stripped:
            return False
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if len(lines) < 5:
            return False
        code_prefixes = (
            'def ', 'class ', 'import ', 'from ', 'async ', 'await ', 'return ',
            'if ', 'elif ', 'else:', 'for ', 'while ', 'try:', 'except ', 'with ',
            'function ', 'const ', 'let ', 'var ', 'export ', 'public ', 'private ',
            '<', '{', '}', '#!', '@', 'package ', 'use ', 'namespace ',
        )
        code_markers = (' = ', ' == ', ' != ', ' <= ', ' >= ', '=>', '();', ');', ' {', '};')
        code_lines = 0
        prose_lines = 0
        for line in lines:
            lowered = line.lower()
            if lowered.startswith(code_prefixes) or any(marker in line for marker in code_markers):
                code_lines += 1
            words = [word for word in line.split() if word]
            if len(words) >= 8 and line.endswith(('.', '!', '?', ':')):
                prose_lines += 1
        return code_lines / max(1, len(lines)) >= 0.55 and prose_lines <= 1

    def extract_primary(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        from consultation_v2 import clipboard
        from consultation_v2.atspi import find_firefox_for_platform
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
        attempts: list[dict[str, object]] = []
        for attempt in range(5):
            time.sleep(1.0)
            last_scroll = self._scroll_chatgpt_thread_to_bottom()
            firefox = find_firefox_for_platform(self.platform)
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
            last_snapshot = self.runtime.snapshot()
            all_elements = raw_find_elements(firefox, fence_after=[])
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

            target = copy_buttons[-1]
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
            attempt_evidence = {
                'attempt': attempt + 1,
                'scroll': last_scroll,
                'copy_buttons_found': len(copy_buttons),
                'copy_button': copy_button,
                'button_scrolled_to_anywhere': bool(scrolled_button),
                'clicked': bool(clicked),
                'characters': len(content),
                'preview': content[:200],
                'exact_prompt_echo': exact_prompt_echo,
            }
            attempts.append(attempt_evidence)
            if not clicked or not content or exact_prompt_echo:
                continue
            result.response_text = content
            result.add_step(
                'extract_primary',
                True,
                f'ChatGPT response copied from Copy response button ({len(content)} chars, attempt {attempt + 1})',
                source='chatgpt_copy_response_simple',
                **attempt_evidence,
            )
            return True

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
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step('store', True, 'ChatGPT Neo4j storage skipped', storage=result.storage)
            return True
        try:
            session_url = result.session_url_after or result.session_url_before or self.runtime.current_url() or ''
            session_id = neo4j_client.get_or_create_session(self.platform, session_url)
            user_message_id = neo4j_client.add_message(session_id, 'user', request.message, request.attachments)
            assistant_message_id = neo4j_client.add_message(session_id, 'assistant', result.response_text, self.serialize_artifacts(result.extractions))
            result.storage = {
                'session_id': session_id,
                'user_message_id': user_message_id,
                'assistant_message_id': assistant_message_id,
                'url': session_url,
            }
            result.add_step('store', True, 'ChatGPT response stored in Neo4j', storage=result.storage)
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step('store', False, f'ChatGPT Neo4j storage failed: {exc}')
            return False
