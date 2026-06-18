from __future__ import annotations

import os
import time
from typing import Optional

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult, ExtractedArtifact

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


class ChatGPTConsultationDriver(BaseConsultationDriver):
    platform = 'chatgpt'

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

        if not self.clean_composer(request, result):
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
    # Helpers
    # ------------------------------------------------------------------

    def _click_strategy(self) -> str:
        """Return click strategy from top-level YAML key; fall back to 'at_spi'."""
        return self.cfg.get('click_strategy', 'at_spi')

    def _click(self, element) -> bool:
        """Dispatch click using the YAML-declared strategy."""
        strategy = self._click_strategy()
        return self.runtime.click(element, strategy=strategy)

    def _focus_composer(self):
        """Focus the YAML-mapped ChatGPT input and return it after tree proof.

        The send contract is input-entry focus -> Return. focus_firefox() only
        activates the window; it does not prove keyboard focus is in the
        composer. Live recovery for issue #154 used the exact mapped entry
        (name="Chat with ChatGPT", role=entry), then Return.
        """
        self.runtime.focus_firefox()
        time.sleep(0.2)

        def _find_input_entry():
            snap = self.runtime.snapshot()
            return self.find_first(snap, 'input')

        node = self.runtime.wait_until(_find_input_entry, timeout=10, interval=0.4)
        if node is None:
            return None
        if not self.runtime.click(node):
            return None

        def _focused_input_entry():
            snap = self.runtime.snapshot()
            focused = self.find_first(snap, 'input')
            if focused and 'focused' in {s.lower() for s in (focused.states or [])}:
                return focused
            return None

        return self.runtime.wait_until(_focused_input_entry, timeout=4.0, interval=0.3)

    def _activate_element(self, snapshot, key: str, result: ConsultationResult, step: str, reason_prefix: str) -> bool:
        element = self.find_first(snapshot, key)
        if not element:
            result.add_step(step, False, f'{reason_prefix} {key} not found', snapshot=snapshot.serializable())
            return False
        spec = dict(self.cfg.get('tree', {}).get('element_map', {}).get(key, {}))
        trigger_type = str(spec.get('trigger_type') or 'click').strip().lower()
        if trigger_type == 'hover':
            if not self.runtime.hover(element):
                result.add_step(step, False, f'{reason_prefix} {key} hover failed', snapshot=snapshot.serializable())
                return False
            return True
        if not self._click(element):
            result.add_step(step, False, f'{reason_prefix} {key} click failed', snapshot=snapshot.serializable())
            return False
        return True

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
        CPT-packing packet). Clicking the sidebar 'New chat' link discards the
        draft, the stale attachment, and the old thread in one action — a fresh
        chat is empty with NO attachment, so there is nothing stale to remove.
        The ctrl+a/Delete is a belt-and-suspenders clear of any draft the fresh
        chat still restores. We then VERIFY the composer is empty (no leftover
        Send button presence from restored text) before proceeding.

        For a follow-up session (request.session_url set) we must NOT start a new
        chat — that would abandon the thread. Skip in that case.
        """
        from core import input as _inp

        if request.session_url:
            result.add_step('clean_composer', True,
                            'ChatGPT follow-up session — keeping existing thread (no New chat)')
            return True

        snap = self.runtime.snapshot()
        new_chat = self.find_first(snap, 'new_chat')
        if not new_chat:
            result.add_step('clean_composer', False,
                            'ChatGPT New chat link not found — cannot force a clean fresh chat',
                            snapshot=snap.serializable())
            return False
        if not self._click(new_chat):
            result.add_step('clean_composer', False,
                            'ChatGPT New chat click failed',
                            snapshot=snap.serializable())
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
        # primitive is keyboard-to-focused-composer. A fresh New chat composer
        # already holds keyboard focus; activate the Firefox window so the keys
        # land, then ctrl+a + Delete clears any restored draft text. This is the
        # documented working ChatGPT method (100_TIMES / memory: "ProseMirror not
        # in AT-SPI; paste directly into the focused composer"), NOT a fallback.
        self.runtime.focus_firefox()
        time.sleep(0.3)
        _inp.press_key('ctrl+a')
        time.sleep(0.15)
        _inp.press_key('Delete')
        time.sleep(0.3)

        # VERIFY the composer is empty: the 'Send prompt' button only renders
        # once the composer holds content, so prompt_ready being TRUE here means
        # a draft survived the clear — fail loud rather than send contaminated
        # state. (TODO: if a stale file-attachment chip can survive a fresh New
        # chat, map its exact remove-control name from a live scan and remove it
        # here. The current live map — consultations/p2_map_chatgpt_exact.md —
        # has no exact name for a ChatGPT attachment-remove control; a fresh New
        # chat carries no attachment, so none is expected.)
        verify_snap = self.runtime.snapshot()
        draft_present = self.validation_passes(verify_snap, 'prompt_ready')
        if draft_present:
            result.add_step('clean_composer', False,
                            'ChatGPT composer still holds a draft after New chat + clear',
                            snapshot=verify_snap.serializable())
            return False
        result.add_step('clean_composer', True,
                        'ChatGPT forced clean fresh chat (no draft / attachment / stale thread)',
                        snapshot=verify_snap.serializable())
        return True

    # ------------------------------------------------------------------
    # Model / mode / tool selection
    # ------------------------------------------------------------------

    def select_model_mode_tools(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        workflow = self.cfg['workflow']['selection']
        requested_mode = (
            (self.cfg['workflow']['defaults'].get('mode') or '').strip().lower()
            if request.mode is None
            else request.mode.strip().lower()
        )
        requested_model = (request.model or self.cfg['workflow']['defaults'].get('model') or '').strip().lower()
        target = requested_mode or requested_model

        snap = self.runtime.snapshot()
        mode_active_key = f"{target}_active"
        if self.validation_passes(snap, mode_active_key):
            result.add_step('select_model_mode', True, f'ChatGPT {target} already active')
        elif target in workflow.get('composite_modes', {}):
            if not self._apply_composite_mode(target, workflow, result):
                return False
        elif target and target in workflow.get('model_targets', {}):
            if not self._apply_model_target(target, workflow, result):
                return False
        else:
            result.add_step(
                'select_model_mode', True,
                'ChatGPT using current/default model and mode',
                requested_model=request.model,
                requested_mode=request.mode,
            )

        # Tool toggles
        for tool_name in request.tools:
            if not self._apply_tool(tool_name, workflow, result):
                return False
        return True

    def _apply_composite_mode(self, target: str, workflow: dict, result: ConsultationResult) -> bool:
        """
        Execute a composite mode sequence fully driven by YAML.

        Each step in composite_modes[target] may carry:
          use_menu_snapshot: true   — read the open portal via menu_snapshot()
                                      (omit or false → use snapshot())
        """
        steps = workflow['composite_modes'][target]
        for index, step in enumerate(steps, start=1):
            # --- open the trigger ---
            # Settle + rescan first: the trigger can be absent from a premature
            # snapshot (scan before render, esp. fresh ?temporary-chat= page).
            self.runtime.wait_until(
                lambda: self.runtime.snapshot().has(step['trigger']),
                timeout=10,
                interval=0.4,
            )
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, step['trigger'])
            if not trigger:
                result.add_step(
                    f'select_{index}', False,
                    f"ChatGPT trigger {step['trigger']} not found",
                    snapshot=snap.serializable(),
                )
                return False
            if not self._click(trigger):
                result.add_step(
                    f'select_{index}', False,
                    f"ChatGPT trigger {step['trigger']} click failed",
                    snapshot=snap.serializable(),
                )
                return False
            time.sleep(1.0)

            # --- read the portal or document tree depending on YAML flag ---
            if step.get('use_menu_snapshot', False):
                tile_snap = self.runtime.menu_snapshot()
            else:
                tile_snap = self.runtime.snapshot()

            tile = self.find_first(tile_snap, step['target'])
            if not tile:
                result.add_step(
                    f'select_{index}', False,
                    f"ChatGPT tile {step['target']} not visible after trigger",
                    snapshot=tile_snap.serializable(),
                )
                return False

            clicked = self._click(tile)
            verify_snap = self.wait_for_validation(
                step['verification'],
                timeout=6.0,
                interval=0.4,
            )
            verified = clicked and self.validation_passes(verify_snap, step['verification'])
            result.add_step(
                f'select_{index}', verified,
                f"ChatGPT applied {step['target']}",
                selected=step['target'],
                snapshot=verify_snap.serializable(),
            )
            if not verified:
                return False
        return True

    def _apply_model_target(self, target: str, workflow: dict, result: ConsultationResult) -> bool:
        """Open model selector portal and click the target model item."""
        # Settle + rescan FIRST: the persistent model selector can be absent from
        # a premature snapshot — scan fired before the page rendered (esp. on a
        # fresh ?temporary-chat= page). Poll before declaring missing (same
        # readiness pattern as the attach steps).
        self.runtime.wait_until(
            lambda: self.runtime.snapshot().has('model_selector'),
            timeout=10,
            interval=0.4,
        )
        snap = self.runtime.snapshot()
        selector = self.find_first(snap, 'model_selector')
        if not selector:
            result.add_step('select_model', False, 'ChatGPT model selector not found', snapshot=snap.serializable())
            return False
        if not self._click(selector):
            result.add_step('select_model', False, 'ChatGPT model selector click failed', snapshot=snap.serializable())
            return False
        time.sleep(1.0)

        # Model selector is a React portal — must use menu_snapshot()
        dropdown_snap = self.runtime.menu_snapshot()
        target_key = workflow['model_targets'][target]
        item = self.find_first(dropdown_snap, target_key)
        if not item:
            result.add_step('select_model', False, f'ChatGPT menu item {target_key} not found', snapshot=dropdown_snap.serializable())
            return False
        clicked = self._click(item)
        verify_snap = self.wait_for_validation(
            f"{target}_active",
            timeout=6.0,
            interval=0.4,
        )
        verified = clicked and self.validation_passes(verify_snap, f"{target}_active")
        result.add_step('select_model', verified, f'ChatGPT model set to {target}', snapshot=verify_snap.serializable())
        return verified

    def _apply_tool(self, tool_name: str, workflow: dict, result: ConsultationResult) -> bool:
        """Open attach dropdown (React portal) and toggle a tool item."""
        normalized = tool_name.strip().lower().replace(' ', '_')
        target_spec = workflow.get('tool_targets', {}).get(normalized)
        via_key = None
        if isinstance(target_spec, dict):
            target_key = target_spec.get('target')
            via_key = target_spec.get('via')
        else:
            target_key = target_spec
        if not target_key:
            result.add_step('select_tool', False, f'ChatGPT tool {tool_name!r} is not mapped in Consultation V2 YAML')
            return False

        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger or not self._click(trigger):
            result.add_step('select_tool', False, f'ChatGPT failed to open tools dropdown for {tool_name}', snapshot=snap.serializable())
            return False
        time.sleep(1.0)

        if via_key:
            via_snap = self.runtime.menu_snapshot()
            if not self._activate_element(via_snap, via_key, result, 'select_tool',
                                         f'ChatGPT submenu trigger for {tool_name}'):
                return False
            time.sleep(0.6)

        # Attach dropdown is a React portal — must use menu_snapshot()
        dropdown_snap = self.runtime.menu_snapshot()
        item = self.find_first(dropdown_snap, target_key)
        if not item:
            result.add_step('select_tool', False, f'ChatGPT tool item {target_key} not found', snapshot=dropdown_snap.serializable())
            return False
        clicked = self._click(item)
        validation_key = f'{normalized}_active'
        if validation_key not in self.cfg.get('validation', {}):
            verify_snap = self.runtime.snapshot()
            result.add_step(
                'select_tool',
                False,
                f'ChatGPT tool {tool_name!r} has no tree validation key {validation_key!r}',
                snapshot=verify_snap.serializable(),
            )
            return False
        verify_snap = self.wait_for_validation(validation_key, timeout=6.0, interval=0.4)
        verified = bool(clicked and self.validation_passes(verify_snap, validation_key))
        result.add_step('select_tool', verified, f'ChatGPT tool click validated for {tool_name}', snapshot=verify_snap.serializable())
        return verified

    # ------------------------------------------------------------------
    # File attachment
    # ------------------------------------------------------------------

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
            time.sleep(0.7)

            # Attach dropdown is a React portal — must use menu_snapshot()
            portal_snap = self.runtime.menu_snapshot()
            upload_item = self.find_first(portal_snap, 'tool_upload')
            if not upload_item:
                result.add_step('attach', False, f'ChatGPT upload item not found for {abs_path}', snapshot=portal_snap.serializable())
                return False
            clicked = self._click(upload_item)
            if not clicked:
                result.add_step('attach', False, f'ChatGPT upload item click failed for {abs_path}', snapshot=portal_snap.serializable())
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
            result.add_step('attach', verified, f'ChatGPT attached {os.path.basename(abs_path)}', file=abs_path, snapshot=verify_snap.serializable())
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
        from core import input as _inp
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
        # VERIFY the composer holds the intended content before send: the 'Send
        # prompt' button only renders once the composer has text, so prompt_ready
        # is the available "content landed" signal (ChatGPT's ProseMirror does
        # not expose composer text reliably over AT-SPI, so a char-read cannot be
        # trusted here).
        verify_snap = self.wait_for_validation(
            'prompt_ready',
            timeout=8.0,
            interval=0.4,
        )
        verified = bool(pasted and self.validation_passes(verify_snap, 'prompt_ready'))
        result.add_step('prompt', verified, 'ChatGPT prompt entered', snapshot=verify_snap.serializable())
        return verified

    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        # Use the pre-navigation baseline captured in run() — file attachment
        # can change the URL before send, making current_url() stale.
        before = result.session_url_before
        # SEND = focus the composer, then Enter. focus_firefox() alone activates
        # the WINDOW but does NOT put keyboard focus on the ProseMirror
        # contenteditable, so a bare Enter submits nothing (PROD 2026-06-15:
        # select_model+attach+prompt all OK, yet Return did not send, message
        # staged unsent, url stayed at chatgpt.com/). Click an editable composer
        # paragraph node FIRST (structural role+editable selector — the composer
        # is nameless ProseMirror, no findable entry), THEN Enter. Proven live
        # on :2: click editable paragraph -> Enter -> SENT (stop appeared, url ->
        # /c/...). We do NOT click the 'Send prompt' React button (no usable
        # AT-SPI action per 100_TIMES §11) — Enter on the focused composer is the
        # submit.
        attempts = []
        configured_timeout = float(
            self.cfg.get('validation', {}).get('send_success', {}).get('timeout', 120) or 120
        )
        full_timeout = max(120.0, configured_timeout)
        first_probe_timeout = min(12.0, full_timeout)

        for attempt in (1, 2):
            send_snap = None
            focus_node = self._focus_composer()
            if focus_node is None:
                attempts.append({'attempt': attempt, 'focused': False, 'pressed': False})
                if attempt == 2:
                    break
                continue

            pressed = self.runtime.press('Return')
            if not pressed:
                attempts.append({'attempt': attempt, 'focused': True, 'pressed': False})
                if attempt == 2:
                    break
                continue

            timeout = first_probe_timeout if attempt == 1 else full_timeout
            send_snap = self.wait_for_validation('send_success', timeout=timeout, interval=0.6)
            stop_seen = self.validation_passes(send_snap, 'send_success')
            after = self.runtime.wait_for_url_change(
                before,
                timeout=30.0 if stop_seen else 5.0,
                interval=1.0,
            )
            result.session_url_after = after or self.runtime.current_url() or before
            url_changed = bool(result.session_url_after and result.session_url_after != before)
            prompt_still_staged = False
            if attempt == 1 and not stop_seen and not url_changed:
                prompt_still_staged = self.validation_passes(
                    self.runtime.snapshot(),
                    'prompt_ready',
                )
            verified = bool(pressed and stop_seen and (request.session_url or url_changed))
            attempts.append({
                'attempt': attempt,
                'focused': True,
                'pressed': True,
                'stop_seen': stop_seen,
                'url_changed': url_changed,
                'prompt_still_staged': prompt_still_staged,
            })
            if verified:
                verify_snap = send_snap
                result.add_step(
                    'send', True,
                    'ChatGPT send validated by Stop button and URL capture',
                    url_before=before,
                    url_after=result.session_url_after,
                    stop_seen=stop_seen,
                    url_changed=url_changed,
                    attempts=attempts,
                    snapshot=verify_snap.serializable(),
                )
                return True

            # The only retry Jesse authorized here is the focus+Enter path when
            # the first Enter clearly did not land: no Stop, no URL movement, and
            # the prompt is still staged in the composer. If any send evidence
            # appears, do not press Enter again.
            if attempt == 1 and not stop_seen and not url_changed and prompt_still_staged:
                continue
            break

        verify_snap = send_snap or self.runtime.snapshot()
        result.add_step(
            'send', False,
            'ChatGPT send failed validation after focus+Enter retry gate',
            url_before=before,
            url_after=result.session_url_after or self.runtime.current_url() or before,
            attempts=attempts,
            snapshot=verify_snap.serializable(),
        )
        return False

    # ------------------------------------------------------------------
    # Generation monitoring and extraction
    # ------------------------------------------------------------------

    def monitor_generation(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        # Shared stop-transition detector (consultation_v2.completion). ChatGPT
        # send_prompt already gates on the Stop button appearing, so ever_seen is
        # seeded — a fast reply whose Stop button only showed during send still
        # completes. pro_extended is a deep mode (2 stop-gone cycles).
        return super().monitor_generation(request, result, seed_stop_seen=True)

    def extract_primary(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        time.sleep(2.0)
        # RULE: scroll to bottom before extract — a long response's Copy button
        # sits below the fold and is not in the AT-SPI tree until on-screen.
        # Anchor the scroll on the composer's `attach_trigger` push button
        # ("Add files and more"): ChatGPT's composer is nameless ProseMirror
        # paragraphs with NO findable `input` element (live-verified :2
        # 2026-06-15), so find_first('input') returned None and scroll_to_bottom
        # silently no-op'd (None anchor → no scroll → the long-response Copy
        # stayed below the fold). attach_trigger is an EXACT-matched,
        # bottom-anchored composer control — the correct hover anchor.
        self.runtime.scroll_to_bottom(self.find_first(self.runtime.snapshot(), 'attach_trigger'))
        time.sleep(0.6)
        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step('extract_primary', False, 'ChatGPT copy button not found', snapshot=snap.serializable())
            return False
        self.runtime.write_clipboard('')
        time.sleep(0.3)
        if not self.runtime.click(copy_button, strategy='atspi_only'):
            result.add_step('extract_primary', False, 'ChatGPT copy button click failed', snapshot=snap.serializable())
            return False
        time.sleep(1.0)
        content = self.runtime.read_clipboard().strip()
        result.response_text = content
        verified = bool(content) and content != request.message
        result.add_step('extract_primary', verified, f'ChatGPT response copied ({len(content)} chars)', characters=len(content), preview=content[:200])
        return verified

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
