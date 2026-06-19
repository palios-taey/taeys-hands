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
        displayed_file = display_name.split()[0] if display_name else ''
        for expected in (expected_path, expected_name):
            if display_name == expected or displayed_file == expected:
                return True
            if '...' in displayed_file:
                prefix, suffix = displayed_file.split('...', 1)
                if expected.startswith(prefix) and expected.endswith(suffix):
                    return True
        return False

    def _attachment_visible(self, snapshot: Snapshot, filename: str) -> bool:
        all_elements = []
        for items in getattr(snapshot, 'mapped', {}).values():
            all_elements.extend(items)
        all_elements.extend(getattr(snapshot, 'unknown', []) or [])
        all_elements.extend(getattr(snapshot, 'sidebar', []) or [])
        all_elements.extend(getattr(snapshot, 'menu_items', []) or [])
        allowed_roles = {'push button', 'list item', 'heading'}
        return any(
            element.role in allowed_roles
            and self._attachment_name_matches(element.name or '', filename)
            for element in all_elements
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
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Claude tab')
            return False
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(
                target_url,
                verify_change=bool(urls.get('verify_navigation')),
            )
            snap = self.runtime.snapshot()
            result.add_step(
                'navigate', navigated, 'Navigated to Claude session target',
                target_url=target_url, snapshot=snap.serializable(),
            )
            if not navigated:
                return False
        if not self.tree_conformance_gate(result):
            return False
        if not self.apply_selection_plan(request, result):
            return False
        if not self.attach_files(request, result):
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
    # Attach files
    # ------------------------------------------------------------------

    def attach_files(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        self.runtime.close_stale_dialogs()
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            toggle_menu = self.find_first(snap, 'toggle_menu')
            if not toggle_menu:
                result.add_step('attach', False,
                                f'Claude toggle menu missing for {abs_path}',
                                snapshot=snap.serializable())
                return False
            if not self.runtime.click(toggle_menu):
                result.add_step('attach', False,
                                f'Claude toggle menu click failed for {abs_path}',
                                snapshot=snap.serializable())
                return False
            menu_snap = self.runtime.wait_for_stable_menu_snapshot(
                consecutive=2,
                timeout=8,
                interval=0.4,
                anchor_key='upload_files_item',
                require_non_empty=True,
            )
            upload_item = self.find_first(menu_snap, 'upload_files_item')
            if not upload_item:
                result.add_step('attach', False,
                                f'Claude upload item not found for {abs_path}',
                                snapshot=menu_snap.serializable())
                return False
            if not self.runtime.click(upload_item):
                result.add_step('attach', False,
                                f'Claude upload item click failed for {abs_path}',
                                snapshot=menu_snap.serializable())
                return False
            time.sleep(1.0)
            self.runtime.focus_file_dialog()
            self.runtime.press('ctrl+l')
            time.sleep(0.3)
            if not self.runtime.paste(abs_path):
                self.runtime.type_text(abs_path, delay_ms=5)
            time.sleep(0.3)
            self.runtime.press('Return')
            verify_snap = self._wait_for_attach_success(abs_path)
            verified = self._attachment_visible(verify_snap, abs_path)
            result.add_step('attach', verified,
                            f'Claude attached {os.path.basename(abs_path)}',
                            file=abs_path, snapshot=verify_snap.serializable())
            if not verified:
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Claude attachments requested')
        return True

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
        send_snap = self.runtime.wait_until(
            lambda: (
                snap if self.snapshot_has_any(snap := self.runtime.snapshot(), stop_keys) else None
            ),
            timeout=30,
            interval=0.6,
        ) or self.runtime.snapshot()
        stop_seen = self.snapshot_has_any(send_snap, stop_keys)
        # Carry the send-phase stop observation into the shared completion
        # detector: a sub-second Extended Thinking reply may only show the stop
        # button during send, so seeding ever_seen_stop lets it complete on the
        # stop-gone transition without a content/copy-button fallback.
        self._send_stop_seen = bool(stop_seen)
        after = self.runtime.wait_for_url_change(before, timeout=30.0, interval=1.0)
        result.session_url_after = after or self.runtime.current_url()
        verify_snap = self.runtime.snapshot()
        url_changed = result.session_url_after and result.session_url_after != before
        is_new_session = not request.session_url
        if is_new_session:
            verified = bool(clicked and stop_seen and url_changed)
        else:
            verified = bool(clicked and stop_seen and result.session_url_after)
        result.add_step(
            'send', verified, 'Claude send validated by Stop button and URL capture',
            url_before=before, url_after=result.session_url_after,
            stop_seen=stop_seen, url_changed=bool(url_changed),
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
        if seed_stop_seen:
            detector.ever_seen_stop = True
            detector.stop_was_visible = True
        stop_keys = self._stop_keys()
        completed = False
        terminal_snapshot: Snapshot | None = None
        continue_clicks = 0
        continue_click_failed = False
        self._claude_continue_clicks = 0

        def _poll() -> bool:
            nonlocal detector, completed, terminal_snapshot
            nonlocal continue_clicks, continue_click_failed
            snap = self.runtime.snapshot()
            stop_present = self.snapshot_has_any(snap, stop_keys)
            verdict = detector.observe(stop_present=stop_present)
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
                    detector.ever_seen_stop = True
                    detector.stop_was_visible = True
                return False

            if not self.snapshot_has_any(continue_snap, stop_keys):
                completed = True
                terminal_snapshot = continue_snap
                return True
            return False

        self.runtime.wait_until(_poll, timeout=float(timeout or request.timeout), interval=1.0)
        verify_snap = terminal_snapshot or self.runtime.snapshot()
        stop_absent = not self.snapshot_has_any(verify_snap, stop_keys)
        continue_present = bool(verify_snap.has('continue_button'))
        verified = bool(
            completed
            and stop_absent
            and not continue_present
            and not continue_click_failed
        )
        result.add_step(
            step_name,
            verified,
            message,
            stop_seen=detector.ever_seen_stop,
            mode=detector_mode or 'default',
            stop_keys=stop_keys,
            stop_gone_cycles=detector.stop_cycles,
            continue_clicks=continue_clicks,
            continue_present=continue_present,
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
        from consultation_v2 import clipboard

        if not self.reassert_captured_session_url(
            result,
            answer_url_predicate=self._is_answer_thread_url,
        ):
            return False

        # Retry: scroll the conversation to the BOTTOM each pass, THEN scan.
        # The response's Copy button only enters the AT-SPI tree when on-screen;
        # on a long Claude answer it sits below the fold and is never found.
        # Scroll the document surface itself before every tree scan; do not use
        # the composer as the scroll anchor.
        all_el = []
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
                clipboard.write('')
                time.sleep(0.3)
                if not atspi_click(target):
                    continue
                time.sleep(1.5)
                segment = (clipboard.read() or '').strip()
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
                        elements=len(all_el) if all_el else 0)
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
        from consultation_v2 import clipboard

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
            expanded_snap = self.wait_for_key('hide_thinking', timeout=6.0, interval=0.4)
            hide_toggle = self.find_last(expanded_snap, 'hide_thinking')
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

        clipboard.write('')
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
        thinking_text = (clipboard.read() or '').strip()
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
