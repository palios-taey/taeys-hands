from __future__ import annotations

import os
import time
from urllib.parse import urlparse

from consultation_v2.completion import COMPLETE, DEEP_MODES, CompletionDetector
from consultation_v2.drivers.base import BaseConsultationDriver, DEEP_GENERATION_FLOOR_SECONDS
from consultation_v2.stop_conditions import is_stop_condition
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, Snapshot


GEMINI_DEEP_THINK_MIN_REAL_ANSWER_CHARS = 160
GEMINI_DEEP_THINK_INTERIM_MARKERS = (
    "i'm on it",
    "i’m on it",
    'responses with deep think can take some time',
    'deep think response in progress',
    'generating your response',
    'check back later',
)
GEMINI_DEEP_THINK_UI_TEXT = {
    'copy',
    'deep think',
    'deselect deep think',
    'microphone',
    'new chat',
    'send message',
    'share & export',
    'stop response',
    'upload & tools',
}


class GeminiConsultationDriver(BaseConsultationDriver):
    platform = 'gemini'

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
            result.add_step('navigate', False, 'Could not switch to Gemini tab')
            return False
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(
                target_url,
                verify_change=bool(urls.get('verify_navigation')),
            )
            snap = self.runtime.snapshot()
            result.add_step(
                'navigate', navigated, 'Navigated to Gemini session target',
                target_url=target_url, snapshot=snap.serializable(),
            )
            if not navigated:
                return False
            if not self.wait_for_page_ready_after_navigation(result):
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

    def attach_files(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        self.runtime.close_stale_dialogs()
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'upload_menu')
            if not trigger:
                result.add_step('attach', False,
                                f'Gemini upload menu trigger missing for {abs_path}',
                                snapshot=snap.serializable())
                return False
            open_attempts = []
            menu_snap = self.runtime.menu_snapshot()
            upload_item = self.find_first(menu_snap, 'upload_files_item')
            trigger_states = {str(state).lower() for state in (getattr(trigger, 'states', None) or [])}
            if not upload_item and 'expanded' not in trigger_states:
                clicked = self.runtime.click(trigger, strategy='atspi_first')
                open_attempts.append({'strategy': 'atspi_first', 'clicked': bool(clicked)})
                if not clicked:
                    result.add_step('attach', False,
                                    f'Gemini upload menu trigger click failed for {abs_path}',
                                    snapshot=snap.serializable())
                    return False
                menu_snap, upload_item = self.wait_for_key(
                    'upload_files_item',
                    timeout=5.0,
                    interval=0.4,
                    scope='menu',
                )
            if not upload_item:
                result.add_step('attach', False,
                                f'Gemini upload item not found for {abs_path}',
                                open_attempts=open_attempts,
                                menu=menu_snap.serializable())
                return False
            if not self.runtime.click(upload_item, strategy='atspi_first'):
                result.add_step('attach', False,
                                f'Gemini upload item click failed for {abs_path}',
                                menu=menu_snap.serializable())
                return False
            time.sleep(0.8)
            if not self.runtime.focus_file_dialog():
                result.add_step(
                    'attach', False,
                    f'Gemini file dialog did not focus for {abs_path}',
                    menu=menu_snap.serializable(),
                    open_attempts=open_attempts,
                )
                return False
            if not self.runtime.press('ctrl+l'):
                result.add_step(
                    'attach', False,
                    f'Gemini file dialog location shortcut failed for {abs_path}',
                    open_attempts=open_attempts,
                )
                return False
            time.sleep(0.2)
            if not self.runtime.press('ctrl+a'):
                result.add_step(
                    'attach', False,
                    f'Gemini file dialog select-all failed for {abs_path}',
                    open_attempts=open_attempts,
                )
                return False
            time.sleep(0.1)
            if not self.runtime.paste(abs_path):
                result.add_step(
                    'attach', False,
                    f'Gemini file dialog path paste failed for {abs_path}',
                    open_attempts=open_attempts,
                )
                return False
            time.sleep(0.2)
            # ONE Return is sufficient: selects the file and closes the GTK dialog.
            # A second Return would hit the now-focused chat input and submit garbage.
            if not self.runtime.focus_file_dialog():
                result.add_step(
                    'attach', False,
                    f'Gemini file dialog lost focus before submit for {abs_path}',
                    open_attempts=open_attempts,
                )
                return False
            if not self.runtime.press('Return'):
                result.add_step(
                    'attach', False,
                    f'Gemini file dialog submit failed for {abs_path}',
                    open_attempts=open_attempts,
                )
                return False
            verify_snap = self.wait_for_validation(
                'attach_success',
                filename=abs_path,
                timeout=15.0,
                interval=0.5,
            )
            verified = self.validation_passes(verify_snap, 'attach_success', filename=abs_path)
            result.add_step('attach', verified,
                            f'Gemini attached {os.path.basename(abs_path)}',
                            file=abs_path, open_attempts=open_attempts,
                            snapshot=verify_snap.serializable())
            if not verified:
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Gemini attachments requested')
        return True

    def enter_prompt(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, 'input')
        if not input_el:
            result.add_step('prompt', False, 'Gemini input field not found',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.click(input_el, strategy='atspi_first'):
            result.add_step('prompt', False, 'Gemini input focus click failed',
                            snapshot=snap.serializable())
            return False
        time.sleep(0.3)
        pasted = self.runtime.paste(request.message)
        verify_snap = self.wait_for_validation(
            'prompt_ready',
            timeout=8.0,
            interval=0.4,
        )
        verified = bool(pasted and self.validation_passes(verify_snap, 'prompt_ready'))
        result.add_step('prompt', verified, 'Gemini prompt entered',
                        snapshot=verify_snap.serializable())
        return verified

    def send_prompt(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        # Use the pre-navigation baseline captured in run() — file attachment
        # can change the URL before send, making current_url() stale.
        before = result.session_url_before
        snap = self.runtime.snapshot()
        send_button = self.find_first(snap, 'send_button')
        if not send_button:
            result.add_step('send', False, 'Gemini send button not found',
                            snapshot=snap.serializable())
            return False
        clicked = self.runtime.click(send_button, strategy='atspi_first')
        if not clicked:
            result.add_step(
                'send', False, 'Gemini send button click failed',
                snapshot=snap.serializable(),
            )
            return False
        post_send_clicked = False
        # Deep Research is a TWO-STEP flow: the submit first generates a research
        # PLAN (a stop_button shows during plan generation), THEN renders a plan
        # card with a "Start research" button that MUST be clicked to execute the
        # actual research. The button only appears AFTER the plan finishes, so we
        # wait for start_research itself (not merely the plan's stop_button) before
        # clicking — otherwise we extract the ~80-char plan echo instead of the
        # report. Generous timeout: plan generation can take ~1 min. Gated on the
        # deep_research mode so single-step modes (deep_think/normal/…) are
        # unaffected. (Jesse 2026-06-15: prior runs harvested only the plan.)
        is_dr_send = str(request.selection_value('mode', '') or '').strip().lower() == 'deep_research'
        if is_dr_send:
            start_button = self.runtime.wait_until(
                lambda: self.find_first(self.runtime.snapshot(), 'start_research'),
                timeout=180,
                interval=1.5,
            )
            if not start_button:
                result.add_step(
                    'send', False,
                    'Gemini Deep Research "Start research" never appeared after submit',
                    snapshot=self.runtime.snapshot().serializable(),
                )
                return False
            # Click via atspi_only (do_action): the React "Start research" button
            # no-ops under atspi_first in practice (p8 2026-06-21: start_research
            # returned clicked=True yet the research never started, so no stop
            # button appeared and send-validation false-failed). A direct AT-SPI
            # action reliably fires the research run.
            post_send_clicked = self.runtime.click(start_button, strategy='atspi_only')
            if not post_send_clicked:
                result.add_step(
                    'send', False, 'Gemini "Start research" click failed',
                    snapshot=self.runtime.snapshot().serializable(),
                )
                return False
            time.sleep(2.0)
        # Confirm the generation (the research run, for DR) actually started. DR
        # research spin-up can lag after Start research, so allow a generous window
        # for the research-phase stop button to appear.
        send_snap = self.wait_for_validation(
            'send_success', timeout=(60 if is_dr_send else 30), interval=0.6
        )
        stop_seen = self.validation_passes(send_snap, 'send_success')
        answer_url = self._wait_for_answer_thread_url(timeout=30.0)
        result.session_url_after = answer_url or self.runtime.current_url()
        verify_snap = self.runtime.snapshot()
        url_changed = result.session_url_after and result.session_url_after != before
        answer_thread = self._is_answer_thread_url(result.session_url_after)
        is_new_session = not request.session_url
        if is_new_session:
            verified = bool(clicked and stop_seen and url_changed and answer_thread)
        else:
            verified = bool(clicked and stop_seen and answer_thread)
        result.add_step(
            'send', verified,
            'Gemini send validated by Stop button and answer-thread URL capture',
            url_before=before,
            url_after=result.session_url_after,
            start_research_clicked=post_send_clicked,
            stop_seen=stop_seen,
            url_changed=bool(url_changed),
            answer_thread=bool(answer_thread),
            snapshot=verify_snap.serializable(),
        )
        return verified

    def _is_answer_thread_url(self, url: str | None) -> bool:
        parsed = urlparse((url or '').strip())
        if parsed.netloc and parsed.netloc != 'gemini.google.com':
            return False
        segments = [segment for segment in parsed.path.split('/') if segment]
        return len(segments) >= 2 and segments[0] == 'app' and bool(segments[1])

    def is_resumable_session_url(self, url: str | None) -> bool:
        return self._is_answer_thread_url(url)

    def _wait_for_answer_thread_url(self, *, timeout: float = 12.0) -> str | None:
        def _current_answer_url() -> str | None:
            current = (self.runtime.current_url() or '').strip()
            return current if self._is_answer_thread_url(current) else None

        found = self.runtime.wait_until(_current_answer_url, timeout=timeout, interval=0.5)
        return str(found) if found else None

    def monitor_generation(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        mode: str | None = None,
        seed_stop_seen: bool = False,
    ) -> bool:
        detector_mode = self._monitor_detector_mode(request, mode)
        if detector_mode != 'deep_think':
            return super().monitor_generation(
                request,
                result,
                mode=mode,
                seed_stop_seen=seed_stop_seen,
            )
        return self._monitor_deep_think_generation(
            request,
            result,
            detector_mode=detector_mode,
            seed_stop_seen=seed_stop_seen,
        )

    def _monitor_detector_mode(
        self,
        request: ConsultationRequest,
        mode: str | None = None,
    ) -> str:
        selected = mode if mode is not None else request.selection_value('mode', '')
        return str(selected or '').strip().lower()

    def _monitor_deep_think_generation(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
        *,
        detector_mode: str,
        seed_stop_seen: bool = False,
    ) -> bool:
        detector = CompletionDetector(mode=detector_mode)
        stop_key = self._stop_key()
        completed = False
        observed_stop = bool(seed_stop_seen)
        intermediate_failed = False
        answer_thread_lost = False
        intermediate_actions: dict[str, int] = {}
        terminal_snapshot: Snapshot | None = None
        interim_ack_seen = False
        post_ack_stop_seen = False
        interim_ack_blocking_cycles = 0
        terminal_answer_ready = False
        terminal_answer_evidence: dict[str, object] = {}

        def _poll() -> bool:
            nonlocal completed, observed_stop, intermediate_failed, answer_thread_lost, detector
            nonlocal terminal_snapshot, interim_ack_seen, post_ack_stop_seen, interim_ack_blocking_cycles
            nonlocal terminal_answer_ready, terminal_answer_evidence
            _thread_ok, thread_lost, thread_restored = self._reassert_monitor_answer_thread(
                result,
                answer_url_predicate=self._is_answer_thread_url,
            )
            if thread_lost:
                answer_thread_lost = True
                terminal_snapshot = self.runtime.snapshot()
                return True
            if thread_restored:
                return False
            snap = self.runtime.snapshot()
            stop_present = snap.has(stop_key)
            observed_stop = observed_stop or stop_present
            handled, failed = self._handle_monitor_intermediate_state(
                snap,
                result,
                intermediate_actions,
            )
            if handled:
                self._reset_detector_after_intermediate(detector)
                intermediate_failed = failed
                terminal_snapshot = snap
                return bool(failed)
            ack_absent, _ack_evidence = self._interim_ack_absent(snap)
            if not ack_absent:
                interim_ack_seen = True
                post_ack_stop_seen = False
                interim_ack_blocking_cycles += 1
                terminal_answer_ready = False
                detector = CompletionDetector(mode=detector_mode)
                return False
            if interim_ack_seen and not post_ack_stop_seen:
                if stop_present:
                    post_ack_stop_seen = True
                else:
                    interim_ack_blocking_cycles += 1
                    return False
            if stop_present:
                detector.observe(stop_present=True)
                return False
            verdict = detector.observe(stop_present=False)
            if verdict != COMPLETE:
                return False
            answer_ready, answer_evidence = self._deep_think_real_answer_evidence(snap, request)
            if not answer_ready:
                interim_ack_blocking_cycles += 1
                terminal_answer_ready = False
                terminal_answer_evidence = answer_evidence
                return False
            completed = True
            terminal_snapshot = snap
            terminal_answer_ready = True
            terminal_answer_evidence = answer_evidence
            return True

        effective_timeout = float(request.timeout)
        if detector_mode in DEEP_MODES:
            effective_timeout = max(effective_timeout, DEEP_GENERATION_FLOOR_SECONDS)
        self.runtime.wait_until(_poll, timeout=effective_timeout, interval=1.0)
        verify_snap = self.wait_for_validation(
            'response_complete',
            timeout=5.0,
            interval=0.5,
        )
        ack_absent, ack_evidence = self._interim_ack_absent(verify_snap)
        if not ack_absent:
            interim_ack_seen = True
        verify_answer_ready, verify_answer_evidence = self._deep_think_real_answer_evidence(
            verify_snap,
            request,
        )
        if not observed_stop:
            if answer_thread_lost:
                result.add_step(
                    'monitor', False,
                    'gemini answer_thread_lost: monitor could not restore pinned answer thread',
                    stop_seen=observed_stop, seed_stop_seen=bool(seed_stop_seen),
                    mode=detector_mode,
                    stop_condition='answer_thread_lost',
                    **ack_evidence,
                    snapshot=verify_snap.serializable(),
                )
                return False
            result.add_step(
                'monitor', False,
                'gemini monitor never observed Stop button after send',
                stop_seen=False, seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode,
                **ack_evidence,
                snapshot=verify_snap.serializable(),
            )
            return False
        if answer_thread_lost:
            result.add_step(
                'monitor', False,
                'gemini answer_thread_lost: monitor could not restore pinned answer thread',
                stop_seen=observed_stop, seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode,
                stop_condition='answer_thread_lost',
                **ack_evidence,
                snapshot=verify_snap.serializable(),
            )
            return False
        if intermediate_failed:
            result.add_step(
                'monitor', False,
                'gemini monitor failed while disposing intermediate state',
                stop_seen=observed_stop, seed_stop_seen=bool(seed_stop_seen),
                mode=detector_mode,
                intermediate_actions=intermediate_actions,
                **ack_evidence,
                snapshot=verify_snap.serializable(),
            )
            return False
        stop_absent = self.validation_passes(verify_snap, 'response_complete')
        post_ack_gate_satisfied = bool(post_ack_stop_seen or not interim_ack_seen)
        answer_ready = bool(terminal_answer_ready or verify_answer_ready)
        answer_evidence = terminal_answer_evidence if terminal_answer_ready else verify_answer_evidence
        verified = bool(
            completed
            and stop_absent
            and ack_absent
            and post_ack_gate_satisfied
            and answer_ready
        )
        stop_still_present = bool(verify_snap.has(stop_key))
        stop_condition = (
            'generation_stalled'
            if (not verified and stop_still_present and is_stop_condition('generation_stalled'))
            else None
        )
        if verified:
            monitor_message = 'gemini Deep Think response completed after interim ACK cleared'
        elif stop_condition == 'generation_stalled':
            monitor_message = (
                f'gemini generation_stalled: Stop still present after '
                f'{effective_timeout:.0f}s (mode={detector_mode}) -- loud bound, not completion'
            )
        elif not ack_absent:
            monitor_message = 'gemini Deep Think interim ACK still present after Stop-gone'
        elif interim_ack_seen and not post_ack_stop_seen:
            monitor_message = 'gemini Deep Think interim ACK cleared before real generation Stop appeared'
        elif not answer_ready:
            monitor_message = 'gemini Deep Think terminal snapshot lacked real answer content'
        else:
            monitor_message = 'gemini Deep Think response did not reach Stop-gone completion'
        result.add_step(
            'monitor', verified, monitor_message,
            stop_seen=observed_stop,
            seed_stop_seen=bool(seed_stop_seen),
            mode=detector_mode,
            stop_condition=stop_condition,
            stop_absent=stop_absent,
            interim_ack_seen=interim_ack_seen,
            post_ack_stop_seen=post_ack_stop_seen,
            interim_ack_blocking_cycles=interim_ack_blocking_cycles,
            real_answer_ready=answer_ready,
            real_answer_evidence=answer_evidence,
            terminal_snapshot_seen=terminal_snapshot is not None,
            **ack_evidence,
            snapshot=verify_snap.serializable(),
        )
        if verified:
            self.checkpoint_run_state(
                request, self.RUN_STATE_COMPLETION_OBSERVED,
                result=result,
                url=result.session_url_after or self.runtime.current_url() or '',
            )
        return verified

    def _interim_ack_absent(self, snapshot: Snapshot) -> tuple[bool, dict[str, object]]:
        key = self._deep_think_interim_ack_key()
        present = snapshot.has(key)
        return not present, {
            'deep_think_interim_ack_key': key,
            'deep_think_interim_ack_present': present,
        }

    def _deep_think_real_answer_evidence(
        self,
        snapshot: Snapshot,
        request: ConsultationRequest,
    ) -> tuple[bool, dict[str, object]]:
        candidates: list[dict[str, object]] = []
        interim_hits: list[dict[str, object]] = []
        prompt_norm = self._normalized_text(request.message).lower()
        for element in snapshot.unknown:
            for field, text in self._deep_think_element_text_fields(element):
                normalized = self._normalized_text(text)
                if not normalized:
                    continue
                lowered = normalized.lower()
                marker = self._deep_think_interim_marker(lowered)
                if marker:
                    interim_hits.append({
                        'marker': marker,
                        'field': field,
                        'role': element.role,
                        'chars': len(normalized),
                        'preview': normalized[:160],
                    })
                    continue
                if lowered in GEMINI_DEEP_THINK_UI_TEXT:
                    continue
                if self._deep_think_text_matches_prompt(normalized, prompt_norm):
                    continue
                candidates.append({
                    'field': field,
                    'role': element.role,
                    'chars': len(normalized),
                    'preview': normalized[:200],
                })
        best = max(candidates, key=lambda item: int(item['chars']), default=None)
        best_chars = int(best['chars']) if best else 0
        return best_chars >= GEMINI_DEEP_THINK_MIN_REAL_ANSWER_CHARS, {
            'min_real_answer_chars': GEMINI_DEEP_THINK_MIN_REAL_ANSWER_CHARS,
            'best_candidate': best,
            'candidate_count': len(candidates),
            'interim_hits': interim_hits[:5],
            'unknown_count': len(snapshot.unknown),
        }

    @staticmethod
    def _deep_think_element_text_fields(element: ElementRef) -> tuple[tuple[str, str], ...]:
        return (
            ('name', element.name or ''),
            ('text', element.text or ''),
            ('description', element.description or ''),
        )

    @staticmethod
    def _deep_think_interim_marker(lowered_text: str) -> str:
        for marker in GEMINI_DEEP_THINK_INTERIM_MARKERS:
            if marker in lowered_text:
                return marker
        return ''

    def _deep_think_text_matches_prompt(self, normalized: str, prompt_norm: str) -> bool:
        if not prompt_norm:
            return False
        lowered = normalized.lower()
        if len(lowered) >= 80 and lowered in prompt_norm:
            return True
        if len(prompt_norm) >= 80 and prompt_norm in lowered:
            return True
        return bool(self._prompt_echo_evidence(normalized, prompt_norm).get('is_echo'))

    def _deep_think_interim_ack_key(self) -> str:
        monitor_cfg = (self.cfg.get('workflow') or {}).get('monitor') or {}
        key = str(monitor_cfg.get('deep_think_interim_ack_key') or '').strip()
        if not key:
            raise ValueError('gemini deep_think_interim_ack_key must be configured')
        return key

    def extract_primary(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        if not self.reassert_captured_session_url(
            result,
            answer_url_predicate=self._is_answer_thread_url,
        ):
            return False
        # Deep Research renders its report in a CANVAS/immersive panel — the chat
        # bubble holds only a ~89-char "I've completed your research" stub. The
        # full report is copied via the panel's "Share & Export" -> "Copy" (a
        # menu item in the popover), NOT the chat-bubble Copy push button.
        # Proven 2026-06-15: 36KB report via this path vs 89 chars via the bubble.
        if str(request.selection_value('mode', '') or '').strip().lower() == 'deep_research':
            # Resolve Share & Export from a LIVE app-root scan (no cache-clear) so
            # the atspi_obj is fresh — a stale snapshot ref do_action's True but
            # doesn't open the popover (p8 2026-06-21). atspi_only = do_action(0)
            # = the button's only action ('press'), which reliably opens it.
            snap = self.runtime.app_root_snapshot()
            share = self.find_first(snap, 'share_export')
            if not share or not self.runtime.click(share, strategy='atspi_only'):
                result.add_step('extract_primary', False,
                                'Gemini Deep Research "Share & Export" not found/clickable',
                                snapshot=snap.serializable())
                return False
            time.sleep(2.5)
            # The Share & Export popover is a transient React portal that
            # menu_snapshot's clear_cache_single() DISMISSES before its scan (it
            # returned 0 items with the popover provably open). app_root_snapshot
            # scans the live tree directly with no cache-clear, so the popover's
            # "Copy" menu item is captured (raw path got 22814ch vs the 89-char
            # bubble stub).
            menu = self.runtime.app_root_snapshot(allowed_roles=['menu item'])
            copy_item = self.find_first(menu, 'copy_content_item')
            if not copy_item or not self.runtime.click(copy_item, strategy='atspi_only'):
                result.add_step('extract_primary', False,
                                'Gemini Deep Research Share & Export -> Copy item not found',
                                menu=menu.serializable())
                return False
            time.sleep(0.8)
            content = self.runtime.read_clipboard().strip()
            if not content:
                result.add_step('extract_primary', False,
                                'Gemini Deep Research Share & Export -> Copy returned empty clipboard',
                                characters=0, preview='')
                return False
            if not self.set_response_text_if_not_prompt_echo(
                request,
                result,
                content,
                step='extract_primary',
                source='gemini_deep_research_copy',
            ):
                return False
            result.add_step('extract_primary', True,
                            'Gemini Deep Research report copied via Share & Export -> Copy',
                            characters=len(content), preview=content[:200])
            return True
        # RULE: scroll to bottom before extract — a long response's Copy button
        # sits below the fold and is not in the AT-SPI tree until on-screen.
        self.runtime.scroll_to_bottom(self.find_first(self.runtime.snapshot(), 'input'))
        time.sleep(0.6)
        snap = self.runtime.snapshot()
        # copy_button resolves the exact "Copy" control; find_last picks the response action.
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step('extract_primary', False, 'Gemini copy button not found',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.click(copy_button, strategy='atspi_first'):
            result.add_step('extract_primary', False, 'Gemini copy button click failed',
                            snapshot=snap.serializable())
            return False
        time.sleep(0.4)
        content = self.runtime.read_clipboard().strip()
        if not content:
            result.add_step('extract_primary', False,
                            'Gemini response Copy returned empty clipboard',
                            characters=0, preview='')
            return False
        if not self.set_response_text_if_not_prompt_echo(
            request,
            result,
            content,
            step='extract_primary',
            source='gemini_copy_response',
            copy_button=copy_button.serializable(),
        ):
            return False
        result.add_step('extract_primary', True,
                        'Gemini response copied to clipboard',
                        characters=len(content), preview=content[:200])
        return True

    def extract_additional(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        mode = str(request.selection_value('mode', '') or '').strip().lower()
        # For Deep Research, extract_primary already captured the full report via
        # Share & Export -> Copy; re-running that path here would only duplicate it.
        if mode == 'deep_research':
            result.add_step('extract_additional', True,
                            'Gemini Deep Research report already captured by extract_primary')
            return True
        result.add_step('extract_additional', True,
                        'Gemini additional export is Deep Research-only; primary extraction is final',
                        mode=mode or None,
                        primary_characters=len(result.response_text or ''),
                        artifacts=[])
        return True

    def store_in_neo4j(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        if request.no_neo4j:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step('store', True, 'Gemini Neo4j storage skipped',
                            storage=result.storage)
            return True
        session_url = (
            result.session_url_after
            or result.session_url_before
            or self.runtime.current_url()
            or ''
        )
        result.storage = self.store_consultation(
            session_url,
            request.message,
            result.response_text,
            attachments=request.attachments,
        )
        result.storage['url'] = session_url
        if result.storage.get('stored'):
            result.add_step('store', True, 'Gemini response stored in Neo4j',
                            storage=result.storage)
            return True
        result.add_step('store', True, 'Gemini Neo4j storage skipped',
                        storage=result.storage)
        return True
