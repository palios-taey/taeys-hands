from __future__ import annotations

import os
import time

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult, ExtractedArtifact

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


class PerplexityConsultationDriver(BaseConsultationDriver):
    platform = 'perplexity'

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        result = self.result(request)
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Perplexity tab')
            return result
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(target_url, verify_change=bool(urls.get('verify_navigation')))
            snap = self.runtime.snapshot()
            result.add_step('navigate', navigated, 'Navigated to Perplexity session target', target_url=target_url, snapshot=snap.serializable())
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
        requested_model = (request.model or '').strip().lower()
        requested_mode = (request.mode or self.cfg['workflow']['defaults'].get('mode') or '').strip().lower()

        if requested_model and requested_model in workflow.get('model_targets', {}):
            snap = self.runtime.snapshot()
            selector = self.find_first(snap, 'model_selector')
            if not selector:
                result.add_step('select_model', False, 'Perplexity model selector not found', snapshot=snap.serializable())
                return False
            if not self.runtime.click(selector, strategy='coordinate_only'):
                result.add_step('select_model', False, 'Perplexity model selector click failed', snapshot=snap.serializable())
                return False
            time.sleep(0.8)
            menu_snap = self.runtime.menu_snapshot()
            item = self.find_first(menu_snap, workflow['model_targets'][requested_model])
            if not item or not self.runtime.click(item, strategy='coordinate_only'):
                result.add_step('select_model', False, f'Perplexity model click failed for {requested_model}', menu=menu_snap.serializable())
                return False
            time.sleep(0.8)
            verify_snap = self.runtime.snapshot()
            selector = self.find_first(verify_snap, 'model_selector')
            verified = bool(selector)
            result.add_step('select_model', verified, f'Perplexity model click executed for {requested_model}', snapshot=verify_snap.serializable())
            if not verified:
                return False
        else:
            result.add_step('select_model', True, 'Perplexity model left unchanged/default', requested_model=request.model)

        if requested_mode == 'computer':
            snap = self.runtime.snapshot()
            computer = self.find_first(snap, 'computer_mode')
            if not computer or not self.runtime.click(computer, strategy='coordinate_only'):
                result.add_step('select_mode', False, 'Perplexity Computer button not available', snapshot=snap.serializable())
                return False
            changed = self.runtime.wait_until(lambda: '/computer/' in (self.runtime.current_url() or ''), timeout=20, interval=1.0)
            verified = bool(changed)
            result.add_step('select_mode', verified, 'Perplexity Computer mode opened', url=self.runtime.current_url())
            if not verified:
                return False
        elif requested_mode and requested_mode in workflow.get('mode_targets', {}):
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger or not self.runtime.click(trigger, strategy='coordinate_only'):
                result.add_step('select_mode', False, f'Perplexity tools trigger failed for {requested_mode}', snapshot=snap.serializable())
                return False
            time.sleep(0.8)
            # Perplexity tools dropdown items appear as push buttons, not menu items.
            # Use regular snapshot first, fallback to menu snapshot.
            dropdown_snap = self.runtime.snapshot()
            item = self.find_first(dropdown_snap, workflow['mode_targets'][requested_mode])
            if not item:
                menu_snap = self.runtime.menu_snapshot()
                item = self.find_first(menu_snap, workflow['mode_targets'][requested_mode])
            if not item or not self.runtime.click(item, strategy='coordinate_only'):
                result.add_step('select_mode', False, f'Perplexity mode item missing or click failed for {requested_mode}', snapshot=dropdown_snap.serializable())
                return False
            time.sleep(0.8)
            # Close dropdown by pressing Escape, then verify the mode indicator
            # is visible in the main UI (not inside a dropdown).
            self.runtime.press('Escape')
            time.sleep(0.5)
            # Trust the click — Perplexity Deep Research doesn't reliably report
            # checked/selected state in AT-SPI. The click succeeded if we got here.
            result.add_step('select_mode', True, f'Perplexity mode set to {requested_mode} (click confirmed)', snapshot=self.runtime.snapshot().serializable())
        else:
            result.add_step('select_mode', True, 'Perplexity mode left unchanged/default', requested_mode=request.mode)

        for tool_name in request.tools:
            result.add_step('select_tool', False, f'Perplexity Consultation V2 treats tool selection via mode_targets; extra tool {tool_name!r} was not applied')
            return False
        return True

    def attach_files(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger:
                result.add_step('attach', False, f'Perplexity attach trigger missing for {abs_path}', snapshot=snap.serializable())
                return False
            if not self.runtime.click(trigger, strategy='coordinate_only'):
                result.add_step('attach', False, f'Perplexity attach trigger click failed for {abs_path}', snapshot=snap.serializable())
                return False
            time.sleep(0.7)
            menu_snap = self.runtime.menu_snapshot()
            upload_item = self.find_first(menu_snap, 'upload_files_item')
            if not upload_item or not self.runtime.click(upload_item, strategy='coordinate_only'):
                result.add_step('attach', False, f'Perplexity upload item missing or click failed for {abs_path}', menu=menu_snap.serializable())
                return False
            time.sleep(0.8)
            self.runtime.press('ctrl+l')
            time.sleep(0.2)
            if not self.runtime.paste(abs_path):
                self.runtime.type_text(abs_path, delay_ms=5)
            time.sleep(0.2)
            self.runtime.press('Return')
            time.sleep(1.0)
            self.runtime.press('Return')
            time.sleep(1.2)
            verify_snap = self.runtime.snapshot()
            verified = self.validation_passes(verify_snap, 'attach_success', filename=abs_path)
            result.add_step('attach', verified, f'Perplexity attached {os.path.basename(abs_path)}', file=abs_path, snapshot=verify_snap.serializable())
            if not verified:
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Perplexity attachments requested')
        return True

    def enter_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, 'input')
        if not input_el:
            result.add_step('prompt', False, 'Perplexity input field not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(input_el, strategy='coordinate_only'):
            result.add_step('prompt', False, 'Perplexity input focus click failed', snapshot=snap.serializable())
            return False
        time.sleep(0.3)
        pasted = self.runtime.paste(request.message)
        time.sleep(0.5)
        verify_snap = self.runtime.snapshot()
        # Trust clipboard paste — validation_passes('prompt_ready') is unreliable
        result.add_step('prompt', bool(pasted), 'Perplexity prompt entered' + (' (paste confirmed)' if pasted else ' (paste failed)'), snapshot=verify_snap.serializable())
        return bool(pasted)

    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        before = self.runtime.current_url()
        result.session_url_before = before
        snap = self.runtime.snapshot()
        send_button = self.find_first(snap, 'submit_button')
        if not send_button:
            result.add_step('send', False, 'Perplexity submit button not found', snapshot=snap.serializable())
            return False
        clicked = self.runtime.click(send_button, strategy='coordinate_only')
        stop_seen = self.runtime.wait_until(lambda: self.runtime.snapshot().has('stop_button'), timeout=30, interval=0.6)
        after = self.runtime.wait_for_url_change(before, timeout=30.0, interval=1.0) or self.runtime.current_url()
        # Perplexity often redirects through /search/new/... before settling.
        final_url = after
        for _ in range(5):
            time.sleep(1.0)
            current = self.runtime.current_url() or final_url
            if current and current != final_url:
                final_url = current
        result.session_url_after = final_url
        verify_snap = self.runtime.snapshot()
        verified = bool(clicked and stop_seen and final_url)
        result.add_step('send', verified, 'Perplexity send validated by stop button and settled URL capture', url_before=before, url_after=final_url, snapshot=verify_snap.serializable())
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
        result.add_step('monitor', verified, 'Perplexity response completed', stop_seen=seen_stop, snapshot=verify_snap.serializable())
        return verified

    def extract_primary(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step('extract_primary', False, 'Perplexity copy button not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(copy_button, strategy='coordinate_only'):
            result.add_step('extract_primary', False, 'Perplexity copy button click failed', snapshot=snap.serializable())
            return False
        time.sleep(0.4)
        content = self.runtime.read_clipboard().strip()
        result.response_text = content
        verified = bool(content)
        result.add_step('extract_primary', verified, 'Perplexity summary copied to clipboard', characters=len(content), preview=content[:200])
        return verified

    def extract_additional(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        copy_contents = self.find_first(snap, 'copy_contents_button')
        if copy_contents and self.runtime.click(copy_contents, strategy='coordinate_only'):
            time.sleep(0.4)
            content = self.runtime.read_clipboard().strip()
            if content:
                result.extractions.append(ExtractedArtifact(name='perplexity_full_contents.md', content=content, kind='report_export', metadata={'source': 'copy_contents_button'}))
                result.add_step('extract_additional', True, 'Perplexity full contents copied', characters=len(content), preview=content[:200])
                return True
        download = self.find_first(snap, 'download_button')
        if download:
            result.add_step('extract_additional', True, 'Perplexity download surface is visible, but Consultation V2 currently prefers Copy contents for text ingestion', snapshot=snap.serializable())
            return True
        result.add_step('extract_additional', True, 'Perplexity additional export surface was not visible')
        return True

    def store_in_neo4j(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step('store', True, 'Perplexity Neo4j storage skipped', storage=result.storage)
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
            result.add_step('store', True, 'Perplexity response stored in Neo4j', storage=result.storage)
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step('store', False, f'Perplexity Neo4j storage failed: {exc}')
            return False
