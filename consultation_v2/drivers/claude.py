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

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        result = self.result(request)
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Claude tab')
            return result
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
                return result
        if not self.select_model_mode_tools(request, result):
            return result
        if not self.attach_files(request, result):
            return result
        if not self.enter_prompt(request, result):
            return result
        if not self.send_prompt(request, result):
            return result
        if not self.monitor_generation(request, result):
            return result
        if not self.extract_primary(request, result):
            return result
        if not self.extract_additional(request, result):
            return result
        if not self.store_in_neo4j(request, result):
            return result
        result.ok = True
        return result

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
            selector = self.find_first(snap, 'model_selector')
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
            time.sleep(0.8)
            verify_snap = self.runtime.snapshot()
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
            snap = self.runtime.snapshot()
            mode_active_key = f'{requested_mode}_active'
            if self.validation_passes(snap, mode_active_key):
                result.add_step('select_mode', True, f'Claude {requested_mode} already active')
                return True

            selector = self.find_first(snap, 'model_selector')
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

            # Extended thinking is a toggle button INSIDE the menu item, not
            # a plain menu-item click.  Find the toggle child and flip it.
            if requested_mode == 'extended_thinking':
                toggle = self.find_first(menu_snap, 'toggle_extended_thinking')
                if not toggle:
                    result.add_step('select_mode', False,
                                    'Claude ET toggle button not found in model dropdown',
                                    snapshot=menu_snap.serializable())
                    self.runtime.press('Escape')
                    return False
                already_on = bool(
                    toggle.states
                    and 'checked' in [s.lower() for s in toggle.states]
                )
                if already_on:
                    # Already enabled — dismiss dropdown and confirm
                    self.runtime.press('Escape')
                    time.sleep(0.4)
                    verify_snap = self.runtime.snapshot()
                    result.add_step('select_mode', True,
                                    'Claude extended_thinking toggle already ON',
                                    snapshot=verify_snap.serializable())
                    return True
                clicked = self.runtime.click(toggle)
                time.sleep(0.5)
                # Dismiss dropdown after toggling
                self.runtime.press('Escape')
                time.sleep(0.4)
            else:
                clicked = self.runtime.click(item)
                time.sleep(0.8)

            verify_snap = self.runtime.snapshot()
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
            time.sleep(0.6)
            verify_snap = self.runtime.snapshot()
            result.add_step('select_tool', bool(clicked),
                            f'Claude tool click executed for {tool_name}',
                            snapshot=verify_snap.serializable())
            if not clicked:
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
            time.sleep(1.0)
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
            time.sleep(4.0)
            verify_snap = self.runtime.snapshot()
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
        time.sleep(0.5)
        verify_snap = self.runtime.snapshot()
        verified = bool(pasted and self.validation_passes(verify_snap, 'prompt_ready'))
        result.add_step('prompt', verified, 'Claude prompt entered',
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
        stop_seen = self.runtime.wait_until(
            lambda: self.runtime.snapshot().has('stop_button'),
            timeout=30, interval=0.6,
        )
        after = self.runtime.wait_for_url_change(before, timeout=30.0, interval=1.0)
        result.session_url_after = after or self.runtime.current_url()
        verify_snap = self.runtime.snapshot()
        url_changed = result.session_url_after and result.session_url_after != before
        is_new_session = not request.session_url
        if is_new_session:
            verified = bool(clicked and stop_seen and url_changed)
        else:
            verified = bool(clicked and stop_seen)
        result.add_step(
            'send', verified, 'Claude send validated by stop button',
            url_before=before, url_after=result.session_url_after,
            snapshot=verify_snap.serializable(),
        )
        return verified

    # ------------------------------------------------------------------
    # Monitor generation
    # ------------------------------------------------------------------

    def monitor_generation(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        seen_stop = False

        def _poll() -> bool:
            nonlocal seen_stop
            snap = self.runtime.snapshot()
            if snap.has('stop_button'):
                seen_stop = True
                return False
            return seen_stop and snap.has('copy_button')

        completed = self.runtime.wait_until(
            _poll, timeout=float(request.timeout), interval=1.0,
        )
        verify_snap = self.runtime.snapshot()
        verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
        result.add_step('monitor', verified, 'Claude response completed',
                        stop_seen=seen_stop, snapshot=verify_snap.serializable())
        return verified

    # ------------------------------------------------------------------
    # Extract primary (copy-button strategy)
    # ------------------------------------------------------------------

    def extract_primary(
        self, request: ConsultationRequest, result: ConsultationResult
    ) -> bool:
        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step('extract_primary', False, 'Claude copy button not found',
                            snapshot=snap.serializable())
            return False
        if not self.runtime.click(copy_button):
            result.add_step('extract_primary', False, 'Claude copy button click failed',
                            snapshot=snap.serializable())
            return False
        time.sleep(0.4)
        content = self.runtime.read_clipboard().strip()
        result.response_text = content
        verified = bool(content)
        result.add_step('extract_primary', verified,
                        'Claude response copied to clipboard',
                        characters=len(content), preview=content[:200])
        return verified

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
