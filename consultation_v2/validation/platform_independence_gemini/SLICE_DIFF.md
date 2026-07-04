# Gemini Package Slice Diff

Pinned source SHA: `ddc55dc89538bffddd9622ae03103cbcc48a133a`.

Comparison scope: AST method bodies for every inlined method, plus Gemini Deep Think constants because those are moved behavioral data for the interim-ACK guard.

Source files: `consultation_v2/drivers/base.py`, `consultation_v2/completion.py`, and `consultation_v2/drivers/gemini.py` at the pinned SHA.

Target files: `consultation_v2/platforms/gemini/driver.py` and `consultation_v2/platforms/gemini/monitor.py` in this working tree.

## Gemini Deep Think Constants

Source lines: `consultation_v2/drivers/gemini.py:13-32`.

Target lines: `consultation_v2/platforms/gemini/driver.py:2867-2886`.

NO BODY DIFF

## Shared lifecycle base

Source class: `consultation_v2/drivers/base.py`::BaseConsultationDriver. Target class: `consultation_v2/platforms/gemini/driver.py`::_GeminiInlineBase.

Method count: source `112`, target `112`.

### BaseConsultationDriver.__init__ -> _GeminiInlineBase.__init__

Source body lines: `consultation_v2/drivers/base.py:74-76`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:75-77`.

NO BODY DIFF

### BaseConsultationDriver._activate_selection_path_element -> _GeminiInlineBase._activate_selection_path_element

Source body lines: `consultation_v2/drivers/base.py:1397-1402`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1398-1403`.

NO BODY DIFF

### BaseConsultationDriver._apply_selection_step -> _GeminiInlineBase._apply_selection_step

Source body lines: `consultation_v2/drivers/base.py:820-1063`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:821-1064`.

NO BODY DIFF

### BaseConsultationDriver._assert_monitor_answer_thread -> _GeminiInlineBase._assert_monitor_answer_thread

Source body lines: `consultation_v2/drivers/base.py:2490-2524`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2491-2525`.

NO BODY DIFF

### BaseConsultationDriver._conformance_anchor_key -> _GeminiInlineBase._conformance_anchor_key

Source body lines: `consultation_v2/drivers/base.py:318-333`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:319-334`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancies_still_present -> _GeminiInlineBase._conformance_discrepancies_still_present

Source body lines: `consultation_v2/drivers/base.py:307-308`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:308-309`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancy_key -> _GeminiInlineBase._conformance_discrepancy_key

Source body lines: `consultation_v2/drivers/base.py:312-315`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:313-316`.

NO BODY DIFF

### BaseConsultationDriver._conformance_findings -> _GeminiInlineBase._conformance_findings

Source body lines: `consultation_v2/drivers/base.py:203-213`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:204-214`.

NO BODY DIFF

### BaseConsultationDriver._conformance_menu_surface_closed -> _GeminiInlineBase._conformance_menu_surface_closed

Source body lines: `consultation_v2/drivers/base.py:358-362`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:359-363`.

NO BODY DIFF

### BaseConsultationDriver._conformance_snapshot -> _GeminiInlineBase._conformance_snapshot

Source body lines: `consultation_v2/drivers/base.py:238-250`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:239-251`.

NO BODY DIFF

### BaseConsultationDriver._conformance_surface_is_menu_only -> _GeminiInlineBase._conformance_surface_is_menu_only

Source body lines: `consultation_v2/drivers/base.py:369-374`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:370-375`.

NO BODY DIFF

### BaseConsultationDriver._conformance_unknown_discrepancies -> _GeminiInlineBase._conformance_unknown_discrepancies

Source body lines: `consultation_v2/drivers/base.py:220-227`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:221-228`.

NO BODY DIFF

### BaseConsultationDriver._display -> _GeminiInlineBase._display

Source body lines: `consultation_v2/drivers/base.py:1741-1741`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1742-1742`.

NO BODY DIFF

### BaseConsultationDriver._display_dispatch_lock -> _GeminiInlineBase._display_dispatch_lock

Source body lines: `consultation_v2/drivers/base.py:1745-1774`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1746-1775`.

NO BODY DIFF

### BaseConsultationDriver._echo_tokens -> _GeminiInlineBase._echo_tokens

Source body lines: `consultation_v2/drivers/base.py:2352-2352`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2353-2353`.

NO BODY DIFF

### BaseConsultationDriver._element_scope -> _GeminiInlineBase._element_scope

Source body lines: `consultation_v2/drivers/base.py:1645-1649`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1646-1650`.

NO BODY DIFF

### BaseConsultationDriver._expected_keys_for_surface -> _GeminiInlineBase._expected_keys_for_surface

Source body lines: `consultation_v2/drivers/base.py:342-350`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:343-351`.

NO BODY DIFF

### BaseConsultationDriver._fail_duplicate_send_risk -> _GeminiInlineBase._fail_duplicate_send_risk

Source body lines: `consultation_v2/drivers/base.py:2019-2035`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2020-2036`.

NO BODY DIFF

### BaseConsultationDriver._gate_selection_plan -> _GeminiInlineBase._gate_selection_plan

Source body lines: `consultation_v2/drivers/base.py:1652-1665`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1653-1666`.

NO BODY DIFF

### BaseConsultationDriver._handle_monitor_intermediate_state -> _GeminiInlineBase._handle_monitor_intermediate_state

Source body lines: `consultation_v2/drivers/base.py:2294-2344`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2295-2345`.

NO BODY DIFF

### BaseConsultationDriver._invalidate_unresumable_landed_send -> _GeminiInlineBase._invalidate_unresumable_landed_send

Source body lines: `consultation_v2/drivers/base.py:2075-2097`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2076-2098`.

NO BODY DIFF

### BaseConsultationDriver._is_incidental_base_unknown -> _GeminiInlineBase._is_incidental_base_unknown

Source body lines: `consultation_v2/drivers/base.py:231-235`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:232-236`.

NO BODY DIFF

### BaseConsultationDriver._is_landed_send -> _GeminiInlineBase._is_landed_send

Source body lines: `consultation_v2/drivers/base.py:2042-2054`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2043-2055`.

NO BODY DIFF

### BaseConsultationDriver._is_menu_scoped_element -> _GeminiInlineBase._is_menu_scoped_element

Source body lines: `consultation_v2/drivers/base.py:378-385`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:379-386`.

NO BODY DIFF

### BaseConsultationDriver._is_prompt_echo -> _GeminiInlineBase._is_prompt_echo

Source body lines: `consultation_v2/drivers/base.py:2432-2432`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2433-2433`.

NO BODY DIFF

### BaseConsultationDriver._is_setup_complete_send_quarantine -> _GeminiInlineBase._is_setup_complete_send_quarantine

Source body lines: `consultation_v2/drivers/base.py:1965-1969`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1966-1970`.

NO BODY DIFF

### BaseConsultationDriver._is_unresumable_landed_send -> _GeminiInlineBase._is_unresumable_landed_send

Source body lines: `consultation_v2/drivers/base.py:2061-2067`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2062-2068`.

NO BODY DIFF

### BaseConsultationDriver._landed_run_state_statuses -> _GeminiInlineBase._landed_run_state_statuses

Source body lines: `consultation_v2/drivers/base.py:1954-1958`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1955-1959`.

NO BODY DIFF

### BaseConsultationDriver._live_resumable_send_url -> _GeminiInlineBase._live_resumable_send_url

Source body lines: `consultation_v2/drivers/base.py:1972-1975`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1973-1976`.

NO BODY DIFF

### BaseConsultationDriver._missing_expected_elements -> _GeminiInlineBase._missing_expected_elements

Source body lines: `consultation_v2/drivers/base.py:394-411`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:395-412`.

NO BODY DIFF

### BaseConsultationDriver._monitor_id -> _GeminiInlineBase._monitor_id

Source body lines: `consultation_v2/drivers/base.py:1802-1805`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1803-1806`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_max_actions -> _GeminiInlineBase._monitor_intermediate_max_actions

Source body lines: `consultation_v2/drivers/base.py:2271-2278`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2272-2279`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_states -> _GeminiInlineBase._monitor_intermediate_states

Source body lines: `consultation_v2/drivers/base.py:2240-2251`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2241-2252`.

NO BODY DIFF

### BaseConsultationDriver._monitor_state_keys -> _GeminiInlineBase._monitor_state_keys

Source body lines: `consultation_v2/drivers/base.py:2254-2268`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2255-2269`.

NO BODY DIFF

### BaseConsultationDriver._normalized_text -> _GeminiInlineBase._normalized_text

Source body lines: `consultation_v2/drivers/base.py:2348-2348`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2349-2349`.

NO BODY DIFF

### BaseConsultationDriver._open_selection_menu -> _GeminiInlineBase._open_selection_menu

Source body lines: `consultation_v2/drivers/base.py:1072-1130`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1073-1131`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_group_labels -> _GeminiInlineBase._page_ready_group_labels

Source body lines: `consultation_v2/drivers/base.py:590-593`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:591-594`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_key_groups -> _GeminiInlineBase._page_ready_key_groups

Source body lines: `consultation_v2/drivers/base.py:489-524`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:490-525`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_missing_groups -> _GeminiInlineBase._page_ready_missing_groups

Source body lines: `consultation_v2/drivers/base.py:600-604`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:601-605`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_optional_keys -> _GeminiInlineBase._page_ready_optional_keys

Source body lines: `consultation_v2/drivers/base.py:580-580`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:581-581`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_present_optional_keys -> _GeminiInlineBase._page_ready_present_optional_keys

Source body lines: `consultation_v2/drivers/base.py:583-586`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:584-587`.

NO BODY DIFF

### BaseConsultationDriver._popup_recovery_settle_seconds -> _GeminiInlineBase._popup_recovery_settle_seconds

Source body lines: `consultation_v2/drivers/base.py:293-299`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:294-300`.

NO BODY DIFF

### BaseConsultationDriver._post_popup_recovery_findings -> _GeminiInlineBase._post_popup_recovery_findings

Source body lines: `consultation_v2/drivers/base.py:257-290`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:258-291`.

NO BODY DIFF

### BaseConsultationDriver._prompt_echo_evidence -> _GeminiInlineBase._prompt_echo_evidence

Source body lines: `consultation_v2/drivers/base.py:2359-2429`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2360-2430`.

NO BODY DIFF

### BaseConsultationDriver._register_monitor -> _GeminiInlineBase._register_monitor

Source body lines: `consultation_v2/drivers/base.py:2135-2163`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2136-2164`.

NO BODY DIFF

### BaseConsultationDriver._reset_detector_after_intermediate -> _GeminiInlineBase._reset_detector_after_intermediate

Source body lines: `consultation_v2/drivers/base.py:2282-2284`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2283-2285`.

NO BODY DIFF

### BaseConsultationDriver._resume_landed_send -> _GeminiInlineBase._resume_landed_send

Source body lines: `consultation_v2/drivers/base.py:2105-2126`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2106-2127`.

NO BODY DIFF

### BaseConsultationDriver._resume_possibly_landed_send -> _GeminiInlineBase._resume_possibly_landed_send

Source body lines: `consultation_v2/drivers/base.py:1984-2011`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1985-2012`.

NO BODY DIFF

### BaseConsultationDriver._scoped_snapshot -> _GeminiInlineBase._scoped_snapshot

Source body lines: `consultation_v2/drivers/base.py:730-735`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:731-736`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_anchor_key -> _GeminiInlineBase._selection_base_anchor_key

Source body lines: `consultation_v2/drivers/base.py:1239-1255`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1240-1256`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_snapshot_clean -> _GeminiInlineBase._selection_base_snapshot_clean

Source body lines: `consultation_v2/drivers/base.py:1212-1225`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1213-1226`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_base_anchor -> _GeminiInlineBase._selection_click_base_anchor

Source body lines: `consultation_v2/drivers/base.py:1182-1192`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1183-1193`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_readiness -> _GeminiInlineBase._selection_click_readiness

Source body lines: `consultation_v2/drivers/base.py:1451-1468`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1452-1469`.

NO BODY DIFF

### BaseConsultationDriver._selection_close_active_selection_menu -> _GeminiInlineBase._selection_close_active_selection_menu

Source body lines: `consultation_v2/drivers/base.py:1324-1332`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1325-1333`.

NO BODY DIFF

### BaseConsultationDriver._selection_conformance_gate -> _GeminiInlineBase._selection_conformance_gate

Source body lines: `consultation_v2/drivers/base.py:1638-1642`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1639-1643`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_click_ready -> _GeminiInlineBase._selection_element_click_ready

Source body lines: `consultation_v2/drivers/base.py:1438-1444`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1439-1445`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_has_state -> _GeminiInlineBase._selection_element_has_state

Source body lines: `consultation_v2/drivers/base.py:1492-1493`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1493-1494`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_matches_active_recognition -> _GeminiInlineBase._selection_element_matches_active_recognition

Source body lines: `consultation_v2/drivers/base.py:1500-1505`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1501-1506`.

NO BODY DIFF

### BaseConsultationDriver._selection_find_once -> _GeminiInlineBase._selection_find_once

Source body lines: `consultation_v2/drivers/base.py:1405-1405`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1406-1406`.

NO BODY DIFF

### BaseConsultationDriver._selection_prepare_base_for_menu -> _GeminiInlineBase._selection_prepare_base_for_menu

Source body lines: `consultation_v2/drivers/base.py:1133-1179`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1134-1180`.

NO BODY DIFF

### BaseConsultationDriver._selection_settle_seconds -> _GeminiInlineBase._selection_settle_seconds

Source body lines: `consultation_v2/drivers/base.py:1481-1489`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1482-1490`.

NO BODY DIFF

### BaseConsultationDriver._selection_snapshot -> _GeminiInlineBase._selection_snapshot

Source body lines: `consultation_v2/drivers/base.py:1471-1478`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1472-1479`.

NO BODY DIFF

### BaseConsultationDriver._selection_stable_snapshot -> _GeminiInlineBase._selection_stable_snapshot

Source body lines: `consultation_v2/drivers/base.py:1605-1630`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1606-1631`.

NO BODY DIFF

### BaseConsultationDriver._selection_trigger_keys -> _GeminiInlineBase._selection_trigger_keys

Source body lines: `consultation_v2/drivers/base.py:527-564`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:528-565`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_element -> _GeminiInlineBase._selection_wait_for_active_element

Source body lines: `consultation_v2/drivers/base.py:1539-1560`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1540-1561`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_state -> _GeminiInlineBase._selection_wait_for_active_state

Source body lines: `consultation_v2/drivers/base.py:1513-1531`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1514-1532`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_trigger -> _GeminiInlineBase._selection_wait_for_active_trigger

Source body lines: `consultation_v2/drivers/base.py:1569-1596`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1570-1597`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_clean_base -> _GeminiInlineBase._selection_wait_for_clean_base

Source body lines: `consultation_v2/drivers/base.py:1195-1209`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1196-1210`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_click_ready -> _GeminiInlineBase._selection_wait_for_click_ready

Source body lines: `consultation_v2/drivers/base.py:1416-1431`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1417-1432`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_hover_revealed_anchor -> _GeminiInlineBase._selection_wait_for_hover_revealed_anchor

Source body lines: `consultation_v2/drivers/base.py:1335-1348`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1336-1349`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_menu_closed -> _GeminiInlineBase._selection_wait_for_menu_closed

Source body lines: `consultation_v2/drivers/base.py:1228-1236`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1229-1237`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_revealed_anchor -> _GeminiInlineBase._selection_wait_for_revealed_anchor

Source body lines: `consultation_v2/drivers/base.py:1351-1394`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1352-1395`.

NO BODY DIFF

### BaseConsultationDriver._stop_key -> _GeminiInlineBase._stop_key

Source body lines: `consultation_v2/drivers/base.py:2236-2237`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2237-2238`.

NO BODY DIFF

### BaseConsultationDriver._urls_equivalent -> _GeminiInlineBase._urls_equivalent

Source body lines: `consultation_v2/drivers/base.py:2481-2481`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2482-2482`.

NO BODY DIFF

### BaseConsultationDriver._uses_identity_schema -> _GeminiInlineBase._uses_identity_schema

Source body lines: `consultation_v2/drivers/base.py:336-339`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:337-340`.

NO BODY DIFF

### BaseConsultationDriver._walk_selection_path -> _GeminiInlineBase._walk_selection_path

Source body lines: `consultation_v2/drivers/base.py:1265-1321`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1266-1322`.

NO BODY DIFF

### BaseConsultationDriver._workflow_prompt_keys -> _GeminiInlineBase._workflow_prompt_keys

Source body lines: `consultation_v2/drivers/base.py:567-577`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:568-578`.

NO BODY DIFF

### BaseConsultationDriver.acquire_display_lock -> _GeminiInlineBase.acquire_display_lock

Source body lines: `consultation_v2/drivers/base.py:1685-1689`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1686-1690`.

NO BODY DIFF

### BaseConsultationDriver.active_element_key -> _GeminiInlineBase.active_element_key

Source body lines: `consultation_v2/drivers/base.py:103-106`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:104-107`.

NO BODY DIFF

### BaseConsultationDriver.apply_selection_plan -> _GeminiInlineBase.apply_selection_plan

Source body lines: `consultation_v2/drivers/base.py:795-817`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:796-818`.

NO BODY DIFF

### BaseConsultationDriver.assert_session_not_dead -> _GeminiInlineBase.assert_session_not_dead

Source body lines: `consultation_v2/drivers/base.py:1701-1701`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1702-1702`.

NO BODY DIFF

### BaseConsultationDriver.checkpoint_run_state -> _GeminiInlineBase.checkpoint_run_state

Source body lines: `consultation_v2/drivers/base.py:1814-1853`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1815-1854`.

NO BODY DIFF

### BaseConsultationDriver.clear_run_state -> _GeminiInlineBase.clear_run_state

Source body lines: `consultation_v2/drivers/base.py:1704-1704`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1705-1705`.

NO BODY DIFF

### BaseConsultationDriver.deregister_monitor_session -> _GeminiInlineBase.deregister_monitor_session

Source body lines: `consultation_v2/drivers/base.py:1710-1710`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1711-1711`.

NO BODY DIFF

### BaseConsultationDriver.element_active_state -> _GeminiInlineBase.element_active_state

Source body lines: `consultation_v2/drivers/base.py:88-90`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:89-91`.

NO BODY DIFF

### BaseConsultationDriver.element_is_active -> _GeminiInlineBase.element_is_active

Source body lines: `consultation_v2/drivers/base.py:93-100`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:94-101`.

NO BODY DIFF

### BaseConsultationDriver.find_first -> _GeminiInlineBase.find_first

Source body lines: `consultation_v2/drivers/base.py:82-82`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:83-83`.

NO BODY DIFF

### BaseConsultationDriver.find_first_any -> _GeminiInlineBase.find_first_any

Source body lines: `consultation_v2/drivers/base.py:112-116`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:113-117`.

NO BODY DIFF

### BaseConsultationDriver.find_last -> _GeminiInlineBase.find_last

Source body lines: `consultation_v2/drivers/base.py:85-85`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:86-86`.

NO BODY DIFF

### BaseConsultationDriver.guarded_send -> _GeminiInlineBase.guarded_send

Source body lines: `consultation_v2/drivers/base.py:1860-1948`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1861-1949`.

NO BODY DIFF

### BaseConsultationDriver.is_resumable_session_url -> _GeminiInlineBase.is_resumable_session_url

Source body lines: `consultation_v2/drivers/base.py:1951-1951`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1952-1952`.

NO BODY DIFF

### BaseConsultationDriver.monitor_and_extract -> _GeminiInlineBase.monitor_and_extract

Source body lines: `consultation_v2/drivers/base.py:2852-2856`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2859-2863`.

NO BODY DIFF

### BaseConsultationDriver.monitor_generation -> _GeminiInlineBase.monitor_generation

Source body lines: `consultation_v2/drivers/base.py:2615-2782`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2616-2783`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.monitor_generation
+++ consultation_v2/platforms/gemini/driver.py:_GeminiInlineBase.monitor_generation
@@ -1,5 +1,5 @@
         """Poll until the response completes, using the SHARED stop-transition
-        detector (consultation_v2.completion.CompletionDetector) — the single
+        detector (consultation_v2.platforms.gemini.monitor.GeminiCompletionDetector) — the single
         source of truth that mirrors monitor/central.py::_detect_completion.

         Completion = the stop button was SEEN and is now GONE for the required
@@ -20,7 +20,7 @@
         detector_mode = (
             (mode if mode is not None else request.selection_value('mode', None)) or ''
         ).strip().lower()
-        detector = CompletionDetector(mode=detector_mode)
+        detector = GeminiCompletionDetector(mode=detector_mode)
         stop_key = self._stop_key()
         completed = False
         observed_stop = bool(seed_stop_seen)
```

### BaseConsultationDriver.read_run_state -> _GeminiInlineBase.read_run_state

Source body lines: `consultation_v2/drivers/base.py:1698-1698`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1699-1699`.

NO BODY DIFF

### BaseConsultationDriver.reassert_captured_session_url -> _GeminiInlineBase.reassert_captured_session_url

Source body lines: `consultation_v2/drivers/base.py:2533-2606`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2534-2607`.

NO BODY DIFF

### BaseConsultationDriver.register_monitor_session -> _GeminiInlineBase.register_monitor_session

Source body lines: `consultation_v2/drivers/base.py:1707-1707`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1708-1708`.

NO BODY DIFF

### BaseConsultationDriver.reject_prompt_echo_response -> _GeminiInlineBase.reject_prompt_echo_response

Source body lines: `consultation_v2/drivers/base.py:2444-2455`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2445-2456`.

NO BODY DIFF

### BaseConsultationDriver.release_display_lock -> _GeminiInlineBase.release_display_lock

Source body lines: `consultation_v2/drivers/base.py:1692-1692`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1693-1693`.

NO BODY DIFF

### BaseConsultationDriver.result -> _GeminiInlineBase.result

Source body lines: `consultation_v2/drivers/base.py:79-79`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:80-80`.

NO BODY DIFF

### BaseConsultationDriver.run -> _GeminiInlineBase.run

Source body lines: `consultation_v2/drivers/base.py:2790-2835`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2791-2844`.

```diff
--- consultation_v2/drivers/base.py:BaseConsultationDriver.run
+++ consultation_v2/platforms/gemini/driver.py:_GeminiInlineBase.run
@@ -43,4 +43,12 @@
             # handed off). The display lock is now RELEASED (with-block exited), so a
             # concurrent consultation may set up/send on this display while we monitor.
             self.monitor_and_extract(request, result)
+            if result.ok and result.response_text and self.reject_prompt_echo_response(
+                request,
+                result,
+                result.response_text,
+                step='extract_primary',
+                source='gemini_package_run_delivery_gate',
+            ):
+                result.ok = False
             return result
```

### BaseConsultationDriver.serialize_artifacts -> _GeminiInlineBase.serialize_artifacts

Source body lines: `consultation_v2/drivers/base.py:1668-1668`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1669-1669`.

NO BODY DIFF

### BaseConsultationDriver.set_response_text_if_not_prompt_echo -> _GeminiInlineBase.set_response_text_if_not_prompt_echo

Source body lines: `consultation_v2/drivers/base.py:2467-2477`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2468-2478`.

NO BODY DIFF

### BaseConsultationDriver.setup_and_send -> _GeminiInlineBase.setup_and_send

Source body lines: `consultation_v2/drivers/base.py:2841-2846`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2849-2854`.

NO BODY DIFF

### BaseConsultationDriver.snapshot_has_any -> _GeminiInlineBase.snapshot_has_any

Source body lines: `consultation_v2/drivers/base.py:109-109`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:110-110`.

NO BODY DIFF

### BaseConsultationDriver.store_consultation -> _GeminiInlineBase.store_consultation

Source body lines: `consultation_v2/drivers/base.py:2172-2186`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2173-2187`.

NO BODY DIFF

### BaseConsultationDriver.store_response_for_delivery -> _GeminiInlineBase.store_response_for_delivery

Source body lines: `consultation_v2/drivers/base.py:2196-2229`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2197-2230`.

NO BODY DIFF

### BaseConsultationDriver.tree_conformance_gate -> _GeminiInlineBase.tree_conformance_gate

Source body lines: `consultation_v2/drivers/base.py:124-196`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:125-197`.

NO BODY DIFF

### BaseConsultationDriver.validation_passes -> _GeminiInlineBase.validation_passes

Source body lines: `consultation_v2/drivers/base.py:607-727`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:608-728`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_key -> _GeminiInlineBase.wait_for_key

Source body lines: `consultation_v2/drivers/base.py:775-792`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:776-793`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_page_ready_after_navigation -> _GeminiInlineBase.wait_for_page_ready_after_navigation

Source body lines: `consultation_v2/drivers/base.py:419-486`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:420-487`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_validation -> _GeminiInlineBase.wait_for_validation

Source body lines: `consultation_v2/drivers/base.py:746-764`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:747-765`.

NO BODY DIFF

### BaseConsultationDriver.write_run_state -> _GeminiInlineBase.write_run_state

Source body lines: `consultation_v2/drivers/base.py:1695-1695`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:1696-1696`.

NO BODY DIFF

## Completion monitor

Source class: `consultation_v2/completion.py`::CompletionDetector. Target class: `consultation_v2/platforms/gemini/monitor.py`::GeminiCompletionDetector.

Method count: source `2`, target `2`.

### CompletionDetector.__post_init__ -> GeminiCompletionDetector.__post_init__

Source body lines: `consultation_v2/completion.py:63-64`.

Target body lines: `consultation_v2/platforms/gemini/monitor.py:63-64`.

NO BODY DIFF

### CompletionDetector.observe -> GeminiCompletionDetector.observe

Source body lines: `consultation_v2/completion.py:67-99`.

Target body lines: `consultation_v2/platforms/gemini/monitor.py:67-99`.

NO BODY DIFF

## Gemini driver methods

Source class: `consultation_v2/drivers/gemini.py`::GeminiConsultationDriver. Target class: `consultation_v2/platforms/gemini/driver.py`::GeminiConsultationDriver.

Method count: source `20`, target `20`.

### GeminiConsultationDriver._deep_think_element_text_fields -> GeminiConsultationDriver._deep_think_element_text_fields

Source body lines: `consultation_v2/drivers/gemini.py:610-614`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3464-3468`.

NO BODY DIFF

### GeminiConsultationDriver._deep_think_interim_ack_key -> GeminiConsultationDriver._deep_think_interim_ack_key

Source body lines: `consultation_v2/drivers/gemini.py:634-638`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3488-3492`.

NO BODY DIFF

### GeminiConsultationDriver._deep_think_interim_marker -> GeminiConsultationDriver._deep_think_interim_marker

Source body lines: `consultation_v2/drivers/gemini.py:618-621`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3472-3475`.

NO BODY DIFF

### GeminiConsultationDriver._deep_think_real_answer_evidence -> GeminiConsultationDriver._deep_think_real_answer_evidence

Source body lines: `consultation_v2/drivers/gemini.py:569-606`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3423-3460`.

NO BODY DIFF

### GeminiConsultationDriver._deep_think_text_matches_prompt -> GeminiConsultationDriver._deep_think_text_matches_prompt

Source body lines: `consultation_v2/drivers/gemini.py:624-631`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3478-3485`.

NO BODY DIFF

### GeminiConsultationDriver._interim_ack_absent -> GeminiConsultationDriver._interim_ack_absent

Source body lines: `consultation_v2/drivers/gemini.py:557-562`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3411-3416`.

NO BODY DIFF

### GeminiConsultationDriver._is_answer_thread_url -> GeminiConsultationDriver._is_answer_thread_url

Source body lines: `consultation_v2/drivers/gemini.py:315-319`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3169-3173`.

NO BODY DIFF

### GeminiConsultationDriver._monitor_deep_think_generation -> GeminiConsultationDriver._monitor_deep_think_generation

Source body lines: `consultation_v2/drivers/gemini.py:370-554`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3224-3408`.

```diff
--- consultation_v2/drivers/gemini.py:GeminiConsultationDriver._monitor_deep_think_generation
+++ consultation_v2/platforms/gemini/driver.py:GeminiConsultationDriver._monitor_deep_think_generation
@@ -1,4 +1,4 @@
-        detector = CompletionDetector(mode=detector_mode)
+        detector = GeminiCompletionDetector(mode=detector_mode)
         stop_key = self._stop_key()
         completed = False
         observed_stop = bool(seed_stop_seen)
@@ -43,7 +43,7 @@
                 post_ack_stop_seen = False
                 interim_ack_blocking_cycles += 1
                 terminal_answer_ready = False
-                detector = CompletionDetector(mode=detector_mode)
+                detector = GeminiCompletionDetector(mode=detector_mode)
                 return False
             if interim_ack_seen and not post_ack_stop_seen:
                 if stop_present:
```

### GeminiConsultationDriver._monitor_detector_mode -> GeminiConsultationDriver._monitor_detector_mode

Source body lines: `consultation_v2/drivers/gemini.py:359-360`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3213-3214`.

NO BODY DIFF

### GeminiConsultationDriver._wait_for_answer_thread_url -> GeminiConsultationDriver._wait_for_answer_thread_url

Source body lines: `consultation_v2/drivers/gemini.py:325-330`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3179-3184`.

NO BODY DIFF

### GeminiConsultationDriver.attach_files -> GeminiConsultationDriver.attach_files

Source body lines: `consultation_v2/drivers/gemini.py:98-201`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2952-3055`.

NO BODY DIFF

### GeminiConsultationDriver.enter_prompt -> GeminiConsultationDriver.enter_prompt

Source body lines: `consultation_v2/drivers/gemini.py:206-226`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3060-3080`.

NO BODY DIFF

### GeminiConsultationDriver.extract_additional -> GeminiConsultationDriver.extract_additional

Source body lines: `consultation_v2/drivers/gemini.py:737-749`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3591-3603`.

NO BODY DIFF

### GeminiConsultationDriver.extract_primary -> GeminiConsultationDriver.extract_primary

Source body lines: `consultation_v2/drivers/gemini.py:643-732`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3497-3586`.

NO BODY DIFF

### GeminiConsultationDriver.is_resumable_session_url -> GeminiConsultationDriver.is_resumable_session_url

Source body lines: `consultation_v2/drivers/gemini.py:322-322`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3176-3176`.

NO BODY DIFF

### GeminiConsultationDriver.monitor_and_extract -> GeminiConsultationDriver.monitor_and_extract

Source body lines: `consultation_v2/drivers/gemini.py:83-93`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2937-2947`.

NO BODY DIFF

### GeminiConsultationDriver.monitor_generation -> GeminiConsultationDriver.monitor_generation

Source body lines: `consultation_v2/drivers/gemini.py:339-352`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3193-3206`.

NO BODY DIFF

### GeminiConsultationDriver.send_prompt -> GeminiConsultationDriver.send_prompt

Source body lines: `consultation_v2/drivers/gemini.py:233-312`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3087-3166`.

NO BODY DIFF

### GeminiConsultationDriver.setup_and_send -> GeminiConsultationDriver.setup_and_send

Source body lines: `consultation_v2/drivers/gemini.py:45-78`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:2899-2932`.

NO BODY DIFF

### GeminiConsultationDriver.store_in_neo4j -> GeminiConsultationDriver.store_in_neo4j

Source body lines: `consultation_v2/drivers/gemini.py:754-765`.

Target body lines: `consultation_v2/platforms/gemini/driver.py:3608-3619`.

NO BODY DIFF
