from __future__ import annotations

import os
import time

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import ConsultationRequest, ConsultationResult

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


class GrokConsultationDriver(BaseConsultationDriver):
    platform = 'grok'

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        result = self.result(request)
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Grok tab')
            return result
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(target_url, verify_change=bool(urls.get('verify_navigation')))
            snap = self.runtime.snapshot()
            result.add_step('navigate', navigated, 'Navigated to Grok session target', target_url=target_url, snapshot=snap.serializable())
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

    def _remove_stale_attachment_buttons(self) -> int:
        snapshot = self.runtime.snapshot()
        remove_spec = {'name_contains': 'Remove', 'role_contains': 'button'}
        candidates = []
        for bucket in snapshot.mapped.values():
            candidates.extend(bucket)
        candidates.extend(snapshot.unknown)
        removed = 0
        for element in candidates:
            if matches_spec(element, remove_spec):
                if self.runtime.click(element, strategy='coordinate_only'):
                    removed += 1
                    time.sleep(0.2)
        return removed

    def _input_has_text(self) -> bool:
        snapshot = self.runtime.snapshot()
        input_el = self.find_first(snapshot, 'input')
        if not input_el or not input_el.atspi_obj:
            return False
        try:
            text_iface = input_el.atspi_obj.get_text_iface()
            if text_iface:
                text = text_iface.get_text(0, -1) or ''
                if text.strip():
                    return True
        except Exception:
            pass
        try:
            value_iface = input_el.atspi_obj.get_value_iface()
            if value_iface is not None and str(value_iface.get_current_value()).strip():
                return True
        except Exception:
            pass
        return False

    def select_model_mode_tools(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        workflow = self.cfg['workflow']['selection']
        # None = use YAML default; empty string = skip selection
        if request.mode is None:
            requested_mode = (self.cfg['workflow']['defaults'].get('mode') or '').strip().lower()
        else:
            requested_mode = request.mode.strip().lower()
        if request.model is None:
            target = requested_mode
        else:
            target = requested_mode or request.model.strip().lower()
        if not target:
            result.add_step('select_model_mode', True, 'Grok using current/default model')
            return True
        if target not in workflow.get('model_targets', {}):
            result.add_step('select_model_mode', False, f'Grok target {target!r} is not mapped in Consultation V2 YAML')
            return False
        snap = self.runtime.snapshot()
        selector = self.find_first(snap, 'model_selector')
        if not selector:
            result.add_step('select_model_mode', False, 'Grok model selector not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(selector, strategy='coordinate_only'):
            result.add_step('select_model_mode', False, 'Grok model selector click failed', snapshot=snap.serializable())
            return False
        time.sleep(0.8)
        snap = self.runtime.snapshot()
        item = self.find_first(snap, workflow['model_targets'][target])
        if not item:
            result.add_step('select_model_mode', False, f'Grok model item {target} not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(item, strategy='coordinate_only'):
            result.add_step('select_model_mode', False, f'Grok model item click failed for {target}', snapshot=snap.serializable())
            return False
        time.sleep(0.8)
        # Grok requires explicit re-open verification because the selector label does not update reliably.
        verify_root = self.runtime.snapshot()
        selector = self.find_first(verify_root, 'model_selector')
        verified = False
        if selector and self.runtime.click(selector, strategy='coordinate_only'):
            time.sleep(0.5)
            verify_snap = self.runtime.snapshot()
            verify_item = self.find_first(verify_snap, workflow['model_targets'][target])
            verified = bool(verify_item and any(state.lower() in {'checked', 'selected'} for state in verify_item.states))
        result.add_step('select_model_mode', verified, f'Grok model set to {target}', snapshot=self.runtime.snapshot().serializable())
        return verified

    def attach_files(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        if request.attachments and request.session_url is None:
            removed = self._remove_stale_attachment_buttons()
            if removed:
                result.add_step('attach_preflight', True, 'Grok stale attachment chips cleared before new upload', removed=removed)
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger:
                result.add_step('attach', False, f'Grok attach trigger missing for {abs_path}', snapshot=snap.serializable())
                return False
            if not self.runtime.click(trigger, strategy='coordinate_only'):
                result.add_step('attach', False, f'Grok attach trigger click failed for {abs_path}', snapshot=snap.serializable())
                return False
            time.sleep(0.6)
            snap = self.runtime.snapshot()
            upload_item = self.find_first(snap, 'upload_files_item')
            if not upload_item:
                result.add_step('attach', False, f'Grok upload item not found for {abs_path}', snapshot=snap.serializable())
                return False
            if not self.runtime.click(upload_item, strategy='coordinate_only'):
                result.add_step('attach', False, f'Grok upload item click failed for {abs_path}', snapshot=snap.serializable())
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
            result.add_step('attach', verified, f'Grok attached {os.path.basename(abs_path)}', file=abs_path, snapshot=verify_snap.serializable())
            if not verified:
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Grok attachments requested')
        return True

    def enter_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, 'input')
        if not input_el:
            result.add_step('prompt', False, 'Grok input field not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(input_el, strategy='coordinate_only'):
            result.add_step('prompt', False, 'Grok input focus click failed', snapshot=snap.serializable())
            return False
        time.sleep(0.3)
        pasted = self.runtime.paste(request.message)
        time.sleep(0.5)
        # Grok uses section-role input — AT-SPI text/value interfaces may not work.
        # Trust the paste if clipboard operation succeeded.
        at_spi_verified = self._input_has_text()
        verified = bool(pasted)  # Trust paste; AT-SPI verification is bonus
        msg = 'Grok prompt entered' + (' (AT-SPI verified)' if at_spi_verified else ' (paste trusted)')
        result.add_step('prompt', verified, msg, snapshot=self.runtime.snapshot().serializable())
        return verified

    def send_prompt(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        before = self.runtime.current_url()
        result.session_url_before = before
        pressed = self.runtime.press('Return')
        # Stop button OR copy button confirms send succeeded.
        # Fast responses: stop appears and disappears before poll catches it,
        # but copy_button appears when response completes — confirms send worked.
        def _send_confirmed():
            snap = self.runtime.snapshot()
            return snap.has('stop_button') or snap.has('copy_button')
        stop_seen = self.runtime.wait_until(_send_confirmed, timeout=60, interval=0.6)
        # URL capture is bookkeeping, not a gate condition
        result.session_url_after = self.runtime.current_url() or before
        verify_snap = self.runtime.snapshot()
        verified = bool(pressed and stop_seen)
        result.add_step('send', verified, 'Grok send validated by Return + stop button', url_before=before, url_after=result.session_url_after, snapshot=verify_snap.serializable())
        return verified

    def monitor_generation(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        seen_stop = False

        def _poll() -> bool:
            nonlocal seen_stop
            snap = self.runtime.snapshot()
            if snap.has('stop_button'):
                seen_stop = True
                return False
            # Complete if: (1) saw stop then copy appeared, OR
            # (2) copy present and no stop — response finished before we started
            if snap.has('copy_button') and not snap.has('stop_button'):
                return True
            return False

        completed = self.runtime.wait_until(_poll, timeout=float(request.timeout), interval=1.0)
        verify_snap = self.runtime.snapshot()
        verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
        result.add_step('monitor', verified, 'Grok response completed', stop_seen=seen_stop, snapshot=verify_snap.serializable())
        return verified

    def extract_primary(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step('extract_primary', False, 'Grok copy button not found', snapshot=snap.serializable())
            return False
        if not self.runtime.click(copy_button, strategy='atspi_only'):
            result.add_step('extract_primary', False, 'Grok copy button AT-SPI action failed', snapshot=snap.serializable())
            return False
        time.sleep(0.4)
        content = self.runtime.read_clipboard().strip()
        result.response_text = content
        verified = bool(content)
        result.add_step('extract_primary', verified, 'Grok response copied to clipboard', characters=len(content), preview=content[:200])
        return verified

    def extract_additional(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        result.add_step('extract_additional', True, 'Grok additional attachment extraction not configured in YAML yet')
        return True

    def store_in_neo4j(self, request: ConsultationRequest, result: ConsultationResult) -> bool:
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step('store', True, 'Grok Neo4j storage skipped', storage=result.storage)
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
            result.add_step('store', True, 'Grok response stored in Neo4j', storage=result.storage)
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step('store', False, f'Grok Neo4j storage failed: {exc}')
            return False
