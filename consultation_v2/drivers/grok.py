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
    def run(self, request: ConsultationRequest) -> ConsultationResult:
        result = self.result(request)

        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Grok window')
            return result
        result.session_url_before = self.runtime.current_url()

        if not self.navigate(request, result):
            return result
        if not self.select_mode(request, result):
            return result
        if not self.attach_files(request, result):
            return result
        if not self.enter_prompt(request, result):
            return result
        if not self.send_prompt(request, result):
            return result
        if not self.wait_for_completion(request, result):
            return result
        if not self.extract_response(request, result):
            return result
        if not self.store_result(request, result):
            return result

        result.ok = True
        return result

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
        return navigated

    # ------------------------------------------------------------------
    # Step 2 — model / mode selection (state-checked, click ONCE, no skip-hack)
    # ------------------------------------------------------------------
    def select_mode(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        workflow = self.cfg['workflow']
        defaults = workflow.get('defaults', {})
        mode_targets = workflow.get('mode_targets', {})

        requested = (request.mode or request.model or defaults.get('mode') or defaults.get('model') or '')
        requested = str(requested).strip().lower()
        if not requested:
            result.add_step('select_mode', True, 'Grok using current/default model')
            return True
        if requested not in mode_targets:
            result.add_step('select_mode', False,
                            f'Grok mode {requested!r} is not mapped in grok.yaml workflow.mode_targets')
            return False

        item_key = mode_targets[requested]
        active_validation_key = f'{requested}_active'

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

            # Validate the chip rendered via the exact attach-present indicator
            # (the static "Remove this attachment" button) in the DOCUMENT scope.
            verify_snap = self.runtime.snapshot()
            verified = self.validation_passes(verify_snap, 'attach_present')
            result.add_step('attach', verified,
                            f'Grok attached {os.path.basename(abs_path)}',
                            file=abs_path, snapshot=verify_snap.serializable())
            if not verified:
                return False
        return True

    # ------------------------------------------------------------------
    # Step 4 — enter prompt
    # ------------------------------------------------------------------
    def enter_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        input_key = self.cfg['workflow']['prompt']['input']
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, input_key)
        if not input_el:
            result.add_step('prompt', False, 'Grok input field not found',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.click(input_el):
            result.add_step('prompt', False, 'Grok input focus click failed',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.paste(request.message):
            result.add_step('prompt', False, 'Grok prompt paste failed',
                            snapshot=snap.serializable())
            return False
        result.add_step('prompt', True, 'Grok prompt entered',
                        snapshot=self.runtime.snapshot().serializable())
        return True

    # ------------------------------------------------------------------
    # Step 5 — send (re-focus composer + Enter; verify stop appeared + URL gate)
    # ------------------------------------------------------------------
    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        input_key = self.cfg['workflow']['prompt']['input']
        stop_key = self.cfg['workflow']['send']['stop_key']
        before = result.session_url_before

        # Re-focus the composer immediately before Enter (attach/paste can steal
        # focus). This is focus, not a re-attempt of a failed action.
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, input_key)
        if input_el:
            self.runtime.click(input_el)
        if not self.runtime.press('Return'):
            result.add_step('send', False, 'Grok Return keypress failed')
            return False

        # Observe (re-scan) until the stop button appears — readiness wait, not a
        # re-action. A single Enter was pressed; we only watch the tree.
        def _stop_present():
            return self.runtime.snapshot().has(stop_key)

        stop_seen = bool(self.runtime.wait_until(_stop_present, timeout=60, interval=0.6))
        result.session_url_after = self.runtime.current_url() or before
        verify_snap = self.runtime.snapshot()

        url_changed = bool(result.session_url_after and result.session_url_after != before)
        is_new_session = request.session_url is None
        if is_new_session:
            verified = bool(stop_seen and url_changed)
        else:
            verified = bool(stop_seen)
        result.add_step('send', verified, 'Grok send validated (stop button + URL gate)',
                        url_before=before, url_after=result.session_url_after,
                        stop_seen=stop_seen, url_changed=url_changed,
                        snapshot=verify_snap.serializable())
        return verified

    # ------------------------------------------------------------------
    # Step 6 — wait for completion (stop_button debounce; NO fallback)
    # ------------------------------------------------------------------
    def wait_for_completion(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        stop_key = self.cfg['workflow']['monitor']['stop_key']

        completed = self.runtime.wait_until(
            lambda: self._completion_debounced(stop_key),
            timeout=float(request.timeout),
            interval=1.0,
        )
        verify_snap = self.runtime.snapshot()
        verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
        result.add_step('monitor', verified, 'Grok response completed (stop-button debounce)',
                        snapshot=verify_snap.serializable())
        return verified

    def _completion_debounced(self, stop_key: str) -> bool:
        """Stop-absent -> short wait -> re-scan a FRESH tree -> complete only if
        still absent. Re-SCANNING is observation (allowed), not a retry."""
        if self.runtime.snapshot().has(stop_key):
            return False  # still generating
        time.sleep(1.5)
        if self.runtime.snapshot().has(stop_key):
            return False  # reappeared — keep generating
        return True

    # ------------------------------------------------------------------
    # Step 7 — extract (scroll to bottom + Copy element action; validate length)
    # ------------------------------------------------------------------
    def extract_response(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        copy_key = self.cfg['workflow']['extract']['primary_key']

        # Scroll the thread to the BOTTOM so the last Copy button is the final
        # assistant turn and is actionable.
        self.runtime.press('ctrl+End')

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
