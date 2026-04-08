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

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        result = self.result(request)
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to ChatGPT tab')
            return result
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(target_url, verify_change=bool(urls.get('verify_navigation')))
            snap = self.runtime.snapshot()
            result.add_step('navigate', navigated, 'Navigated to ChatGPT session target', target_url=target_url, snapshot=snap.serializable())
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
    # Helpers
    # ------------------------------------------------------------------

    def _click_strategy(self) -> str:
        """Return click strategy from top-level YAML key; fall back to 'at_spi'."""
        return self.cfg.get('click_strategy', 'at_spi')

    def _click(self, element) -> bool:
        """Dispatch click using the YAML-declared strategy."""
        strategy = self._click_strategy()
        return self.runtime.click(element, strategy=strategy)

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
            time.sleep(0.8)
            verify_snap = self.runtime.snapshot()
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
        time.sleep(1.0)
        verify_snap = self.runtime.snapshot()
        verified = clicked and self.validation_passes(verify_snap, f"{target}_active")
        result.add_step('select_model', verified, f'ChatGPT model set to {target}', snapshot=verify_snap.serializable())
        return verified

    def _apply_tool(self, tool_name: str, workflow: dict, result: ConsultationResult) -> bool:
        """Open attach dropdown (React portal) and toggle a tool item."""
        normalized = tool_name.strip().lower().replace(' ', '_')
        target_key = workflow.get('tool_targets', {}).get(normalized)
        if not target_key:
            result.add_step('select_tool', False, f'ChatGPT tool {tool_name!r} is not mapped in Consultation V2 YAML')
            return False

        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger or not self._click(trigger):
            result.add_step('select_tool', False, f'ChatGPT failed to open tools dropdown for {tool_name}', snapshot=snap.serializable())
            return False
        time.sleep(1.0)

        # Attach dropdown is a React portal — must use menu_snapshot()
        dropdown_snap = self.runtime.menu_snapshot()
        item = self.find_first(dropdown_snap, target_key)
        if not item:
            result.add_step('select_tool', False, f'ChatGPT tool item {target_key} not found', snapshot=dropdown_snap.serializable())
            return False
        clicked = self._click(item)
        time.sleep(0.6)
        verify_snap = self.runtime.snapshot()
        verified = bool(clicked)
        result.add_step('select_tool', verified, f'ChatGPT tool click executed for {tool_name}', snapshot=verify_snap.serializable())
        return verified

    # ------------------------------------------------------------------
    # File attachment
    # ------------------------------------------------------------------

    def attach_files(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
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
            self.runtime.press('ctrl+l')
            time.sleep(0.2)
            if not self.runtime.paste(abs_path):
                self.runtime.type_text(abs_path, delay_ms=5)
            time.sleep(0.2)
            self.runtime.press('Return')
            time.sleep(0.8)
            self.runtime.press('Return')
            time.sleep(1.2)
            verify_snap = self.runtime.snapshot()
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
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, 'input')
        if not input_el:
            result.add_step('prompt', False, 'ChatGPT input field not found', snapshot=snap.serializable())
            return False
        if not self._click(input_el):
            result.add_step('prompt', False, 'ChatGPT input focus click failed', snapshot=snap.serializable())
            return False
        time.sleep(0.3)
        pasted = self.runtime.paste(request.message)
        time.sleep(0.5)
        verify_snap = self.runtime.snapshot()
        verified = bool(pasted and self.validation_passes(verify_snap, 'prompt_ready'))
        result.add_step('prompt', verified, 'ChatGPT prompt entered', snapshot=verify_snap.serializable())
        return verified

    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        # Use the pre-navigation baseline captured in run() — file attachment
        # can change the URL before send, making current_url() stale.
        before = result.session_url_before
        snap = self.runtime.snapshot()
        send_button = self.find_first(snap, 'send_button')
        if not send_button:
            result.add_step('send', False, 'ChatGPT send button not found', snapshot=snap.serializable())
            return False
        clicked = self._click(send_button)
        def _send_confirmed():
            snap = self.runtime.snapshot()
            return snap.has('stop_button') or snap.has('copy_button')
        stop_seen = self.runtime.wait_until(_send_confirmed, timeout=120, interval=0.6)
        result.session_url_after = self.runtime.current_url() or before
        verify_snap = self.runtime.snapshot()
        url_changed = result.session_url_after and result.session_url_after != before
        is_new_session = not request.session_url
        if is_new_session:
            verified = bool(clicked and (stop_seen or url_changed))
        else:
            verified = bool(clicked and stop_seen)
        result.add_step('send', verified, 'ChatGPT send validated by stop/copy button', url_before=before, url_after=result.session_url_after, snapshot=verify_snap.serializable())
        return verified

    # ------------------------------------------------------------------
    # Generation monitoring and extraction
    # ------------------------------------------------------------------

    def monitor_generation(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        seen_stop = False

        def _poll() -> bool:
            nonlocal seen_stop
            snap = self.runtime.snapshot()
            if snap.has('stop_button'):
                seen_stop = True
                return False
            # Complete when copy button present and stop button absent
            if snap.has('copy_button') and not snap.has('stop_button'):
                return True
            return False

        completed = self.runtime.wait_until(_poll, timeout=float(request.timeout), interval=1.0)
        verify_snap = self.runtime.snapshot()
        # response_complete uses name_contains: Copy in YAML (not exact name match)
        verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
        result.add_step('monitor', verified, 'ChatGPT response completed', stop_seen=seen_stop, snapshot=verify_snap.serializable())
        return verified

    def extract_primary(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step('extract_primary', False, 'ChatGPT copy button not found', snapshot=snap.serializable())
            return False
        if not self._click(copy_button):
            result.add_step('extract_primary', False, 'ChatGPT copy button click failed', snapshot=snap.serializable())
            return False
        time.sleep(0.4)
        content = self.runtime.read_clipboard().strip()
        result.response_text = content
        verified = bool(content)
        result.add_step('extract_primary', verified, 'ChatGPT response copied to clipboard', characters=len(content), preview=content[:200])
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
