"""Isolated Grok consultation driver (consultation_v2).

Imports ONLY from the shared core (base / types / runtime / snapshot /
yaml_contract). Carries ZERO Grok-specific strings: every element name, role,
and key is read from ``consultation_v2/platforms/grok.yaml`` via ``self.cfg``.

Contract (DRIVER_CONTRACT A-J / 100_TIMES):
  * EXACT-match YAML only; the driver never hardcodes a platform string.
  * ZERO retries on any action (100_TIMES §4a): a first-try miss returns
    failure (STOP + escalate) — never a re-click, settle-poll, or fallback.
  * Completion = stop_button debounce (absent -> re-scan fresh tree -> complete
    only if still absent). NO fallback completion.
  * Extract = scroll to bottom (Ctrl+End) then the Copy button via its AT-SPI
    element action; validate length >> prompt.
"""
from __future__ import annotations

import os
import time

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


class GrokConsultationDriver(BaseConsultationDriver):
    platform = 'grok'

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    # run() is the shared two-phase template on BaseConsultationDriver (FLOW §10):
    # it holds the DISPLAY-scoped dispatch lock across setup_and_send (below) and
    # releases it before monitor_and_extract so monitoring runs concurrently.

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): navigate → mode → attach → prompt →
        guarded send + monitor registration."""
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Grok window')
            return False
        result.session_url_before = self.runtime.current_url()

        if not self.navigate(request, result):
            return False
        if not self.select_mode(request, result):
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
        """UNLOCKED phase (FLOW §10): wait for completion → extract → store.
        Display lock is already released so a concurrent consultation can set
        up/send here."""
        if not self.wait_for_completion(request, result):
            return
        if not self.extract_response(request, result):
            return
        if not self.store_result(request, result):
            return
        result.ok = True

    # ------------------------------------------------------------------
    # Step 1 — navigate
    # ------------------------------------------------------------------
    def navigate(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not target_url:
            result.add_step('navigate', True, 'Grok using current tab (no target URL)')
            return True
        verify = bool(urls.get('verify_navigation')) and request.session_url is None
        navigated = self.runtime.navigate(target_url, verify_change=verify)
        snap = self.runtime.snapshot()
        result.add_step('navigate', navigated, 'Navigated to Grok target',
                        target_url=target_url, snapshot=snap.serializable())
        if not navigated:
            return False
        return self.wait_for_page_ready_after_navigation(result)

    # ------------------------------------------------------------------
    # Step 2 — model / mode selection (state-checked, click ONCE, no skip-hack)
    # ------------------------------------------------------------------
    def select_mode(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        workflow = self.cfg['workflow']
        defaults = workflow.get('defaults', {})
        selection = workflow.get('selection', {})
        mode_targets = selection.get('mode_targets', {})
        model_targets = selection.get('model_targets', {})

        requested_mode = request.selection_value('mode') or defaults.get('mode') or ''
        requested_model = request.selection_value('model') or defaults.get('model') or ''
        requested = requested_mode or requested_model
        requested = str(requested).strip().lower()
        if not requested:
            result.add_step('select_mode', True, 'Grok using current/default model')
            return True
        target_map = mode_targets if requested_mode else model_targets
        target_kind = 'mode' if requested_mode else 'model'
        if requested not in target_map:
            result.add_step('select_mode', False,
                            f'Grok {target_kind} {requested!r} is not mapped in grok.yaml workflow.selection.{target_kind}_targets')
            return False

        item_key = target_map[requested]
        active_validation_key = f'{requested}_active'

        # ONE bounded readiness wait (DRIVER_CONTRACT §E — allowed: a single
        # readiness wait before a SINGLE action). A cold navigate to the grok.com
        # home page renders the composer/toolbar slower than a warm thread, so the
        # model_selector may not be in the tree the instant navigate() returns.
        # Re-SNAPSHOT here is observation (waiting for the page to render), NOT a
        # retry of any action. After the page is ready we open the dropdown ONCE.
        self.runtime.wait_until(
            lambda: self.runtime.snapshot().has('model_selector'),
            timeout=12,
            interval=0.5,
        )

        # Open the model dropdown ONCE (a single, necessary action — not a retry).
        snap = self.runtime.snapshot()
        selector = self.find_first(snap, 'model_selector')
        if not selector:
            result.add_step('select_mode', False, 'Grok model selector not found',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.click(selector):
            result.add_step('select_mode', False, 'Grok model selector click failed',
                            snapshot=snap.serializable())
            return False

        # ONE bounded readiness wait (DRIVER_CONTRACT §E) — the dropdown's menu
        # items ("Heavy Team of Experts" etc.) render a beat after the selector
        # click, so menu_snapshot() can fire before they exist. Re-SNAPSHOT here
        # is observation while the portal renders; the selector is NOT re-clicked.
        # Ready = the target item is present OR the current-mode active indicator
        # already shows (the dropdown rendered with this mode selected).
        self.runtime.wait_until(
            lambda: (self.runtime.menu_snapshot().has(item_key)
                     or self.validation_passes(self.runtime.menu_snapshot(), active_validation_key)),
            timeout=10,
            interval=0.4,
        )

        menu = self.runtime.menu_snapshot()

        # State check: if the requested item is already the active model, do NOT
        # click it — close the dropdown and report success.
        if self.validation_passes(menu, active_validation_key):
            self.runtime.press('Escape')
            result.add_step('select_mode', True, f'Grok {requested} already active (no click)',
                            snapshot=menu.serializable())
            return True

        item = self.find_first(menu, item_key)
        if not item:
            self.runtime.press('Escape')
            result.add_step('select_mode', False,
                            f'Grok model item {item_key!r} not found in dropdown',
                            snapshot=menu.serializable())
            return False
        if not self.runtime.click(item):
            self.runtime.press('Escape')
            result.add_step('select_mode', False,
                            f'Grok model item click failed for {item_key!r}',
                            snapshot=menu.serializable())
            return False

        result.add_step('select_mode', True, f'Grok model set to {requested}')
        return True

    # ------------------------------------------------------------------
    # Step 3 — attach (exact Attach -> menu_snapshot -> exact Upload a file,
    #          ONCE each; no stale-cache, no re-click recovery)
    # ------------------------------------------------------------------
    def attach_files(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        if not request.attachments:
            result.add_step('attach', True, 'No Grok attachments requested')
            return True

        attachment = self.cfg['workflow']['attachment']
        trigger_key = attachment['trigger']
        upload_key = attachment['menu_target']

        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            self.runtime.close_stale_dialogs()

            # Resolve the Attach push button FRESH from a current snapshot
            # (no stale/cached element) and click it ONCE.
            # Settle + rescan FIRST (DRIVER_CONTRACT §E): the persistent Attach
            # trigger can be absent from a *premature* snapshot — a scan fired
            # before the page finished rendering (right after navigate). Poll for
            # it (observation only, no re-click) before declaring it missing, the
            # same readiness pattern the model-select + upload-item steps use.
            self.runtime.wait_until(
                lambda: self.runtime.snapshot().has(trigger_key),
                timeout=10,
                interval=0.4,
            )
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, trigger_key)
            if not trigger:
                result.add_step('attach', False, f'Grok attach trigger missing for {abs_path}',
                                snapshot=snap.serializable())
                return False
            if not self.runtime.click(trigger):
                result.add_step('attach', False, f'Grok attach trigger click failed for {abs_path}',
                                snapshot=snap.serializable())
                return False

            # ONE bounded readiness wait (DRIVER_CONTRACT §E) — the attach
            # dropdown's menu items ("Upload a file" etc.) render a beat after the
            # Attach click, so menu_snapshot() can fire before they exist.
            # Re-SNAPSHOT here is observation while the portal renders; the Attach
            # trigger is NOT re-clicked.
            self.runtime.wait_until(
                lambda: self.runtime.menu_snapshot().has(upload_key),
                timeout=10,
                interval=0.4,
            )

            # Read the dropdown via menu_snapshot (React portal). If the exact
            # Upload item is absent on this single read, that is a STOP/failure
            # — NOT a re-click (the wrong-menu re-click was the §4a bug).
            menu = self.runtime.menu_snapshot()
            upload_item = self.find_first(menu, upload_key)
            if not upload_item:
                result.add_step('attach', False,
                                f'Grok upload item {upload_key!r} not in attach menu for {abs_path}',
                                snapshot=menu.serializable())
                return False
            if not self.runtime.click(upload_item):
                result.add_step('attach', False, f'Grok upload item click failed for {abs_path}',
                                snapshot=menu.serializable())
                return False

            # GTK file dialog: focus it, type the absolute path, confirm ONCE.
            self.runtime.focus_file_dialog()
            self.runtime.press('ctrl+l')
            if not self.runtime.paste(abs_path):
                self.runtime.type_text(abs_path, delay_ms=5)
            self.runtime.press('Return')

            # ONE bounded readiness wait (DRIVER_CONTRACT §E — a single readiness
            # wait before a SINGLE action/check; NOT a retry of the upload). Grok
            # renders the chip + its "Remove this attachment" button slightly after
            # the file dialog closes, same render-race as mode-select; re-SNAPSHOT
            # here is observation while the chip renders. The upload is NOT
            # re-performed — we only wait for the indicator, then validate ONCE.
            # Validate the chip rendered via the exact attach-present indicator
            # (the static "Remove this attachment" button) in the DOCUMENT scope.
            verify_snap = self.wait_for_validation(
                'attach_present',
                timeout=15.0,
                interval=0.5,
            )
            verified = self.validation_passes(verify_snap, 'attach_present')
            result.add_step('attach', verified,
                            f'Grok attached {os.path.basename(abs_path)}',
                            file=abs_path, snapshot=verify_snap.serializable())
            if not verified:
                return False
        return True

    # ------------------------------------------------------------------
    # Shared: focus the composer the PROVEN way (coord-click + grab_focus)
    # ------------------------------------------------------------------
    def _focus_input(self):
        """Focus the composer like the battle-tested scripts/consultation.py::
        _focus_input_field: coordinate-click the input, then grab_focus() on its
        AT-SPI component. A plain element click alone does NOT reliably land
        keyboard focus on grok's composer (verify6: focus+Enter failed without
        grab_focus). Returns the resolved input ElementRef, or None if absent."""
        input_key = self.cfg['workflow']['prompt']['input']
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, input_key)
        if not input_el:
            return None
        # 1) coordinate click on the input (xdotool), 2) grab_focus on its
        # component interface — mirrors the proven path exactly.
        self.runtime.click(input_el, strategy='coordinate_only')
        time.sleep(0.3)
        obj = input_el.atspi_obj
        if obj is not None:
            try:
                comp = obj.get_component_iface()
                if comp:
                    comp.grab_focus()
            except Exception:
                pass
        time.sleep(0.3)
        return input_el

    # ------------------------------------------------------------------
    # Step 4 — enter prompt
    # ------------------------------------------------------------------
    def enter_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        input_el = self._focus_input()
        if not input_el:
            result.add_step('prompt', False, 'Grok input field not found',
                            snapshot=self.runtime.snapshot().serializable())
            return False
        if not self.runtime.paste(request.message):
            result.add_step('prompt', False, 'Grok prompt paste failed',
                            snapshot=self.runtime.snapshot().serializable())
            return False
        result.add_step('prompt', True, 'Grok prompt entered',
                        snapshot=self.runtime.snapshot().serializable())
        return True

    # ------------------------------------------------------------------
    # Step 5 — send (re-focus composer the proven way + Return; stop|URL gate)
    # ------------------------------------------------------------------
    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        before = result.session_url_before

        # Re-focus the composer immediately before send (attach/paste steals
        # focus) the PROVEN way (coord-click + grab_focus), then submit with a
        # single Return. This is the battle-tested scripts/consultation.py grok
        # path. The Submit-button doAction was intermittent (worked verify7,
        # failed verify9 leaving the message unsent) — Return on a grab_focus'd
        # composer is the reliable submit. This is focus, not a re-attempt.
        input_el = self._focus_input()
        if not input_el:
            result.add_step('send', False, 'Grok input field not found for send',
                            snapshot=self.runtime.snapshot().serializable())
            return False
        if not self.runtime.press('Return'):
            result.add_step('send', False, 'Grok Return keypress failed')
            return False

        send_snap = self.wait_for_validation('send_fired', timeout=12.0, interval=0.5)
        stop_seen = self.validation_passes(send_snap, 'send_fired')
        # Carry the send-phase stop observation into the shared completion
        # detector (a fast reply can clear the stop button before monitor runs).
        self._send_stop_seen = bool(stop_seen)
        after = self.runtime.wait_for_url_change(before, timeout=30.0, interval=1.0)
        result.session_url_after = after or self.runtime.current_url() or before
        verify_snap = self.runtime.snapshot()

        url_changed = bool(result.session_url_after and result.session_url_after != before)
        is_new_session = request.session_url is None
        if is_new_session:
            verified = bool(stop_seen and url_changed)
        else:
            verified = bool(stop_seen and result.session_url_after)
        result.add_step('send', verified, 'Grok send validated by Stop button and URL capture',
                        url_before=before, url_after=result.session_url_after,
                        stop_seen=stop_seen, url_changed=url_changed,
                        snapshot=verify_snap.serializable())
        return verified

    # ------------------------------------------------------------------
    # Step 6 — wait for completion — shared stop-transition detector
    # (consultation_v2.completion via BaseConsultationDriver.monitor_generation).
    # 'heavy' is a deep mode (2 stop-gone cycles) — the prior bespoke 1.5s
    # debounce was a single re-scan; the shared 2-cycle gate is the stronger,
    # canonical form. The send-phase stop observation is seeded.
    # ------------------------------------------------------------------
    def wait_for_completion(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        defaults = self.cfg['workflow'].get('defaults', {})
        resolved_mode = (
            request.selection_value('mode')
            or request.selection_value('model')
            or defaults.get('mode')
            or defaults.get('model')
            or ''
        )
        return self.monitor_generation(
            request, result, mode=str(resolved_mode),
            seed_stop_seen=getattr(self, '_send_stop_seen', False),
        )

    # ------------------------------------------------------------------
    # Step 7 — extract (scroll to bottom + Copy element action; validate length)
    # ------------------------------------------------------------------
    def extract_response(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        copy_key = self.cfg['workflow']['extract']['primary_key']

        # Scroll the thread to the BOTTOM so the last Copy button is the final
        # assistant turn and is actionable.
        self.runtime.press('ctrl+End')

        # ONE bounded readiness wait (DRIVER_CONTRACT §E) — the Copy button on the
        # final assistant turn can render a beat after the stop button disappears
        # / after the scroll settles. Re-SNAPSHOT here is observation; the Copy
        # button is NOT clicked until found ONCE below.
        self.runtime.wait_until(
            lambda: self.runtime.snapshot().has(copy_key),
            timeout=10,
            interval=0.4,
        )

        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, copy_key)
        if not copy_button:
            result.add_step('extract', False, 'Grok copy button not found',
                            snapshot=snap.serializable())
            return False

        self.runtime.write_clipboard('')
        # Click the Copy button via its AT-SPI element action (never raw x/y).
        if not self.runtime.click(copy_button, strategy='atspi_only'):
            result.add_step('extract', False, 'Grok copy button AT-SPI action failed',
                            snapshot=snap.serializable())
            return False

        # ONE bounded readiness wait (DRIVER_CONTRACT §E) — the copy button's
        # clipboard write completes a beat after the element action returns;
        # reading immediately yields 0 chars. Re-READING the clipboard is
        # observation (the copy button is NOT re-clicked), so we poll until it
        # populates, then read ONCE. Still empty after the wait -> real STOP.
        self.runtime.wait_until(
            lambda: bool(self.runtime.read_clipboard().strip()),
            timeout=4,
            interval=0.3,
        )

        content = self.runtime.read_clipboard().strip()
        result.response_text = content
        # Validate the extract is real: non-empty, longer than the prompt, not an echo.
        verified = bool(content) and content != request.message and len(content) > len(request.message)
        result.add_step('extract', verified, f'Grok response copied ({len(content)} chars)',
                        characters=len(content), prompt_len=len(request.message),
                        preview=content[:200])
        return verified

    # ------------------------------------------------------------------
    # Step 8 — store
    # ------------------------------------------------------------------
    def store_result(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step('store', True, 'Grok Neo4j storage skipped', storage=result.storage)
            return True
        try:
            session_url = (result.session_url_after or result.session_url_before
                           or self.runtime.current_url() or '')
            session_id = neo4j_client.get_or_create_session(self.platform, session_url)
            user_message_id = neo4j_client.add_message(
                session_id, 'user', request.message, request.attachments)
            assistant_message_id = neo4j_client.add_message(
                session_id, 'assistant', result.response_text,
                self.serialize_artifacts(result.extractions))
            result.storage = {
                'session_id': session_id,
                'user_message_id': user_message_id,
                'assistant_message_id': assistant_message_id,
                'url': session_url,
            }
            result.add_step('store', True, 'Grok response stored in Neo4j', storage=result.storage)
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step('store', False, f'Grok Neo4j storage failed: {exc}')
            return False
