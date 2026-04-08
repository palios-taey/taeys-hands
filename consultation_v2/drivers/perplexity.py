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

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        result = self.result(request)
        urls = self.cfg.get('urls', {})
        target_url = request.session_url or urls.get('fresh')
        if not self.runtime.switch():
            result.add_step('navigate', False, 'Could not switch to Perplexity tab')
            return result
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
                return result
        if not self.select_model_mode_tools(request, result):
            return result
        if request.connectors:
            if not self.toggle_connectors(request, result):
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
            time.sleep(0.8)
            verify_snap = self.runtime.snapshot()
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
            # Check if mode is already active before opening any dropdown
            snap = self.runtime.snapshot()
            mode_active_key = f'{requested_mode}_active'
            if self.validation_passes(snap, mode_active_key):
                result.add_step(
                    'select_mode', True,
                    f'Perplexity {requested_mode} already active',
                )
            else:
                # Determine whether target lives in the "More" sub-menu
                submenu_keys = self.cfg['workflow']['selection'].get('mode_submenu_keys', [])
                in_submenu = requested_mode in submenu_keys

                if in_submenu:
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
                    'select_tool', True,
                    f'Unknown tool {tool_name!r} ignored; Perplexity does not support individual tool toggles',
                )
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
        # Attach dropdown is a React portal — must use menu_snapshot()
        menu_snap = self.runtime.menu_snapshot()
        item = self.find_first(menu_snap, workflow['mode_targets'][requested_mode])
        if not item:
            result.add_step(
                'select_mode', False,
                f'Perplexity mode item not found for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        # Check if already checked in dropdown — if so, just close and skip
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
        if not self.runtime.click(item):
            result.add_step(
                'select_mode', False,
                f'Perplexity mode click failed for {requested_mode}',
                snapshot=menu_snap.serializable(),
            )
            return False
        time.sleep(1.0)
        # Close dropdown — direct items don't auto-close
        self.runtime.press('Escape')
        time.sleep(1.0)
        # Verify via persistent toolbar indicator (document scope)
        verify_snap = self.runtime.snapshot()
        verified = self.validation_passes(verify_snap, mode_active_key)
        result.add_step(
            'select_mode', verified,
            f'Perplexity mode set to {requested_mode}',
            snapshot=verify_snap.serializable(),
        )
        return verified

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
        # Attach dropdown is a React portal — must use menu_snapshot()
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
        # Sub-menu also renders in the portal — another menu_snapshot() required
        submenu_snap = self.runtime.menu_snapshot()
        item = self.find_first(submenu_snap, workflow['mode_targets'][requested_mode])
        if not item:
            result.add_step(
                'select_mode', False,
                f'Perplexity sub-menu item not found for {requested_mode}',
                snapshot=submenu_snap.serializable(),
            )
            return False
        # Check if already checked in sub-menu — if so, just close and skip
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
        if not self.runtime.click(item):
            result.add_step(
                'select_mode', False,
                f'Perplexity sub-menu item click failed for {requested_mode}',
                snapshot=submenu_snap.serializable(),
            )
            return False
        time.sleep(1.0)
        # Sub-menu items auto-close the dropdown after click.
        # Verify via persistent toolbar indicator (document scope)
        verify_snap = self.runtime.snapshot()
        verified = self.validation_passes(verify_snap, mode_active_key)
        result.add_step(
            'select_mode', verified,
            f'Perplexity sub-menu mode set to {requested_mode}',
            snapshot=verify_snap.serializable(),
        )
        return verified

    # ------------------------------------------------------------------
    # Connector toggles
    # ------------------------------------------------------------------

    def toggle_connectors(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        """
        Enable the connectors listed in request.connectors.

        Flow:
          1. Click attach_trigger to open the attach dropdown.
          2. Click git_connector_item to open the connectors/sources panel
             (renders in a Firefox portal — use menu_snapshot()).
          3. For each requested connector:
             a. Find search_sources in the panel and click it.
             b. Clear any existing text (Ctrl+A, Delete), then type the connector name.
             c. Take a fresh menu_snapshot() to find the now-filtered item.
             d. Look up the element key via workflow.connectors.source_targets.
             e. If NOT already checked, click to enable.  If already checked, skip.
             f. Clear the search box (Ctrl+A, Delete) before moving to the next connector.
          4. Press Escape to close the panel.
          5. Verify each connector's final state via a fresh re-open of the panel,
             using the same search-box approach so the item is visible.
        """
        cfg_connectors = self.cfg['workflow'].get('connectors', {})
        source_targets: dict[str, str] = cfg_connectors.get('source_targets', {})

        # ── Step 1: open attach dropdown ─────────────────────────────
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

        # ── Step 2: click git_connector_item to open the panel ───────
        # Attach dropdown is a React portal — must use menu_snapshot()
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

        # ── Step 3: for each connector, use search box to surface it ─
        for connector_name in request.connectors:
            normalized = connector_name.strip().lower()
            element_key = source_targets.get(normalized)
            if not element_key:
                result.add_step(
                    'toggle_connectors', False,
                    f'Connector {connector_name!r} not found in source_targets mapping',
                )
                return False

            # 3a. Find the search_sources box in the panel
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

            # 3b. Click the search box, clear it, type the connector name
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

            # 3c. Take a fresh snapshot — the filtered item should now be visible
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

            # 3d/3e. Check state and click if not already enabled
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

            # 3f. Clear the search box before moving to the next connector
            panel_snap2 = self.runtime.menu_snapshot()
            search_box2 = self.find_first(panel_snap2, 'search_sources')
            if search_box2:
                self.runtime.click(search_box2)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.3)

        # ── Step 4: close the panel with Escape ──────────────────────
        self.runtime.press('Escape')
        time.sleep(0.8)

        # ── Step 5: verify — re-open panel and confirm checked states ─
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

            # Use search box to surface the item before verifying
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

            # Clear search before next iteration
            verify_panel_snap3 = self.runtime.menu_snapshot()
            search_box3 = self.find_first(verify_panel_snap3, 'search_sources')
            if search_box3:
                self.runtime.click(search_box3)
                time.sleep(0.2)
                self.runtime.press('ctrl+a')
                time.sleep(0.1)
                self.runtime.press('Delete')
                time.sleep(0.3)

        # Close the panel before continuing
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
            time.sleep(0.7)
            # Attach dropdown is a React portal — must use menu_snapshot()
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
        time.sleep(1.0)
        verify_snap = self.runtime.snapshot()
        submit_visible = self.find_first(verify_snap, 'submit_button')
        msg = 'Perplexity prompt entered'
        if submit_visible:
            msg += ' (Submit button appeared)'
        elif pasted:
            msg += ' (paste ok but Submit not visible — may need focus)'
        result.add_step('prompt', bool(pasted), msg, snapshot=verify_snap.serializable())
        return bool(pasted)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_prompt(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        # Use the pre-navigation baseline captured in run() at line 29.
        # If files were attached, Perplexity may have already changed the URL
        # by send time — so self.runtime.current_url() here would produce a
        # stale "before" that matches "after", causing the URL-change gate to
        # fail.  result.session_url_before is always the original target URL.
        before = result.session_url_before
        snap = self.runtime.snapshot()
        send_button = self.find_first(snap, 'submit_button')
        if send_button:
            clicked = self.runtime.click(send_button)
        else:
            clicked = self.runtime.press('Return')

        def _send_confirmed() -> bool:
            s = self.runtime.snapshot()
            return s.has('stop_button') or s.has('copy_button')

        stop_seen = self.runtime.wait_until(_send_confirmed, timeout=60, interval=0.6)
        # Settle redirect chain — Perplexity routes through /search/new/ before landing
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
            verified = bool(clicked and stop_seen and url_changed)
        else:
            verified = bool(clicked and stop_seen)
        result.add_step(
            'send', verified,
            'Perplexity send validated by stop/copy button',
            url_before=before,
            url_after=settled_url,
            snapshot=verify_snap.serializable(),
        )
        return verified

    # ------------------------------------------------------------------
    # Monitor generation
    # ------------------------------------------------------------------

    def monitor_generation(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        seen_stop = False

        def _poll() -> bool:
            nonlocal seen_stop
            snap = self.runtime.snapshot()
            if snap.has('stop_button'):
                seen_stop = True
                return False
            if snap.has('copy_button') and not snap.has('stop_button'):
                return True
            return False

        completed = self.runtime.wait_until(
            _poll,
            timeout=float(request.timeout),
            interval=1.0,
        )
        verify_snap = self.runtime.snapshot()
        verified = bool(
            completed and self.validation_passes(verify_snap, 'response_complete')
        )
        result.add_step(
            'monitor', verified,
            'Perplexity response completed',
            stop_seen=seen_stop,
            snapshot=verify_snap.serializable(),
        )
        return verified

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract_primary(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        snap = self.runtime.snapshot()
        copy_button = self.find_last(snap, 'copy_button')
        if not copy_button:
            result.add_step(
                'extract_primary', False,
                'Perplexity copy button not found',
                snapshot=snap.serializable(),
            )
            return False
        if not self.runtime.click(copy_button):
            result.add_step(
                'extract_primary', False,
                'Perplexity copy button click failed',
                snapshot=snap.serializable(),
            )
            return False
        time.sleep(0.4)
        content = self.runtime.read_clipboard().strip()
        result.response_text = content
        verified = bool(content)
        result.add_step(
            'extract_primary', verified,
            'Perplexity summary copied to clipboard',
            characters=len(content),
            preview=content[:200],
        )
        return verified

    def extract_additional(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        snap = self.runtime.snapshot()
        copy_contents = self.find_first(snap, 'copy_contents_button')
        if copy_contents and self.runtime.click(copy_contents):
            time.sleep(0.4)
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
                    'Perplexity full contents copied',
                    characters=len(content),
                    preview=content[:200],
                )
                return True
        result.add_step(
            'extract_additional', True,
            'Perplexity copy_contents_button not found or yielded no content',
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
