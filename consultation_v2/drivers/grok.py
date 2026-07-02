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
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse

from consultation_v2 import display_readiness
from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.platforms_runtime import get_platform_display
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, Snapshot

class _GrokSetupStepTimeout(TimeoutError):
    pass


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
        if not self._run_setup_step('switch', self.runtime.switch):
            result.add_step('navigate', False, 'Could not switch to Grok window')
            return False
        result.session_url_before = self.runtime.current_url()

        if not self._run_setup_step('navigate', lambda: self.navigate(request, result)):
            return False
        if not self._run_setup_step(
            'mode-select',
            lambda: self.apply_selection_plan(request, result),
        ):
            return False
        if not self._run_setup_step('attach', lambda: self.attach_files(request, result)):
            return False
        if not self._run_setup_step('composer-find', lambda: self.enter_prompt(request, result)):
            return False
        # Idempotent send seam (FLOW §8): guarded_send reads durable run-state
        # first and RESUMES a landed send instead of re-sending; otherwise it
        # performs the real send via self.send_prompt and checkpoints submitted.
        if not self._run_setup_step('send', lambda: self.guarded_send(request, result)):
            return False
        return True

    def _setup_step_timeout_seconds(self, step_name: str) -> float:
        selection_timeout = max(self._selection_settle_seconds() * 4.0, 30.0)
        return {
            'switch': 10.0,
            'navigate': max(self._fresh_chat_action_timeout() + 10.0, 40.0),
            'new_chat': max(self._fresh_chat_action_timeout(), 20.0),
            'page-ready': max(self._fresh_chat_action_timeout() + 10.0, 40.0),
            'mode-select': selection_timeout,
            'attach': max(self._attach_menu_timeout() + 60.0, 75.0),
            'composer-find': 25.0,
            'send': 75.0,
        }.get(step_name, 30.0)

    def _log_setup_progress(
        self,
        event: str,
        step_name: str,
        *,
        timeout_seconds: float,
        elapsed_seconds: float | None = None,
    ) -> None:
        parts = [
            '[grok-setup]',
            event,
            step_name,
            f'timeout={timeout_seconds:.1f}s',
        ]
        if elapsed_seconds is not None:
            parts.append(f'elapsed={elapsed_seconds:.3f}s')
        print(' '.join(parts), file=sys.stderr, flush=True)

    def _run_setup_step(self, step_name: str, callback):
        timeout_seconds = self._setup_step_timeout_seconds(step_name)
        started = time.monotonic()
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)

        def _on_timeout(_signum, _frame):
            elapsed = time.monotonic() - started
            self._log_setup_progress(
                'TIMEOUT',
                step_name,
                timeout_seconds=timeout_seconds,
                elapsed_seconds=elapsed,
            )
            raise _GrokSetupStepTimeout(
                f'Grok setup step {step_name!r} exceeded {timeout_seconds:.1f}s'
            )

        self._log_setup_progress('START', step_name, timeout_seconds=timeout_seconds)
        signal.signal(signal.SIGALRM, _on_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        try:
            value = callback()
        except _GrokSetupStepTimeout:
            raise
        except Exception:
            self._log_setup_progress(
                'ERROR',
                step_name,
                timeout_seconds=timeout_seconds,
                elapsed_seconds=time.monotonic() - started,
            )
            raise
        else:
            event = 'DONE' if bool(value) else 'FAILED'
            self._log_setup_progress(
                event,
                step_name,
                timeout_seconds=timeout_seconds,
                elapsed_seconds=time.monotonic() - started,
            )
            return value
        finally:
            elapsed = time.monotonic() - started
            signal.setitimer(signal.ITIMER_REAL, 0.0)
            signal.signal(signal.SIGALRM, previous_handler)
            previous_remaining, previous_interval = previous_timer
            if previous_remaining > 0.0:
                restored_remaining = max(previous_remaining - elapsed, 0.001)
                signal.setitimer(
                    signal.ITIMER_REAL,
                    restored_remaining,
                    previous_interval,
                )

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
        if not self._run_setup_step('new_chat', lambda: self._trigger_new_chat(result, snap)):
            return False
        return self._run_setup_step('page-ready', lambda: self._wait_for_fresh_chat_ready(result))

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
        # Grok's live text/value interfaces can block inside the AT-SPI bus; the
        # fresh-page gate is bounded only if it trusts the snapshot payload.
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
    # Shared: focus the composer with coordinate action + snapshot confirmation
    # ------------------------------------------------------------------
    def _focus_input(self):
        """Coordinate-click the composer and confirm focus from a fresh snapshot.

        Grok setup must not call live AT-SPI focus/action interfaces before send:
        those calls can block inside the bus and defeat outer workflow timeouts.
        """
        self._last_focus_failure: dict[str, object] = {}
        input_key = self.cfg['workflow']['prompt']['input']
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, input_key)
        if not input_el:
            self._last_focus_failure = {
                'stage': 'input_lookup',
                'input_key': input_key,
                'reason': 'missing',
            }
            return None
        if not self.runtime.click(input_el):
            self._last_focus_failure = {
                'stage': 'coordinate_click',
                'input_key': input_key,
                'reason': 'click_failed',
                'element': input_el.serializable(),
            }
            return None
        focused_snapshot, focused_input = self.wait_for_key(
            input_key,
            timeout=1.5,
            interval=0.2,
            scope='document',
        )
        focused_states = self._state_set(focused_input)
        if focused_input is None or 'focused' not in focused_states:
            self._last_focus_failure = {
                'stage': 'focus_confirmation',
                'input_key': input_key,
                'reason': 'not_focused',
                'input_present': focused_input is not None,
                'input_states': sorted(focused_states),
                'snapshot': focused_snapshot.serializable(),
            }
            return None
        return focused_input

    def _focus_failure_step_data(self) -> dict[str, object]:
        failure = getattr(self, '_last_focus_failure', {})
        return {'focus_failure': failure} if failure else {}

    # ------------------------------------------------------------------
    # Step 4 — enter prompt
    # ------------------------------------------------------------------
    def enter_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        input_el = self._focus_input()
        if not input_el:
            result.add_step('prompt', False, 'Grok input field not found',
                            snapshot=self.runtime.snapshot().serializable(),
                            **self._focus_failure_step_data())
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
    # Step 5 — send (focused composer + Return; hard answer-thread URL gate)
    # ------------------------------------------------------------------
    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        before = self.runtime.current_url() or result.session_url_before

        input_el = self._focus_input()
        if not input_el:
            result.add_step('send', False, 'Grok input field not found for send',
                            snapshot=self.runtime.snapshot().serializable(),
                            **self._focus_failure_step_data())
            return False
        copy_key = self.cfg['workflow']['extract']['primary_key']
        pre_send_copy_baseline = self._copy_button_baseline(copy_key)
        self._pre_send_copy_button_baseline = pre_send_copy_baseline
        if not self.runtime.press('Return'):
            result.add_step('send', False, 'Grok Return keypress failed')
            return False

        send_snap = self.wait_for_validation('send_fired', timeout=12.0, interval=0.5)
        stop_seen = self.validation_passes(send_snap, 'send_fired')
        # Carry the send-phase stop observation into the shared completion
        # detector (a fast reply can clear the stop button before monitor runs).
        self._send_stop_seen = bool(stop_seen)
        post_send_timeout = 30.0
        self._log_setup_progress(
            'START',
            'post-send-url',
            timeout_seconds=post_send_timeout,
        )
        answer_url = self._wait_for_send_answer_thread_url(timeout=post_send_timeout, interval=0.5)
        self._log_setup_progress(
            'DONE' if answer_url else 'FAILED',
            'post-send-url',
            timeout_seconds=post_send_timeout,
        )
        current_url = self.runtime.current_url() or before
        result.session_url_after = answer_url or current_url
        verify_snap = self.runtime.snapshot()
        if not answer_url:
            result.add_step(
                'send',
                False,
                'Grok send did not create an answer-thread URL before the bounded post-send gate',
                url_before=before,
                url_after=current_url,
                stop_seen=stop_seen,
                answer_thread=False,
                url_changed=not self._urls_equivalent(current_url, before),
                answer_thread_timeout_seconds=post_send_timeout,
                pre_send_copy_button_baseline=pre_send_copy_baseline,
                snapshot=verify_snap.serializable(),
            )
            return False

        url_changed = bool(
            result.session_url_after
            and not self._urls_equivalent(result.session_url_after, before)
        )
        answer_thread = self._is_answer_thread_url(result.session_url_after)
        is_new_session = request.session_url is None
        if is_new_session:
            verified = bool(stop_seen and answer_thread and url_changed)
        else:
            verified = bool(stop_seen and answer_thread)
        result.add_step('send', verified, 'Grok send validated by Stop button and URL capture',
                        url_before=before, url_after=result.session_url_after,
                        stop_seen=stop_seen, url_changed=url_changed,
                        answer_thread=answer_thread,
                        pre_send_copy_button_baseline=pre_send_copy_baseline,
                        snapshot=verify_snap.serializable())
        return verified

    def _wait_for_send_answer_thread_url(
        self,
        *,
        timeout: float,
        interval: float,
    ) -> str | None:
        last_answer_url = ''

        def _current_answer_thread() -> str | None:
            nonlocal last_answer_url
            current = (self.runtime.current_url() or '').strip()
            if self._is_answer_thread_url(current):
                if self._urls_equivalent(current, last_answer_url):
                    return current
                last_answer_url = current
                return None
            last_answer_url = ''
            return None

        return self.runtime.wait_until(_current_answer_thread, timeout=timeout, interval=interval)

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

    @staticmethod
    def _is_answer_thread_url(url: str | None) -> bool:
        parsed = urlparse((url or '').strip())
        if parsed.netloc and parsed.netloc not in {'grok.com', 'www.grok.com'}:
            return False
        path = (parsed.path or '').rstrip('/')
        parts = [part for part in path.split('/') if part]
        return len(parts) >= 2 and parts[0] == 'c' and bool(parts[1])

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

    @staticmethod
    def _copy_button_signature(element: ElementRef) -> tuple[object, ...]:
        return (
            element.name,
            element.role,
            element.x,
            element.y,
        )

    def _copy_button_baseline(self, copy_key: str) -> dict[str, object]:
        snapshot = self.runtime.snapshot()
        buttons = (snapshot.mapped or {}).get(copy_key) or []
        signatures = [self._copy_button_signature(button) for button in buttons]
        return {
            'copy_key': copy_key,
            'count': len(buttons),
            'signatures': signatures,
            'buttons': [button.serializable() for button in buttons],
        }

    def _new_copy_buttons_since_baseline(
        self,
        snapshot: Snapshot,
        copy_key: str,
        baseline: dict[str, object],
    ) -> list[ElementRef]:
        buttons = list((snapshot.mapped or {}).get(copy_key) or [])
        baseline_count = int(baseline.get('count') or 0)
        baseline_signatures = {
            tuple(signature)
            for signature in (baseline.get('signatures') or [])
            if isinstance(signature, (list, tuple))
        }
        if len(buttons) <= baseline_count:
            return []
        return [
            button for button in buttons
            if self._copy_button_signature(button) not in baseline_signatures
        ]

    def _copy_buttons_ready_snapshot(
        self,
        copy_key: str,
        baseline: dict[str, object],
        timeout: float = 20.0,
        interval: float = 0.4,
    ) -> tuple[Snapshot | None, dict[str, object]]:
        started = time.monotonic()
        last_title = ''
        last_conversation_title = ''
        last_copy_count = 0
        last_new_copy_count = 0
        samples: list[dict[str, object]] = []

        def _probe() -> Snapshot | None:
            nonlocal last_title, last_conversation_title, last_copy_count, last_new_copy_count
            snapshot = self.runtime.snapshot()
            last_title = self._grok_window_title()
            last_conversation_title = self._conversation_title(last_title)
            generic_title = last_conversation_title == self.platform
            last_copy_count = len((snapshot.mapped or {}).get(copy_key) or [])
            last_new_copy_count = len(self._new_copy_buttons_since_baseline(snapshot, copy_key, baseline))
            samples.append({
                'elapsed_seconds': round(time.monotonic() - started, 3),
                'title': last_title,
                'conversation_title': last_conversation_title,
                'generic_title': generic_title,
                'copy_button_count': last_copy_count,
                'baseline_copy_button_count': int(baseline.get('count') or 0),
                'new_copy_button_count': last_new_copy_count,
            })
            if last_new_copy_count > 0 and last_conversation_title and not generic_title:
                return snapshot
            return None

        matched = self.runtime.wait_until(_probe, timeout=timeout, interval=interval)
        snapshot = matched if isinstance(matched, Snapshot) else None
        evidence = {
            'copy_button_settle_timeout_seconds': timeout,
            'copy_button_settle_interval_seconds': interval,
            'copy_button_settle_elapsed_seconds': round(time.monotonic() - started, 3),
            'copy_button_settle_matched': bool(snapshot),
            'title': last_title,
            'conversation_title': last_conversation_title,
            'generic_title': last_conversation_title == self.platform,
            'copy_button_count': last_copy_count,
            'baseline_copy_button_count': int(baseline.get('count') or 0),
            'new_copy_button_count': last_new_copy_count,
            'baseline_copy_buttons': baseline.get('buttons') or [],
            'settle_samples': samples[-8:],
        }
        return snapshot, evidence

    def extract_response(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        copy_key = self.cfg['workflow']['extract']['primary_key']
        copy_button_baseline = getattr(self, '_pre_send_copy_button_baseline', None)
        if not isinstance(copy_button_baseline, dict):
            result.add_step(
                'extract',
                False,
                'Grok pre-send Copy baseline missing; refusing to extract from possibly stale Copy buttons',
                bottom_evidence={},
                copy_button_settle={'reason': 'pre_send_copy_button_baseline_missing'},
                snapshot=self.runtime.snapshot().serializable(),
            )
            return False

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

        snap, copy_button_settle = self._copy_buttons_ready_snapshot(copy_key, copy_button_baseline)
        if snap is None:
            result.add_step('extract', False, 'Grok new Copy button did not appear before settle timeout',
                            bottom_evidence=bottom_evidence,
                            copy_button_settle=copy_button_settle,
                            snapshot=self.runtime.snapshot().serializable())
            return False
        copy_buttons = sorted(
            self._new_copy_buttons_since_baseline(snap, copy_key, copy_button_baseline),
            key=lambda item: (
                item.y is not None,
                item.y if item.y is not None else -1,
                item.x is not None,
                item.x if item.x is not None else -1,
            ),
            reverse=True,
        )
        if not copy_buttons:
            result.add_step('extract', False, 'Grok new Copy button not found after settle',
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
        session_url = (result.session_url_after or result.session_url_before
                       or self.runtime.current_url() or '')
        return self.store_response_for_delivery(
            request,
            result,
            session_url,
            label='Grok',
        )
