from __future__ import annotations

import os
import time
from urllib.parse import urlparse

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult


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

    # monitor_generation is inherited from BaseConsultationDriver — the shared
    # stop-transition detector (consultation_v2.completion). deep_think /
    # deep_research are deep modes (2 stop-gone cycles).

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
