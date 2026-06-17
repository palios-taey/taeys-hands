from __future__ import annotations

import os
import time

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult, ExtractedArtifact

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


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

    def _activate_element(self, snapshot, key: str, step: str, reason_prefix: str):
        element = self.find_first(snapshot, key)
        if not element:
            return False
        spec = dict(self.cfg.get('tree', {}).get('element_map', {}).get(key, {}))
        trigger_type = str(spec.get('trigger_type') or 'click').strip().lower()
        if trigger_type == 'hover':
            return self.runtime.hover(element)
        return self.runtime.click(element, strategy='atspi_first')

    def select_model_mode_tools(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        workflow = self.cfg['workflow']['selection']
        requested_model = (request.model or '').strip().lower()
        requested_mode = (
            self.cfg['workflow']['defaults'].get('mode') or ''
        ).strip().lower() if request.mode is None else request.mode.strip().lower()

        # Gemini Deep Think REQUIRES the 3.1 Pro model selected FIRST. Toggling
        # the Deep Think *tool* on the account default (3.5 Flash) silently runs
        # the consult on FLASH (per this YAML's own note + Jesse 2026-06-15: a
        # Family consult ran on Flash because select_model left the model on
        # default). So if deep_think is requested with no explicit model, force
        # Pro — otherwise the consult is degraded to a fast model.
        if requested_mode == 'deep_think' and not requested_model:
            requested_model = 'pro'

        # ── Model selection via mode picker ──────────────────────────────────
        if requested_model and requested_model in workflow.get('model_targets', {}):
            snap = self.runtime.snapshot()
            picker = self.find_first(snap, 'mode_picker')
            if not picker:
                result.add_step('select_model', False, 'Gemini mode picker not found',
                                snapshot=snap.serializable())
                return False
            if not self.runtime.click(picker, strategy='atspi_first'):
                result.add_step('select_model', False, 'Gemini mode picker click failed',
                                snapshot=snap.serializable())
                return False
            time.sleep(0.8)
            # BUG 8 FIX: use menu_snapshot() for portal/dropdown reads
            menu_snap = self.runtime.menu_snapshot()
            item = self.find_first(menu_snap, workflow['model_targets'][requested_model])
            if not item:
                result.add_step('select_model', False,
                                f'Gemini model item {requested_model} not found',
                                menu=menu_snap.serializable())
                return False
            if not self.runtime.click(item, strategy='atspi_first'):
                result.add_step('select_model', False,
                                f'Gemini model click failed for {requested_model}',
                                menu=menu_snap.serializable())
                return False
            time.sleep(0.8)
            # Re-open picker to validate checked state, then close
            verify_root = self.runtime.snapshot()
            picker = self.find_first(verify_root, 'mode_picker')
            verified = False
            if picker and self.runtime.click(picker, strategy='atspi_first'):
                time.sleep(0.5)
                # BUG 8 FIX: menu_snapshot for portal
                verify_menu = self.wait_for_validation(
                    f'{requested_model}_active',
                    timeout=6.0,
                    interval=0.4,
                    scope='menu',
                )
                verified = self.validation_passes(verify_menu, f'{requested_model}_active')
                # BUG 10 FIX: close the dropdown after verification
                self.runtime.press('Escape')
                time.sleep(0.3)
            result.add_step('select_model', verified,
                            f'Gemini model set to {requested_model}',
                            snapshot=self.runtime.snapshot().serializable())
            if not verified:
                return False
        else:
            result.add_step('select_model', True, 'Gemini model left unchanged/default',
                            requested_model=request.model)

        # ── Mode / primary tool selection via Tools dropdown ──────────────────
        if requested_mode and requested_mode in workflow.get('tool_targets', {}):
            snap = self.runtime.snapshot()
            mode_active_key = f'{requested_mode}_active'
            if self.validation_passes(snap, mode_active_key):
                result.add_step('select_mode', True, f'Gemini {requested_mode} already active')
            else:
                tools_button = self.find_first(snap, 'tools_button')
                if not tools_button:
                    result.add_step('select_mode', False,
                                    'Gemini tools button not found',
                                    snapshot=snap.serializable())
                    return False
                if not self.runtime.click(tools_button, strategy='atspi_first'):
                    result.add_step('select_mode', False,
                                    'Gemini tools button click failed',
                                    snapshot=snap.serializable())
                    return False
                time.sleep(0.8)
                # BUG 8 FIX: menu_snapshot for Tools portal
                menu_snap = self.runtime.menu_snapshot()
                item = self.find_first(menu_snap, workflow['tool_targets'][requested_mode])
                if not item:
                    # "Deep think" / "Guided learning" live behind a "More tools"
                    # expander inside the Upload & tools menu (UI 2026-05-21).
                    # Expand it before declaring the tool missing.
                    if self._activate_element(menu_snap, 'more_tools', 'select_mode', 'Gemini more tools expander'):
                        time.sleep(0.6)
                        menu_snap = self.runtime.menu_snapshot()
                        item = self.find_first(menu_snap, workflow['tool_targets'][requested_mode])
                if not item:
                    result.add_step('select_mode', False,
                                    f'Gemini tool item {requested_mode} not found',
                                    menu=menu_snap.serializable())
                    return False
                if not self.runtime.click(item, strategy='atspi_first'):
                    result.add_step('select_mode', False,
                                    f'Gemini tool click failed for {requested_mode}',
                                    menu=menu_snap.serializable())
                    return False
                time.sleep(0.8)
                if requested_mode in ('deep_think', 'deep_research'):
                    # Both expose a COMPOSER toggle ("Deselect Deep think" /
                    # "Deselect Deep research") that renders a beat after the
                    # tool click — poll a normal snapshot for it. Do NOT re-open
                    # the Tools menu to verify these: the indicator lives in the
                    # composer, not the tools portal, so a menu re-check never
                    # finds it and aborts a genuinely-engaged Deep Research.
                    verify_snap = self.wait_for_validation(
                        mode_active_key,
                        timeout=6.0,
                        interval=0.4,
                    )
                    verified = self.validation_passes(verify_snap, mode_active_key)
                    evidence_snap = verify_snap
                else:
                    # Re-open Tools to verify checked state, then close
                    verify_root = self.runtime.snapshot()
                    tools_button = self.find_first(verify_root, 'tools_button')
                    verified = False
                    if tools_button and self.runtime.click(tools_button, strategy='atspi_first'):
                        time.sleep(0.5)
                        # BUG 8 FIX: menu_snapshot for portal
                        verify_menu = self.wait_for_validation(
                            mode_active_key,
                            timeout=6.0,
                            interval=0.4,
                            scope='menu',
                        )
                        verified = self.validation_passes(verify_menu, mode_active_key)
                        # BUG 10 FIX: close the dropdown after verification
                        self.runtime.press('Escape')
                        time.sleep(0.3)
                    evidence_snap = self.runtime.snapshot()
                result.add_step('select_mode', verified,
                                f'Gemini mode/tool set to {requested_mode}',
                                snapshot=evidence_snap.serializable())
                if not verified:
                    return False
        else:
            result.add_step('select_mode', True, 'Gemini mode left unchanged/default',
                            requested_mode=request.mode)

        # ── Additional tools requested in request.tools ───────────────────────
        for tool_name in request.tools:
            normalized = tool_name.strip().lower().replace(' ', '_')
            target_key = workflow.get('tool_targets', {}).get(normalized)
            if not target_key:
                result.add_step('select_tool', False,
                                f'Gemini tool {tool_name!r} not mapped in Consultation V2 YAML')
                return False
            snap = self.runtime.snapshot()
            tools_button = self.find_first(snap, 'tools_button')
            if not tools_button or not self.runtime.click(tools_button, strategy='atspi_first'):
                result.add_step('select_tool', False,
                                f'Gemini failed to open tools menu for {tool_name}',
                                snapshot=snap.serializable())
                return False
            time.sleep(0.6)
            # BUG 8 FIX: menu_snapshot() — not snapshot() — for portal reads
            menu_snap = self.runtime.menu_snapshot()
            item = self.find_first(menu_snap, target_key)
            if not item:
                result.add_step('select_tool', False,
                                f'Gemini tool item {target_key} not found',
                                menu=menu_snap.serializable())
                return False
            if not self.runtime.click(item, strategy='atspi_first'):
                result.add_step('select_tool', False,
                                f'Gemini failed to click tool {tool_name}',
                                menu=menu_snap.serializable())
                return False
            validation_key = f'{normalized}_active'
            self.runtime.press('Escape')
            if validation_key not in self.cfg.get('validation', {}):
                result.add_step(
                    'select_tool',
                    False,
                    f'Gemini tool {tool_name!r} has no tree validation key {validation_key!r}',
                    snapshot=self.runtime.snapshot().serializable(),
                )
                return False
            verify_snap = self.wait_for_validation(validation_key, timeout=6.0, interval=0.4)
            verified = self.validation_passes(verify_snap, validation_key)
            result.add_step('select_tool', verified,
                            f'Gemini tool click validated for {tool_name}',
                            snapshot=verify_snap.serializable())
            if not verified:
                return False
        return True

    def _active_snapshot(self, validation_key: str):
        snap = self.runtime.snapshot()
        if self.validation_passes(snap, validation_key):
            return snap
        return None

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
            if not self.runtime.click(trigger, strategy='atspi_first'):
                result.add_step('attach', False,
                                f'Gemini upload menu trigger click failed for {abs_path}',
                                snapshot=snap.serializable())
                return False
            time.sleep(0.7)
            # BUG 8 FIX: menu_snapshot for upload portal
            menu_snap = self.runtime.menu_snapshot()
            upload_item = self.find_first(menu_snap, 'upload_files_item')
            if not upload_item:
                result.add_step('attach', False,
                                f'Gemini upload item not found for {abs_path}',
                                menu=menu_snap.serializable())
                return False
            if not self.runtime.click(upload_item, strategy='atspi_first'):
                result.add_step('attach', False,
                                f'Gemini upload item click failed for {abs_path}',
                                menu=menu_snap.serializable())
                return False
            time.sleep(0.8)
            self.runtime.focus_file_dialog()
            self.runtime.press('ctrl+l')
            time.sleep(0.2)
            if not self.runtime.paste(abs_path):
                self.runtime.type_text(abs_path, delay_ms=5)
            time.sleep(0.2)
            # ONE Return is sufficient: selects the file and closes the GTK dialog.
            # A second Return would hit the now-focused chat input and submit garbage.
            self.runtime.press('Return')
            verify_snap = self.wait_for_validation(
                'attach_success',
                filename=abs_path,
                timeout=15.0,
                interval=0.5,
            )
            verified = self.validation_passes(verify_snap, 'attach_success', filename=abs_path)
            result.add_step('attach', verified,
                            f'Gemini attached {os.path.basename(abs_path)}',
                            file=abs_path, snapshot=verify_snap.serializable())
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
        if (request.mode or '').strip().lower() == 'deep_research':
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
            post_send_clicked = self.runtime.click(start_button, strategy='atspi_first')
            if not post_send_clicked:
                result.add_step(
                    'send', False, 'Gemini "Start research" click failed',
                    snapshot=self.runtime.snapshot().serializable(),
                )
                return False
            time.sleep(1.5)
        # Confirm the generation (the research run, for DR) actually started.
        send_snap = self.wait_for_validation('send_success', timeout=30, interval=0.6)
        stop_seen = self.validation_passes(send_snap, 'send_success')
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
            'send', verified,
            'Gemini send validated by Stop button and URL capture',
            url_before=before,
            url_after=result.session_url_after,
            start_research_clicked=post_send_clicked,
            stop_seen=stop_seen,
            url_changed=bool(url_changed),
            snapshot=verify_snap.serializable(),
        )
        return verified

    # monitor_generation is inherited from BaseConsultationDriver — the shared
    # stop-transition detector (consultation_v2.completion). deep_think /
    # deep_research are deep modes (2 stop-gone cycles).

    def extract_primary(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        # Deep Research renders its report in a CANVAS/immersive panel — the chat
        # bubble holds only a ~89-char "I've completed your research" stub. The
        # full report is copied via the panel's "Share & Export" -> "Copy" (a
        # menu item in the popover), NOT the chat-bubble Copy push button.
        # Proven 2026-06-15: 36KB report via this path vs 89 chars via the bubble.
        if (request.mode or '').strip().lower() == 'deep_research':
            snap = self.runtime.snapshot()
            share = self.find_first(snap, 'share_export')
            if not share or not self.runtime.click(share, strategy='atspi_first'):
                result.add_step('extract_primary', False,
                                'Gemini Deep Research "Share & Export" not found/clickable',
                                snapshot=snap.serializable())
                return False
            time.sleep(1.2)
            menu = self.runtime.menu_snapshot()
            copy_item = self.find_first(menu, 'copy_content_item')
            if not copy_item or not self.runtime.click(copy_item, strategy='atspi_first'):
                result.add_step('extract_primary', False,
                                'Gemini Deep Research Share & Export -> Copy item not found',
                                menu=menu.serializable())
                return False
            time.sleep(0.8)
            content = self.runtime.read_clipboard().strip()
            result.response_text = content
            verified = bool(content)
            result.add_step('extract_primary', verified,
                            'Gemini Deep Research report copied via Share & Export -> Copy',
                            characters=len(content), preview=content[:200])
            return verified
        # RULE: scroll to bottom before extract — a long response's Copy button
        # sits below the fold and is not in the AT-SPI tree until on-screen.
        self.runtime.scroll_to_bottom(self.find_first(self.runtime.snapshot(), 'input'))
        time.sleep(0.6)
        snap = self.runtime.snapshot()
        # copy_button resolves via element_map name_contains: Copy → find_last picks last response
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
        result.response_text = content
        verified = bool(content)
        result.add_step('extract_primary', verified,
                        'Gemini response copied to clipboard',
                        characters=len(content), preview=content[:200])
        return verified

    def extract_additional(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        # For Deep Research, extract_primary already captured the full report via
        # Share & Export -> Copy; re-running that path here would only duplicate it.
        if (request.mode or '').strip().lower() == 'deep_research':
            result.add_step('extract_additional', True,
                            'Gemini Deep Research report already captured by extract_primary')
            return True
        snap = self.runtime.snapshot()
        share_export = self.find_first(snap, 'share_export')
        if not share_export:
            result.add_step('extract_additional', True,
                            'Gemini no additional export surface was visible')
            return True
        if not self.runtime.click(share_export, strategy='atspi_first'):
            result.add_step('extract_additional', False,
                            'Gemini Share & export click failed',
                            snapshot=snap.serializable())
            return False
        time.sleep(0.7)
        # BUG 8 FIX: Share & export submenu is a portal — use menu_snapshot
        menu_snap = self.runtime.menu_snapshot()
        copy_item = self.find_first(menu_snap, 'copy_content_item')
        if not copy_item:
            result.add_step('extract_additional', True,
                            'Gemini Share & export opened but Copy Content item was not exposed',
                            menu=menu_snap.serializable())
            return True
        if not self.runtime.click(copy_item, strategy='atspi_first'):
            result.add_step('extract_additional', False,
                            'Gemini Copy Content click failed',
                            menu=menu_snap.serializable())
            return False
        time.sleep(0.5)
        content = self.runtime.read_clipboard().strip()
        if content:
            result.extractions.append(ExtractedArtifact(
                name='gemini_export.md',
                content=content,
                kind='report_export',
                metadata={'source': 'share_export_copy_content'},
            ))
            result.add_step('extract_additional', True,
                            'Gemini additional export copied',
                            characters=len(content), preview=content[:200])
            return True
        result.add_step('extract_additional', False,
                        'Gemini additional export clipboard was empty')
        return False

    def store_in_neo4j(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step('store', True, 'Gemini Neo4j storage skipped',
                            storage=result.storage)
            return True
        try:
            # BUG 9 FIX: URL used only for bookkeeping/storage, never as a gate
            session_url = (
                result.session_url_after
                or result.session_url_before
                or self.runtime.current_url()
                or ''
            )
            session_id = neo4j_client.get_or_create_session(self.platform, session_url)
            user_message_id = neo4j_client.add_message(
                session_id, 'user', request.message, request.attachments
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
            result.add_step('store', True, 'Gemini response stored in Neo4j',
                            storage=result.storage)
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step('store', False, f'Gemini Neo4j storage failed: {exc}')
            return False
