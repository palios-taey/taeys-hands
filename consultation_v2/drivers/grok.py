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
from urllib.parse import urlparse

from consultation_v2 import display_readiness
from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, Snapshot

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
        if request.session_url:
            navigated = self.runtime.navigate(target_url, verify_change=False)
            snap = self.runtime.snapshot()
            result.add_step('navigate', navigated, 'Navigated to Grok target',
                            target_url=target_url, snapshot=snap.serializable())
            if not navigated:
                return False
            return self.wait_for_page_ready_after_navigation(result)

        verify = False
        navigated = self.runtime.navigate(target_url, verify_change=verify)
        snap = self.runtime.snapshot()
        result.add_step('navigate', navigated, 'Navigated to Grok target',
                        target_url=target_url, fresh_chat_required=True,
                        verify_change=verify, snapshot=snap.serializable())
        if not navigated:
            return False
        if not self._trigger_new_chat(result, snap):
            return False
        return self._wait_for_fresh_chat_ready(result)

    def _trigger_new_chat(self, result: ConsultationResult, snapshot: Snapshot) -> bool:
        nav_cfg = (self.cfg.get('workflow') or {}).get('navigate') or {}
        key = nav_cfg.get('new_chat_key') or nav_cfg.get('new_chat')
        shortcut = nav_cfg.get('new_chat_shortcut')
        element = snapshot.first(key) if isinstance(key, str) else None

        if isinstance(key, str) and not element:
            element = self.runtime.wait_until(
                lambda: self.runtime.snapshot().first(key),
                timeout=3.0,
                interval=0.4,
            )

        if isinstance(element, ElementRef):
            clicked = self.runtime.click(element)
            result.add_step(
                'new_chat',
                clicked,
                'Triggered Grok new chat',
                action='click',
                key=key,
                element=element.serializable(),
            )
            return clicked

        if isinstance(shortcut, str) and shortcut.strip():
            self.runtime.focus_firefox()
            pressed = self.runtime.press(shortcut)
            result.add_step(
                'new_chat',
                pressed,
                'Triggered Grok new chat',
                action='shortcut',
                shortcut=shortcut,
                configured_key=key,
                mapped_before=bool(snapshot.has(key)) if isinstance(key, str) else False,
            )
            return pressed

        result.add_step(
            'new_chat',
            False,
            'Grok new chat affordance missing from YAML/current tree',
            configured_key=key,
            configured_shortcut=shortcut,
            snapshot=snapshot.serializable(),
        )
        return False

    def _wait_for_fresh_chat_ready(
        self,
        result: ConsultationResult,
        *,
        timeout: float = 15.0,
    ) -> bool:
        nav_cfg = (self.cfg.get('workflow') or {}).get('navigate') or {}
        prompt_cfg = (self.cfg.get('workflow') or {}).get('prompt') or {}
        input_key = nav_cfg.get('fresh_input_key') or prompt_cfg.get('input') or 'input'
        groups = self._page_ready_key_groups()
        started = time.time()
        last_snapshot: Snapshot | None = None
        last_evidence: dict[str, object] = {}

        def _probe() -> Snapshot | None:
            nonlocal last_snapshot, last_evidence
            snap = self.runtime.snapshot()
            last_snapshot = snap
            input_el = snap.first(input_key) if isinstance(input_key, str) else None
            input_states = self._state_set(input_el)
            missing = self._page_ready_missing_groups(snap, groups)
            input_text, input_text_observed, input_text_source = self._input_text(input_el)
            input_editable = 'editable' in input_states
            remove_attachment_present = snap.has('remove_attachment')
            current_url = (self.runtime.current_url() or snap.url or '').strip()
            fresh_url = self._is_fresh_chat_url(current_url)
            input_text_length = len(input_text)
            input_observed_empty = bool(
                input_text == ''
                and (
                    input_text_observed
                    or (input_text_source == 'unobserved' and input_text_length == 0)
                )
            )
            last_evidence = {
                'required': self._page_ready_group_labels(groups),
                'missing': missing,
                'current_url': current_url,
                'fresh_url': fresh_url,
                'input_key': input_key,
                'input_present': input_el is not None,
                'input_states': sorted(input_states),
                'input_editable': input_editable,
                'input_observed_empty': input_observed_empty,
                'input_text_observed': input_text_observed,
                'input_text_source': input_text_source,
                'input_text_length': input_text_length,
                'remove_attachment_present': remove_attachment_present,
                'optional_present': self._page_ready_present_optional_keys(snap),
            }
            if not (
                fresh_url
                and input_el is not None
                and input_editable
                and input_observed_empty
                and not remove_attachment_present
            ):
                return None
            return snap

        matched = self.runtime.wait_until(_probe, timeout=max(float(timeout), 15.0), interval=0.4)
        if isinstance(matched, Snapshot):
            readiness = display_readiness.check(self.platform)
            readiness_ok = (
                bool(readiness.get('ready'))
                and readiness.get('windows') == 1
                and readiness.get('tabs') == 1
            )
            if not readiness_ok:
                result.add_step(
                    'page_ready',
                    False,
                    'Grok fresh composer ready but display topology is not isolated',
                    elapsed_seconds=round(time.time() - started, 2),
                    readiness=readiness,
                    snapshot=matched.serializable(),
                    **last_evidence,
                )
                return False
            result.add_step(
                'page_ready',
                True,
                'Grok fresh composer ready after navigation',
                elapsed_seconds=round(time.time() - started, 2),
                readiness=readiness,
                snapshot=matched.serializable(),
                **last_evidence,
            )
            return True

        snapshot = last_snapshot or self.runtime.snapshot()
        result.add_step(
            'page_ready',
            False,
            'Grok fresh composer not ready after new-chat action',
            timeout_seconds=max(float(timeout), 15.0),
            snapshot=snapshot.serializable(),
            **last_evidence,
        )
        return False

    @staticmethod
    def _is_fresh_chat_url(url: str | None) -> bool:
        parsed = urlparse((url or '').strip())
        if parsed.netloc and parsed.netloc not in {'grok.com', 'www.grok.com'}:
            return False
        path = (parsed.path or '/').rstrip('/')
        return path in {'', '/'}

    @staticmethod
    def _state_set(element: ElementRef | None) -> set[str]:
        if element is None:
            return set()
        return {str(state).lower() for state in (element.states or [])}

    @staticmethod
    def _input_text(element: ElementRef | None) -> tuple[str, bool, str]:
        if element is None:
            return '', False, 'missing_input'
        if element.text is not None:
            return str(element.text), True, 'snapshot_text'
        if 'text' in element.raw:
            return str(element.raw.get('text') or ''), True, 'raw_text'
        try:
            if element.atspi_obj is not None:
                text_iface = element.atspi_obj.get_text_iface()
                if text_iface:
                    return text_iface.get_text(0, -1) or '', True, 'atspi_text'
        except Exception:
            pass
        try:
            if element.atspi_obj is not None:
                value_iface = element.atspi_obj.get_value_iface()
                if value_iface is not None:
                    value = value_iface.get_current_value()
                    return '' if value is None else str(value), True, 'atspi_value'
        except Exception:
            pass
        return '', False, 'unobserved'

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
            if not self.runtime.focus_file_dialog():
                result.add_step(
                    'attach', False,
                    f'Grok file dialog did not focus for {abs_path}',
                    snapshot=menu.serializable(),
                )
                return False
            if not self.runtime.press('ctrl+l'):
                result.add_step(
                    'attach', False,
                    f'Grok file dialog location shortcut failed for {abs_path}',
                )
                return False
            if not self.runtime.paste(abs_path):
                result.add_step(
                    'attach', False,
                    f'Grok file dialog path paste failed for {abs_path}',
                )
                return False
            if not self.runtime.focus_file_dialog():
                result.add_step(
                    'attach', False,
                    f'Grok file dialog lost focus before submit for {abs_path}',
                )
                return False
            if not self.runtime.press('Return'):
                result.add_step(
                    'attach', False,
                    f'Grok file dialog submit failed for {abs_path}',
                )
                return False

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
        if not self.runtime.click(input_el):
            return None
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
        if not self.runtime.press('ctrl+a'):
            result.add_step('prompt', False, 'Grok prompt stale-draft select-all failed',
                            snapshot=self.runtime.snapshot().serializable())
            return False
        if not self.runtime.press('BackSpace'):
            result.add_step('prompt', False, 'Grok prompt stale-draft clear failed',
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
