from __future__ import annotations

import os
import time

from core import input as inp
from core.interact import atspi_click
from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, ExtractedArtifact, Snapshot

try:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
except Exception:  # pragma: no cover - optional dependency in runtime
    Atspi = None

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


class PerplexityConsultationDriver(BaseConsultationDriver):
    platform = 'perplexity'

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    # run() is the shared two-phase template on BaseConsultationDriver (FLOW §10):
    # it holds the DISPLAY-scoped dispatch lock across setup_and_send (below) and
    # releases it before monitor_and_extract so monitoring runs concurrently.

    def setup_and_send(
        self, request: ConsultationRequest, result: ConsultationResult,
    ) -> bool:
        """LOCKED phase (FLOW §10): navigate → mode → connectors → attach →
        prompt → guarded send + monitor registration."""
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Perplexity tab')
            return False
        result.session_url_before = self.runtime.current_url()
        if target_url:
            navigated = self.runtime.navigate(
                target_url,
                verify_change=bool(urls.get('verify_navigation')),
            )
            snap = self.runtime.snapshot()
            result.add_step(
                'navigate', navigated,
                'Navigated to Perplexity session target',
                target_url=target_url,
                snapshot=snap.serializable(),
            )
            if not navigated:
                return False
        if not self._wait_for_prompt_ready(result):
            return False
        if not self.select_model_mode_tools(request, result):
            return False
        if request.connectors:
            if not self.toggle_connectors(request, result):
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
        """UNLOCKED phase (FLOW §10): monitor → extract → store. Display lock is
        already released so a concurrent consultation can set up/send here."""
        if not self.monitor_generation(request, result):
            return
        if not self.extract_primary(request, result):
            return
        if not self.extract_additional(request, result):
            return
        if not self.store_in_neo4j(request, result):
            return
        result.ok = True

    def _wait_for_prompt_ready(self, result: ConsultationResult) -> bool:
        snap = self.wait_for_validation('prompt_ready', timeout=5.0, interval=0.5)
        verified = self.validation_passes(snap, 'prompt_ready')
        result.add_step(
            'prompt_ready', verified,
            (
                'Perplexity prompt ready before mode selection'
                if verified else
                'Perplexity prompt not ready before mode selection'
            ),
            snapshot=snap.serializable(),
        )
        return verified

    # ------------------------------------------------------------------
    # Model / mode / tool selection
    # ------------------------------------------------------------------

    def select_model_mode_tools(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        workflow = self.cfg['workflow']['selection']
        requested_model = (request.model or '').strip().lower()
        requested_mode = (
            self.cfg['workflow']['defaults'].get('mode') or ''
        ).strip().lower() if request.mode is None else request.mode.strip().lower()

        # ── Model selection ───────────────────────────────────────────
        if requested_model and requested_model in workflow.get('model_targets', {}):
            snap = self.runtime.snapshot()
            selector = self.find_first(snap, 'model_selector')
            if not selector:
                result.add_step(
                    'select_model', False,
                    'Perplexity model selector not found',
                    snapshot=snap.serializable(),
                )
                return False
            if not self.runtime.click(selector):
                result.add_step(
                    'select_model', False,
                    'Perplexity model selector click failed',
                    snapshot=snap.serializable(),
                )
                return False
            time.sleep(0.8)
            # Model selector dropdown is a portal — must use menu_snapshot()
            menu_snap = self.runtime.menu_snapshot()
            item = self.find_first(menu_snap, workflow['model_targets'][requested_model])
            if not item:
                result.add_step(
                    'select_model', False,
                    f'Perplexity model item not found for {requested_model}',
                    snapshot=menu_snap.serializable(),
                )
                return False
            clicked = self.runtime.click(item)
            verify_snap = self.wait_for_validation(
                f'{requested_model}_active',
                timeout=5.0,
                interval=0.4,
            )
            verified = clicked and self.validation_passes(verify_snap, f'{requested_model}_active')
            result.add_step(
                'select_model', verified,
                f'Perplexity model set to {requested_model}',
                snapshot=verify_snap.serializable(),
            )
            if not verified:
                return False
        else:
            result.add_step(
                'select_model', True,
                'Perplexity model left unchanged/default',
                requested_model=request.model,
            )

        # ── Mode selection ────────────────────────────────────────────
        if requested_mode and requested_mode in workflow.get('mode_targets', {}):
            snap = self.runtime.snapshot()
            mode_active_key = f'{requested_mode}_active'
            if self.validation_passes(snap, mode_active_key):
                result.add_step(
                    'select_mode', True,
                    f'Perplexity {requested_mode} already active',
                )
            else:
                submenu_keys = self.cfg['workflow']['selection'].get('mode_submenu_keys', [])
                in_submenu = requested_mode in submenu_keys
                search_toggle_modes = {'deep_research', 'model_council', 'learn_step_by_step'}

                if requested_mode in search_toggle_modes:
                    ok = self._select_mode_via_search_toggle(
                        requested_mode,
                        mode_active_key,
                        workflow,
                        result,
                    )
                elif in_submenu:
                    ok = self._select_mode_via_submenu(
                        requested_mode, mode_active_key, workflow, result,
                    )
                else:
                    ok = self._select_mode_direct(
                        requested_mode, mode_active_key, workflow, result,
                    )
                if not ok:
                    return False
        else:
            result.add_step(
                'select_mode', True,
                'Perplexity mode left unchanged/default',
                requested_mode=request.mode,
            )

        # ── Tools (mode_targets handles all known tools) ──────────────
        mode_target_names = set(workflow.get('mode_targets', {}).keys())
        for tool_name in request.tools:
            normalized = tool_name.strip().lower().replace(' ', '_')
            if normalized in mode_target_names:
                result.add_step(
                    'select_tool', True,
                    f'Tool {tool_name!r} already handled via mode_targets',
                )
            else:
                result.add_step(
                    'select_tool', False,
                    f'Perplexity tool {tool_name!r} is not mapped in workflow.mode_targets',
                )
                return False
        return True

    def _select_mode_direct(
        self,
        requested_mode: str,
        mode_active_key: str,
        workflow: dict,
        result: ConsultationResult,
    ) -> bool:
        """Select a mode item that appears directly in the attach dropdown (not sub-menu)."""
        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger or not self.runtime.click(trigger):
            result.add_step(
                'select_mode', False,
                f'Perplexity attach trigger failed for mode {requested_mode}',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(0.8)
        menu_key = self._mode_menu_item_key(requested_mode, workflow)
        found = self.runtime.wait_until(
            lambda: self._menu_item_probe(menu_key),
            timeout=3.0,
            interval=0.4,
        )
        if not found:
            menu_snap = self.runtime.menu_snapshot()
            result.add_step(
                'select_mode', False,
                f'Perplexity mode item not found for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        menu_snap, item = found
        if not item:
            result.add_step(
                'select_mode', False,
                f'Perplexity mode item not found for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        if item.states and 'checked' in [s.lower() for s in item.states]:
            self.runtime.press('Escape')
            time.sleep(0.5)
            verify_snap = self.runtime.snapshot()
            verified = self.validation_passes(verify_snap, mode_active_key)
            result.add_step(
                'select_mode', verified,
                f'Perplexity {requested_mode} already checked in dropdown',
                snapshot=verify_snap.serializable(),
            )
            return verified
        if not self._click_menu_item_via_pointer(item):
            result.add_step(
                'select_mode', False,
                f'Perplexity mode click failed for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        verify_snap = self.runtime.wait_until(
            lambda: self._active_snapshot(mode_active_key),
            timeout=3.0,
            interval=0.4,
        ) or self.runtime.snapshot()
        result.add_step(
            'select_mode', self.validation_passes(verify_snap, mode_active_key),
            f'Perplexity mode set to {requested_mode}',
            snapshot=verify_snap.serializable(),
        )
        return self.validation_passes(verify_snap, mode_active_key)

    def _toggle_mode_button(
        self,
        toggle_key: str,
        mode_active_key: str,
        result: ConsultationResult,
        requested_mode: str,
    ) -> bool:
        snap = self.runtime.snapshot()
        toggle = self.find_first(snap, toggle_key)
        if not toggle:
            result.add_step(
                'select_mode', False,
                f'Perplexity toggle button {toggle_key} not found for {requested_mode}',
                snapshot=snap.serializable(),
            )
            return False
        if not self.runtime.click(toggle, strategy='atspi_first'):
            result.add_step(
                'select_mode', False,
                f'Perplexity toggle button click failed for {requested_mode}',
                snapshot=snap.serializable(),
            )
            return False
        verify_snap = self.runtime.wait_until(
            lambda: self._active_snapshot(mode_active_key),
            timeout=3.0,
            interval=0.4,
        ) or self.runtime.snapshot()
        result.add_step(
            'select_mode',
            self.validation_passes(verify_snap, mode_active_key),
            f'Perplexity mode set to {requested_mode}',
            snapshot=verify_snap.serializable(),
        )
        return self.validation_passes(verify_snap, mode_active_key)

    def _select_mode_via_search_toggle(
        self,
        requested_mode: str,
        mode_active_key: str,
        workflow: dict,
        result: ConsultationResult,
    ) -> bool:
        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'search_mode_trigger')
        if not trigger:
            result.add_step(
                'select_mode', False,
                f'Perplexity search mode trigger not found for {requested_mode}',
                snapshot=snap.serializable(),
            )
            return False
        if not self.runtime.click(trigger):
            result.add_step(
                'select_mode', False,
                f'Perplexity search mode trigger click failed for {requested_mode}',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(0.8)
        menu_key = self._mode_menu_item_key(requested_mode, workflow)
        found = self.runtime.wait_until(
            lambda: self._menu_item_probe(menu_key),
            timeout=3.0,
            interval=0.4,
        )
        if not found:
            menu_snap = self.runtime.menu_snapshot()
            result.add_step(
                'select_mode', False,
                f'Perplexity mode item not found for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        menu_snap, item = found
        if not item:
            result.add_step(
                'select_mode', False,
                f'Perplexity mode item not found for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        if item.states and 'checked' in [s.lower() for s in item.states]:
            self.runtime.press('Escape')
            time.sleep(0.5)
            verify_snap = self.runtime.snapshot()
            verified = self.validation_passes(verify_snap, mode_active_key)
            result.add_step(
                'select_mode', verified,
                f'Perplexity {requested_mode} already checked in search menu',
                snapshot=verify_snap.serializable(),
            )
            return verified
        if not self._click_menu_item_via_pointer(item):
            result.add_step(
                'select_mode', False,
                f'Perplexity mode item click failed for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        verify_snap = self.runtime.wait_until(
            lambda: self._active_snapshot(mode_active_key),
            timeout=3.0,
            interval=0.4,
        ) or self.runtime.snapshot()
        result.add_step(
            'select_mode',
            self.validation_passes(verify_snap, mode_active_key),
            f'Perplexity mode set to {requested_mode}',
            snapshot=verify_snap.serializable(),
        )
        return self.validation_passes(verify_snap, mode_active_key)

    def _select_mode_via_submenu(
        self,
        requested_mode: str,
        mode_active_key: str,
        workflow: dict,
        result: ConsultationResult,
    ) -> bool:
        """Select a mode item that lives inside the 'More' sub-menu of the attach dropdown."""
        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger or not self.runtime.click(trigger):
            result.add_step(
                'select_mode', False,
                f'Perplexity attach trigger failed for sub-menu mode {requested_mode}',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(0.8)
        menu_snap = self.runtime.menu_snapshot()
        more_item = self.find_first(menu_snap, 'attach_more_trigger')
        if not more_item:
            result.add_step(
                'select_mode', False,
                f'Perplexity "More" menu item not found (needed for {requested_mode})',
                snapshot=menu_snap.serializable(),
            )
            return False
        if not self.runtime.click(more_item):
            result.add_step(
                'select_mode', False,
                f'Perplexity "More" menu item click failed (needed for {requested_mode})',
                snapshot=menu_snap.serializable(),
            )
            return False
        time.sleep(0.5)
        menu_key = self._mode_menu_item_key(requested_mode, workflow)
        found = self.runtime.wait_until(
            lambda: self._menu_item_probe(menu_key),
            timeout=3.0,
            interval=0.4,
        )
        if not found:
            submenu_snap = self.runtime.menu_snapshot()
            result.add_step(
                'select_mode', False,
                f'Perplexity sub-menu item not found for {requested_mode}',
                snapshot=submenu_snap.serializable(),
            )
            return False
        submenu_snap, item = found
        if not item:
            result.add_step(
                'select_mode', False,
                f'Perplexity sub-menu item not found for {requested_mode}',
                snapshot=submenu_snap.serializable(),
            )
            return False
        if item.states and 'checked' in [s.lower() for s in item.states]:
            self.runtime.press('Escape')
            time.sleep(0.5)
            verify_snap = self.runtime.snapshot()
            verified = self.validation_passes(verify_snap, mode_active_key)
            result.add_step(
                'select_mode', verified,
                f'Perplexity {requested_mode} already checked in sub-menu',
                snapshot=verify_snap.serializable(),
            )
            return verified
        if not self._click_menu_item_via_pointer(item):
            result.add_step(
                'select_mode', False,
                f'Perplexity sub-menu item click failed for {requested_mode}',
                snapshot=submenu_snap.serializable(),
            )
            return False
        verify_snap = self.runtime.wait_until(
            lambda: self._active_snapshot(mode_active_key),
            timeout=3.0,
            interval=0.4,
        ) or self.runtime.snapshot()
        result.add_step(
            'select_mode', self.validation_passes(verify_snap, mode_active_key),
            f'Perplexity sub-menu mode set to {requested_mode}',
            snapshot=verify_snap.serializable(),
        )
        return self.validation_passes(verify_snap, mode_active_key)

    def _mode_menu_item_key(self, requested_mode: str, workflow: dict) -> str:
        if requested_mode == 'deep_research':
            return 'deep_research'
        return workflow['mode_targets'][requested_mode]

    def _menu_item_probe(self, item_key: str):
        menu_snap = self.runtime.menu_snapshot()
        item = self.find_first(menu_snap, item_key)
        if not item:
            return None
        return menu_snap, item

    def _active_snapshot(self, validation_key: str):
        snap = self.runtime.snapshot()
        if self.validation_passes(snap, validation_key):
            return snap
        return None

    def _click_menu_item_via_pointer(self, item) -> bool:
        atspi_obj = getattr(item, 'atspi_obj', None)
        if not atspi_obj:
            return False
        try:
            component = atspi_obj.get_component_iface()
            if not component:
                return False
            coord_type = Atspi.CoordType.SCREEN if Atspi is not None else 0
            ext = component.get_extents(coord_type)
            x = int(ext.x + (ext.width / 2))
            y = int(ext.y + (ext.height / 2))
        except Exception:
            return False
        return bool(inp.click_at(x, y))

    # ------------------------------------------------------------------
    # Connector toggles
    # ------------------------------------------------------------------

    def toggle_connectors(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        self.runtime.close_stale_dialogs()
        cfg_connectors = self.cfg['workflow'].get('connectors', {})
        source_targets: dict[str, str] = cfg_connectors.get('source_targets', {})

        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger:
            result.add_step(
                'toggle_connectors', False,
                'Perplexity attach_trigger not found for connector panel',
                snapshot=snap.serializable(),
            )
            return False
        if not self.runtime.click(trigger):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity attach_trigger click failed for connector panel',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(1.5)

        menu_snap = self.runtime.menu_snapshot()
        panel_trigger = self.find_first(menu_snap, 'git_connector_item')
        if not panel_trigger:
            result.add_step(
                'toggle_connectors', False,
                'Perplexity git_connector_item not found in attach dropdown',
                snapshot=menu_snap.serializable(),
            )
            return False
        if not self.runtime.click(panel_trigger):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity git_connector_item click failed',
                snapshot=menu_snap.serializable(),
            )
            return False
        time.sleep(2.0)

        for connector_name in request.connectors:
            normalized = connector_name.strip().lower()
            element_key = source_targets.get(normalized)
            if not element_key:
                result.add_step(
                    'toggle_connectors', False,
                    f'Connector {connector_name!r} not found in source_targets mapping',
                )
                return False

            panel_snap = self.runtime.menu_snapshot()
            search_box = self.find_first(panel_snap, 'search_sources')
            if not search_box:
                result.add_step(
                    'toggle_connectors', False,
                    f'Perplexity search_sources not found in connector panel '
                    f'(needed for {connector_name!r})',
                    snapshot=panel_snap.serializable(),
                )
                return False

            if not self.runtime.click(search_box):
                result.add_step(
                    'toggle_connectors', False,
                    f'Perplexity search_sources click failed for {connector_name!r}',
                    snapshot=panel_snap.serializable(),
                )
                return False
            time.sleep(0.3)
            self.runtime.press('ctrl+a')
            time.sleep(0.1)
            self.runtime.press('Delete')
            time.sleep(0.1)
            self.runtime.type_text(connector_name, delay_ms=40)
            time.sleep(1.5)

            filtered_snap = self.runtime.menu_snapshot()
            item = self.find_first(filtered_snap, element_key)
            if not item:
                result.add_step(
                    'toggle_connectors', False,
                    f'Perplexity connector element {element_key!r} not found in panel '
                    f'after searching for {connector_name!r}',
                    snapshot=filtered_snap.serializable(),
                )
                return False

            already_checked = bool(
                item.states and 'checked' in [s.lower() for s in item.states]
            )
            if already_checked:
                result.add_step(
                    'toggle_connectors', True,
                    f'Connector {connector_name!r} already enabled — skipping',
                )
            else:
                if not self.runtime.click(item):
                    result.add_step(
                        'toggle_connectors', False,
                        f'Perplexity connector click failed for {connector_name!r}',
                        snapshot=filtered_snap.serializable(),
                    )
                    return False
                time.sleep(0.5)
                result.add_step(
                    'toggle_connectors', True,
                    f'Connector {connector_name!r} clicked to enable',
                )

            panel_snap2 = self.runtime.menu_snapshot()
            search_box2 = self.find_first(panel_snap2, 'search_sources')
            if search_box2:
                self.runtime.click(search_box2)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.3)

        self.runtime.press('Escape')
        time.sleep(0.8)

        snap = self.runtime.snapshot()
        trigger = self.find_first(snap, 'attach_trigger')
        if not trigger or not self.runtime.click(trigger):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity attach_trigger re-open failed during connector verification',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(1.5)

        menu_snap2 = self.runtime.menu_snapshot()
        panel_trigger2 = self.find_first(menu_snap2, 'git_connector_item')
        if not panel_trigger2 or not self.runtime.click(panel_trigger2):
            result.add_step(
                'toggle_connectors', False,
                'Perplexity git_connector_item re-open failed during connector verification',
                snapshot=menu_snap2.serializable(),
            )
            return False
        time.sleep(2.0)

        all_verified = True
        for connector_name in request.connectors:
            normalized = connector_name.strip().lower()
            element_key = source_targets.get(normalized)
            if not element_key:
                continue

            verify_panel_snap = self.runtime.menu_snapshot()
            search_box = self.find_first(verify_panel_snap, 'search_sources')
            if search_box:
                self.runtime.click(search_box)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.1)
                self.runtime.type_text(connector_name, delay_ms=40)
                time.sleep(1.5)

            verify_panel_snap2 = self.runtime.menu_snapshot()
            verify_item = self.find_first(verify_panel_snap2, element_key)
            is_checked = bool(
                verify_item
                and verify_item.states
                and 'checked' in [s.lower() for s in verify_item.states]
            )
            if not is_checked:
                all_verified = False
            result.add_step(
                'verify_connector', is_checked,
                f'Connector {connector_name!r} verified {"enabled" if is_checked else "NOT enabled"}',
                snapshot=verify_panel_snap2.serializable(),
            )

            verify_panel_snap3 = self.runtime.menu_snapshot()
            search_box3 = self.find_first(verify_panel_snap3, 'search_sources')
            if search_box3:
                self.runtime.click(search_box3)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.3)

        self.runtime.press('Escape')
        time.sleep(0.5)

        result.add_step(
            'toggle_connectors', all_verified,
            'Perplexity connector toggle complete',
            requested=request.connectors,
        )
        return all_verified

    # ------------------------------------------------------------------
    # File attachment
    # ------------------------------------------------------------------

    def attach_files(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        self.runtime.close_stale_dialogs()
        for file_path in request.attachments:
            abs_path = os.path.abspath(file_path)
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, 'attach_trigger')
            if not trigger:
                result.add_step(
                    'attach', False,
                    f'Perplexity attach trigger missing for {abs_path}',
                    snapshot=snap.serializable(),
                )
                return False
            if not self.runtime.click(trigger):
                result.add_step(
                    'attach', False,
                    f'Perplexity attach trigger click failed for {abs_path}',
                    snapshot=snap.serializable(),
                )
                return False
            # Settle + rescan (DRIVER_CONTRACT §E): the attach dropdown's
            # "Upload files or images" item renders a beat after the trigger
            # click. A fixed time.sleep(0.7) + one-shot read flaked ("upload
            # item not found") when the menu was slow to render — the item was
            # present moments later. Poll for it (observation only, no re-click)
            # before declaring it missing, same readiness pattern as mode-select.
            self.runtime.wait_until(
                lambda: self.runtime.menu_snapshot().has('upload_files_item'),
                timeout=10,
                interval=0.4,
            )
            menu_snap = self.runtime.menu_snapshot()
            upload_item = self.find_first(menu_snap, 'upload_files_item')
            if not upload_item:
                result.add_step(
                    'attach', False,
                    f'Perplexity upload item not found for {abs_path}',
                    snapshot=menu_snap.serializable(),
                )
                return False
            if not self.runtime.click(upload_item):
                result.add_step(
                    'attach', False,
                    f'Perplexity upload item click failed for {abs_path}',
                    snapshot=menu_snap.serializable(),
                )
                return False
            time.sleep(0.8)
            self.runtime.focus_file_dialog()
            self.runtime.press('ctrl+l')
            time.sleep(0.2)
            if not self.runtime.paste(abs_path):
                self.runtime.type_text(abs_path, delay_ms=5)
            time.sleep(0.2)
            self.runtime.press('Return')
            time.sleep(1.2)
            verify_snap = self.wait_for_validation(
                'attach_success',
                filename=abs_path,
                timeout=15.0,
                interval=0.5,
            )
            verified = self.validation_passes(verify_snap, 'attach_success', filename=abs_path)
            result.add_step(
                'attach', verified,
                f'Perplexity attached {os.path.basename(abs_path)}',
                file=abs_path,
                snapshot=verify_snap.serializable(),
            )
            if not verified:
                return False
        if not request.attachments:
            result.add_step('attach', True, 'No Perplexity attachments requested')
        return True

    # ------------------------------------------------------------------
    # Prompt entry
    # ------------------------------------------------------------------

    def enter_prompt(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, 'input')
        if not input_el:
            result.add_step(
                'prompt', False,
                'Perplexity input field not found',
                snapshot=snap.serializable(),
            )
            return False
        if not self.runtime.click(input_el):
            result.add_step(
                'prompt', False,
                'Perplexity input focus click failed',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(0.3)
        pasted = self.runtime.paste(request.message)
        verify_snap, submit_visible = self.wait_for_key(
            'submit_button',
            timeout=8.0,
            interval=0.4,
            select='last',
        )
        verified = bool(pasted and submit_visible)
        result.add_step(
            'prompt',
            verified,
            (
                'Perplexity prompt entered and Submit button appeared'
                if verified else
                'Perplexity prompt entry failed validation: Submit button did not appear'
            ),
            snapshot=verify_snap.serializable(),
        )
        return verified

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_prompt(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        before = result.session_url_before
        snap, send_button, submit_scope = self._find_submit_button_for_send()
        if send_button:
            click_returned = self.runtime.click(send_button)
        else:
            result.add_step(
                'send', False,
                'Perplexity submit button not found',
                submit_scope=submit_scope,
                snapshot=snap.serializable(),
            )
            return False

        send_timeout = float(self.cfg.get('validation', {}).get('send_success', {}).get('timeout', 60))
        send_snap = self.wait_for_validation(
            'send_success',
            timeout=send_timeout,
            interval=0.6,
        )
        stop_seen = self.validation_passes(send_snap, 'send_success')
        settled_url = self.runtime.current_url() or before
        for _ in range(8):
            time.sleep(1.0)
            current = self.runtime.current_url() or settled_url
            if current and current != settled_url:
                settled_url = current
            else:
                break
        result.session_url_after = settled_url
        verify_snap = self.runtime.snapshot()
        url_changed = settled_url and settled_url != before
        is_new_session = not request.session_url
        if is_new_session:
            verified = bool(click_returned and stop_seen and url_changed)
        else:
            verified = bool(click_returned and stop_seen and settled_url)
        msg = (
            'Perplexity send validated by Stop button appearance and URL capture'
            if verified else
            'Perplexity send failed validation: Stop button did not appear or URL was not captured'
        )
        result.add_step(
            'send', verified,
            msg,
            url_before=before,
            url_after=settled_url,
            submit_scope=submit_scope,
            click_returned=click_returned,
            stop_seen=bool(stop_seen),
            snapshot=verify_snap.serializable(),
        )
        return verified

    def _find_submit_button_for_send(self) -> tuple[Snapshot, ElementRef | None, str]:
        snap = self.runtime.snapshot()
        send_button = self.find_last(snap, 'submit_button')
        if send_button:
            return snap, send_button, 'document'
        app_root_snap = self.runtime.menu_snapshot()
        send_button = self.find_last(app_root_snap, 'submit_button')
        if send_button:
            return app_root_snap, send_button, 'app_root'
        return app_root_snap, None, 'not_found'

    # ------------------------------------------------------------------
    # Monitor generation — inherited from BaseConsultationDriver (the shared
    # stop-transition detector, consultation_v2.completion). deep_research is a
    # deep mode (2 stop-gone cycles) so a transient stop-drop mid-research never
    # false-completes.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _is_deep_research(self, request: ConsultationRequest) -> bool:
        """Return True if the current request is a Deep Research mode query."""
        mode = (request.mode or '').strip().lower()
        if mode == 'deep_research':
            return True
        default_mode = (
            self.cfg.get('workflow', {}).get('defaults', {}).get('mode') or ''
        ).strip().lower()
        return default_mode == 'deep_research'

    def _dr_select_all_copy(self, result: ConsultationResult) -> str | None:
        """
        Deep Research clipboard extraction via Ctrl+A / Ctrl+C on the response body.

        Strategy:
          1. Clear clipboard (sentinel).
          2. Click into the response document area to focus it.
          3. Ctrl+A to select all rendered text.
          4. Ctrl+C to copy selection to clipboard.
          5. Read and return clipboard content.

        Returns the clipboard string (may be empty) or None on hard failure
        (e.g. cannot locate a focusable response area).
        """
        # Step 1 — clear clipboard so stale content cannot masquerade as a fresh copy
        self.runtime.write_clipboard('')
        time.sleep(0.2)

        # Step 2 — focus the response area.
        # V2 only maps the stable Copy button, so we use that as the focus
        # anchor before selecting all rendered text.
        snap = self.runtime.snapshot()

        # Focus the response area via the last visible Copy button; V2 does not
        # map a stable response_body key, so the mapped copy_button is the only
        # approved focus anchor here.
        copy_btn = self.find_last(snap, 'copy_button')
        if copy_btn:
            self.runtime.click(copy_btn)
        else:
            result.add_step(
                'extract_primary', False,
                'Perplexity DR: cannot locate copy_button for focus',
                snapshot=snap.serializable(),
            )
            return None

        time.sleep(0.4)

        # Step 3 — Ctrl+A: select all content in the focused region
        self.runtime.press('ctrl+a')
        time.sleep(0.5)

        # Step 4 — Ctrl+C: copy selection
        self.runtime.press('ctrl+c')
        time.sleep(1.0)

        # Step 5 — read clipboard
        content = self.runtime.read_clipboard()
        return content

    def _is_report_tree_text_value(
        self,
        text: str,
        role: str,
        x: int | None,
    ) -> bool:
        text = (text or '').strip()
        if not text:
            return False
        if role not in {'heading', 'list item', 'table cell'}:
            return False
        if x is None or x < 600:
            return False
        lowered = text.lower()
        rejected = {
            'answer',
            'links',
            'images',
            'prepared by deep research',
            'run as a separate task in computer for better results',
            'computer produces a richer output using more tools and context.',
        }
        if lowered in rejected:
            return False
        if text.endswith('.md') or text.startswith('Family consultation —'):
            return False
        if lowered.startswith('add files') or lowered.startswith('mozilla firefox'):
            return False
        if lowered.startswith('search with google') or lowered.startswith('open context menu'):
            return False
        return True

    def _is_report_tree_text(self, element: ElementRef) -> bool:
        return self._is_report_tree_text_value(element.name, element.role, element.x)

    def _collect_report_tree_text(self) -> tuple[str, dict[str, object]]:
        """Collect Perplexity DR report text from the live AT-SPI tree.

        Current Perplexity DR occasionally exposes only the bottom `Copy` button,
        which copies an empty clipboard. When the report-level `Copy contents`
        control is absent, the answer body is still present as main-column
        AT-SPI text nodes. This fallback reads those nodes directly, bounded by
        scroll rounds and minimum extracted length.
        """
        first_snap = self.runtime.snapshot()
        anchor = self.find_first(first_snap, 'input')
        chunks: list[str] = []
        seen: set[str] = set()
        rounds = 0

        def collect(snapshot: Snapshot) -> int:
            added = 0
            try:
                from core import atspi
                from core.tree import find_elements as raw_find_elements
                firefox = atspi.find_firefox_for_platform(self.platform)
                doc = atspi.get_platform_document(firefox, self.platform) if firefox else None
                raw_elements = raw_find_elements(doc or firefox, max_depth=30, fence_after=[])
                raw_elements = sorted(
                    raw_elements,
                    key=lambda item: (item.get('y') or 0, item.get('x') or 0),
                )
            except Exception:
                raw_elements = []

            for raw in raw_elements:
                text = ' '.join(((raw.get('name') or '')).split())
                role = raw.get('role') or ''
                x = raw.get('x')
                if not self._is_report_tree_text_value(text, role, x):
                    continue
                if text in seen:
                    continue
                seen.add(text)
                chunks.append(text)
                added += 1

            if added:
                return added

            buckets = list(snapshot.mapped.values()) + [
                snapshot.unknown,
                snapshot.sidebar,
                snapshot.menu_items,
            ]
            for items in buckets:
                for element in items:
                    if not self._is_report_tree_text(element):
                        continue
                    text = ' '.join((element.name or '').split())
                    if text in seen:
                        continue
                    seen.add(text)
                    chunks.append(text)
                    added += 1
            return added

        self.runtime.press('ctrl+Home')
        time.sleep(0.2)
        self.runtime.press('Home')
        time.sleep(0.8)
        stable_rounds = 0
        last_count = 0
        for _ in range(14):
            rounds += 1
            snap = self.runtime.menu_snapshot()
            collect(snap)
            if len(chunks) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = len(chunks)
            if stable_rounds >= 2 and rounds >= 3:
                break
            if anchor and anchor.x is not None and anchor.y is not None:
                self.runtime.scroll_to_bottom(anchor, clicks=8, max_rounds=1, settle=0.5)
            else:
                self.runtime.press('Page_Down')
                time.sleep(0.5)

        content = '\n\n'.join(chunks).strip()
        metadata = {
            'tree_items': len(chunks),
            'scroll_rounds': rounds,
            'characters': len(content),
        }
        if len(content) < 1000 or len(chunks) < 3:
            return '', metadata
        return content, metadata

    def extract_primary(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        # Wait for response to fully render.
        time.sleep(2.0)

        # NOTE: Perplexity DR is a REPORT (Jesse's rule: "reports require
        # special handling"). The full-report "Copy contents" control is a
        # report-level button, NOT bottom-anchored like a chat-bubble Copy, so
        # the blanket scroll-to-bottom used on the chat platforms does NOT apply
        # cleanly here (it could scroll past the report controls). This path was
        # already extracting full reports in place (copy_contents_button first,
        # then plain copy_button), so it is left as-is rather than risking the
        # report grab with a blanket scroll. If a long plain-answer ever needs
        # scroll, gate it to the copy_button fallback only, never copy_contents.

        # Use snapshot (which clears AT-SPI cache via build_snapshot) to find
        # copy buttons. Raw find_elements bypasses cache clearing and misses
        # elements after the long monitor polling phase.
        snap = self.runtime.snapshot()

        # Prefer "Copy contents" for DR. Do NOT fall back to the visible bottom
        # `Copy` button for DR: production 2026-06-17 showed that button can
        # return an empty clipboard on a completed report.
        is_deep_research = self._is_deep_research(request)
        target = self.find_last(snap, 'copy_contents_button')
        if not is_deep_research and target is None:
            target = self.find_last(snap, 'copy_button')
        if not target:
            if is_deep_research:
                content, metadata = self._collect_report_tree_text()
                if content:
                    result.response_text = content
                    result.add_step(
                        'extract_primary', True,
                        'Perplexity DR extracted via AT-SPI report tree text '
                        '(copy_contents_button absent)',
                        preview=content[:200],
                        **metadata,
                    )
                    return True
            result.add_step(
                'extract_primary', False,
                'Perplexity no usable copy target found',
                snapshot=snap.serializable(),
            )
            return False

        # Perplexity's DR Copy / "Copy contents" returns an EMPTY clipboard if
        # action-clicked while OFF-SCREEN — scroll the button itself into view
        # first (Component.scroll_to ANYWHERE). This is the report special-
        # handling: scroll the CONTROL, not the page. (Production-observed:
        # without this the copy click landed empty; with it, 23.7k extracted.)
        self.runtime.scroll_element_into_view(target)
        time.sleep(0.5)
        # Clear clipboard, click via AT-SPI action, read clipboard
        self.runtime.write_clipboard('')
        time.sleep(0.3)
        clicked = self.runtime.click(target, strategy='atspi_only')
        time.sleep(1.0)
        content = self.runtime.read_clipboard().strip()
        if not content:
            # Empty clipboard → the button likely wasn't in view yet. Re-scroll
            # the control + re-click ONCE (a local copy action, not a send/nav
            # retry — extraction retries are allowed, cf. claude extract).
            self.runtime.scroll_element_into_view(target)
            time.sleep(0.6)
            self.runtime.click(target, strategy='atspi_only')
            time.sleep(1.2)
            content = self.runtime.read_clipboard().strip()

        if content:
            result.response_text = content
            result.add_step(
                'extract_primary', True,
                f'Perplexity response extracted via {target.name!r} ({len(content)} chars)',
                characters=len(content),
                preview=content[:200],
            )
            return True

        if is_deep_research:
            content, metadata = self._collect_report_tree_text()
            if content:
                result.response_text = content
                result.add_step(
                    'extract_primary', True,
                    'Perplexity DR extracted via AT-SPI report tree text '
                    f'after empty clipboard from {target.name!r}',
                    preview=content[:200],
                    **metadata,
                )
                return True

        result.add_step(
            'extract_primary', False,
            f'Perplexity copy target clicked but clipboard empty (button: {target.name!r})',
        )
        return False

    def extract_additional(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        snap = self.runtime.snapshot()
        copy_contents = self.find_first(snap, 'copy_contents_button')

        # If extract_primary already consumed the DR path (Ctrl+A/Ctrl+C),
        # skip copy_contents_button here to avoid double-extraction.
        if copy_contents and not self._is_deep_research(request):
            self.runtime.write_clipboard('')
            time.sleep(0.2)

            if self.runtime.click(copy_contents):
                time.sleep(1.0)
                content = self.runtime.read_clipboard().strip()
                if content:
                    result.extractions.append(
                        ExtractedArtifact(
                            name='perplexity_full_contents.md',
                            content=content,
                            kind='report_export',
                            metadata={'source': 'copy_contents_button'},
                        )
                    )
                    result.add_step(
                        'extract_additional', True,
                        'Perplexity full contents copied via copy_contents_button',
                        characters=len(content),
                        preview=content[:200],
                    )
                    return True

                result.add_step(
                    'extract_additional', True,
                    'Perplexity copy_contents_button clicked but clipboard empty; '
                    'AT-SPI action did not fire — skipping',
                )
                return True

        # copy_contents_button not found, not clickable, or DR already extracted
        result.add_step(
            'extract_additional', True,
            'Perplexity copy_contents_button not found or skipped (DR already extracted)',
        )
        return True

    # ------------------------------------------------------------------
    # Neo4j storage
    # ------------------------------------------------------------------

    def store_in_neo4j(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        if request.no_neo4j or neo4j_client is None:
            result.storage = {'skipped': True, 'reason': 'Neo4j disabled or unavailable'}
            result.add_step(
                'store', True,
                'Perplexity Neo4j storage skipped',
                storage=result.storage,
            )
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
                session_id, 'assistant',
                result.response_text,
                self.serialize_artifacts(result.extractions),
            )
            result.storage = {
                'session_id': session_id,
                'user_message_id': user_message_id,
                'assistant_message_id': assistant_message_id,
                'url': session_url,
            }
            result.add_step(
                'store', True,
                'Perplexity response stored in Neo4j',
                storage=result.storage,
            )
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step(
                'store', False,
                f'Perplexity Neo4j storage failed: {exc}',
            )
            return False
