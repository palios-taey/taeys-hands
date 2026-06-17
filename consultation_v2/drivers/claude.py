from __future__ import annotations

import os
import time

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult

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

    def _activate_element(self, snapshot, key: str) -> bool:
        element = self.find_first(snapshot, key)
        if not element:
            return False
        spec = dict(self.cfg.get('tree', {}).get('element_map', {}).get(key, {}))
        trigger_type = str(spec.get('trigger_type') or 'click').strip().lower()
        if trigger_type == 'hover':
            return self.runtime.hover(element)
        return self.runtime.click(element)

    def _find_claude_model_selector(self, snapshot):
        toggle_menu = self.find_first(snapshot, 'toggle_menu')
        if not toggle_menu or toggle_menu.x is None or toggle_menu.y is None:
            return None
        candidates = []
        for items in snapshot.mapped.values():
            for element in items:
                if element.role.lower() != 'push button':
                    continue
                if element.name == toggle_menu.name:
                    continue
                if element.x is None or element.y is None:
                    continue
                if abs(int(element.y) - int(toggle_menu.y)) > 24:
                    continue
                if int(element.x) <= int(toggle_menu.x):
                    continue
                candidates.append(element)
        if not candidates:
            return None
        return max(candidates, key=lambda element: int(element.x or 0))

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
        if not self.select_model_mode_tools(request, result):
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
    # Model / mode / tool selection
    # ------------------------------------------------------------------

    def select_model_mode_tools(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        workflow = self.cfg['workflow']['selection']
        requested_model = (request.model or '').strip().lower()
        requested_mode = (
            self.cfg['workflow']['defaults'].get('mode') or ''
        ).strip().lower() if request.mode is None else request.mode.strip().lower()

        # -- model --
        if requested_model and requested_model in workflow.get('model_targets', {}):
            snap = self.runtime.snapshot()
            selector = self._find_claude_model_selector(snap)
            if not selector:
                result.add_step('select_model', False, 'Claude model selector not found',
                                snapshot=snap.serializable())
                return False
            if not self.runtime.click(selector):
                result.add_step('select_model', False, 'Claude model selector click failed',
                                snapshot=snap.serializable())
                return False
            time.sleep(0.8)
            menu_snap = self.runtime.menu_snapshot()
            item = self.find_first(menu_snap, workflow['model_targets'][requested_model])
            if not item:
                result.add_step('select_model', False,
                                f'Claude model item for {requested_model} not found',
                                snapshot=menu_snap.serializable())
                return False
            clicked = self.runtime.click(item)
            verify_snap = self.wait_for_validation(
                f'{requested_model}_active',
                timeout=6.0,
                interval=0.4,
            )
            verified = clicked and self.validation_passes(verify_snap, f'{requested_model}_active')
            result.add_step('select_model', verified, f'Claude model set to {requested_model}',
                            snapshot=verify_snap.serializable())
            if not verified:
                return False
        else:
            result.add_step('select_model', True, 'Claude model left unchanged/default',
                            requested_model=request.model)

        # -- mode --
        if requested_mode and requested_mode in workflow.get('mode_targets', {}):
            # Settle: after navigate, the composer + model selector render into
            # the AT-SPI tree a beat late. Poll for the selector BEFORE checking
            # mode-active or looking it up, so select_mode doesn't scan before
            # render — that race was failing 'model selector unavailable' AND
            # missing the already-active state on a slow :3 (reproducible).
            self.runtime.wait_until(
                lambda: self._find_claude_model_selector(self.runtime.snapshot()) is not None,
                timeout=12, interval=0.5,
            )
            snap = self.runtime.snapshot()
            mode_active_key = f'{requested_mode}_active'
            if self.validation_passes(snap, mode_active_key):
                result.add_step('select_mode', True, f'Claude {requested_mode} already active')
                return True

            selector = self._find_claude_model_selector(snap)
            if not selector:
                result.add_step('select_mode', False,
                                'Claude model selector unavailable for mode toggle',
                                snapshot=snap.serializable())
                return False
            if not self.runtime.click(selector):
                result.add_step('select_mode', False, 'Claude mode dropdown click failed',
                                snapshot=snap.serializable())
                return False
            time.sleep(0.8)
            menu_snap = self.runtime.menu_snapshot()
            item = self.find_first(menu_snap, workflow['mode_targets'][requested_mode])
            if not item:
                result.add_step('select_mode', False,
                                f'Claude mode item {requested_mode} not found',
                                snapshot=menu_snap.serializable())
                return False
            clicked = self.runtime.click(item)
            time.sleep(0.8)

            # Claude max-mode is a two-stage path: choose the base model, then
            # set the Effort flyout to Extra. Selecting the model radio item
            # above CLOSES the selector menu (empirically verified: effort_menu
            # absent after the model click), so the Effort flyout is no longer
            # reachable. Re-open the selector before hovering Effort Max.
            if requested_mode == 'extended_thinking':
                reopen = self._find_claude_model_selector(self.runtime.snapshot())
                if not reopen or not self.runtime.click(reopen):
                    result.add_step('select_mode', False,
                                    'Claude selector re-open for effort failed',
                                    snapshot=self.runtime.snapshot().serializable())
                    return False
                time.sleep(0.8)
                effort_snap = self.runtime.menu_snapshot()
                if not self._activate_element(effort_snap, 'effort_menu'):
                    result.add_step('select_mode', False,
                                    'Claude effort submenu hover failed',
                                    snapshot=effort_snap.serializable())
                    return False
                # The Effort flyout renders ~0.4s after the hover; poll instead
                # of a fixed sleep (scan-before-render — same class as grok /
                # perplexity attach). menu_snapshot is an AT-SPI read (no mouse
                # move), so the hover-submenu stays open while polling.
                self.runtime.wait_until(
                    lambda: self.runtime.menu_snapshot().has('effort_max'),
                    timeout=8, interval=0.4,
                )
                submenu_snap = self.runtime.menu_snapshot()
                extra = self.find_first(submenu_snap, 'effort_max')
                if not extra:
                    result.add_step('select_mode', False,
                                    'Claude effort Max item not found',
                                    snapshot=submenu_snap.serializable())
                    self.runtime.press('Escape')
                    return False
                clicked = clicked and self.runtime.click(extra)
                time.sleep(0.5)
                self.runtime.press('Escape')
                time.sleep(0.4)

            verify_snap = self.wait_for_validation(
                mode_active_key,
                timeout=6.0,
                interval=0.4,
            )
            verified = clicked and self.validation_passes(verify_snap, mode_active_key)
            result.add_step('select_mode', verified, f'Claude mode applied: {requested_mode}',
                            snapshot=verify_snap.serializable())
            if not verified:
                return False

        # -- tools --
        for tool_name in request.tools:
            normalized = tool_name.strip().lower().replace(' ', '_')
            target_key = workflow.get('tool_targets', {}).get(normalized)
            if not target_key:
                result.add_step('select_tool', False,
                                f'Claude tool {tool_name!r} not mapped in Consultation V2 YAML')
                return False
            snap = self.runtime.snapshot()
            toggle_menu = self.find_first(snap, 'toggle_menu')
            if not toggle_menu or not self.runtime.click(toggle_menu):
                result.add_step('select_tool', False,
                                f'Claude failed to open toggle menu for {tool_name}',
                                snapshot=snap.serializable())
                return False
            time.sleep(0.8)
            menu_snap = self.runtime.menu_snapshot()
            item = self.find_first(menu_snap, target_key)
            if not item:
                result.add_step('select_tool', False,
                                f'Claude tool item {target_key} not found',
                                snapshot=menu_snap.serializable())
                return False
            clicked = self.runtime.click(item)
            validation_key = f'{normalized}_active'
            if validation_key not in self.cfg.get('validation', {}):
                verify_snap = self.runtime.snapshot()
                result.add_step(
                    'select_tool',
                    False,
                    f'Claude tool {tool_name!r} has no tree validation key {validation_key!r}',
                    snapshot=verify_snap.serializable(),
                )
                return False
            verify_snap = self.wait_for_validation(validation_key, timeout=6.0, interval=0.4)
            verified = bool(clicked and self.validation_passes(verify_snap, validation_key))
            result.add_step('select_tool', verified,
                            f'Claude tool click validated for {tool_name}',
                            snapshot=verify_snap.serializable())
            if not verified:
                return False
        return True

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
            # Settle: the toggle menu's items render a beat after the click —
            # poll for the upload item instead of one fixed-sleep snapshot.
            # Without this, the SECOND attachment intermittently failed 'upload
            # item not found' (scan-before-render on the re-opened menu).
            self.runtime.wait_until(
                lambda: self.runtime.menu_snapshot().has('upload_files_item'),
                timeout=8, interval=0.4,
            )
            menu_snap = self.runtime.menu_snapshot()
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
            verify_snap = self.wait_for_validation(
                'attach_success',
                filename=abs_path,
                timeout=20.0,
                interval=0.5,
            )
            verified = self.validation_passes(verify_snap, 'attach_success', filename=abs_path)
            result.add_step('attach', verified,
                            f'Claude attached {os.path.basename(abs_path)}',
                            file=abs_path, snapshot=verify_snap.serializable())
            if not verified:
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Claude attachments requested')
        return True

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
        verify_snap = self.wait_for_validation(
            'prompt_ready',
            timeout=8.0,
            interval=0.4,
        )
        # The "Send message" button only appears once the composer holds content,
        # so prompt_ready is the reliable "text landed" signal. Do NOT gate on a
        # char-count read of the composer: Claude's React contenteditable does
        # not report its text reliably over AT-SPI, which false-negatived a paste
        # that DID land and triggered a type_text fallback that DOUBLED the prompt
        # (production-observed). One paste + Send-button-present is the contract.
        prompt_ready = self.validation_passes(verify_snap, 'prompt_ready')
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
        send_snap = self.wait_for_validation('send_success', timeout=30, interval=0.6)
        stop_seen = self.validation_passes(send_snap, 'send_success')
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
    # Monitor generation — shared stop-transition detector
    # (consultation_v2.completion). extended_thinking is a deep mode (2
    # stop-gone cycles). The send-phase stop observation is seeded so a
    # sub-second reply completes on the stop-gone transition.
    # ------------------------------------------------------------------

    def monitor_generation(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        return super().monitor_generation(
            request, result, seed_stop_seen=getattr(self, '_send_stop_seen', False)
        )

    # ------------------------------------------------------------------
    # Extract primary (copy-button strategy)
    # ------------------------------------------------------------------

    def extract_primary(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        from core.atspi import find_firefox_for_platform
        from core.tree import find_elements as raw_find_elements
        from core.interact import atspi_click
        from core import clipboard

        from core import input as _inp
        # Retry: scroll the conversation to the BOTTOM each pass, THEN scan.
        # The response's Copy button only enters the AT-SPI tree when on-screen;
        # on a long Claude answer it sits below the fold and is never found
        # (this is why extract intermittently saw <2 Copy buttons). ctrl+End is
        # WRONG here — it focuses the empty composer and was measured to HIDE a
        # copy button (2->1). Scroll the wheel over the conversation column;
        # the hover point is DERIVED from the composer input (bottom-centre),
        # never a magic coordinate.
        for attempt in range(5):
            time.sleep(2.0)
            snap = self.runtime.snapshot()
            inp_el = self.find_first(snap, 'input')
            if inp_el is not None and inp_el.x is not None and inp_el.y is not None:
                # SCROLL TO BOTTOM, EVERY TIME — robust loop-until-bottom, not a
                # single 25-click burst. A long verdict's Copy sits far below the
                # fold; one burst leaves only the PROMPT's Copy in the tree and
                # extract grabs the packet echo (production 2026-06-15: 22k-char
                # audit, the response Copy rendered only after ~120 clicks).
                self.runtime.scroll_to_bottom(inp_el)
                time.sleep(0.5)
            firefox = find_firefox_for_platform(self.platform)
            if not firefox:
                continue
            try:
                firefox.clear_cache_single()
            except Exception:
                pass
            all_el = raw_find_elements(firefox, fence_after=[])
            copy_btns = [e for e in all_el
                         if (e.get('name') or '').strip() == 'Copy'
                         and 'button' in (e.get('role') or '')]
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
            target = max(copy_btns, key=lambda e: e.get('y') or 0)
            clipboard.write('')
            time.sleep(0.3)
            atspi_click(target)
            time.sleep(1.5)
            content = (clipboard.read() or '').strip()
            # Reject the PROMPT echo, not just an exact match: the rendered
            # prompt bubble equals the dispatched packet but differs in
            # whitespace, so a bare `!= request.message` let a 1977-char packet
            # echo through as if it were the verdict (2026-06-15). Compare on
            # whitespace-normalized openings.
            def _norm(s: str) -> str:
                return ' '.join((s or '').split())
            nc, nm = _norm(content), _norm(request.message)
            is_echo = bool(nc) and (nc == nm or (len(nm) >= 60 and nc[:60] == nm[:60]))
            if content and not is_echo:
                result.response_text = content
                result.add_step('extract_primary', True,
                                f'Claude response copied ({len(content)} chars, attempt {attempt+1})',
                                characters=len(content), preview=content[:200])
                return True

        result.add_step('extract_primary', False,
                        f'Claude extraction failed after 5 attempts',
                        elements=len(all_el) if all_el else 0)
        return False

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
