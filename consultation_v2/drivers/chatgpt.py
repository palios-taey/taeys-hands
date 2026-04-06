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

    def select_model_mode_tools(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        workflow = self.cfg['workflow']['selection']
        requested_mode = (request.mode or self.cfg['workflow']['defaults'].get('mode') or '').strip().lower()
        requested_model = (request.model or self.cfg['workflow']['defaults'].get('model') or '').strip().lower()
        target = requested_mode or requested_model

        if target in workflow.get('composite_modes', {}):
            steps = workflow['composite_modes'][target]
            for index, step in enumerate(steps, start=1):
                snap = self.runtime.snapshot()
                trigger = self.find_first(snap, step['trigger'])
                if not trigger:
                    result.add_step(f'select_{index}', False, f"ChatGPT trigger {step['trigger']} not found", snapshot=snap.serializable())
                    return False
                if not self.runtime.click(trigger, strategy='coordinate_only'):
                    result.add_step(f'select_{index}', False, f"ChatGPT trigger {step['trigger']} click failed", snapshot=snap.serializable())
                    return False
                time.sleep(1.0)
                if step['target'].startswith('thinking_'):
                    tile_snap = self.runtime.snapshot()
                    tile = self.find_first(tile_snap, step['target'])
                    if not tile:
                        result.add_step(f'select_{index}', False, f"ChatGPT tile {step['target']} not visible after trigger", snapshot=tile_snap.serializable())
                        return False
                    clicked = self.runtime.click(tile, strategy='coordinate_only')
                    time.sleep(0.8)
                    verify_snap = self.runtime.snapshot()
                    verified = clicked and self.validation_passes(verify_snap, step['verification'])
                    result.add_step(f'select_{index}', verified, f"ChatGPT applied {step['target']}", selected=step['target'], snapshot=verify_snap.serializable())
                    if not verified:
                        return False
                    continue

                time.sleep(1.0)
                dropdown_snap = self.runtime.snapshot()
                target_el = self.find_first(dropdown_snap, step['target'])
                if not target_el:
                    result.add_step(f'select_{index}', False, f"ChatGPT model item {step['target']} not found", snapshot=dropdown_snap.serializable())
                    return False
                clicked = self.runtime.click(target_el, strategy='coordinate_only')
                time.sleep(0.8)
                verify_snap = self.runtime.snapshot()
                selector = self.find_first(verify_snap, 'model_selector')
                # ChatGPT model selector name is static ("Model selector") — does NOT
                # update to show current model. Verify by checking dropdown closed
                # (target item no longer visible) and click succeeded.
                verify_snap2 = self.runtime.snapshot()
                target_still_visible = self.find_first(verify_snap2, step['target'])
                verified = bool(clicked and not target_still_visible)
                result.add_step(f'select_{index}', verified, f"ChatGPT applied {step['target']}", selected=step['target'], snapshot=verify_snap.serializable())
                if not verified:
                    return False
        elif target and target in workflow.get('model_targets', {}):
            snap = self.runtime.snapshot()
            selector = self.find_first(snap, 'model_selector')
            if not selector:
                result.add_step('select_model', False, 'ChatGPT model selector not found', snapshot=snap.serializable())
                return False
            if not self.runtime.click(selector, strategy='coordinate_only'):
                result.add_step('select_model', False, 'ChatGPT model selector click failed', snapshot=snap.serializable())
                return False
            time.sleep(1.0)
            dropdown_snap = self.runtime.snapshot()
            target_key = workflow['model_targets'][target]
            item = self.find_first(dropdown_snap, target_key)
            if not item:
                result.add_step('select_model', False, f'ChatGPT menu item {target_key} not found', snapshot=dropdown_snap.serializable())
                return False
            clicked = self.runtime.click(item, strategy='coordinate_only')
            time.sleep(0.8)
            # ChatGPT model selector name is static ("Model selector") — does NOT
            # update to show current model. Verify by checking dropdown closed.
            verify_snap = self.runtime.snapshot()
            target_still_visible = self.find_first(verify_snap, target_key)
            verified = bool(clicked and not target_still_visible)
            result.add_step('select_model', verified, f'ChatGPT model set to {target}', snapshot=verify_snap.serializable())
            if not verified:
                return False
        else:
            result.add_step('select_model_mode', True, 'ChatGPT using current/default model and mode', requested_model=request.model, requested_mode=request.mode)

        for tool_name in request.tools:
            normalized = tool_name.strip().lower().replace(' ', '_')
            target_key = workflow.get('tool_targets', {}).get(normalized)
            if not target_key:
                result.add_step('select_tool', False, f'ChatGPT tool {tool_name!r} is not mapped in Consultation V2 YAML')
                return False
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger or not self.runtime.click(trigger, strategy='coordinate_only'):
                result.add_step('select_tool', False, f'ChatGPT failed to open tools dropdown for {tool_name}', snapshot=snap.serializable())
                return False
            time.sleep(1.0)
            snap = self.runtime.snapshot()
            item = self.find_first(snap, target_key)
            if not item:
                result.add_step('select_tool', False, f'ChatGPT tool item {target_key} not found', snapshot=snap.serializable())
                return False
            clicked = self.runtime.click(item, strategy='coordinate_only')
            time.sleep(0.6)
            verify_snap = self.runtime.snapshot()
            verified = bool(clicked)
            result.add_step('select_tool', verified, f'ChatGPT tool click executed for {tool_name}', snapshot=verify_snap.serializable())
            if not verified:
                return False
        return True

    def attach_files(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger:
                result.add_step('attach', False, f'ChatGPT attach trigger not found for {abs_path}', snapshot=snap.serializable())
                return False
            if not self.runtime.click(trigger, strategy='coordinate_only'):
                result.add_step('attach', False, f'ChatGPT attach trigger click failed for {abs_path}', snapshot=snap.serializable())
                return False
            time.sleep(0.7)
            snap = self.runtime.snapshot()
            upload_item = self.find_first(snap, 'tool_upload')
            if not upload_item:
                result.add_step('attach', False, f'ChatGPT upload item not found for {abs_path}', snapshot=snap.serializable())
                return False
            clicked = self.runtime.click(upload_item, strategy='coordinate_only')
            if not clicked:
                result.add_step('attach', False, f'ChatGPT upload item click failed for {abs_path}', snapshot=snap.serializable())
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

    def enter_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, 'input')
        if not input_el:
            result.add_step('prompt', False, 'ChatGPT input field not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(input_el, strategy='coordinate_only'):
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
        before = self.runtime.current_url()
        result.session_url_before = before
        snap = self.runtime.snapshot()
        send_button = self.find_first(snap, 'send_button')
        if not send_button:
            result.add_step('send', False, 'ChatGPT send button not found', snapshot=snap.serializable())
            return False
        clicked = self.runtime.click(send_button, strategy='coordinate_only')
        stop_seen = self.runtime.wait_until(lambda: self.runtime.snapshot().has('stop_button'), timeout=30, interval=0.6)
        after = self.runtime.wait_for_url_change(before, timeout=30.0, interval=1.0)
        result.session_url_after = after or self.runtime.current_url()
        verify_snap = self.runtime.snapshot()
        verified = bool(clicked and stop_seen and result.session_url_after)
        result.add_step('send', verified, 'ChatGPT send validated by stop button and URL capture', url_before=before, url_after=result.session_url_after, snapshot=verify_snap.serializable())
        return verified

    def monitor_generation(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        seen_stop = False

        def _poll() -> bool:
            nonlocal seen_stop
            snap = self.runtime.snapshot()
            if snap.has('stop_button'):
                seen_stop = True
                return False
            return seen_stop and snap.has('copy_button')

        completed = self.runtime.wait_until(_poll, timeout=float(request.timeout), interval=1.0)
        verify_snap = self.runtime.snapshot()
        verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
        result.add_step('monitor', verified, 'ChatGPT response completed', stop_seen=seen_stop, snapshot=verify_snap.serializable())
        return verified

    def extract_primary(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step('extract_primary', False, 'ChatGPT copy button not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(copy_button, strategy='coordinate_only'):
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
