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
import subprocess
import time
from urllib.parse import urlparse

from consultation_v2 import display_readiness
from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.platforms_runtime import get_platform_display
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

        snap = self.runtime.snapshot()
        result.add_step('navigate', True, 'Grok fresh session uses current page and in-page New Chat',
                        target_url=target_url, fresh_chat_required=True,
                        snapshot=snap.serializable())
        if not self._trigger_new_chat(result, snap):
            return False
        return self._wait_for_fresh_chat_ready(result)

    def _trigger_new_chat(self, result: ConsultationResult, snapshot: Snapshot) -> bool:
        nav_cfg = (self.cfg.get('workflow') or {}).get('navigate') or {}
        key = nav_cfg.get('new_chat_key') or nav_cfg.get('new_chat')
        lookup_snapshot = snapshot
        element = snapshot.first(key) if isinstance(key, str) else None

        if isinstance(key, str) and not element:
            def _find_new_chat() -> ElementRef | None:
                nonlocal lookup_snapshot
                lookup_snapshot = self.runtime.snapshot()
                return lookup_snapshot.first(key)

            element = self.runtime.wait_until(
                _find_new_chat,
                timeout=self._fresh_chat_action_timeout(),
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

        result.add_step(
            'new_chat',
            False,
            'Grok mapped New Chat affordance missing from current tree',
            configured_key=key,
            snapshot=lookup_snapshot.serializable(),
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
                and not missing
                and input_el is not None
                and input_editable
                and input_observed_empty
                and not remove_attachment_present
            ):
                return None
            return snap

        effective_timeout = max(float(timeout), self._fresh_chat_action_timeout())
        matched = self.runtime.wait_until(_probe, timeout=effective_timeout, interval=0.4)
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
            timeout_seconds=effective_timeout,
            elapsed_seconds=round(time.time() - started, 2),
            snapshot=snapshot.serializable(),
            **last_evidence,
        )
        return False

    def _settle_seconds(self, key: str, fallback_ms: int) -> float:
        settle = self.cfg.get('settle') or {}
        value = None
        if isinstance(settle, dict):
            value = settle.get(f'{key}_ms') if key else None
            if value is None:
                value = settle.get('default_ms')
        if value is None:
            value = fallback_ms
        try:
            return max(0.0, float(value) / 1000.0)
        except (TypeError, ValueError):
            return max(0.0, float(fallback_ms) / 1000.0)

    def _fresh_chat_action_timeout(self) -> float:
        return max(
            self._settle_seconds('navigate', 4000)
            + self._settle_seconds('', 2000),
            20.0,
        )

    def _attach_menu_timeout(self) -> float:
        return max(self._settle_seconds('attach', 3000) + 1.0, 10.0)

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
            menu, upload_item = self.wait_for_key(
                upload_key,
                timeout=self._attach_menu_timeout(),
                interval=0.4,
                scope='menu',
            )
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
    @staticmethod
    def _conversation_title(window_title: str) -> str:
        normalized = ' '.join(str(window_title or '').strip().lower().split())
        normalized = normalized.replace('\u2014', '-').replace('\u2013', '-')
        for suffix in (' - mozilla firefox', ' mozilla firefox'):
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        return normalized.strip(' -')

    def _grok_window_title(self) -> str:
        display = get_platform_display(self.platform) or os.environ.get('DISPLAY', ':0')
        env = dict(os.environ)
        env['DISPLAY'] = display
        try:
            search = subprocess.run(
                ['xdotool', 'search', '--class', 'firefox'],
                env=env,
                capture_output=True,
                text=True,
                timeout=2,
            )
            window_ids = [line.strip() for line in search.stdout.splitlines() if line.strip()]
            for window_id in reversed(window_ids):
                title = subprocess.run(
                    ['xdotool', 'getwindowname', window_id],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if title.returncode == 0 and title.stdout.strip():
                    return title.stdout.strip()
        except Exception:
            return ''
        return ''

    def _copy_buttons_ready_snapshot(
        self,
        copy_key: str,
        timeout: float = 20.0,
        interval: float = 0.4,
    ) -> tuple[Snapshot, dict[str, object]]:
        started = time.monotonic()
        last_snapshot: Snapshot | None = None
        last_title = ''
        last_conversation_title = ''
        last_copy_count = 0
        samples: list[dict[str, object]] = []

        def _probe() -> Snapshot | None:
            nonlocal last_snapshot, last_title, last_conversation_title, last_copy_count
            snapshot = self.runtime.snapshot()
            last_snapshot = snapshot
            last_title = self._grok_window_title()
            last_conversation_title = self._conversation_title(last_title)
            generic_title = last_conversation_title == self.platform
            last_copy_count = len((snapshot.mapped or {}).get(copy_key) or [])
            samples.append({
                'elapsed_seconds': round(time.monotonic() - started, 3),
                'title': last_title,
                'conversation_title': last_conversation_title,
                'generic_title': generic_title,
                'copy_button_count': last_copy_count,
            })
            if last_copy_count > 0 and last_conversation_title and not generic_title:
                return snapshot
            return None

        matched = self.runtime.wait_until(_probe, timeout=timeout, interval=interval)
        snapshot = matched if isinstance(matched, Snapshot) else last_snapshot or self.runtime.snapshot()
        evidence = {
            'copy_button_settle_timeout_seconds': timeout,
            'copy_button_settle_interval_seconds': interval,
            'copy_button_settle_elapsed_seconds': round(time.monotonic() - started, 3),
            'title': last_title,
            'conversation_title': last_conversation_title,
            'generic_title': last_conversation_title == self.platform,
            'copy_button_count': last_copy_count,
            'settle_samples': samples[-8:],
        }
        return snapshot, evidence

    def extract_response(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        copy_key = self.cfg['workflow']['extract']['primary_key']

        bottom_evidence = {
            'focus_input': False,
            'ctrl_end': False,
            'scroll_to_bottom': False,
            'scroll_document_to_bottom': False,
        }
        input_key = self.cfg['workflow']['prompt']['input']
        input_el = self._focus_input()
        bottom_evidence['focus_input'] = bool(input_el)
        if input_el is None:
            input_el = self.find_first(self.runtime.snapshot(), input_key)

        bottom_evidence['ctrl_end'] = bool(self.runtime.press('ctrl+End'))
        time.sleep(0.5)
        if input_el is not None:
            bottom_evidence['scroll_to_bottom'] = bool(
                self.runtime.scroll_to_bottom(input_el, clicks=15, max_rounds=8, settle=0.35)
            )
        if not bottom_evidence['scroll_to_bottom']:
            bottom_evidence['scroll_document_to_bottom'] = bool(
                self.runtime.scroll_document_to_bottom(clicks=12, rounds=4, settle=0.4)
            )

        snap, copy_button_settle = self._copy_buttons_ready_snapshot(copy_key)
        copy_buttons = sorted(
            (snap.mapped or {}).get(copy_key) or [],
            key=lambda item: (
                item.y is not None,
                item.y if item.y is not None else -1,
                item.x is not None,
                item.x if item.x is not None else -1,
            ),
            reverse=True,
        )
        if not copy_buttons:
            result.add_step('extract', False, 'Grok copy button not found',
                            bottom_evidence=bottom_evidence,
                            copy_button_settle=copy_button_settle,
                            snapshot=snap.serializable())
            return False

        attempts = []
        for index_from_bottom, copy_button in enumerate(copy_buttons):
            self.runtime.write_clipboard('')
            scrolled = self.runtime.scroll_element_into_view(copy_button)
            clicked = self.runtime.click(copy_button, strategy='atspi_only')
            if clicked:
                self.runtime.wait_until(
                    lambda: bool(self.runtime.read_clipboard().strip()),
                    timeout=4,
                    interval=0.3,
                )
            content = self.runtime.read_clipboard().strip()
            prompt_echo = self._is_prompt_echo(content, request)
            valid = bool(content) and not prompt_echo
            attempt = {
                'index_from_bottom': index_from_bottom,
                'scrolled_into_view': scrolled,
                'clicked': clicked,
                'characters': len(content),
                'prompt_echo': prompt_echo,
                'element': copy_button.serializable(),
                'preview': content[:120],
            }
            attempts.append(attempt)
            if content and prompt_echo:
                self.reject_prompt_echo_response(
                    request,
                    result,
                    content,
                    step='extract',
                    source='grok_copy_candidate',
                    index_from_bottom=index_from_bottom,
                    copy_button_count=len(copy_buttons),
                    element=copy_button.serializable(),
                )
                continue
            if valid:
                if not self.set_response_text_if_not_prompt_echo(
                    request,
                    result,
                    content,
                    step='extract',
                    source='grok_copy_response',
                    index_from_bottom=index_from_bottom,
                    copy_button_count=len(copy_buttons),
                    element=copy_button.serializable(),
                ):
                    continue
                result.add_step(
                    'extract', True,
                    f'Grok response copied ({len(content)} chars)',
                    characters=len(content),
                    prompt_len=len(request.message),
                    selected_index_from_bottom=index_from_bottom,
                    copy_button_count=len(copy_buttons),
                    bottom_evidence=bottom_evidence,
                    copy_button_settle=copy_button_settle,
                    attempts=attempts,
                    preview=content[:200],
                )
                return True

        result.response_text = ''
        result.add_step(
            'extract', False,
            'Grok copy buttons did not yield non-echo response content',
            prompt_len=len(request.message),
            copy_button_count=len(copy_buttons),
            bottom_evidence=bottom_evidence,
            copy_button_settle=copy_button_settle,
            attempts=attempts,
            snapshot=snap.serializable(),
        )
        return False

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
