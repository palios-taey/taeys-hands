from __future__ import annotations

import os
import time
from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, ExtractedArtifact, Snapshot

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


class PerplexityConsultationDriver(BaseConsultationDriver):
    platform = 'perplexity'

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    # run() is the shared two-phase template on BaseConsultationDriver (FLOW §10):
    # it holds the DISPLAY-scoped dispatch lock across setup_and_send (below) and
    # releases it before monitor_and_extract so monitoring runs concurrently.

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): navigate → mode → connectors → attach →
        prompt → guarded send + monitor registration."""
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
            if not self.wait_for_page_ready_after_navigation(result):
                return False
        if not self._wait_for_prompt_ready(result):
            return False
        if not self.apply_selection_plan(request, result):
            return False
        if request.selection_list('connectors'):
            if not self.toggle_connectors(request, result):
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
            timeout=max(self._mode_settle_timeout(), 8.0),
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

    def _mode_settle_timeout(self) -> float:
        settle = self.cfg.get('settle') or {}
        if 'default_ms' not in settle:
            raise ValueError('Perplexity YAML settle.default_ms is required for mode validation')
        try:
            return max(float(int(settle['default_ms'])) / 1000.0, 0.1)
        except (TypeError, ValueError) as exc:
            raise ValueError('Perplexity YAML settle.default_ms must be integer milliseconds') from exc

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
                    f'Connector {connector_name!r} already enabled — skipping',
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
            # Settle + rescan (DRIVER_CONTRACT §E): the attach dropdown's
            # "Upload files or images" item renders a beat after the trigger
            # click. A fixed time.sleep(0.7) + one-shot read flaked ("upload
            # item not found") when the menu was slow to render — the item was
            # present moments later. Poll for it (observation only, no re-click)
            # before declaring it missing, same readiness pattern as mode-select.
            self.runtime.wait_until(
                lambda: self.runtime.menu_snapshot().has('upload_files_item'),
                timeout=10,
                interval=0.4,
            )
            menu_snap = self.runtime.menu_snapshot()
            upload_item = self.find_first(menu_snap, 'upload_files_item')
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
            if not self.runtime.focus_file_dialog():
                result.add_step(
                    'attach', False,
                    f'Perplexity file dialog did not focus for {abs_path}',
                    snapshot=menu_snap.serializable(),
                )
                return False
            if not self.runtime.press('ctrl+l'):
                result.add_step(
                    'attach', False,
                    f'Perplexity file dialog location shortcut failed for {abs_path}',
                )
                return False
            time.sleep(0.2)
            if not self.runtime.press('ctrl+a'):
                result.add_step(
                    'attach', False,
                    f'Perplexity file dialog select-all failed for {abs_path}',
                )
                return False
            time.sleep(0.1)
            if not self.runtime.paste(abs_path):
                result.add_step(
                    'attach', False,
                    f'Perplexity file dialog path paste failed for {abs_path}',
                )
                return False
            time.sleep(0.2)
            if not self.runtime.focus_file_dialog():
                result.add_step(
                    'attach', False,
                    f'Perplexity file dialog lost focus before submit for {abs_path}',
                )
                return False
            if not self.runtime.press('Return'):
                result.add_step(
                    'attach', False,
                    f'Perplexity file dialog submit failed for {abs_path}',
                )
                return False
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
            click_returned = self.runtime.click(send_button)
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

        send_timeout = float(self.cfg.get('validation', {}).get('send_success', {}).get('timeout', 60))
        send_snap = self.wait_for_validation(
            'send_success',
            timeout=send_timeout,
            interval=0.6,
        )
        stop_seen = self.validation_passes(send_snap, 'send_success')
        settled_url = self._wait_for_answer_thread_url(timeout=12.0)
        if not settled_url:
            result.add_step(
                'send', False,
                'Perplexity answer thread URL was not captured after submit',
                url_before=before,
                submit_scope=submit_scope,
                click_returned=click_returned,
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
            # wait-loop keeps polling until the upload finishes and submit enables —
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
    # Monitor generation — inherited from BaseConsultationDriver (the shared
    # stop-transition detector, consultation_v2.completion). deep_research is a
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
        if self._is_prompt_echo(content, request):
            result.add_step(
                'extract_primary', False,
                'Perplexity extraction matched the submitted prompt; refusing prompt echo',
                **step_evidence,
            )
            return False
        result.response_text = content
        result.add_step(
            'extract_primary', True,
            message,
            **step_evidence,
        )
        return True

    def extract_primary(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        # Wait for response to fully render.
        time.sleep(2.0)
        if not self._ensure_answer_thread(result):
            return False

        is_deep_research = self._is_deep_research(request)
        if not is_deep_research:
            self.runtime.scroll_document_to_bottom(clicks=12, rounds=3, settle=0.5)

        # Use snapshot (which clears AT-SPI cache via build_snapshot) to find
        # copy buttons. Raw find_elements bypasses cache clearing and misses
        # elements after the long monitor polling phase.
        snap = self.runtime.snapshot()

        # Deep Research renders in one of several mapped output shapes; extract via
        # the control actually PRESENT (observe-then-dispatch, mapped states — NOT a
        # fallback-on-action-miss chain). The previous code hardcoded
        # copy_contents_button for ALL deep_research and FALSE-FAILED when DR rendered
        # the inline-answer shape (p8 2026-06-21: copy_button held the full 13998-char
        # answer). Selection by presence:
        #   - report-card present -> copy_contents_button (full report; preferred — the
        #     bottom copy_button is also present on a report-card but yields only the
        #     intro stub there, so report-card MUST win when both are present)
        #   - inline answer (no report-card) -> copy_button (the inline answer is the
        #     full content)
        if is_deep_research:
            if self.find_last(snap, 'copy_contents_button'):
                target_key = 'copy_contents_button'
            elif self.find_last(snap, 'copy_button'):
                target_key = 'copy_button'
            else:
                target_key = None
        else:
            target_key = 'copy_button'

        target = self.find_last(snap, target_key) if target_key else None
        if not target:
            result.add_step(
                'extract_primary', False,
                (
                    'Perplexity Deep Research: no mapped extraction control present '
                    '(neither copy_contents_button report-card nor copy_button inline answer)'
                    if is_deep_research
                    else f'Perplexity required extraction target {target_key!r} not found'
                ),
                stop_condition='extraction_failed',
                snapshot=snap.serializable(),
            )
            return False

        # Perplexity's DR Copy / "Copy contents" returns an EMPTY clipboard if
        # action-clicked while OFF-SCREEN — scroll the button itself into view
        # first (Component.scroll_to ANYWHERE). This is the report special-
        # handling: scroll the CONTROL, not the page. (Production-observed:
        # without this the copy click landed empty; with it, 23.7k extracted.)
        self.runtime.scroll_element_into_view(target)
        time.sleep(0.5)
        # Clear clipboard, click via AT-SPI action, read clipboard
        self.runtime.write_clipboard('')
        time.sleep(0.3)
        clicked = self.runtime.click(target, strategy='atspi_only')
        if not clicked:
            result.add_step(
                'extract_primary', False,
                f'Perplexity copy target click failed (button: {target.name!r})',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(1.0)
        content = self.runtime.read_clipboard().strip()

        if content:
            return self._accept_extracted_content(
                content,
                request,
                result,
                f'Perplexity response extracted via {target.name!r} ({len(content)} chars)',
            )

        result.add_step(
            'extract_primary', False,
            f'Perplexity copy target clicked but clipboard empty (button: {target.name!r})',
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
        time.sleep(1.0)
        content = self.runtime.read_clipboard().strip()
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
            )
            return True

        result.add_step(
            'extract_additional', False,
            'Perplexity copy_contents_button clicked but clipboard empty',
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
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step(
                'store', True,
                'Perplexity Neo4j storage skipped',
                storage=result.storage,
            )
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
                session_id, 'assistant',
                result.response_text,
                self.serialize_artifacts(result.extractions),
            )
            result.storage = {
                'session_id': session_id,
                'user_message_id': user_message_id,
                'assistant_message_id': assistant_message_id,
                'url': session_url,
            }
            result.add_step(
                'store', True,
                'Perplexity response stored in Neo4j',
                storage=result.storage,
            )
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step(
                'store', False,
                f'Perplexity Neo4j storage failed: {exc}',
            )
            return False
