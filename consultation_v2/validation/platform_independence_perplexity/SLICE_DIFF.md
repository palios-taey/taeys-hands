# Perplexity Package Slice Diff

Pinned source SHA: `0aac0047dd9d0d83772d9344f95eb731f1f2aa8c`.

Comparison scope: AST method bodies only. Each method body is extracted from the first executable/docstring body line through the method end line, then compared against the package-owned implementation.

Source files: `consultation_v2/drivers/base.py`, `consultation_v2/completion.py`, and `consultation_v2/drivers/perplexity.py` at the pinned SHA.

Target files: `consultation_v2/platforms/perplexity/driver.py` and `consultation_v2/platforms/perplexity/monitor.py` in this working tree.

## Shared lifecycle base

Source class: `consultation_v2/drivers/base.py`::BaseConsultationDriver. Target class: `consultation_v2/platforms/perplexity/driver.py`::_PerplexityInlineBase.

Method count: source `112`, target `112`.

### BaseConsultationDriver.__init__ -> _PerplexityInlineBase.__init__

Source body lines: `consultation_v2/drivers/base.py:74-76`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:75-77`.

NO BODY DIFF

### BaseConsultationDriver._activate_selection_path_element -> _PerplexityInlineBase._activate_selection_path_element

Source body lines: `consultation_v2/drivers/base.py:1397-1402`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1398-1403`.

NO BODY DIFF

### BaseConsultationDriver._apply_selection_step -> _PerplexityInlineBase._apply_selection_step

Source body lines: `consultation_v2/drivers/base.py:820-1063`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:821-1064`.

NO BODY DIFF

### BaseConsultationDriver._assert_monitor_answer_thread -> _PerplexityInlineBase._assert_monitor_answer_thread

Source body lines: `consultation_v2/drivers/base.py:2490-2524`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2491-2525`.

NO BODY DIFF

### BaseConsultationDriver._conformance_anchor_key -> _PerplexityInlineBase._conformance_anchor_key

Source body lines: `consultation_v2/drivers/base.py:318-333`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:319-334`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancies_still_present -> _PerplexityInlineBase._conformance_discrepancies_still_present

Source body lines: `consultation_v2/drivers/base.py:307-308`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:308-309`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancy_key -> _PerplexityInlineBase._conformance_discrepancy_key

Source body lines: `consultation_v2/drivers/base.py:312-315`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:313-316`.

NO BODY DIFF

### BaseConsultationDriver._conformance_findings -> _PerplexityInlineBase._conformance_findings

Source body lines: `consultation_v2/drivers/base.py:203-213`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:204-214`.

NO BODY DIFF

### BaseConsultationDriver._conformance_menu_surface_closed -> _PerplexityInlineBase._conformance_menu_surface_closed

Source body lines: `consultation_v2/drivers/base.py:358-362`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:359-363`.

NO BODY DIFF

### BaseConsultationDriver._conformance_snapshot -> _PerplexityInlineBase._conformance_snapshot

Source body lines: `consultation_v2/drivers/base.py:238-250`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:239-251`.

NO BODY DIFF

### BaseConsultationDriver._conformance_surface_is_menu_only -> _PerplexityInlineBase._conformance_surface_is_menu_only

Source body lines: `consultation_v2/drivers/base.py:369-374`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:370-375`.

NO BODY DIFF

### BaseConsultationDriver._conformance_unknown_discrepancies -> _PerplexityInlineBase._conformance_unknown_discrepancies

Source body lines: `consultation_v2/drivers/base.py:220-227`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:221-228`.

NO BODY DIFF

### BaseConsultationDriver._display -> _PerplexityInlineBase._display

Source body lines: `consultation_v2/drivers/base.py:1741-1741`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1742-1742`.

NO BODY DIFF

### BaseConsultationDriver._display_dispatch_lock -> _PerplexityInlineBase._display_dispatch_lock

Source body lines: `consultation_v2/drivers/base.py:1745-1774`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1746-1775`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver._display_dispatch_lock
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase._display_dispatch_lock
@@ -1,13 +1,13 @@
         """Hold the DISPLAY-scoped dispatch lock for the duration of the
-        ``with`` block (the setup+send+register region, FLOW §10).
+        ``with`` block (the setup+send+register region, FLOW Section 10).

         Yields ``True`` if the lock was acquired (this dispatch owns the display
         and may drive the browser), ``False`` if another consultation already
-        holds it (the caller must NOT proceed — a busy display is a loud failure,
+        holds it (the caller must NOT proceed - a busy display is a loud failure,
         not a silent shared-browser race).

         RELEASE-SAFE: the release runs in a ``finally`` so a failed/halted/raising
-        setup or send still frees the display — no deadlock can leave a DISPLAY
+        setup or send still frees the display - no deadlock can leave a DISPLAY
         permanently locked. The lock is released ONLY if THIS context acquired it,
         so a False (already-held-by-another) exit never deletes the other
         dispatch's lock.
```

### BaseConsultationDriver._echo_tokens -> _PerplexityInlineBase._echo_tokens

Source body lines: `consultation_v2/drivers/base.py:2352-2352`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2353-2353`.

NO BODY DIFF

### BaseConsultationDriver._element_scope -> _PerplexityInlineBase._element_scope

Source body lines: `consultation_v2/drivers/base.py:1645-1649`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1646-1650`.

NO BODY DIFF

### BaseConsultationDriver._expected_keys_for_surface -> _PerplexityInlineBase._expected_keys_for_surface

Source body lines: `consultation_v2/drivers/base.py:342-350`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:343-351`.

NO BODY DIFF

### BaseConsultationDriver._fail_duplicate_send_risk -> _PerplexityInlineBase._fail_duplicate_send_risk

Source body lines: `consultation_v2/drivers/base.py:2019-2035`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2020-2036`.

NO BODY DIFF

### BaseConsultationDriver._gate_selection_plan -> _PerplexityInlineBase._gate_selection_plan

Source body lines: `consultation_v2/drivers/base.py:1652-1665`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1653-1666`.

NO BODY DIFF

### BaseConsultationDriver._handle_monitor_intermediate_state -> _PerplexityInlineBase._handle_monitor_intermediate_state

Source body lines: `consultation_v2/drivers/base.py:2294-2344`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2295-2345`.

NO BODY DIFF

### BaseConsultationDriver._invalidate_unresumable_landed_send -> _PerplexityInlineBase._invalidate_unresumable_landed_send

Source body lines: `consultation_v2/drivers/base.py:2075-2097`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2076-2098`.

NO BODY DIFF

### BaseConsultationDriver._is_incidental_base_unknown -> _PerplexityInlineBase._is_incidental_base_unknown

Source body lines: `consultation_v2/drivers/base.py:231-235`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:232-236`.

NO BODY DIFF

### BaseConsultationDriver._is_landed_send -> _PerplexityInlineBase._is_landed_send

Source body lines: `consultation_v2/drivers/base.py:2042-2054`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2043-2055`.

NO BODY DIFF

### BaseConsultationDriver._is_menu_scoped_element -> _PerplexityInlineBase._is_menu_scoped_element

Source body lines: `consultation_v2/drivers/base.py:378-385`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:379-386`.

NO BODY DIFF

### BaseConsultationDriver._is_prompt_echo -> _PerplexityInlineBase._is_prompt_echo

Source body lines: `consultation_v2/drivers/base.py:2432-2432`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2433-2433`.

NO BODY DIFF

### BaseConsultationDriver._is_setup_complete_send_quarantine -> _PerplexityInlineBase._is_setup_complete_send_quarantine

Source body lines: `consultation_v2/drivers/base.py:1965-1969`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1966-1970`.

NO BODY DIFF

### BaseConsultationDriver._is_unresumable_landed_send -> _PerplexityInlineBase._is_unresumable_landed_send

Source body lines: `consultation_v2/drivers/base.py:2061-2067`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2062-2068`.

NO BODY DIFF

### BaseConsultationDriver._landed_run_state_statuses -> _PerplexityInlineBase._landed_run_state_statuses

Source body lines: `consultation_v2/drivers/base.py:1954-1958`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1955-1959`.

NO BODY DIFF

### BaseConsultationDriver._live_resumable_send_url -> _PerplexityInlineBase._live_resumable_send_url

Source body lines: `consultation_v2/drivers/base.py:1972-1975`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1973-1976`.

NO BODY DIFF

### BaseConsultationDriver._missing_expected_elements -> _PerplexityInlineBase._missing_expected_elements

Source body lines: `consultation_v2/drivers/base.py:394-411`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:395-412`.

NO BODY DIFF

### BaseConsultationDriver._monitor_id -> _PerplexityInlineBase._monitor_id

Source body lines: `consultation_v2/drivers/base.py:1802-1805`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1803-1806`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_max_actions -> _PerplexityInlineBase._monitor_intermediate_max_actions

Source body lines: `consultation_v2/drivers/base.py:2271-2278`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2272-2279`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_states -> _PerplexityInlineBase._monitor_intermediate_states

Source body lines: `consultation_v2/drivers/base.py:2240-2251`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2241-2252`.

NO BODY DIFF

### BaseConsultationDriver._monitor_state_keys -> _PerplexityInlineBase._monitor_state_keys

Source body lines: `consultation_v2/drivers/base.py:2254-2268`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2255-2269`.

NO BODY DIFF

### BaseConsultationDriver._normalized_text -> _PerplexityInlineBase._normalized_text

Source body lines: `consultation_v2/drivers/base.py:2348-2348`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2349-2349`.

NO BODY DIFF

### BaseConsultationDriver._open_selection_menu -> _PerplexityInlineBase._open_selection_menu

Source body lines: `consultation_v2/drivers/base.py:1072-1130`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1073-1131`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_group_labels -> _PerplexityInlineBase._page_ready_group_labels

Source body lines: `consultation_v2/drivers/base.py:590-593`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:591-594`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_key_groups -> _PerplexityInlineBase._page_ready_key_groups

Source body lines: `consultation_v2/drivers/base.py:489-524`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:490-525`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_missing_groups -> _PerplexityInlineBase._page_ready_missing_groups

Source body lines: `consultation_v2/drivers/base.py:600-604`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:601-605`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_optional_keys -> _PerplexityInlineBase._page_ready_optional_keys

Source body lines: `consultation_v2/drivers/base.py:580-580`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:581-581`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_present_optional_keys -> _PerplexityInlineBase._page_ready_present_optional_keys

Source body lines: `consultation_v2/drivers/base.py:583-586`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:584-587`.

NO BODY DIFF

### BaseConsultationDriver._popup_recovery_settle_seconds -> _PerplexityInlineBase._popup_recovery_settle_seconds

Source body lines: `consultation_v2/drivers/base.py:293-299`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:294-300`.

NO BODY DIFF

### BaseConsultationDriver._post_popup_recovery_findings -> _PerplexityInlineBase._post_popup_recovery_findings

Source body lines: `consultation_v2/drivers/base.py:257-290`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:258-291`.

NO BODY DIFF

### BaseConsultationDriver._prompt_echo_evidence -> _PerplexityInlineBase._prompt_echo_evidence

Source body lines: `consultation_v2/drivers/base.py:2359-2429`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2360-2430`.

NO BODY DIFF

### BaseConsultationDriver._register_monitor -> _PerplexityInlineBase._register_monitor

Source body lines: `consultation_v2/drivers/base.py:2135-2163`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2136-2164`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver._register_monitor
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase._register_monitor
@@ -1,7 +1,7 @@
         """Register (idempotently) the in-flight monitor session for this
-        consultation. Registration failure is a loud step (FLOW §8: a dispatch
+        consultation. Registration failure is a loud step (FLOW Section 8: a dispatch
         that cannot be registered must not be silently treated as monitored),
-        but it does not undo a landed send — the run continues so the response
+        but it does not undo a landed send - the run continues so the response
         is still observed/extracted in-process."""
         session = {
             'platform': self.platform,
```

### BaseConsultationDriver._reset_detector_after_intermediate -> _PerplexityInlineBase._reset_detector_after_intermediate

Source body lines: `consultation_v2/drivers/base.py:2282-2284`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2283-2285`.

NO BODY DIFF

### BaseConsultationDriver._resume_landed_send -> _PerplexityInlineBase._resume_landed_send

Source body lines: `consultation_v2/drivers/base.py:2105-2126`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2106-2127`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver._resume_landed_send
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase._resume_landed_send
@@ -5,15 +5,15 @@
         monitor_id = str(prior.get('monitor_id') or self._monitor_id(request))
         # Navigate the existing tab to the captured chat URL so monitor/extract
         # operate on the real in-flight/completed turn. This is navigation, not a
-        # send — it produces no new irreversible turn.
+        # send - it produces no new irreversible turn.
         navigated = self.runtime.navigate(captured_url) if captured_url else False
         result.session_url_after = captured_url
         self._register_monitor(request, result, monitor_id, captured_url)
         result.add_step(
             'send', True,
-            f'{self.platform} send RESUMED from durable run-state — prior send '
+            f'{self.platform} send RESUMED from durable run-state - prior send '
             f'already landed at {captured_url!r}; NOT re-sending (duplicate-send '
-            f'guard, FLOW §8 / CONTRACT §10)',
+            f'guard, FLOW Section 8 / CONTRACT Section 10)',
             resumed=True,
             url_after=captured_url,
             prior_status=prior.get('status'),
```

### BaseConsultationDriver._resume_possibly_landed_send -> _PerplexityInlineBase._resume_possibly_landed_send

Source body lines: `consultation_v2/drivers/base.py:1984-2011`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1985-2012`.

NO BODY DIFF

### BaseConsultationDriver._scoped_snapshot -> _PerplexityInlineBase._scoped_snapshot

Source body lines: `consultation_v2/drivers/base.py:730-735`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:731-736`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_anchor_key -> _PerplexityInlineBase._selection_base_anchor_key

Source body lines: `consultation_v2/drivers/base.py:1239-1255`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1240-1256`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_snapshot_clean -> _PerplexityInlineBase._selection_base_snapshot_clean

Source body lines: `consultation_v2/drivers/base.py:1212-1225`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1213-1226`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_base_anchor -> _PerplexityInlineBase._selection_click_base_anchor

Source body lines: `consultation_v2/drivers/base.py:1182-1192`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1183-1193`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_readiness -> _PerplexityInlineBase._selection_click_readiness

Source body lines: `consultation_v2/drivers/base.py:1451-1468`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1452-1469`.

NO BODY DIFF

### BaseConsultationDriver._selection_close_active_selection_menu -> _PerplexityInlineBase._selection_close_active_selection_menu

Source body lines: `consultation_v2/drivers/base.py:1324-1332`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1325-1333`.

NO BODY DIFF

### BaseConsultationDriver._selection_conformance_gate -> _PerplexityInlineBase._selection_conformance_gate

Source body lines: `consultation_v2/drivers/base.py:1638-1642`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1639-1643`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_click_ready -> _PerplexityInlineBase._selection_element_click_ready

Source body lines: `consultation_v2/drivers/base.py:1438-1444`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1439-1445`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_has_state -> _PerplexityInlineBase._selection_element_has_state

Source body lines: `consultation_v2/drivers/base.py:1492-1493`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1493-1494`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_matches_active_recognition -> _PerplexityInlineBase._selection_element_matches_active_recognition

Source body lines: `consultation_v2/drivers/base.py:1500-1505`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1501-1506`.

NO BODY DIFF

### BaseConsultationDriver._selection_find_once -> _PerplexityInlineBase._selection_find_once

Source body lines: `consultation_v2/drivers/base.py:1405-1405`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1406-1406`.

NO BODY DIFF

### BaseConsultationDriver._selection_prepare_base_for_menu -> _PerplexityInlineBase._selection_prepare_base_for_menu

Source body lines: `consultation_v2/drivers/base.py:1133-1179`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1134-1180`.

NO BODY DIFF

### BaseConsultationDriver._selection_settle_seconds -> _PerplexityInlineBase._selection_settle_seconds

Source body lines: `consultation_v2/drivers/base.py:1481-1489`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1482-1490`.

NO BODY DIFF

### BaseConsultationDriver._selection_snapshot -> _PerplexityInlineBase._selection_snapshot

Source body lines: `consultation_v2/drivers/base.py:1471-1478`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1472-1479`.

NO BODY DIFF

### BaseConsultationDriver._selection_stable_snapshot -> _PerplexityInlineBase._selection_stable_snapshot

Source body lines: `consultation_v2/drivers/base.py:1605-1630`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1606-1631`.

NO BODY DIFF

### BaseConsultationDriver._selection_trigger_keys -> _PerplexityInlineBase._selection_trigger_keys

Source body lines: `consultation_v2/drivers/base.py:527-564`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:528-565`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_element -> _PerplexityInlineBase._selection_wait_for_active_element

Source body lines: `consultation_v2/drivers/base.py:1539-1560`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1540-1561`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_state -> _PerplexityInlineBase._selection_wait_for_active_state

Source body lines: `consultation_v2/drivers/base.py:1513-1531`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1514-1532`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_trigger -> _PerplexityInlineBase._selection_wait_for_active_trigger

Source body lines: `consultation_v2/drivers/base.py:1569-1596`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1570-1597`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_clean_base -> _PerplexityInlineBase._selection_wait_for_clean_base

Source body lines: `consultation_v2/drivers/base.py:1195-1209`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1196-1210`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_click_ready -> _PerplexityInlineBase._selection_wait_for_click_ready

Source body lines: `consultation_v2/drivers/base.py:1416-1431`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1417-1432`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_hover_revealed_anchor -> _PerplexityInlineBase._selection_wait_for_hover_revealed_anchor

Source body lines: `consultation_v2/drivers/base.py:1335-1348`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1336-1349`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_menu_closed -> _PerplexityInlineBase._selection_wait_for_menu_closed

Source body lines: `consultation_v2/drivers/base.py:1228-1236`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1229-1237`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_revealed_anchor -> _PerplexityInlineBase._selection_wait_for_revealed_anchor

Source body lines: `consultation_v2/drivers/base.py:1351-1394`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1352-1395`.

NO BODY DIFF

### BaseConsultationDriver._stop_key -> _PerplexityInlineBase._stop_key

Source body lines: `consultation_v2/drivers/base.py:2236-2237`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2237-2238`.

NO BODY DIFF

### BaseConsultationDriver._urls_equivalent -> _PerplexityInlineBase._urls_equivalent

Source body lines: `consultation_v2/drivers/base.py:2481-2481`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2482-2482`.

NO BODY DIFF

### BaseConsultationDriver._uses_identity_schema -> _PerplexityInlineBase._uses_identity_schema

Source body lines: `consultation_v2/drivers/base.py:336-339`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:337-340`.

NO BODY DIFF

### BaseConsultationDriver._walk_selection_path -> _PerplexityInlineBase._walk_selection_path

Source body lines: `consultation_v2/drivers/base.py:1265-1321`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1266-1322`.

NO BODY DIFF

### BaseConsultationDriver._workflow_prompt_keys -> _PerplexityInlineBase._workflow_prompt_keys

Source body lines: `consultation_v2/drivers/base.py:567-577`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:568-578`.

NO BODY DIFF

### BaseConsultationDriver.acquire_display_lock -> _PerplexityInlineBase.acquire_display_lock

Source body lines: `consultation_v2/drivers/base.py:1685-1689`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1686-1690`.

NO BODY DIFF

### BaseConsultationDriver.active_element_key -> _PerplexityInlineBase.active_element_key

Source body lines: `consultation_v2/drivers/base.py:103-106`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:104-107`.

NO BODY DIFF

### BaseConsultationDriver.apply_selection_plan -> _PerplexityInlineBase.apply_selection_plan

Source body lines: `consultation_v2/drivers/base.py:795-817`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:796-818`.

NO BODY DIFF

### BaseConsultationDriver.assert_session_not_dead -> _PerplexityInlineBase.assert_session_not_dead

Source body lines: `consultation_v2/drivers/base.py:1701-1701`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1702-1702`.

NO BODY DIFF

### BaseConsultationDriver.checkpoint_run_state -> _PerplexityInlineBase.checkpoint_run_state

Source body lines: `consultation_v2/drivers/base.py:1814-1853`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1815-1854`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.checkpoint_run_state
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase.checkpoint_run_state
@@ -1,22 +1,22 @@
         """Merge a milestone checkpoint into the durable run-state record for
-        this consultation (FLOW §8). ``status`` is the milestone reached;
+        this consultation (FLOW Section 8). ``status`` is the milestone reached;
         ``fields`` are the milestone-specific values (e.g. ``url=...``,
         ``monitor_id=...``) that are PERSISTED into the run-state record.

         ``result`` is an OUT-OF-BAND handle used only to record a failed-step
-        audit entry if the checkpoint cannot be written — it is a named
+        audit entry if the checkpoint cannot be written - it is a named
         parameter, NOT part of ``fields``, so it is never serialized into the
         record. (Root cause: previously the result was smuggled through
         ``fields['_result']`` and then spread via ``**fields`` into the
         json.dumps'd state, which raised "Object of type ConsultationResult is
-        not JSON serializable" on EVERY checkpoint — silently defeating the
+        not JSON serializable" on EVERY checkpoint - silently defeating the
         duplicate-send guard because no ``submitted`` record ever persisted.)

         Run-state is a durable idempotency CONVENIENCE, not the system of record
         (that is the Neo4j plan/message rows on success). If Redis is
         unreachable the checkpoint write raises out of the primitive; we do NOT
         let that abort a consultation whose irreversible work may already be in
-        flight — we surface it loudly via the step audit and continue. This is
+        flight - we surface it loudly via the step audit and continue. This is
         NOT a silent swallow: the failure is recorded as a visible failed step,
         and the send guard below treats an unreadable run-state as
         "cannot prove a prior send" (it still gates on the live URL/Stop tree)."""
```

### BaseConsultationDriver.clear_run_state -> _PerplexityInlineBase.clear_run_state

Source body lines: `consultation_v2/drivers/base.py:1704-1704`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1705-1705`.

NO BODY DIFF

### BaseConsultationDriver.deregister_monitor_session -> _PerplexityInlineBase.deregister_monitor_session

Source body lines: `consultation_v2/drivers/base.py:1710-1710`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1711-1711`.

NO BODY DIFF

### BaseConsultationDriver.element_active_state -> _PerplexityInlineBase.element_active_state

Source body lines: `consultation_v2/drivers/base.py:88-90`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:89-91`.

NO BODY DIFF

### BaseConsultationDriver.element_is_active -> _PerplexityInlineBase.element_is_active

Source body lines: `consultation_v2/drivers/base.py:93-100`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:94-101`.

NO BODY DIFF

### BaseConsultationDriver.find_first -> _PerplexityInlineBase.find_first

Source body lines: `consultation_v2/drivers/base.py:82-82`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:83-83`.

NO BODY DIFF

### BaseConsultationDriver.find_first_any -> _PerplexityInlineBase.find_first_any

Source body lines: `consultation_v2/drivers/base.py:112-116`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:113-117`.

NO BODY DIFF

### BaseConsultationDriver.find_last -> _PerplexityInlineBase.find_last

Source body lines: `consultation_v2/drivers/base.py:85-85`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:86-86`.

NO BODY DIFF

### BaseConsultationDriver.guarded_send -> _PerplexityInlineBase.guarded_send

Source body lines: `consultation_v2/drivers/base.py:1860-1948`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1861-1949`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.guarded_send
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase.guarded_send
@@ -1,4 +1,4 @@
-        """Idempotent send seam (FLOW §8). Replaces a driver's direct
+        """Idempotent send seam (FLOW Section 8). Replaces a driver's direct
         ``self.send_prompt(...)`` call in run().

         1. READ durable run-state for this consultation's stable request_id.
@@ -12,9 +12,9 @@
            monitor session so the run is observably in-flight.

         A send that the driver could not prove succeeded (``send_prompt``
-        returns False) is NOT checkpointed as submitted and NOT registered — per
-        FLOW §8 an unproven send must not be treated as monitored."""
-        # READ prior run-state FIRST — before writing any checkpoint — so a
+        returns False) is NOT checkpointed as submitted and NOT registered - per
+        FLOW Section 8 an unproven send must not be treated as monitored."""
+        # READ prior run-state FIRST - before writing any checkpoint - so a
         # landed-send record from an earlier run is detected, never clobbered.
         prior = None
         try:
@@ -55,7 +55,7 @@
             monitor_id=self._monitor_id(request),
         )

-        # No proven prior send → perform the real irreversible send.
+        # No proven prior send -> perform the real irreversible send.
         sent = self.send_prompt(request, result)
         if not sent:
             # Unproven send: do not checkpoint submitted, do not register a
```

### BaseConsultationDriver.is_resumable_session_url -> _PerplexityInlineBase.is_resumable_session_url

Source body lines: `consultation_v2/drivers/base.py:1951-1951`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1952-1952`.

NO BODY DIFF

### BaseConsultationDriver.monitor_and_extract -> _PerplexityInlineBase.monitor_and_extract

Source body lines: `consultation_v2/drivers/base.py:2852-2856`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2859-2863`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.monitor_and_extract
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase.monitor_and_extract
@@ -1,4 +1,4 @@
-        """UNLOCKED phase (FLOW §10): poll for completion, extract, store, set
+        """UNLOCKED phase (FLOW Section 10): poll for completion, extract, store, set
         result.ok. Runs AFTER the display lock is released so other consultations
         can set up/send on this display concurrently. Sets result.ok on success;
         leaves it False (with a recorded step) on any monitor/extract failure."""
```

### BaseConsultationDriver.monitor_generation -> _PerplexityInlineBase.monitor_generation

Source body lines: `consultation_v2/drivers/base.py:2615-2782`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2616-2783`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.monitor_generation
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase.monitor_generation
@@ -1,10 +1,10 @@
         """Poll until the response completes, using the SHARED stop-transition
-        detector (consultation_v2.completion.CompletionDetector) — the single
+        detector (consultation_v2.platforms.perplexity.monitor.PerplexityCompletionDetector) - the single
         source of truth that mirrors monitor/central.py::_detect_completion.

         Completion = the stop button was SEEN and is now GONE for the required
         number of cycles (2 for deep modes, 1 otherwise). No content-guess
-        fallback (100_TIMES §1); the stop button is the only completion oracle.
+        fallback (100_TIMES Section 1); the stop button is the only completion oracle.

         ``seed_stop_seen`` is accepted only as explicit upstream proof from a
         validated send. Without that proof, this monitor call must observe Stop
@@ -20,7 +20,7 @@
         detector_mode = (
             (mode if mode is not None else request.selection_value('mode', None)) or ''
         ).strip().lower()
-        detector = CompletionDetector(mode=detector_mode)
+        detector = PerplexityCompletionDetector(mode=detector_mode)
         stop_key = self._stop_key()
         completed = False
         observed_stop = bool(seed_stop_seen)
@@ -61,8 +61,8 @@
             # the false-completion root cause (compounded by BUG1's lost deep
             # debounce). A degraded read is therefore 'unknown', not 'gone': skip
             # the tick (debounce counter untouched) and keep polling. stop_present
-            # is unaffected — a visible stop means generating regardless of tree
-            # size — and the wall-clock effective_timeout still bounds a
+            # is unaffected - a visible stop means generating regardless of tree
+            # size - and the wall-clock effective_timeout still bounds a
             # genuinely-stuck run, so this adds no infinite wait.
             if int(snap.raw_count or 0) < MONITOR_MIN_HEALTHY_RAW_COUNT:
                 return False
@@ -129,8 +129,8 @@
         verified = bool(completed and self.validation_passes(verify_snap, 'response_complete'))
         # Classify a non-completion: if the Stop button is STILL present at the
         # final fresh scan, this is the contract's "genuinely stuck visible-stop"
-        # run bounded by the (now floored) timeout — a LOUD, mapped
-        # generation_stalled failure (FLOW §9 / stop_conditions.py), not a generic
+        # run bounded by the (now floored) timeout - a LOUD, mapped
+        # generation_stalled failure (FLOW Section 9 / stop_conditions.py), not a generic
         # completion miss. (Stop gone but debounce-cycles incomplete is the other,
         # non-stalled, miss.)
         stop_still_present = bool(verify_snap.has(stop_key))
@@ -144,7 +144,7 @@
         elif stop_condition == 'generation_stalled':
             monitor_message = (
                 f'{self.platform} generation_stalled: Stop still present after '
-                f'{effective_timeout:.0f}s (mode={detector_mode or "default"}) — loud bound, not completion'
+                f'{effective_timeout:.0f}s (mode={detector_mode or "default"}) - loud bound, not completion'
             )
         else:
             monitor_message = f'{self.platform} response did not reach Stop-gone completion'
@@ -157,7 +157,7 @@
         )
         if verified:
             # completion_observed milestone: the Stop button was seen then gone
-            # for the required cycles (FLOW §9). Checkpointed so a re-run after a
+            # for the required cycles (FLOW Section 9). Checkpointed so a re-run after a
             # crash between completion and extraction resumes at the captured URL
             # and re-extracts rather than re-sending.
             self.checkpoint_run_state(
```

### BaseConsultationDriver.read_run_state -> _PerplexityInlineBase.read_run_state

Source body lines: `consultation_v2/drivers/base.py:1698-1698`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1699-1699`.

NO BODY DIFF

### BaseConsultationDriver.reassert_captured_session_url -> _PerplexityInlineBase.reassert_captured_session_url

Source body lines: `consultation_v2/drivers/base.py:2533-2606`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2534-2607`.

NO BODY DIFF

### BaseConsultationDriver.register_monitor_session -> _PerplexityInlineBase.register_monitor_session

Source body lines: `consultation_v2/drivers/base.py:1707-1707`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1708-1708`.

NO BODY DIFF

### BaseConsultationDriver.reject_prompt_echo_response -> _PerplexityInlineBase.reject_prompt_echo_response

Source body lines: `consultation_v2/drivers/base.py:2444-2455`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2445-2456`.

NO BODY DIFF

### BaseConsultationDriver.release_display_lock -> _PerplexityInlineBase.release_display_lock

Source body lines: `consultation_v2/drivers/base.py:1692-1692`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1693-1693`.

NO BODY DIFF

### BaseConsultationDriver.result -> _PerplexityInlineBase.result

Source body lines: `consultation_v2/drivers/base.py:79-79`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:80-80`.

NO BODY DIFF

### BaseConsultationDriver.run -> _PerplexityInlineBase.run

Source body lines: `consultation_v2/drivers/base.py:2790-2835`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2791-2844`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.run
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase.run
@@ -1,15 +1,15 @@
         """Two-phase consultation lifecycle with per-display serialization.

-        Phase A (LOCKED, sequential per display): ``setup_and_send`` — switch,
+        Phase A (LOCKED, sequential per display): ``setup_and_send`` - switch,
         navigate, select model/mode/tools/connectors, attach, enter prompt, and
         the guarded (idempotent) send + monitor registration. Held under the
         DISPLAY-scoped dispatch lock so two consultations never drive the same
         Firefox/AT-SPI bus at once.

-        Phase B (UNLOCKED, concurrent): ``monitor_and_extract`` — poll for the
+        Phase B (UNLOCKED, concurrent): ``monitor_and_extract`` - poll for the
         Stop-gone completion, extract, store. Runs with the display lock ALREADY
         RELEASED so the next consultation can set up/send on this display while
-        this one's response is monitored concurrently (FLOW §10 invariant).
+        this one's response is monitored concurrently (FLOW Section 10 invariant).

         The lock is released at the EXACT moment setup_and_send returns (the
         send-registered handoff) AND on any setup/send failure or exception
@@ -22,13 +22,13 @@
             with self._display_dispatch_lock(request) as owns_display:
                 if not owns_display:
                     # Another consultation holds this display's dispatch lock. Per
-                    # FLOW §10 setup/send is sequential per display — do NOT race the
+                    # FLOW Section 10 setup/send is sequential per display - do NOT race the
                     # shared browser. Loud failure, not a silent skip or a wait-loop.
                     result.add_step(
                         'dispatch_lock', False,
                         f'{self.platform} display {self._display()} dispatch lock is '
-                        f'already held by another consultation — setup/send is '
-                        f'sequential per display (FLOW §10); not racing the shared '
+                        f'already held by another consultation - setup/send is '
+                        f'sequential per display (FLOW Section 10); not racing the shared '
                         f'browser/AT-SPI bus',
                         display=self._display(),
                     )
@@ -43,4 +43,12 @@
             # handed off). The display lock is now RELEASED (with-block exited), so a
             # concurrent consultation may set up/send on this display while we monitor.
             self.monitor_and_extract(request, result)
+            if result.ok and result.response_text and self.reject_prompt_echo_response(
+                request,
+                result,
+                result.response_text,
+                step='extract_primary',
+                source='perplexity_package_run_delivery_gate',
+            ):
+                result.ok = False
             return result
```

### BaseConsultationDriver.serialize_artifacts -> _PerplexityInlineBase.serialize_artifacts

Source body lines: `consultation_v2/drivers/base.py:1668-1668`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1669-1669`.

NO BODY DIFF

### BaseConsultationDriver.set_response_text_if_not_prompt_echo -> _PerplexityInlineBase.set_response_text_if_not_prompt_echo

Source body lines: `consultation_v2/drivers/base.py:2467-2477`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2468-2478`.

NO BODY DIFF

### BaseConsultationDriver.setup_and_send -> _PerplexityInlineBase.setup_and_send

Source body lines: `consultation_v2/drivers/base.py:2841-2846`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2849-2854`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.setup_and_send
+++ consultation_v2/platforms/perplexity/driver.py:_PerplexityInlineBase.setup_and_send
@@ -1,6 +1,6 @@
-        """LOCKED phase (FLOW §10): switch/navigate/select/attach/prompt then the
+        """LOCKED phase (FLOW Section 10): switch/navigate/select/attach/prompt then the
         guarded send + monitor registration. Return True iff the send is proven
         and the monitor session is registered (the handoff point); False on any
         setup/send failure (the step audit records why). Runs while THIS driver
-        holds the DISPLAY-scoped dispatch lock — must not block on monitoring."""
+        holds the DISPLAY-scoped dispatch lock - must not block on monitoring."""
         raise NotImplementedError
```

### BaseConsultationDriver.snapshot_has_any -> _PerplexityInlineBase.snapshot_has_any

Source body lines: `consultation_v2/drivers/base.py:109-109`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:110-110`.

NO BODY DIFF

### BaseConsultationDriver.store_consultation -> _PerplexityInlineBase.store_consultation

Source body lines: `consultation_v2/drivers/base.py:2172-2186`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2173-2187`.

NO BODY DIFF

### BaseConsultationDriver.store_response_for_delivery -> _PerplexityInlineBase.store_response_for_delivery

Source body lines: `consultation_v2/drivers/base.py:2196-2229`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2197-2230`.

NO BODY DIFF

### BaseConsultationDriver.tree_conformance_gate -> _PerplexityInlineBase.tree_conformance_gate

Source body lines: `consultation_v2/drivers/base.py:124-196`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:125-197`.

NO BODY DIFF

### BaseConsultationDriver.validation_passes -> _PerplexityInlineBase.validation_passes

Source body lines: `consultation_v2/drivers/base.py:607-727`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:608-728`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_key -> _PerplexityInlineBase.wait_for_key

Source body lines: `consultation_v2/drivers/base.py:775-792`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:776-793`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_page_ready_after_navigation -> _PerplexityInlineBase.wait_for_page_ready_after_navigation

Source body lines: `consultation_v2/drivers/base.py:419-486`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:420-487`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_validation -> _PerplexityInlineBase.wait_for_validation

Source body lines: `consultation_v2/drivers/base.py:746-764`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:747-765`.

NO BODY DIFF

### BaseConsultationDriver.write_run_state -> _PerplexityInlineBase.write_run_state

Source body lines: `consultation_v2/drivers/base.py:1695-1695`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:1696-1696`.

NO BODY DIFF

## Completion monitor

Source class: `consultation_v2/completion.py`::CompletionDetector. Target class: `consultation_v2/platforms/perplexity/monitor.py`::PerplexityCompletionDetector.

Method count: source `2`, target `2`.

### CompletionDetector.__post_init__ -> PerplexityCompletionDetector.__post_init__

Source body lines: `consultation_v2/completion.py:63-64`.

Target body lines: `consultation_v2/platforms/perplexity/monitor.py:63-64`.

NO BODY DIFF

### CompletionDetector.observe -> PerplexityCompletionDetector.observe

Source body lines: `consultation_v2/completion.py:67-99`.

Target body lines: `consultation_v2/platforms/perplexity/monitor.py:67-99`.

```diff
--- consultation_v2/completion.py:CompletionDetector.observe
+++ consultation_v2/platforms/perplexity/monitor.py:PerplexityCompletionDetector.observe
@@ -18,12 +18,12 @@
         # Completion = the stop button was SEEN (ever_seen_stop) and is now GONE,
         # DEBOUNCED across ``required_stop_cycles`` consecutive absent scans
         # (deep modes use 2, others 1). This is the present->gone transition of
-        # 100_TIMES §1 ("stop-absent -> wait -> re-scan fresh tree -> complete
+        # 100_TIMES Section 1 ("stop-absent -> wait -> re-scan fresh tree -> complete
         # only if STILL absent"), generalised to N consecutive absent scans for
         # conservative AT-SPI refresh debounce on long-running modes.
         if not self.ever_seen_stop:
-            # Never seen the stop button yet — cannot complete. NO content
-            # fallback (100_TIMES §1: stop never appeared -> STOP and RAISE).
+            # Never seen the stop button yet - cannot complete. NO content
+            # fallback (100_TIMES Section 1: stop never appeared -> STOP and RAISE).
             return PENDING

         self.stop_was_visible = False
```

## Perplexity driver methods

Source class: `consultation_v2/drivers/perplexity.py`::PerplexityConsultationDriver. Target class: `consultation_v2/platforms/perplexity/driver.py`::PerplexityConsultationDriver.

Method count: source `23`, target `23`.

### PerplexityConsultationDriver._accept_extracted_content -> PerplexityConsultationDriver._accept_extracted_content

Source body lines: `consultation_v2/drivers/perplexity.py:817-836`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3676-3695`.

NO BODY DIFF

### PerplexityConsultationDriver._ensure_answer_thread -> PerplexityConsultationDriver._ensure_answer_thread

Source body lines: `consultation_v2/drivers/perplexity.py:765-786`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3624-3645`.

NO BODY DIFF

### PerplexityConsultationDriver._find_submit_button_for_send -> PerplexityConsultationDriver._find_submit_button_for_send

Source body lines: `consultation_v2/drivers/perplexity.py:670-684`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3529-3543`.

```diff
--- consultation_v2/drivers/perplexity.py:PerplexityConsultationDriver._find_submit_button_for_send
+++ consultation_v2/platforms/perplexity/driver.py:PerplexityConsultationDriver._find_submit_button_for_send
@@ -7,7 +7,7 @@
             # 2026-06-22: ~80KB consolidated attach, submit disabled mid-upload,
             # send false-failed + needed manual recovery). Per CONSULTATION_CONTRACT
             # a disabled control is a DISTINCT state, not a match, so the send
-            # wait-loop keeps polling until the upload finishes and submit enables —
+            # wait-loop keeps polling until the upload finishes and submit enables -
             # i.e. the send gates on attach-upload-complete by construction.
             if 'enabled' in set(send_button.states or []):
                 return snap, send_button, 'document'
```

### PerplexityConsultationDriver._is_answer_thread_url -> PerplexityConsultationDriver._is_answer_thread_url

Source body lines: `consultation_v2/drivers/perplexity.py:687-687`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3546-3546`.

NO BODY DIFF

### PerplexityConsultationDriver._is_deep_research -> PerplexityConsultationDriver._is_deep_research

Source body lines: `consultation_v2/drivers/perplexity.py:800-807`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3659-3666`.

NO BODY DIFF

### PerplexityConsultationDriver._mode_settle_timeout -> PerplexityConsultationDriver._mode_settle_timeout

Source body lines: `consultation_v2/drivers/perplexity.py:132-138`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2991-2997`.

NO BODY DIFF

### PerplexityConsultationDriver._read_clipboard_until_nonempty -> PerplexityConsultationDriver._read_clipboard_until_nonempty

Source body lines: `consultation_v2/drivers/perplexity.py:16-33`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2875-2892`.

NO BODY DIFF

### PerplexityConsultationDriver._send_success_timeout -> PerplexityConsultationDriver._send_success_timeout

Source body lines: `consultation_v2/drivers/perplexity.py:701-705`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3560-3564`.

NO BODY DIFF

### PerplexityConsultationDriver._submit_fire_timeout -> PerplexityConsultationDriver._submit_fire_timeout

Source body lines: `consultation_v2/drivers/perplexity.py:708-721`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3567-3580`.

NO BODY DIFF

### PerplexityConsultationDriver._verify_submit_fired -> PerplexityConsultationDriver._verify_submit_fired

Source body lines: `consultation_v2/drivers/perplexity.py:724-762`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3583-3621`.

NO BODY DIFF

### PerplexityConsultationDriver._wait_for_answer_thread_url -> PerplexityConsultationDriver._wait_for_answer_thread_url

Source body lines: `consultation_v2/drivers/perplexity.py:693-698`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3552-3557`.

NO BODY DIFF

### PerplexityConsultationDriver._wait_for_prompt_ready -> PerplexityConsultationDriver._wait_for_prompt_ready

Source body lines: `consultation_v2/drivers/perplexity.py:112-129`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2971-2988`.

NO BODY DIFF

### PerplexityConsultationDriver._wait_for_submit_button_for_send -> PerplexityConsultationDriver._wait_for_submit_button_for_send

Source body lines: `consultation_v2/drivers/perplexity.py:648-667`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3507-3526`.

NO BODY DIFF

### PerplexityConsultationDriver.attach_files -> PerplexityConsultationDriver.attach_files

Source body lines: `consultation_v2/drivers/perplexity.py:356-460`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3215-3319`.

```diff
--- consultation_v2/drivers/perplexity.py:PerplexityConsultationDriver.attach_files
+++ consultation_v2/platforms/perplexity/driver.py:PerplexityConsultationDriver.attach_files
@@ -17,10 +17,10 @@
                     snapshot=snap.serializable(),
                 )
                 return False
-            # Settle + rescan (DRIVER_CONTRACT §E): the attach dropdown's
+            # Settle + rescan (DRIVER_CONTRACT Section E): the attach dropdown's
             # "Upload files or images" item renders a beat after the trigger
             # click. A fixed time.sleep(0.7) + one-shot read flaked ("upload
-            # item not found") when the menu was slow to render — the item was
+            # item not found") when the menu was slow to render - the item was
             # present moments later. Poll for it (observation only, no re-click)
             # before declaring it missing, same readiness pattern as mode-select.
             menu_snap, upload_item = self.wait_for_key(
```

### PerplexityConsultationDriver.enter_prompt -> PerplexityConsultationDriver.enter_prompt

Source body lines: `consultation_v2/drivers/perplexity.py:471-543`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3330-3402`.

NO BODY DIFF

### PerplexityConsultationDriver.extract_additional -> PerplexityConsultationDriver.extract_additional

Source body lines: `consultation_v2/drivers/perplexity.py:975-1027`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3834-3886`.

NO BODY DIFF

### PerplexityConsultationDriver.extract_primary -> PerplexityConsultationDriver.extract_primary

Source body lines: `consultation_v2/drivers/perplexity.py:844-968`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3703-3827`.

```diff
--- consultation_v2/drivers/perplexity.py:PerplexityConsultationDriver.extract_primary
+++ consultation_v2/platforms/perplexity/driver.py:PerplexityConsultationDriver.extract_primary
@@ -12,12 +12,12 @@
         snap = self.runtime.snapshot()

         # Deep Research renders in one of several mapped output shapes; extract via
-        # the control actually PRESENT (observe-then-dispatch, mapped states — NOT a
+        # the control actually PRESENT (observe-then-dispatch, mapped states - NOT a
         # fallback-on-action-miss chain). The previous code hardcoded
         # copy_contents_button for ALL deep_research and FALSE-FAILED when DR rendered
         # the inline-answer shape (p8 2026-06-21: copy_button held the full 13998-char
         # answer). Selection by presence:
-        #   - report-card present -> copy_contents_button (full report; preferred — the
+        #   - report-card present -> copy_contents_button (full report; preferred - the
         #     bottom copy_button is also present on a report-card but yields only the
         #     intro stub there, so report-card MUST win when both are present)
         #   - inline answer (no report-card) -> copy_button (the inline answer is the
```

### PerplexityConsultationDriver.is_resumable_session_url -> PerplexityConsultationDriver.is_resumable_session_url

Source body lines: `consultation_v2/drivers/perplexity.py:690-690`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3549-3549`.

NO BODY DIFF

### PerplexityConsultationDriver.monitor_and_extract -> PerplexityConsultationDriver.monitor_and_extract

Source body lines: `consultation_v2/drivers/perplexity.py:91-109`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2950-2968`.

```diff
--- consultation_v2/drivers/perplexity.py:PerplexityConsultationDriver.monitor_and_extract
+++ consultation_v2/platforms/perplexity/driver.py:PerplexityConsultationDriver.monitor_and_extract
@@ -1,4 +1,4 @@
-        """UNLOCKED phase (FLOW §10): monitor → extract → store. Display lock is
+        """UNLOCKED phase (FLOW Section 10): monitor -> extract -> store. Display lock is
         already released so a concurrent consultation can set up/send here."""
         if not self._ensure_answer_thread(result):
             return
```

### PerplexityConsultationDriver.send_prompt -> PerplexityConsultationDriver.send_prompt

Source body lines: `consultation_v2/drivers/perplexity.py:554-645`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3413-3504`.

NO BODY DIFF

### PerplexityConsultationDriver.setup_and_send -> PerplexityConsultationDriver.setup_and_send

Source body lines: `consultation_v2/drivers/perplexity.py:46-86`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:2905-2945`.

```diff
--- consultation_v2/drivers/perplexity.py:PerplexityConsultationDriver.setup_and_send
+++ consultation_v2/platforms/perplexity/driver.py:PerplexityConsultationDriver.setup_and_send
@@ -1,5 +1,5 @@
-        """LOCKED phase (FLOW §10): navigate → mode → connectors → attach →
-        prompt → guarded send + monitor registration."""
+        """LOCKED phase (FLOW Section 10): navigate -> mode -> connectors -> attach ->
+        prompt -> guarded send + monitor registration."""
         urls = self.cfg.get('urls', {})
         target_url = request.session_url or urls.get('fresh')
         if not self.runtime.switch():
@@ -33,7 +33,7 @@
             return False
         if not self.enter_prompt(request, result):
             return False
-        # Idempotent send seam (FLOW §8): guarded_send reads durable run-state
+        # Idempotent send seam (FLOW Section 8): guarded_send reads durable run-state
         # first and RESUMES a landed send instead of re-sending; otherwise it
         # performs the real send via self.send_prompt and checkpoints submitted.
         if not self.guarded_send(request, result):
```

### PerplexityConsultationDriver.store_in_neo4j -> PerplexityConsultationDriver.store_in_neo4j

Source body lines: `consultation_v2/drivers/perplexity.py:1038-1049`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3897-3908`.

NO BODY DIFF

### PerplexityConsultationDriver.toggle_connectors -> PerplexityConsultationDriver.toggle_connectors

Source body lines: `consultation_v2/drivers/perplexity.py:149-345`.

Target body lines: `consultation_v2/platforms/perplexity/driver.py:3008-3204`.

```diff
--- consultation_v2/drivers/perplexity.py:PerplexityConsultationDriver.toggle_connectors
+++ consultation_v2/platforms/perplexity/driver.py:PerplexityConsultationDriver.toggle_connectors
@@ -91,7 +91,7 @@
             if already_checked:
                 result.add_step(
                     'toggle_connectors', True,
-                    f'Connector {connector_name!r} already enabled — skipping',
+                    f'Connector {connector_name!r} already enabled - skipping',
                 )
             else:
                 if not self.runtime.click(item):
```
