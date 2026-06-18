from __future__ import annotations

import logging
import os
import time
from typing import Optional

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import ConsultationRequest, ConsultationResult, ExtractedArtifact

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


logger = logging.getLogger(__name__)


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
        if not self.tree_conformance_gate(result):
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

    @staticmethod
    def _bottommost_input(snapshot):
        inputs = list((snapshot.mapped or {}).get('input') or [])
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
            return self._bottommost_input(snap)

        node = self.runtime.wait_until(_find_input_entry, timeout=10, interval=0.4)
        if node is None:
            return None

        for click_attempt in (1, 2):
            if not self.runtime.click(node):
                if click_attempt == 2:
                    return None
                continue
            time.sleep(0.25)

            consecutive_focused = 0

            def _focused_input_entry():
                nonlocal consecutive_focused
                snap = self.runtime.snapshot()
                focused = self._bottommost_input(snap)
                states = {s.lower() for s in (focused.states or [])} if focused else set()
                if focused and 'focused' in states:
                    consecutive_focused += 1
                    if consecutive_focused >= 2:
                        return focused
                else:
                    consecutive_focused = 0
                return None

            focused = self.runtime.wait_until(_focused_input_entry, timeout=5.0, interval=0.25)
            if focused is not None:
                return focused

            refreshed = self._bottommost_input(self.runtime.snapshot())
            if refreshed is not None:
                node = refreshed

        return None

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
        from consultation_v2 import input as _inp

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
        # SEND = exact mapped input focus -> Return. Each attempt clicks the
        # YAML-declared input entry, waits for focused state in two fresh AT-SPI
        # scans, then presses Return. If post-send Stop/URL validation fails and
        # the prompt is still staged, the loop re-clicks the input and retries
        # once. We do NOT click the 'Send prompt' React button (no usable AT-SPI
        # action per 100_TIMES §11).
        attempts = []
        configured_timeout = float(
            self.cfg.get('validation', {}).get('send_success', {}).get('timeout', 120) or 120
        )
        full_timeout = max(120.0, configured_timeout)
        first_probe_timeout = min(12.0, full_timeout)

        for attempt in (1, 2):
            send_snap = None
            focus_node = self._focus_composer()
            focus_evidence = self._element_evidence(focus_node)
            if focus_node is None:
                attempts.append({'attempt': attempt, 'focused': False, 'pressed': False})
                if attempt == 2:
                    break
                continue

            pressed = self.runtime.press('Return')
            if not pressed:
                attempts.append({
                    'attempt': attempt,
                    'focused': True,
                    'pressed': False,
                    'focus_node': focus_evidence,
                })
                if attempt == 2:
                    break
                continue

            timeout = first_probe_timeout if attempt == 1 else full_timeout
            send_snap = self.wait_for_validation('send_success', timeout=timeout, interval=0.6)
            stop_seen = self.validation_passes(send_snap, 'send_success')
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
            prompt_still_staged = False
            if attempt == 1 and not stop_seen and not answer_thread:
                prompt_still_staged = self.validation_passes(
                    self.runtime.snapshot(),
                    'prompt_ready',
                )
            verified = bool(pressed and stop_seen and answer_thread)
            attempts.append({
                'attempt': attempt,
                'focused': True,
                'focus_node': focus_evidence,
                'pressed': True,
                'stop_seen': stop_seen,
                'url_changed': url_changed,
                'answer_thread': answer_thread,
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
            # the first Enter clearly did not land: no Stop, no answer-thread URL, and
            # the prompt is still staged in the composer. If any send evidence
            # appears, do not press Enter again.
            if attempt == 1 and not stop_seen and not answer_thread and prompt_still_staged:
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

    def _hover_above_composer_for_copy_button(self) -> dict:
        from consultation_v2 import input as _inp

        extract_cfg = self.cfg.get('workflow', {}).get('extract', {}) or {}
        anchor_key = str(extract_cfg.get('hover_anchor_key') or 'input')
        try:
            offset_y = int(extract_cfg.get('hover_offset_y') or 60)
        except (TypeError, ValueError):
            offset_y = 60
        evidence = {
            'ok': False,
            'source': 'composer_relative',
            'anchor_key': anchor_key,
            'hover_offset_y': offset_y,
        }
        for _ in range(8):
            snap = self.runtime.snapshot()
            anchor = self.find_last(snap, anchor_key) or self.find_first(snap, anchor_key)
            if anchor:
                rect = self._screen_rect(anchor.atspi_obj)
                if rect:
                    x = int(rect['x'] + rect['width'] // 2)
                    y = max(0, int(rect['y']) - offset_y)
                elif anchor.x is not None and anchor.y is not None:
                    x = int(anchor.x)
                    y = max(0, int(anchor.y) - offset_y)
                else:
                    time.sleep(0.25)
                    continue
                hover_ok = bool(_inp.hover(x, y))
                time.sleep(0.4)

                def _copy_button_visible():
                    copy_snap = self.runtime.snapshot()
                    return copy_snap if (copy_snap.mapped.get('copy_button') or []) else None

                copy_snap = self.runtime.wait_until(
                    _copy_button_visible,
                    timeout=4.0,
                    interval=0.4,
                )
                copy_buttons = (copy_snap.mapped.get('copy_button') or []) if copy_snap else []
                evidence.update({
                    'x': x,
                    'y': y,
                    'anchor_name': anchor.name,
                    'anchor_role': anchor.role,
                    'anchor_rect': rect,
                    'anchor': anchor.serializable(),
                    'hover_ok': hover_ok,
                    'copy_buttons_found': len(copy_buttons),
                    'copy_buttons': [button.serializable() for button in copy_buttons[-3:]],
                })
                evidence['ok'] = bool(hover_ok and copy_buttons)
                logger.warning(
                    'ChatGPT extract hover probe: x=%s y=%s ok=%s '
                    'anchor_key=%r anchor_name=%r anchor_role=%r rect=%s '
                    'copy_buttons=%s',
                    x,
                    y,
                    evidence['ok'],
                    anchor_key,
                    anchor.name,
                    anchor.role,
                    rect,
                    len(copy_buttons),
                )
                return evidence
            time.sleep(0.25)
        logger.warning('ChatGPT extract hover probe: no mapped composer anchor found')
        return evidence

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
        last_snapshot = None
        all_elements: list[dict] = []
        scroll_evidence = {}
        hover_evidence = {}
        for attempt in range(5):
            time.sleep(2.0)
            scroll_evidence = self._scroll_chatgpt_thread_to_bottom()
            if not scroll_evidence.get('ok'):
                result.add_step(
                    'extract_primary', False,
                    'ChatGPT thread scroll-to-bottom failed before Copy response hover',
                    attempt=attempt + 1,
                    scroll=scroll_evidence,
                    snapshot=last_snapshot.serializable() if last_snapshot else {},
                )
                return False
            hover_evidence = self._hover_above_composer_for_copy_button()
            result.add_step(
                'extract_hover_probe',
                bool(hover_evidence.get('ok')),
                'ChatGPT composer-relative hover probe before Copy response scan',
                attempt=attempt + 1,
                scroll=scroll_evidence,
                hover=hover_evidence,
            )
            if not hover_evidence.get('ok'):
                result.add_step(
                    'extract_primary', False,
                    'ChatGPT composer-relative hover failed to mount Copy response',
                    attempt=attempt + 1,
                    scroll=scroll_evidence,
                    hover=hover_evidence,
                    snapshot=last_snapshot.serializable() if last_snapshot else {},
                )
                return False
            time.sleep(0.5)
            last_snapshot = self.runtime.snapshot()
            time.sleep(0.8)

            firefox = find_firefox_for_platform(self.platform)
            if not firefox:
                continue
            try:
                firefox.clear_cache_single()
            except Exception:
                pass
            all_elements = raw_find_elements(firefox, fence_after=[])
            copy_buttons = [
                element for element in all_elements
                if matches_spec(element, copy_spec)
                and element.get('y') is not None
            ]
            if not copy_buttons:
                continue

            target = max(copy_buttons, key=lambda element: int(element.get('y') or 0))
            clipboard.write('')
            time.sleep(0.3)
            if not atspi_click(target):
                continue
            time.sleep(1.2)
            content = (clipboard.read() or '').strip()
            if content and not self._is_prompt_echo(content, request):
                result.response_text = content
                result.add_step(
                    'extract_primary', True,
                    f'ChatGPT response copied ({len(content)} chars, attempt {attempt + 1})',
                    characters=len(content),
                    preview=content[:200],
                    scroll=scroll_evidence,
                    hover=hover_evidence,
                    copy_buttons_found=len(copy_buttons),
                    copy_button={k: target.get(k) for k in ('name', 'role', 'x', 'y')},
                )
                return True
            if content:
                result.add_step(
                    'extract_primary_echo_rejected', True,
                    'ChatGPT copied prompt echo; continuing response-copy search',
                    characters=len(content),
                    preview=content[:200],
                    attempt=attempt + 1,
                    scroll=scroll_evidence,
                    hover=hover_evidence,
                    copy_button={k: target.get(k) for k in ('name', 'role', 'x', 'y')},
                )

        result.add_step(
            'extract_primary', False,
            'ChatGPT response copy button not found or only prompt echo copied',
            elements=len(all_elements),
            last_scroll=scroll_evidence,
            last_hover=hover_evidence,
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
