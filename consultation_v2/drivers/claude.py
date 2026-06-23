from __future__ import annotations

import os
import time

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


class ClaudeConsultationDriver(BaseConsultationDriver):
    platform = 'claude'
    _AUTO_CHIP_ROLES = {'push button', 'list item', 'heading'}
    _AUTO_CHIP_IGNORED_NAMES = {
        'Add files, connectors, and more',
        'Press and hold to record',
        'Send message',
        'Use voice mode',
        'Write your prompt to Claude',
    }
    _BLOCKED_SEND_KEYS = (
        'send_blocked_previous_message',
        'send_blocked_previous_message_curly',
        'send_blocked_caution_banner',
    )
    _LARGE_PACKET_SUBSTANCE_BYTES = 50_000
    _LARGE_PACKET_FAILURE_PHRASES = (
        'middle was truncated',
        'was truncated',
        'got truncated',
        'content was truncated',
        'large and the middle',
        "i don't have the full",
        'i do not have the full',
        "i can't access the attached",
        'i cannot access the attached',
        'unable to access the attached',
        "i can't read the attached",
        'i cannot read the attached',
        "i don't see the diff",
        'i do not see the diff',
        "can't find the actual",
        'cannot find the actual',
        "couldn't find the actual",
        'unable to find the actual',
        'not sure i can',
    )
    _AUDIT_REQUEST_TERMS = (
        'audit',
        'verdict',
        'review',
        'blocker',
        'finding',
        'defect',
        'diff',
        'gate',
        'validate',
        'validation',
        'proof',
        'counterexample',
    )
    _AUDIT_VERDICT_TERMS = (
        'verdict',
        'pass',
        'fail',
        'go',
        'no-go',
        'approved',
        'rejected',
        'blocker',
        'finding',
        'defect',
    )
    _AUDIT_GROUNDING_TERMS = (
        'observed',
        'inferred',
        'unknown',
        'evidence',
        'line',
        'diff',
        'code',
        'because',
        'marker',
        'chunk',
        'sha256',
        'begin',
        'middle',
        'end',
    )

    @staticmethod
    def _snapshot_elements(snapshot: Snapshot) -> list[ElementRef]:
        all_elements: list[ElementRef] = []
        for items in getattr(snapshot, 'mapped', {}).values():
            all_elements.extend(items)
        all_elements.extend(getattr(snapshot, 'unknown', []) or [])
        all_elements.extend(getattr(snapshot, 'sidebar', []) or [])
        all_elements.extend(getattr(snapshot, 'menu_items', []) or [])
        return all_elements

    @classmethod
    def _is_incidental_base_unknown(cls, item: ElementRef) -> bool:
        if super()._is_incidental_base_unknown(item):
            return True
        name = (item.name or '').strip()
        role = (item.role or '').strip().lower()
        description = str(item.description or '').strip()
        if role == 'push button' and name.endswith('.md MD'):
            return True
        if role == 'push button' and name == 'Remove' and description.endswith('.md'):
            return True
        return False

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
            'content',
            'markdown',
            'package',
            'paste',
            'pasted',
            'text',
            'txt',
        )
        if any(term in lower_name for term in attachment_terms):
            return True
        if ',' in lower_name:
            size_terms = (' bytes', ' kb', ' mb', ' lines', ' words')
            return any(term in lower_name for term in size_terms)
        return False

    def _send_blockers(self, snapshot: Snapshot) -> list[str]:
        blockers = [
            key
            for key in self._BLOCKED_SEND_KEYS
            if snapshot.has(key)
        ]
        if snapshot.has('send_button'):
            blockers.append('composer_send_button_present')
        chip_names = sorted(self._paste_chip_names(
            snapshot,
            set(),
            elements=self._composer_scope_elements(snapshot),
        ))
        if chip_names:
            blockers.append('composer_paste_chip_present:' + ', '.join(chip_names[:3]))
        return blockers

    def _composer_scope_elements(self, snapshot: Snapshot) -> list[ElementRef]:
        root = self._composer_scope_root(snapshot)
        if root is None:
            return []
        return [
            element
            for element in self._snapshot_elements(snapshot)
            if self._element_descends_from(element, root)
        ]

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

    def _read_input_text(self) -> str:
        snapshot = self.runtime.snapshot()
        input_el = self.find_first(snapshot, 'input')
        if not input_el or not input_el.atspi_obj:
            return ''
        try:
            text_iface = input_el.atspi_obj.get_text_iface()
            if text_iface:
                return text_iface.get_text(0, -1) or ''
        except Exception:
            pass
        try:
            value_iface = input_el.atspi_obj.get_value_iface()
            if value_iface is not None:
                value = value_iface.get_current_value()
                return '' if value is None else str(value)
        except Exception:
            pass
        return ''

    def _prompt_text_status(self, message: str) -> tuple[int, bool]:
        live_text = self._read_input_text()
        landed_chars = len(live_text)
        expected = len(message)
        if expected <= 0:
            return landed_chars, True
        slack = max(20, int(expected * 0.01))
        min_chars = max(0, expected - slack)
        normalized_message = ' '.join(message.split())
        normalized_live = ' '.join(live_text.split())
        prefix_matches = not normalized_message or normalized_live.startswith(normalized_message[:30])
        return landed_chars, landed_chars >= min_chars and prefix_matches

    @staticmethod
    def _attachment_name_matches(display_name: str, filename: str) -> bool:
        expected_path = os.path.abspath(filename)
        expected_name = os.path.basename(filename)
        display_name = (display_name or '').strip()
        displayed = {display_name}
        if display_name:
            displayed.add(display_name.split()[0].rstrip(','))
            displayed.add(display_name.split(',', 1)[0].strip())
        for expected in (expected_path, expected_name):
            for displayed_file in displayed:
                if displayed_file == expected:
                    return True
                if '...' in displayed_file:
                    prefix, suffix = displayed_file.split('...', 1)
                    if expected.startswith(prefix) and expected.endswith(suffix):
                        return True
        return False

    def _attachment_visible(self, snapshot: Snapshot, filename: str) -> bool:
        return self._attachment_chip_name(snapshot, filename) is not None

    def _attachment_chip_name(self, snapshot: Snapshot, filename: str) -> str | None:
        allowed_roles = {'push button', 'list item', 'heading'}
        return next(
            (
                element.name
                for element in self._snapshot_elements(snapshot)
                if element.role in allowed_roles
                and self._attachment_name_matches(element.name or '', filename)
            ),
            None,
        )

    def _stop_keys(self) -> tuple[str, ...]:
        monitor_cfg = self.cfg.get('workflow', {}).get('monitor', {}) or {}
        keys = monitor_cfg.get('stop_keys') or monitor_cfg.get('stop_key') or ['stop_button']
        keys = keys if isinstance(keys, list) else [keys]
        return tuple(str(key) for key in keys if isinstance(key, str) and key)

    # run() is the shared two-phase template on BaseConsultationDriver (FLOW §10):
    # it holds the DISPLAY-scoped dispatch lock across setup_and_send (below) and
    # releases it before monitor_and_extract so monitoring runs concurrently.

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): navigate → mode → attach → prompt →
        guarded send + monitor registration."""
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or self._fresh_url_with_nonce(urls.get('fresh'))
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Claude tab')
            return False
        result.session_url_before = self.runtime.current_url()
        if target_url:
            if request.session_url:
                navigated = self.runtime.navigate(
                    target_url,
                    verify_change=bool(urls.get('verify_navigation')),
                )
            else:
                navigated = self._navigate_fresh_with_new_tab(target_url)
            snap = self.runtime.snapshot()
            clean_navigation = self._navigation_snapshot_clean(snap)
            navigated = bool(navigated and clean_navigation)
            result.add_step(
                'navigate', navigated, 'Navigated to Claude session target',
                target_url=target_url,
                clean_navigation=clean_navigation,
                snapshot=snap.serializable(),
            )
            if not navigated:
                return False
            if not self.wait_for_page_ready_after_navigation(result):
                return False
        if not self.tree_conformance_gate(result):
            return False
        pre_attach_for_research = 'research' in request.selection_list('tools')
        if pre_attach_for_research:
            if not self._disable_research_mode_before_attach(result):
                return False
            if not self.attach_files(request, result):
                return False
        if not self.apply_selection_plan(request, result):
            return False
        if not pre_attach_for_research and not self.attach_files(request, result):
            return False
        if not self.enter_prompt(request, result):
            return False
        # Idempotent send seam (FLOW §8): guarded_send reads durable run-state
        # first and RESUMES a landed send instead of re-sending; otherwise it
        # performs the real send via self.send_prompt and checkpoints submitted.
        if not self.guarded_send(request, result):
            return False
        return True

    @staticmethod
    def _fresh_url_with_nonce(url: str | None) -> str | None:
        if not url:
            return None
        separator = '&' if '?' in url else '?'
        return f'{url}{separator}taey_fresh={int(time.time() * 1000)}'

    def _navigate_fresh_with_new_tab(self, target_url: str) -> bool:
        before = self.runtime.current_url()
        self.runtime.close_stale_dialogs()
        if not self.runtime.focus_firefox():
            return False
        time.sleep(0.2)
        if not self.runtime.press('ctrl+t'):
            return False
        time.sleep(0.4)
        if not self.runtime.focus_address_bar():
            return False
        if not self.runtime.press('ctrl+a'):
            return False
        time.sleep(0.1)
        if not self.runtime.paste(target_url):
            return False
        time.sleep(0.2)
        if not self.runtime.press('Return'):
            return False
        self.runtime.wait_for_url_change(before, timeout=20.0, interval=0.5)
        current = (self.runtime.current_url() or '').strip()
        if not self._url_matches_target(current, target_url):
            return False
        if not self._close_previous_tab_after_new_tab(target_url):
            return False
        self.runtime.press('Escape')
        time.sleep(0.4)
        return True

    def _close_previous_tab_after_new_tab(self, target_url: str) -> bool:
        if not self.runtime.press('ctrl+shift+Tab'):
            return False
        time.sleep(0.2)
        if not self.runtime.press('ctrl+w'):
            return False
        time.sleep(0.8)
        current = (self.runtime.current_url() or '').strip()
        return self._url_matches_target(current, target_url)

    @staticmethod
    def _url_matches_target(current_url: str, target_url: str) -> bool:
        current = (current_url or '').strip().rstrip('/').lower()
        target = (target_url or '').strip().rstrip('/').lower()
        if not current or not target:
            return False
        if current == target:
            return True
        return any(current.startswith(target + sep) for sep in ('?', '#', '/'))

    def _navigation_snapshot_clean(self, snapshot: Snapshot) -> bool:
        chrome_names = {
            'search with google or enter address',
            'redirecting',
            'wikipedia',
            'youtube',
            'reddit',
        }
        for element in self._snapshot_elements(snapshot):
            name = ' '.join((element.name or '').strip().lower().split())
            if not name:
                continue
            if name in chrome_names:
                return False
            if name.endswith('— wikipedia.org') or name.endswith('— youtube.com') or name.endswith('— reddit.com'):
                return False
        return True

    def _disable_research_mode_before_attach(self, result: ConsultationResult) -> bool:
        snapshot = self.runtime.snapshot()
        research_mode = self.find_first(snapshot, 'research_mode')
        if research_mode is None or not self.element_is_active(snapshot, 'research_mode'):
            return True
        if not self.runtime.click(research_mode):
            result.add_step(
                'attach_prepare',
                False,
                'Claude stale Research mode toggle click failed before attachment',
                snapshot=snapshot.serializable(),
            )
            return False
        settled = self.runtime.wait_until(
            lambda: (
                snap if not self.element_is_active(snap := self.runtime.snapshot(), 'research_mode') else None
            ),
            timeout=5.0,
            interval=0.4,
        )
        if isinstance(settled, Snapshot):
            result.add_step(
                'attach_prepare',
                True,
                'Claude disabled stale Research mode before attachment',
                snapshot=settled.serializable(),
            )
            return True
        final_snapshot = self.runtime.snapshot()
        result.add_step(
            'attach_prepare',
            False,
            'Claude stale Research mode stayed active before attachment',
            snapshot=final_snapshot.serializable(),
        )
        return False

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
        if not self.large_packet_substance_gate(request, result):
            return
        if not self.store_in_neo4j(request, result):
            return
        result.ok = True

    def large_packet_substance_gate(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        sizes: dict[str, int] = {}
        errors: list[str] = []
        for attachment in request.attachments:
            try:
                sizes[attachment] = os.path.getsize(attachment)
            except OSError as exc:
                errors.append(f'{attachment}: {exc}')
        if errors:
            result.add_step(
                'substance_gate',
                False,
                'Claude could not stat attachment(s) for large-packet substance gate',
                errors=errors,
            )
            return False

        total_bytes = sum(sizes.values())
        if total_bytes < self._LARGE_PACKET_SUBSTANCE_BYTES:
            return True

        body = self._response_body_without_thinking(result.response_text)
        normalized_body = self._normalized_text(body)
        normalized_lower = normalized_body.lower()
        failure_phrases = [
            phrase for phrase in self._LARGE_PACKET_FAILURE_PHRASES
            if phrase in normalized_lower
        ]
        body_chars = len(normalized_body)
        has_verdict_term = self._contains_any_term(
            normalized_lower, self._AUDIT_VERDICT_TERMS
        )
        has_grounding_term = self._contains_any_term(
            normalized_lower, self._AUDIT_GROUNDING_TERMS
        )
        has_substantive_large_packet_body = (
            body_chars >= 1500
            and has_verdict_term
            and has_grounding_term
        )
        findings: list[str] = []
        if not normalized_body:
            findings.append('empty assistant body')
        if self._is_prompt_echo(body, request):
            findings.append('assistant body is prompt echo')
        if failure_phrases and not has_substantive_large_packet_body:
            findings.append(
                'large-packet access/truncation uncertainty: '
                + ', '.join(failure_phrases[:5])
            )
        if self._request_requires_audit_substance(request):
            if body_chars < 120:
                findings.append('audit-like large-packet response is too short')
            if not has_verdict_term:
                findings.append('audit-like large-packet response has no verdict term')
            if not has_grounding_term:
                findings.append('audit-like large-packet response has no grounding term')

        if findings:
            result.add_step(
                'substance_gate',
                False,
                'Claude large-packet response failed substance gate',
                attachment_bytes=total_bytes,
                attachment_sizes=sizes,
                findings=findings,
                failure_phrases=failure_phrases[:5],
                response_body_chars=body_chars,
                has_verdict_term=has_verdict_term,
                has_grounding_term=has_grounding_term,
                preview=body[:500],
            )
            return False

        result.add_step(
            'substance_gate',
            True,
            'Claude large-packet response passed substance gate',
            attachment_bytes=total_bytes,
            attachment_sizes=sizes,
            failure_phrases=failure_phrases[:5],
            response_body_chars=body_chars,
            has_verdict_term=has_verdict_term,
            has_grounding_term=has_grounding_term,
        )
        return True

    @staticmethod
    def _response_body_without_thinking(text: str) -> str:
        content = text or ''
        start = content.find('<thinking>')
        end = content.find('</thinking>')
        if start != -1 and end != -1 and end > start:
            return (content[:start] + content[end + len('</thinking>'):]).strip()
        return content.strip()

    def _request_requires_audit_substance(self, request: ConsultationRequest) -> bool:
        request_text = self._normalized_text(
            ' '.join([
                request.message or '',
                request.purpose or '',
                request.session_type or '',
            ])
        ).lower()
        return self._contains_any_term(request_text, self._AUDIT_REQUEST_TERMS)

    @staticmethod
    def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
        normalized = ''.join(
            char if char.isalnum() or char in {'-', '_'} else ' '
            for char in text.lower()
        )
        padded = f' {normalized} '
        for term in terms:
            if f' {term} ' in padded:
                return True
            if term in {'marker', 'sha256'} and term in normalized:
                return True
            if term in {'begin', 'middle', 'end'} and (
                f'{term}_' in normalized or f'{term}-' in normalized
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # Attach files
    # ------------------------------------------------------------------

    def attach_files(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        self.runtime.close_stale_dialogs()
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            if not self._attach_file_via_dialog(abs_path, result):
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Claude attachments requested')
        return True

    def _attach_file_via_dialog(
        self,
        abs_path: str,
        result: ConsultationResult,
    ) -> bool:
        attachment_cfg = self.cfg.get('workflow', {}).get('attachment', {}) or {}
        trigger_key = str(attachment_cfg.get('trigger') or 'toggle_menu')
        trigger_strategy = str(attachment_cfg.get('trigger_click_strategy') or self.cfg.get('click_strategy') or 'atspi_first')
        upload_key = str(attachment_cfg.get('menu_target') or 'upload_files_item')
        self.runtime.focus_firefox()
        self.runtime.press('Escape')
        time.sleep(0.2)
        snap = self.runtime.snapshot()
        toggle_menu = self.find_first(snap, trigger_key)
        if not toggle_menu:
            result.add_step('attach', False,
                            f'Claude attach trigger {trigger_key!r} missing for {abs_path}',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.click(toggle_menu, strategy=trigger_strategy):
            result.add_step('attach', False,
                            f'Claude attach trigger {trigger_key!r} click failed for {abs_path}',
                            snapshot=snap.serializable())
            return False
        menu_snap, upload_item = self._wait_for_upload_menu_item(upload_key)
        if not upload_item:
            result.add_step('attach', False,
                            f'Claude upload item {upload_key!r} not found for {abs_path}',
                            snapshot=menu_snap.serializable())
            return False
        if not self.runtime.click(upload_item):
            result.add_step('attach', False,
                            f'Claude upload item {upload_key!r} click failed for {abs_path}',
                            snapshot=menu_snap.serializable())
            return False
        dialog_open = 'menu_item'
        time.sleep(1.0)
        if not self.runtime.focus_file_dialog():
            shortcut = str(attachment_cfg.get('keyboard_shortcut') or '').strip()
            if shortcut:
                self.runtime.focus_firefox()
                time.sleep(0.2)
                if self.runtime.press(shortcut):
                    time.sleep(1.0)
                    if self.runtime.focus_file_dialog():
                        dialog_open = 'keyboard_shortcut'
            if dialog_open != 'keyboard_shortcut':
                result.add_step('attach', False,
                                f'Claude file dialog did not focus for {abs_path}',
                                file=abs_path,
                                dialog_open=dialog_open,
                                keyboard_shortcut=shortcut or None)
                return False
        if dialog_open == 'keyboard_shortcut':
            result.add_step(
                'attach_prepare',
                True,
                'Claude opened file dialog with attachment keyboard shortcut fallback',
                shortcut=shortcut,
            )
        if not self.runtime.focus_file_dialog():
            result.add_step('attach', False,
                            f'Claude file dialog did not focus for {abs_path}',
                            file=abs_path,
                            dialog_open=dialog_open)
            return False
        if not self.runtime.press('ctrl+l'):
            result.add_step('attach', False,
                            f'Claude file dialog location shortcut failed for {abs_path}',
                            file=abs_path)
            return False
        time.sleep(0.3)
        if not self.runtime.press('ctrl+a'):
            result.add_step('attach', False,
                            f'Claude file dialog path select-all failed for {abs_path}',
                            file=abs_path,
                            dialog_open=dialog_open)
            return False
        time.sleep(0.1)
        if not self.runtime.type_text(abs_path, delay_ms=5):
            result.add_step('attach', False,
                            f'Claude file dialog path typing failed for {abs_path}',
                            file=abs_path)
            return False
        time.sleep(0.3)
        if not self.runtime.focus_file_dialog():
            result.add_step('attach', False,
                            f'Claude file dialog lost focus before submit for {abs_path}',
                            file=abs_path)
            return False
        if not self.runtime.press('Return'):
            result.add_step('attach', False,
                            f'Claude file dialog Return submit failed for {abs_path}',
                            file=abs_path)
            return False
        verify_snap = self._wait_for_attach_success(abs_path)
        chip_name = self._attachment_chip_name(verify_snap, abs_path)
        verified = chip_name is not None
        result.add_step('attach', verified,
                        f'Claude attached {os.path.basename(abs_path)}',
                        file=abs_path,
                        method='file_upload_dialog',
                        trigger=trigger_key,
                        trigger_click_strategy=trigger_strategy,
                        menu_target=upload_key,
                        dialog_open=dialog_open,
                        dialog_submit='return',
                        chip_name=chip_name,
                        snapshot=verify_snap.serializable())
        return verified

    def _wait_for_upload_menu_item(self, upload_key: str) -> tuple[Snapshot, ElementRef | None]:
        deadline = time.time() + 12.0
        last_snapshot: Snapshot | None = None
        while time.time() < deadline:
            for snapshot in (
                self.runtime.menu_snapshot(),
                self.runtime.snapshot(),
                self.runtime.app_root_snapshot(),
            ):
                last_snapshot = snapshot
                upload_item = self.find_first(snapshot, upload_key)
                if upload_item is not None:
                    return snapshot, upload_item
            time.sleep(0.3)
        return last_snapshot or self.runtime.menu_snapshot(), None

    def _wait_for_attach_success(self, abs_path: str):
        last_snapshot = None

        def _probe():
            nonlocal last_snapshot
            for snapshot in (self.runtime.snapshot(), self.runtime.menu_snapshot()):
                last_snapshot = snapshot
                if self._attachment_visible(snapshot, abs_path):
                    return snapshot
            return None

        matched = self.runtime.wait_until(_probe, timeout=20.0, interval=0.5)
        if isinstance(matched, Snapshot):
            return matched
        return last_snapshot or self.runtime.snapshot()

    # ------------------------------------------------------------------
    # Enter prompt
    # ------------------------------------------------------------------

    def enter_prompt(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, 'input')
        if not input_el:
            result.add_step('prompt', False, 'Claude input field not found',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.click(input_el):
            result.add_step('prompt', False, 'Claude input focus click failed',
                            snapshot=snap.serializable())
            return False
        time.sleep(0.3)
        pasted = self.runtime.paste(request.message)
        verify_snap = self.runtime.wait_until(
            lambda: (
                snap if (snap := self.runtime.snapshot()).has('send_button') else None
            ),
            timeout=8.0,
            interval=0.4,
        ) or self.runtime.snapshot()
        # The "Send message" button only appears once the composer holds content,
        # so prompt_ready is the reliable "text landed" signal. Do NOT gate on a
        # char-count read of the composer: Claude's React contenteditable does
        # not report its text reliably over AT-SPI, which false-negatived a paste
        # that DID land and triggered a type_text fallback that DOUBLED the prompt
        # (production-observed). One paste + Send-button-present is the contract.
        prompt_ready = verify_snap.has('send_button')
        landed_chars, _ = self._prompt_text_status(request.message)
        verified = bool(pasted and prompt_ready)
        result.add_step('prompt', verified, 'Claude prompt entered',
                        landed_chars=landed_chars, expected_chars=len(request.message),
                        snapshot=verify_snap.serializable())
        return verified

    # ------------------------------------------------------------------
    # Send prompt
    # ------------------------------------------------------------------

    def send_prompt(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        # Use the pre-navigation baseline captured in run() — file attachment
        # can change the URL before send, making current_url() stale.
        before = result.session_url_before
        snap = self.runtime.snapshot()
        send_button = self.find_first(snap, 'send_button')
        if not send_button:
            result.add_step('send', False, 'Claude send button not found',
                            snapshot=snap.serializable())
            return False
        clicked = self.runtime.click(send_button)
        stop_keys = self._stop_keys()
        stop_seen = False
        last_send_snapshot: Snapshot | None = None

        def _send_observation() -> Snapshot | None:
            nonlocal stop_seen, last_send_snapshot
            last_send_snapshot = self.runtime.snapshot()
            if self.snapshot_has_any(last_send_snapshot, stop_keys):
                stop_seen = True
            blockers = self._send_blockers(last_send_snapshot)
            if any(blocker in self._BLOCKED_SEND_KEYS for blocker in blockers):
                return last_send_snapshot
            if stop_seen and not blockers:
                return last_send_snapshot
            return None

        send_snap = self.runtime.wait_until(
            _send_observation,
            timeout=30,
            interval=0.6,
        ) or last_send_snapshot or self.runtime.snapshot()
        stop_seen = stop_seen or self.snapshot_has_any(send_snap, stop_keys)
        send_blockers = self._send_blockers(send_snap)
        after = self.runtime.wait_for_url_change(before, timeout=30.0, interval=1.0)
        result.session_url_after = after or self.runtime.current_url()
        verify_snap = self.runtime.snapshot()
        verify_blockers = self._send_blockers(verify_snap)
        if verify_blockers:
            send_blockers = verify_blockers
        message_landed = bool(stop_seen and not send_blockers)
        self._send_stop_seen = bool(message_landed)
        url_changed = result.session_url_after and result.session_url_after != before
        answer_thread = self._is_answer_thread_url(result.session_url_after)
        is_new_session = not request.session_url
        if is_new_session:
            verified = bool(clicked and message_landed and url_changed and answer_thread)
        else:
            verified = bool(clicked and message_landed and answer_thread)
        message = (
            'Claude send validated by Stop button, answer-thread URL, and cleared composer'
            if verified else
            'Claude send failed validation: user message did not land in thread'
        )
        result.add_step(
            'send', verified, message,
            url_before=before, url_after=result.session_url_after,
            stop_seen=stop_seen, message_landed=message_landed,
            send_blockers=send_blockers,
            url_changed=bool(url_changed), answer_thread=bool(answer_thread),
            snapshot=verify_snap.serializable(),
        )
        return verified

    # ------------------------------------------------------------------
    # Monitor generation — shared stop-transition detector plus Claude's
    # incomplete-response Continue affordance. Max/extended modes debounce
    # stop-gone in CompletionDetector; Continue is a Claude-scoped veto after
    # that detector says complete.
    # ------------------------------------------------------------------

    def monitor_generation(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        return self._monitor_completion_cycle(
            request,
            result,
            step_name='monitor',
            message='Claude response completed',
            seed_stop_seen=bool(getattr(self, '_send_stop_seen', False)),
            checkpoint=True,
        )

    def _monitor_completion_cycle(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        *,
        step_name: str,
        message: str,
        seed_stop_seen: bool = False,
        timeout: float | None = None,
        checkpoint: bool = False,
    ) -> bool:
        detector_mode = str(request.selection_value('mode', '') or '').strip().lower()
        detector = CompletionDetector(mode=detector_mode)
        stop_keys = self._stop_keys()
        completed = False
        observed_stop = bool(seed_stop_seen)
        if seed_stop_seen:
            detector.ever_seen_stop = True
            detector.stop_was_visible = True
        terminal_snapshot: Snapshot | None = None
        continue_clicks = 0
        continue_click_failed = False
        intermediate_failed = False
        answer_thread_lost = False
        intermediate_actions: dict[str, int] = {}
        self._claude_continue_clicks = 0

        def _poll() -> bool:
            nonlocal detector, completed, observed_stop, terminal_snapshot
            nonlocal continue_clicks, continue_click_failed
            nonlocal intermediate_failed, answer_thread_lost
            _thread_ok, thread_lost, thread_restored = self._reassert_monitor_answer_thread(
                result,
                step_name=step_name,
                answer_url_predicate=self._is_answer_thread_url,
            )
            if thread_lost:
                answer_thread_lost = True
                terminal_snapshot = self.runtime.snapshot()
                return True
            if thread_restored:
                return False
            snap = self.runtime.snapshot()
            stop_present = self.snapshot_has_any(snap, stop_keys)
            observed_stop = observed_stop or stop_present
            if stop_present:
                detector.observe(stop_present=True)
            handled, failed = self._handle_monitor_intermediate_state(
                snap,
                result,
                intermediate_actions,
                step_name=step_name,
            )
            if handled:
                self._reset_detector_after_intermediate(detector)
                intermediate_failed = failed
                terminal_snapshot = snap
                return bool(failed)
            if stop_present:
                return False
            verdict = detector.observe(stop_present=False)
            if verdict != COMPLETE:
                return False

            continue_snap, continue_button, scroll_ok = self._scan_for_continue_button()
            if continue_button:
                clicked = self.runtime.click(continue_button)
                continue_clicks += 1
                self._claude_continue_clicks = continue_clicks
                result.add_step(
                    f'{step_name}_continue',
                    clicked,
                    'Claude Continue affordance clicked; monitoring resumed',
                    continue_clicks=continue_clicks,
                    scroll_ok=scroll_ok,
                    continue_button=continue_button.serializable(),
                    snapshot=continue_snap.serializable(),
                )
                if not clicked:
                    continue_click_failed = True
                    terminal_snapshot = continue_snap
                    return True
                detector = CompletionDetector(mode=detector_mode)
                stop_snap = self.runtime.wait_until(
                    lambda: (
                        follow if self.snapshot_has_any(
                            follow := self.runtime.snapshot(),
                            stop_keys,
                        ) else None
                    ),
                    timeout=15.0,
                    interval=0.5,
                )
                if isinstance(stop_snap, Snapshot):
                    observed_stop = True
                    detector.ever_seen_stop = True
                    detector.stop_was_visible = True
                return False

            if not self.snapshot_has_any(continue_snap, stop_keys):
                if not self._monitor_response_rendered(continue_snap):
                    terminal_snapshot = continue_snap
                    return False
                completed = True
                terminal_snapshot = continue_snap
                return True
            return False

        self.runtime.wait_until(_poll, timeout=float(timeout or request.timeout), interval=1.0)
        verify_snap = terminal_snapshot or self.runtime.snapshot()
        if answer_thread_lost:
            result.add_step(
                step_name,
                False,
                'Claude answer_thread_lost: monitor could not restore pinned answer thread',
                stop_seen=observed_stop,
                seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode or 'default',
                stop_keys=stop_keys,
                stop_condition='answer_thread_lost',
                snapshot=verify_snap.serializable(),
            )
            return False
        if not observed_stop:
            result.add_step(
                step_name,
                False,
                'Claude monitor never observed Stop button after send',
                stop_seen=False,
                seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode or 'default',
                stop_keys=stop_keys,
                snapshot=verify_snap.serializable(),
            )
            return False
        if intermediate_failed:
            result.add_step(
                step_name,
                False,
                'Claude monitor failed while disposing intermediate state',
                stop_seen=observed_stop,
                seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode or 'default',
                stop_keys=stop_keys,
                intermediate_actions=intermediate_actions,
                snapshot=verify_snap.serializable(),
            )
            return False
        stop_absent = not self.snapshot_has_any(verify_snap, stop_keys)
        continue_present = bool(verify_snap.has('continue_button'))
        verified = bool(
            completed
            and stop_absent
            and not continue_present
            and not continue_click_failed
        )
        monitor_message = message if verified else 'Claude response did not reach Stop-gone completion'
        result.add_step(
            step_name,
            verified,
            monitor_message,
            stop_seen=observed_stop,
            seed_stop_seen=bool(seed_stop_seen),
            mode=detector_mode or 'default',
            stop_keys=stop_keys,
            stop_gone_cycles=detector.stop_cycles,
            continue_clicks=continue_clicks,
            continue_present=continue_present,
            response_rendered=self._monitor_response_rendered(verify_snap),
            snapshot=verify_snap.serializable(),
        )
        if verified and checkpoint:
            self.checkpoint_run_state(
                request,
                self.RUN_STATE_COMPLETION_OBSERVED,
                result=result,
                url=result.session_url_after or self.runtime.current_url() or '',
            )
        return verified

    def _monitor_response_rendered(self, snapshot: Snapshot) -> bool:
        return bool(snapshot.has('copy_button'))

    def _scan_for_continue_button(self) -> tuple[Snapshot, ElementRef | None, bool]:
        self.runtime.press('ctrl+End')
        time.sleep(0.2)
        scroll_ok = self.runtime.scroll_document_to_bottom(clicks=8, rounds=2, settle=0.4)
        snap = self.runtime.snapshot()
        return snap, self.find_last(snap, 'continue_button'), scroll_ok

    def _is_answer_thread_url(self, url: str | None) -> bool:
        return '/chat/' in (url or '')

    def is_resumable_session_url(self, url: str | None) -> bool:
        return self._is_answer_thread_url(url)

    # ------------------------------------------------------------------
    # Extract primary (copy-button strategy)
    # ------------------------------------------------------------------

    def extract_primary(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        from consultation_v2.atspi import find_firefox_for_platform
        from consultation_v2.tree import find_elements as raw_find_elements
        from consultation_v2.interact import atspi_click

        if not self.reassert_captured_session_url(
            result,
            answer_url_predicate=self._is_answer_thread_url,
        ):
            return False
        pre_extract_snapshot = self.runtime.snapshot()
        dismissed = self.runtime.close_all_popups(drift_controls=pre_extract_snapshot.unknown)
        if dismissed:
            result.add_step(
                'popup_recovery',
                True,
                'Claude cleared transient popup before extraction',
                dismissed=dismissed,
            )

        # Retry: scroll the conversation to the BOTTOM each pass, THEN scan.
        # The response's Copy button only enters the AT-SPI tree when on-screen;
        # on a long Claude answer it sits below the fold and is never found.
        # Scroll the document surface itself before every tree scan; do not use
        # the composer as the scroll anchor.
        all_el = []
        copy_buttons_seen = 0
        click_failures = 0
        empty_copies = 0
        for attempt in range(5):
            time.sleep(2.0)
            scroll_ok = self.runtime.scroll_document_to_bottom(clicks=14, rounds=3, settle=0.5)
            firefox = find_firefox_for_platform(self.platform)
            if not firefox:
                continue
            try:
                firefox.clear_cache_single()
            except Exception:
                pass
            all_el = raw_find_elements(firefox, fence_after=[])
            copy_btns = self._copy_button_candidates(all_el)
            copy_buttons_seen = max(copy_buttons_seen, len(copy_btns))
            # The response's Copy button is the LOWEST on the page (the latest
            # turn). Do NOT require >=2 (prompt Copy + response Copy): Claude
            # often renders only ONE Copy — the response's — because the user
            # prompt's Copy is hover-only / absent. Requiring 2 made extract
            # fail outright on a long verdict whose only Copy sat far below the
            # fold (production-observed: 21k-char audit, 1 Copy at doc-y 9762).
            # The content != request.message guard below rejects a prompt echo,
            # so taking the lowest Copy when >=1 is safe.
            if not copy_btns:
                continue
            continue_clicks = max(0, int(getattr(self, '_claude_continue_clicks', 0) or 0))
            targets = sorted(copy_btns, key=lambda e: e.get('y') or 0)[-(continue_clicks + 1):]
            copied = []
            for target in targets:
                self.runtime.write_clipboard('')
                time.sleep(0.3)
                self.runtime.scroll_element_into_view(ElementRef(
                    key=None,
                    name=str(target.get('name') or ''),
                    role=str(target.get('role') or ''),
                    x=target.get('x'),
                    y=target.get('y'),
                    states=list(target.get('states') or []),
                    atspi_obj=target.get('atspi_obj'),
                ))
                time.sleep(0.3)
                if not atspi_click(target):
                    click_failures += 1
                    continue
                time.sleep(2.5)
                segment = self.runtime.read_clipboard().strip()
                if segment and not self._is_prompt_echo(segment, request):
                    copied.append((segment, target))
                elif segment:
                    result.add_step(
                        'extract_primary_echo_rejected',
                        True,
                        'Claude copied prompt echo; continuing response-copy search',
                        characters=len(segment),
                        preview=segment[:200],
                        attempt=attempt + 1,
                        copy_button={k: target.get(k) for k in ('name', 'role', 'x', 'y')},
                    )
                else:
                    empty_copies += 1
            segments = self._dedupe_response_segments([segment for segment, _ in copied])
            if segments:
                content = '\n\n'.join(segments)
                target = copied[-1][1]
                result.response_text = content
                if not self.extract_thinking_notes(
                    request,
                    result,
                    response_text=content,
                    response_copy_y=target.get('y'),
                ):
                    return False
                result.add_step('extract_primary', True,
                                f'Claude response copied ({len(content)} chars, attempt {attempt+1})',
                                characters=len(content), preview=content[:200],
                                scroll_ok=scroll_ok,
                                copy_buttons_found=len(copy_btns),
                                copied_segments=len(segments),
                                continue_clicks=continue_clicks,
                                copy_button={k: target.get(k) for k in ('name', 'role', 'x', 'y')})
                return True

        result.add_step('extract_primary', False,
                        f'Claude extraction failed after 5 attempts',
                        elements=len(all_el) if all_el else 0,
                        copy_buttons_seen=copy_buttons_seen,
                        click_failures=click_failures,
                        empty_copies=empty_copies)
        return False

    def _copy_button_candidates(self, elements: list[dict]) -> list[dict]:
        copy_spec = self.cfg.get('tree', {}).get('element_map', {}).get('copy_button', {})
        return [
            element for element in elements
            if matches_spec(element, copy_spec)
            and element.get('y') is not None
        ]

    @staticmethod
    def _dedupe_response_segments(segments: list[str]) -> list[str]:
        deduped: list[str] = []
        for segment in segments:
            normalized = ' '.join(segment.split())
            if not normalized:
                continue
            if any(normalized == ' '.join(existing.split()) for existing in deduped):
                continue
            if any(normalized in ' '.join(existing.split()) for existing in deduped):
                continue
            deduped = [
                existing for existing in deduped
                if ' '.join(existing.split()) not in normalized
            ]
            deduped.append(segment)
        return deduped

    def extract_thinking_notes(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        response_text: str,
        response_copy_y: int | None,
    ) -> bool:
        """Capture Claude's separately-rendered thinking block when the UI
        exposes the mapped Show/Hide thinking control.

        Absence of the toggle is recorded as evidence and is not treated as a
        failure: non-thinking replies and accounts without visible thinking notes
        have nothing to capture. Once the toggle is present, every subsequent
        step is tree/clipboard validated and failures abort extraction.
        """
        from consultation_v2.atspi import find_firefox_for_platform
        from consultation_v2.tree import find_elements as raw_find_elements
        from consultation_v2.interact import atspi_click

        snap = self.runtime.snapshot()
        show_toggle = self.find_last(snap, 'show_thinking')
        hide_toggle = self.find_last(snap, 'hide_thinking')
        if not show_toggle and not hide_toggle:
            result.add_step(
                'extract_thinking',
                True,
                'Claude thinking toggle not visible; assistant response has no separate thinking block',
                snapshot=snap.serializable(),
            )
            return True

        if show_toggle:
            if not self.runtime.click(show_toggle):
                result.add_step(
                    'extract_thinking',
                    False,
                    'Claude Show thinking toggle click failed',
                    snapshot=snap.serializable(),
                )
                return False
            expanded_snap, hide_toggle = self.wait_for_key(
                'hide_thinking',
                timeout=6.0,
                interval=0.4,
                select='last',
            )
            if not hide_toggle:
                result.add_step(
                    'extract_thinking',
                    False,
                    'Claude thinking block did not expand to Hide thinking',
                    snapshot=expanded_snap.serializable(),
                )
                return False

        firefox = find_firefox_for_platform(self.platform)
        if not firefox:
            result.add_step('extract_thinking', False, 'Claude Firefox window not found for thinking extraction')
            return False
        try:
            firefox.clear_cache_single()
        except Exception:
            pass

        all_el = raw_find_elements(firefox, fence_after=[])
        thinking_copy = self._thinking_copy_button(
            all_el,
            toggle_y=hide_toggle.y,
            response_copy_y=response_copy_y,
        )
        if not thinking_copy:
            result.add_step(
                'extract_thinking',
                False,
                'Claude thinking Copy button not found between thinking toggle and response Copy',
                toggle=hide_toggle.serializable(),
                response_copy_y=response_copy_y,
            )
            return False

        self.runtime.write_clipboard('')
        time.sleep(0.3)
        if not atspi_click(thinking_copy):
            result.add_step(
                'extract_thinking',
                False,
                'Claude thinking Copy button action failed',
                copy_button={k: thinking_copy.get(k) for k in ('name', 'role', 'x', 'y')},
            )
            return False
        time.sleep(1.0)
        thinking_text = self.runtime.read_clipboard().strip()
        if not self._valid_thinking_text(thinking_text, response_text, request.message):
            result.add_step(
                'extract_thinking',
                False,
                'Claude thinking clipboard did not contain distinct thinking text',
                characters=len(thinking_text),
                preview=thinking_text[:200],
            )
            return False

        result.extractions.append(ExtractedArtifact(
            name='claude_thinking.md',
            content=thinking_text,
            kind='thinking_notes',
            metadata={'source': 'show_thinking_copy_button'},
        ))
        result.response_text = f'<thinking>\n{thinking_text}\n</thinking>\n\n{response_text}'
        result.add_step(
            'extract_thinking',
            True,
            f'Claude thinking notes copied ({len(thinking_text)} chars)',
            characters=len(thinking_text),
            preview=thinking_text[:200],
        )
        return True

    def _thinking_copy_button(
        self,
        elements: list[dict],
        toggle_y: int | None,
        response_copy_y: int | None,
    ) -> dict | None:
        if toggle_y is None:
            return None
        copy_spec = self.cfg.get('tree', {}).get('element_map', {}).get('copy_button', {})
        candidates = [
            element for element in elements
            if matches_spec(element, copy_spec)
            and element.get('y') is not None
        ]
        if response_copy_y is not None:
            candidates = [
                element for element in candidates
                if int(element.get('y') or 0) >= int(toggle_y)
                and int(element.get('y') or 0) < int(response_copy_y)
            ]
        else:
            candidates = [
                element for element in candidates
                if int(element.get('y') or 0) >= int(toggle_y)
            ]
        if not candidates:
            return None
        return min(candidates, key=lambda element: int(element.get('y') or 0) - int(toggle_y))

    def _valid_thinking_text(self, text: str, response_text: str, prompt_text: str) -> bool:
        if not text:
            return False
        normalized = ' '.join(text.split())
        normalized_response = ' '.join((response_text or '').split())
        normalized_prompt = ' '.join((prompt_text or '').split())
        if normalized == normalized_response:
            return False
        if normalized == normalized_prompt:
            return False
        if len(normalized_prompt) >= 60 and normalized.startswith(normalized_prompt[:60]):
            return False
        if len(normalized_response) >= 60 and normalized.startswith(normalized_response[:60]):
            return False
        return True

    # ------------------------------------------------------------------
    # Extract additional artifacts
    # ------------------------------------------------------------------

    def extract_additional(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        result.add_step(
            'extract_additional', True,
            'Claude artifact-specific extraction needs one live-label pass before enabling',
        )
        return True

    # ------------------------------------------------------------------
    # Store in Neo4j
    # ------------------------------------------------------------------

    def store_in_neo4j(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step('store', True, 'Claude Neo4j storage skipped',
                            storage=result.storage)
            return True
        try:
            session_url = (
                result.session_url_after
                or result.session_url_before
                or self.runtime.current_url()
                or ''
            )
            session_id = neo4j_client.get_or_create_session(self.platform, session_url)
            user_message_id = neo4j_client.add_message(
                session_id, 'user', request.message, request.attachments,
            )
            assistant_message_id = neo4j_client.add_message(
                session_id, 'assistant', result.response_text,
                self.serialize_artifacts(result.extractions),
            )
            result.storage = {
                'session_id': session_id,
                'user_message_id': user_message_id,
                'assistant_message_id': assistant_message_id,
                'url': session_url,
            }
            result.add_step('store', True, 'Claude response stored in Neo4j',
                            storage=result.storage)
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step('store', False, f'Claude Neo4j storage failed: {exc}')
            return False
