# Claude Package Slice Diff

Pinned source SHA: `a04da10a4154247f122ef68cb0c3db65f1c0a26d`.

Comparison scope: AST method bodies for every inlined method, plus Claude class constants because they are moved behavioral data for artifact extraction and large-packet gates.

Source files: `consultation_v2/drivers/base.py`, `consultation_v2/completion.py`, and `consultation_v2/drivers/claude.py` at the pinned SHA.

Target files: `consultation_v2/platforms/claude/driver.py` and `consultation_v2/platforms/claude/monitor.py` in this working tree.

## Claude Class Constants

Source lines: `consultation_v2/drivers/claude.py:21-136`.

Target lines: `consultation_v2/platforms/claude/driver.py:2845-2960`.

NO BODY DIFF

## Shared lifecycle base

Source class: `consultation_v2/drivers/base.py`::BaseConsultationDriver. Target class: `consultation_v2/platforms/claude/driver.py`::_ClaudeInlineBase.

Method count: source `112`, target `112`.

### BaseConsultationDriver.__init__ -> _ClaudeInlineBase.__init__

Source body lines: `consultation_v2/drivers/base.py:74-76`.

Target body lines: `consultation_v2/platforms/claude/driver.py:53-55`.

NO BODY DIFF

### BaseConsultationDriver._activate_selection_path_element -> _ClaudeInlineBase._activate_selection_path_element

Source body lines: `consultation_v2/drivers/base.py:1397-1402`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1376-1381`.

NO BODY DIFF

### BaseConsultationDriver._apply_selection_step -> _ClaudeInlineBase._apply_selection_step

Source body lines: `consultation_v2/drivers/base.py:820-1063`.

Target body lines: `consultation_v2/platforms/claude/driver.py:799-1042`.

NO BODY DIFF

### BaseConsultationDriver._assert_monitor_answer_thread -> _ClaudeInlineBase._assert_monitor_answer_thread

Source body lines: `consultation_v2/drivers/base.py:2490-2524`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2469-2503`.

NO BODY DIFF

### BaseConsultationDriver._conformance_anchor_key -> _ClaudeInlineBase._conformance_anchor_key

Source body lines: `consultation_v2/drivers/base.py:318-333`.

Target body lines: `consultation_v2/platforms/claude/driver.py:297-312`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancies_still_present -> _ClaudeInlineBase._conformance_discrepancies_still_present

Source body lines: `consultation_v2/drivers/base.py:307-308`.

Target body lines: `consultation_v2/platforms/claude/driver.py:286-287`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancy_key -> _ClaudeInlineBase._conformance_discrepancy_key

Source body lines: `consultation_v2/drivers/base.py:312-315`.

Target body lines: `consultation_v2/platforms/claude/driver.py:291-294`.

NO BODY DIFF

### BaseConsultationDriver._conformance_findings -> _ClaudeInlineBase._conformance_findings

Source body lines: `consultation_v2/drivers/base.py:203-213`.

Target body lines: `consultation_v2/platforms/claude/driver.py:182-192`.

NO BODY DIFF

### BaseConsultationDriver._conformance_menu_surface_closed -> _ClaudeInlineBase._conformance_menu_surface_closed

Source body lines: `consultation_v2/drivers/base.py:358-362`.

Target body lines: `consultation_v2/platforms/claude/driver.py:337-341`.

NO BODY DIFF

### BaseConsultationDriver._conformance_snapshot -> _ClaudeInlineBase._conformance_snapshot

Source body lines: `consultation_v2/drivers/base.py:238-250`.

Target body lines: `consultation_v2/platforms/claude/driver.py:217-229`.

NO BODY DIFF

### BaseConsultationDriver._conformance_surface_is_menu_only -> _ClaudeInlineBase._conformance_surface_is_menu_only

Source body lines: `consultation_v2/drivers/base.py:369-374`.

Target body lines: `consultation_v2/platforms/claude/driver.py:348-353`.

NO BODY DIFF

### BaseConsultationDriver._conformance_unknown_discrepancies -> _ClaudeInlineBase._conformance_unknown_discrepancies

Source body lines: `consultation_v2/drivers/base.py:220-227`.

Target body lines: `consultation_v2/platforms/claude/driver.py:199-206`.

NO BODY DIFF

### BaseConsultationDriver._display -> _ClaudeInlineBase._display

Source body lines: `consultation_v2/drivers/base.py:1741-1741`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1720-1720`.

NO BODY DIFF

### BaseConsultationDriver._display_dispatch_lock -> _ClaudeInlineBase._display_dispatch_lock

Source body lines: `consultation_v2/drivers/base.py:1745-1774`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1724-1753`.

NO BODY DIFF

### BaseConsultationDriver._echo_tokens -> _ClaudeInlineBase._echo_tokens

Source body lines: `consultation_v2/drivers/base.py:2352-2352`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2331-2331`.

NO BODY DIFF

### BaseConsultationDriver._element_scope -> _ClaudeInlineBase._element_scope

Source body lines: `consultation_v2/drivers/base.py:1645-1649`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1624-1628`.

NO BODY DIFF

### BaseConsultationDriver._expected_keys_for_surface -> _ClaudeInlineBase._expected_keys_for_surface

Source body lines: `consultation_v2/drivers/base.py:342-350`.

Target body lines: `consultation_v2/platforms/claude/driver.py:321-329`.

NO BODY DIFF

### BaseConsultationDriver._fail_duplicate_send_risk -> _ClaudeInlineBase._fail_duplicate_send_risk

Source body lines: `consultation_v2/drivers/base.py:2019-2035`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1998-2014`.

NO BODY DIFF

### BaseConsultationDriver._gate_selection_plan -> _ClaudeInlineBase._gate_selection_plan

Source body lines: `consultation_v2/drivers/base.py:1652-1665`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1631-1644`.

NO BODY DIFF

### BaseConsultationDriver._handle_monitor_intermediate_state -> _ClaudeInlineBase._handle_monitor_intermediate_state

Source body lines: `consultation_v2/drivers/base.py:2294-2344`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2273-2323`.

NO BODY DIFF

### BaseConsultationDriver._invalidate_unresumable_landed_send -> _ClaudeInlineBase._invalidate_unresumable_landed_send

Source body lines: `consultation_v2/drivers/base.py:2075-2097`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2054-2076`.

NO BODY DIFF

### BaseConsultationDriver._is_incidental_base_unknown -> _ClaudeInlineBase._is_incidental_base_unknown

Source body lines: `consultation_v2/drivers/base.py:231-235`.

Target body lines: `consultation_v2/platforms/claude/driver.py:210-214`.

NO BODY DIFF

### BaseConsultationDriver._is_landed_send -> _ClaudeInlineBase._is_landed_send

Source body lines: `consultation_v2/drivers/base.py:2042-2054`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2021-2033`.

NO BODY DIFF

### BaseConsultationDriver._is_menu_scoped_element -> _ClaudeInlineBase._is_menu_scoped_element

Source body lines: `consultation_v2/drivers/base.py:378-385`.

Target body lines: `consultation_v2/platforms/claude/driver.py:357-364`.

NO BODY DIFF

### BaseConsultationDriver._is_prompt_echo -> _ClaudeInlineBase._is_prompt_echo

Source body lines: `consultation_v2/drivers/base.py:2432-2432`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2411-2411`.

NO BODY DIFF

### BaseConsultationDriver._is_setup_complete_send_quarantine -> _ClaudeInlineBase._is_setup_complete_send_quarantine

Source body lines: `consultation_v2/drivers/base.py:1965-1969`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1944-1948`.

NO BODY DIFF

### BaseConsultationDriver._is_unresumable_landed_send -> _ClaudeInlineBase._is_unresumable_landed_send

Source body lines: `consultation_v2/drivers/base.py:2061-2067`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2040-2046`.

NO BODY DIFF

### BaseConsultationDriver._landed_run_state_statuses -> _ClaudeInlineBase._landed_run_state_statuses

Source body lines: `consultation_v2/drivers/base.py:1954-1958`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1933-1937`.

NO BODY DIFF

### BaseConsultationDriver._live_resumable_send_url -> _ClaudeInlineBase._live_resumable_send_url

Source body lines: `consultation_v2/drivers/base.py:1972-1975`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1951-1954`.

NO BODY DIFF

### BaseConsultationDriver._missing_expected_elements -> _ClaudeInlineBase._missing_expected_elements

Source body lines: `consultation_v2/drivers/base.py:394-411`.

Target body lines: `consultation_v2/platforms/claude/driver.py:373-390`.

NO BODY DIFF

### BaseConsultationDriver._monitor_id -> _ClaudeInlineBase._monitor_id

Source body lines: `consultation_v2/drivers/base.py:1802-1805`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1781-1784`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_max_actions -> _ClaudeInlineBase._monitor_intermediate_max_actions

Source body lines: `consultation_v2/drivers/base.py:2271-2278`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2250-2257`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_states -> _ClaudeInlineBase._monitor_intermediate_states

Source body lines: `consultation_v2/drivers/base.py:2240-2251`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2219-2230`.

NO BODY DIFF

### BaseConsultationDriver._monitor_state_keys -> _ClaudeInlineBase._monitor_state_keys

Source body lines: `consultation_v2/drivers/base.py:2254-2268`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2233-2247`.

NO BODY DIFF

### BaseConsultationDriver._normalized_text -> _ClaudeInlineBase._normalized_text

Source body lines: `consultation_v2/drivers/base.py:2348-2348`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2327-2327`.

NO BODY DIFF

### BaseConsultationDriver._open_selection_menu -> _ClaudeInlineBase._open_selection_menu

Source body lines: `consultation_v2/drivers/base.py:1072-1130`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1051-1109`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_group_labels -> _ClaudeInlineBase._page_ready_group_labels

Source body lines: `consultation_v2/drivers/base.py:590-593`.

Target body lines: `consultation_v2/platforms/claude/driver.py:569-572`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_key_groups -> _ClaudeInlineBase._page_ready_key_groups

Source body lines: `consultation_v2/drivers/base.py:489-524`.

Target body lines: `consultation_v2/platforms/claude/driver.py:468-503`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_missing_groups -> _ClaudeInlineBase._page_ready_missing_groups

Source body lines: `consultation_v2/drivers/base.py:600-604`.

Target body lines: `consultation_v2/platforms/claude/driver.py:579-583`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_optional_keys -> _ClaudeInlineBase._page_ready_optional_keys

Source body lines: `consultation_v2/drivers/base.py:580-580`.

Target body lines: `consultation_v2/platforms/claude/driver.py:559-559`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_present_optional_keys -> _ClaudeInlineBase._page_ready_present_optional_keys

Source body lines: `consultation_v2/drivers/base.py:583-586`.

Target body lines: `consultation_v2/platforms/claude/driver.py:562-565`.

NO BODY DIFF

### BaseConsultationDriver._popup_recovery_settle_seconds -> _ClaudeInlineBase._popup_recovery_settle_seconds

Source body lines: `consultation_v2/drivers/base.py:293-299`.

Target body lines: `consultation_v2/platforms/claude/driver.py:272-278`.

NO BODY DIFF

### BaseConsultationDriver._post_popup_recovery_findings -> _ClaudeInlineBase._post_popup_recovery_findings

Source body lines: `consultation_v2/drivers/base.py:257-290`.

Target body lines: `consultation_v2/platforms/claude/driver.py:236-269`.

NO BODY DIFF

### BaseConsultationDriver._prompt_echo_evidence -> _ClaudeInlineBase._prompt_echo_evidence

Source body lines: `consultation_v2/drivers/base.py:2359-2429`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2338-2408`.

NO BODY DIFF

### BaseConsultationDriver._register_monitor -> _ClaudeInlineBase._register_monitor

Source body lines: `consultation_v2/drivers/base.py:2135-2163`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2114-2142`.

NO BODY DIFF

### BaseConsultationDriver._reset_detector_after_intermediate -> _ClaudeInlineBase._reset_detector_after_intermediate

Source body lines: `consultation_v2/drivers/base.py:2282-2284`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2261-2263`.

NO BODY DIFF

### BaseConsultationDriver._resume_landed_send -> _ClaudeInlineBase._resume_landed_send

Source body lines: `consultation_v2/drivers/base.py:2105-2126`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2084-2105`.

NO BODY DIFF

### BaseConsultationDriver._resume_possibly_landed_send -> _ClaudeInlineBase._resume_possibly_landed_send

Source body lines: `consultation_v2/drivers/base.py:1984-2011`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1963-1990`.

NO BODY DIFF

### BaseConsultationDriver._scoped_snapshot -> _ClaudeInlineBase._scoped_snapshot

Source body lines: `consultation_v2/drivers/base.py:730-735`.

Target body lines: `consultation_v2/platforms/claude/driver.py:709-714`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_anchor_key -> _ClaudeInlineBase._selection_base_anchor_key

Source body lines: `consultation_v2/drivers/base.py:1239-1255`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1218-1234`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_snapshot_clean -> _ClaudeInlineBase._selection_base_snapshot_clean

Source body lines: `consultation_v2/drivers/base.py:1212-1225`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1191-1204`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_base_anchor -> _ClaudeInlineBase._selection_click_base_anchor

Source body lines: `consultation_v2/drivers/base.py:1182-1192`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1161-1171`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_readiness -> _ClaudeInlineBase._selection_click_readiness

Source body lines: `consultation_v2/drivers/base.py:1451-1468`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1430-1447`.

NO BODY DIFF

### BaseConsultationDriver._selection_close_active_selection_menu -> _ClaudeInlineBase._selection_close_active_selection_menu

Source body lines: `consultation_v2/drivers/base.py:1324-1332`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1303-1311`.

NO BODY DIFF

### BaseConsultationDriver._selection_conformance_gate -> _ClaudeInlineBase._selection_conformance_gate

Source body lines: `consultation_v2/drivers/base.py:1638-1642`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1617-1621`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_click_ready -> _ClaudeInlineBase._selection_element_click_ready

Source body lines: `consultation_v2/drivers/base.py:1438-1444`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1417-1423`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_has_state -> _ClaudeInlineBase._selection_element_has_state

Source body lines: `consultation_v2/drivers/base.py:1492-1493`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1471-1472`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_matches_active_recognition -> _ClaudeInlineBase._selection_element_matches_active_recognition

Source body lines: `consultation_v2/drivers/base.py:1500-1505`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1479-1484`.

NO BODY DIFF

### BaseConsultationDriver._selection_find_once -> _ClaudeInlineBase._selection_find_once

Source body lines: `consultation_v2/drivers/base.py:1405-1405`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1384-1384`.

NO BODY DIFF

### BaseConsultationDriver._selection_prepare_base_for_menu -> _ClaudeInlineBase._selection_prepare_base_for_menu

Source body lines: `consultation_v2/drivers/base.py:1133-1179`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1112-1158`.

NO BODY DIFF

### BaseConsultationDriver._selection_settle_seconds -> _ClaudeInlineBase._selection_settle_seconds

Source body lines: `consultation_v2/drivers/base.py:1481-1489`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1460-1468`.

NO BODY DIFF

### BaseConsultationDriver._selection_snapshot -> _ClaudeInlineBase._selection_snapshot

Source body lines: `consultation_v2/drivers/base.py:1471-1478`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1450-1457`.

NO BODY DIFF

### BaseConsultationDriver._selection_stable_snapshot -> _ClaudeInlineBase._selection_stable_snapshot

Source body lines: `consultation_v2/drivers/base.py:1605-1630`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1584-1609`.

NO BODY DIFF

### BaseConsultationDriver._selection_trigger_keys -> _ClaudeInlineBase._selection_trigger_keys

Source body lines: `consultation_v2/drivers/base.py:527-564`.

Target body lines: `consultation_v2/platforms/claude/driver.py:506-543`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_element -> _ClaudeInlineBase._selection_wait_for_active_element

Source body lines: `consultation_v2/drivers/base.py:1539-1560`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1518-1539`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_state -> _ClaudeInlineBase._selection_wait_for_active_state

Source body lines: `consultation_v2/drivers/base.py:1513-1531`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1492-1510`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_trigger -> _ClaudeInlineBase._selection_wait_for_active_trigger

Source body lines: `consultation_v2/drivers/base.py:1569-1596`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1548-1575`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_clean_base -> _ClaudeInlineBase._selection_wait_for_clean_base

Source body lines: `consultation_v2/drivers/base.py:1195-1209`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1174-1188`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_click_ready -> _ClaudeInlineBase._selection_wait_for_click_ready

Source body lines: `consultation_v2/drivers/base.py:1416-1431`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1395-1410`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_hover_revealed_anchor -> _ClaudeInlineBase._selection_wait_for_hover_revealed_anchor

Source body lines: `consultation_v2/drivers/base.py:1335-1348`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1314-1327`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_menu_closed -> _ClaudeInlineBase._selection_wait_for_menu_closed

Source body lines: `consultation_v2/drivers/base.py:1228-1236`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1207-1215`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_revealed_anchor -> _ClaudeInlineBase._selection_wait_for_revealed_anchor

Source body lines: `consultation_v2/drivers/base.py:1351-1394`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1330-1373`.

NO BODY DIFF

### BaseConsultationDriver._stop_key -> _ClaudeInlineBase._stop_key

Source body lines: `consultation_v2/drivers/base.py:2236-2237`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2215-2216`.

NO BODY DIFF

### BaseConsultationDriver._urls_equivalent -> _ClaudeInlineBase._urls_equivalent

Source body lines: `consultation_v2/drivers/base.py:2481-2481`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2460-2460`.

NO BODY DIFF

### BaseConsultationDriver._uses_identity_schema -> _ClaudeInlineBase._uses_identity_schema

Source body lines: `consultation_v2/drivers/base.py:336-339`.

Target body lines: `consultation_v2/platforms/claude/driver.py:315-318`.

NO BODY DIFF

### BaseConsultationDriver._walk_selection_path -> _ClaudeInlineBase._walk_selection_path

Source body lines: `consultation_v2/drivers/base.py:1265-1321`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1244-1300`.

NO BODY DIFF

### BaseConsultationDriver._workflow_prompt_keys -> _ClaudeInlineBase._workflow_prompt_keys

Source body lines: `consultation_v2/drivers/base.py:567-577`.

Target body lines: `consultation_v2/platforms/claude/driver.py:546-556`.

NO BODY DIFF

### BaseConsultationDriver.acquire_display_lock -> _ClaudeInlineBase.acquire_display_lock

Source body lines: `consultation_v2/drivers/base.py:1685-1689`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1664-1668`.

NO BODY DIFF

### BaseConsultationDriver.active_element_key -> _ClaudeInlineBase.active_element_key

Source body lines: `consultation_v2/drivers/base.py:103-106`.

Target body lines: `consultation_v2/platforms/claude/driver.py:82-85`.

NO BODY DIFF

### BaseConsultationDriver.apply_selection_plan -> _ClaudeInlineBase.apply_selection_plan

Source body lines: `consultation_v2/drivers/base.py:795-817`.

Target body lines: `consultation_v2/platforms/claude/driver.py:774-796`.

NO BODY DIFF

### BaseConsultationDriver.assert_session_not_dead -> _ClaudeInlineBase.assert_session_not_dead

Source body lines: `consultation_v2/drivers/base.py:1701-1701`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1680-1680`.

NO BODY DIFF

### BaseConsultationDriver.checkpoint_run_state -> _ClaudeInlineBase.checkpoint_run_state

Source body lines: `consultation_v2/drivers/base.py:1814-1853`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1793-1832`.

NO BODY DIFF

### BaseConsultationDriver.clear_run_state -> _ClaudeInlineBase.clear_run_state

Source body lines: `consultation_v2/drivers/base.py:1704-1704`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1683-1683`.

NO BODY DIFF

### BaseConsultationDriver.deregister_monitor_session -> _ClaudeInlineBase.deregister_monitor_session

Source body lines: `consultation_v2/drivers/base.py:1710-1710`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1689-1689`.

NO BODY DIFF

### BaseConsultationDriver.element_active_state -> _ClaudeInlineBase.element_active_state

Source body lines: `consultation_v2/drivers/base.py:88-90`.

Target body lines: `consultation_v2/platforms/claude/driver.py:67-69`.

NO BODY DIFF

### BaseConsultationDriver.element_is_active -> _ClaudeInlineBase.element_is_active

Source body lines: `consultation_v2/drivers/base.py:93-100`.

Target body lines: `consultation_v2/platforms/claude/driver.py:72-79`.

NO BODY DIFF

### BaseConsultationDriver.find_first -> _ClaudeInlineBase.find_first

Source body lines: `consultation_v2/drivers/base.py:82-82`.

Target body lines: `consultation_v2/platforms/claude/driver.py:61-61`.

NO BODY DIFF

### BaseConsultationDriver.find_first_any -> _ClaudeInlineBase.find_first_any

Source body lines: `consultation_v2/drivers/base.py:112-116`.

Target body lines: `consultation_v2/platforms/claude/driver.py:91-95`.

NO BODY DIFF

### BaseConsultationDriver.find_last -> _ClaudeInlineBase.find_last

Source body lines: `consultation_v2/drivers/base.py:85-85`.

Target body lines: `consultation_v2/platforms/claude/driver.py:64-64`.

NO BODY DIFF

### BaseConsultationDriver.guarded_send -> _ClaudeInlineBase.guarded_send

Source body lines: `consultation_v2/drivers/base.py:1860-1948`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1839-1927`.

NO BODY DIFF

### BaseConsultationDriver.is_resumable_session_url -> _ClaudeInlineBase.is_resumable_session_url

Source body lines: `consultation_v2/drivers/base.py:1951-1951`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1930-1930`.

NO BODY DIFF

### BaseConsultationDriver.monitor_and_extract -> _ClaudeInlineBase.monitor_and_extract

Source body lines: `consultation_v2/drivers/base.py:2852-2856`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2837-2841`.

NO BODY DIFF

### BaseConsultationDriver.monitor_generation -> _ClaudeInlineBase.monitor_generation

Source body lines: `consultation_v2/drivers/base.py:2615-2782`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2594-2761`.

NO BODY DIFF

### BaseConsultationDriver.read_run_state -> _ClaudeInlineBase.read_run_state

Source body lines: `consultation_v2/drivers/base.py:1698-1698`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1677-1677`.

NO BODY DIFF

### BaseConsultationDriver.reassert_captured_session_url -> _ClaudeInlineBase.reassert_captured_session_url

Source body lines: `consultation_v2/drivers/base.py:2533-2606`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2512-2585`.

NO BODY DIFF

### BaseConsultationDriver.register_monitor_session -> _ClaudeInlineBase.register_monitor_session

Source body lines: `consultation_v2/drivers/base.py:1707-1707`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1686-1686`.

NO BODY DIFF

### BaseConsultationDriver.reject_prompt_echo_response -> _ClaudeInlineBase.reject_prompt_echo_response

Source body lines: `consultation_v2/drivers/base.py:2444-2455`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2423-2434`.

NO BODY DIFF

### BaseConsultationDriver.release_display_lock -> _ClaudeInlineBase.release_display_lock

Source body lines: `consultation_v2/drivers/base.py:1692-1692`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1671-1671`.

NO BODY DIFF

### BaseConsultationDriver.result -> _ClaudeInlineBase.result

Source body lines: `consultation_v2/drivers/base.py:79-79`.

Target body lines: `consultation_v2/platforms/claude/driver.py:58-58`.

NO BODY DIFF

### BaseConsultationDriver.run -> _ClaudeInlineBase.run

Source body lines: `consultation_v2/drivers/base.py:2790-2835`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2769-2822`.

```diff
--- consultation_v2/drivers/base.py:run
+++ consultation_v2/platforms/claude/driver.py:run
@@ -43,4 +43,12 @@
     # handed off). The display lock is now RELEASED (with-block exited), so a
     # concurrent consultation may set up/send on this display while we monitor.
     self.monitor_and_extract(request, result)
+    if result.ok and result.response_text and self.reject_prompt_echo_response(
+        request,
+        result,
+        result.response_text,
+        step='claude_package_run_delivery_gate',
+        source='package_run_exit',
+    ):
+        result.ok = False
     return result
```

### BaseConsultationDriver.serialize_artifacts -> _ClaudeInlineBase.serialize_artifacts

Source body lines: `consultation_v2/drivers/base.py:1668-1668`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1647-1647`.

NO BODY DIFF

### BaseConsultationDriver.set_response_text_if_not_prompt_echo -> _ClaudeInlineBase.set_response_text_if_not_prompt_echo

Source body lines: `consultation_v2/drivers/base.py:2467-2477`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2446-2456`.

NO BODY DIFF

### BaseConsultationDriver.setup_and_send -> _ClaudeInlineBase.setup_and_send

Source body lines: `consultation_v2/drivers/base.py:2841-2846`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2827-2832`.

NO BODY DIFF

### BaseConsultationDriver.snapshot_has_any -> _ClaudeInlineBase.snapshot_has_any

Source body lines: `consultation_v2/drivers/base.py:109-109`.

Target body lines: `consultation_v2/platforms/claude/driver.py:88-88`.

NO BODY DIFF

### BaseConsultationDriver.store_consultation -> _ClaudeInlineBase.store_consultation

Source body lines: `consultation_v2/drivers/base.py:2172-2186`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2151-2165`.

NO BODY DIFF

### BaseConsultationDriver.store_response_for_delivery -> _ClaudeInlineBase.store_response_for_delivery

Source body lines: `consultation_v2/drivers/base.py:2196-2229`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2175-2208`.

NO BODY DIFF

### BaseConsultationDriver.tree_conformance_gate -> _ClaudeInlineBase.tree_conformance_gate

Source body lines: `consultation_v2/drivers/base.py:124-196`.

Target body lines: `consultation_v2/platforms/claude/driver.py:103-175`.

NO BODY DIFF

### BaseConsultationDriver.validation_passes -> _ClaudeInlineBase.validation_passes

Source body lines: `consultation_v2/drivers/base.py:607-727`.

Target body lines: `consultation_v2/platforms/claude/driver.py:586-706`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_key -> _ClaudeInlineBase.wait_for_key

Source body lines: `consultation_v2/drivers/base.py:775-792`.

Target body lines: `consultation_v2/platforms/claude/driver.py:754-771`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_page_ready_after_navigation -> _ClaudeInlineBase.wait_for_page_ready_after_navigation

Source body lines: `consultation_v2/drivers/base.py:419-486`.

Target body lines: `consultation_v2/platforms/claude/driver.py:398-465`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_validation -> _ClaudeInlineBase.wait_for_validation

Source body lines: `consultation_v2/drivers/base.py:746-764`.

Target body lines: `consultation_v2/platforms/claude/driver.py:725-743`.

NO BODY DIFF

### BaseConsultationDriver.write_run_state -> _ClaudeInlineBase.write_run_state

Source body lines: `consultation_v2/drivers/base.py:1695-1695`.

Target body lines: `consultation_v2/platforms/claude/driver.py:1674-1674`.

NO BODY DIFF

## Completion monitor

Source class: `consultation_v2/completion.py`::CompletionDetector. Target class: `consultation_v2/platforms/claude/monitor.py`::ClaudeCompletionDetector.

Method count: source `2`, target `2`.

### CompletionDetector.__post_init__ -> ClaudeCompletionDetector.__post_init__

Source body lines: `consultation_v2/completion.py:63-64`.

Target body lines: `consultation_v2/platforms/claude/monitor.py:63-64`.

NO BODY DIFF

### CompletionDetector.observe -> ClaudeCompletionDetector.observe

Source body lines: `consultation_v2/completion.py:67-99`.

Target body lines: `consultation_v2/platforms/claude/monitor.py:67-99`.

NO BODY DIFF

## Claude driver

Source class: `consultation_v2/drivers/claude.py`::ClaudeConsultationDriver. Target class: `consultation_v2/platforms/claude/driver.py`::ClaudeConsultationDriver.

Method count: source `64`, target `64`.

### ClaudeConsultationDriver._artifact_copy_candidates -> ClaudeConsultationDriver._artifact_copy_candidates

Source body lines: `consultation_v2/drivers/claude.py:1747-1766`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4571-4590`.

NO BODY DIFF

### ClaudeConsultationDriver._artifact_copy_keys -> ClaudeConsultationDriver._artifact_copy_keys

Source body lines: `consultation_v2/drivers/claude.py:1732-1744`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4556-4568`.

NO BODY DIFF

### ClaudeConsultationDriver._artifact_name -> ClaudeConsultationDriver._artifact_name

Source body lines: `consultation_v2/drivers/claude.py:1976-1985`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4800-4809`.

NO BODY DIFF

### ClaudeConsultationDriver._artifact_names_from_response -> ClaudeConsultationDriver._artifact_names_from_response

Source body lines: `consultation_v2/drivers/claude.py:1770-1787`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4594-4611`.

NO BODY DIFF

### ClaudeConsultationDriver._artifact_payload_from_clipboard -> ClaudeConsultationDriver._artifact_payload_from_clipboard

Source body lines: `consultation_v2/drivers/claude.py:1801-1827`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4625-4651`.

NO BODY DIFF

### ClaudeConsultationDriver._atspi_path_to_root -> ClaudeConsultationDriver._atspi_path_to_root

Source body lines: `consultation_v2/drivers/claude.py:270-280`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3094-3104`.

NO BODY DIFF

### ClaudeConsultationDriver._attach_file_via_dialog -> ClaudeConsultationDriver._attach_file_via_dialog

Source body lines: `consultation_v2/drivers/claude.py:743-847`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3567-3671`.

NO BODY DIFF

### ClaudeConsultationDriver._attachment_chip_name -> ClaudeConsultationDriver._attachment_chip_name

Source body lines: `consultation_v2/drivers/claude.py:353-362`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3177-3186`.

NO BODY DIFF

### ClaudeConsultationDriver._attachment_name_matches -> ClaudeConsultationDriver._attachment_name_matches

Source body lines: `consultation_v2/drivers/claude.py:332-347`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3156-3171`.

NO BODY DIFF

### ClaudeConsultationDriver._attachment_visible -> ClaudeConsultationDriver._attachment_visible

Source body lines: `consultation_v2/drivers/claude.py:350-350`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3174-3174`.

NO BODY DIFF

### ClaudeConsultationDriver._clear_xsel_clipboard -> ClaudeConsultationDriver._clear_xsel_clipboard

Source body lines: `consultation_v2/drivers/claude.py:1898-1908`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4722-4732`.

NO BODY DIFF

### ClaudeConsultationDriver._composer_paste_chip_names -> ClaudeConsultationDriver._composer_paste_chip_names

Source body lines: `consultation_v2/drivers/claude.py:175-179`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2999-3003`.

NO BODY DIFF

### ClaudeConsultationDriver._composer_scope_elements -> ClaudeConsultationDriver._composer_scope_elements

Source body lines: `consultation_v2/drivers/claude.py:228-235`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3052-3059`.

NO BODY DIFF

### ClaudeConsultationDriver._composer_scope_keys -> ClaudeConsultationDriver._composer_scope_keys

Source body lines: `consultation_v2/drivers/claude.py:256-266`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3080-3090`.

NO BODY DIFF

### ClaudeConsultationDriver._composer_scope_root -> ClaudeConsultationDriver._composer_scope_root

Source body lines: `consultation_v2/drivers/claude.py:238-253`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3062-3077`.

NO BODY DIFF

### ClaudeConsultationDriver._contains_any_term -> ClaudeConsultationDriver._contains_any_term

Source body lines: `consultation_v2/drivers/claude.py:706-720`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3530-3544`.

NO BODY DIFF

### ClaudeConsultationDriver._copy_artifact_from_tree_controls -> ClaudeConsultationDriver._copy_artifact_from_tree_controls

Source body lines: `consultation_v2/drivers/claude.py:1664-1729`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4488-4553`.

NO BODY DIFF

### ClaudeConsultationDriver._copy_button_candidates -> ClaudeConsultationDriver._copy_button_candidates

Source body lines: `consultation_v2/drivers/claude.py:1400-1405`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4224-4229`.

NO BODY DIFF

### ClaudeConsultationDriver._dedupe_response_segments -> ClaudeConsultationDriver._dedupe_response_segments

Source body lines: `consultation_v2/drivers/claude.py:1409-1423`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4233-4247`.

NO BODY DIFF

### ClaudeConsultationDriver._disable_research_mode_before_attach -> ClaudeConsultationDriver._disable_research_mode_before_attach

Source body lines: `consultation_v2/drivers/claude.py:541-575`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3365-3399`.

NO BODY DIFF

### ClaudeConsultationDriver._effective_generation_timeout -> ClaudeConsultationDriver._effective_generation_timeout

Source body lines: `consultation_v2/drivers/claude.py:435-446`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3259-3270`.

NO BODY DIFF

### ClaudeConsultationDriver._element_descends_from -> ClaudeConsultationDriver._element_descends_from

Source body lines: `consultation_v2/drivers/claude.py:284-287`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3108-3111`.

NO BODY DIFF

### ClaudeConsultationDriver._element_evidence -> ClaudeConsultationDriver._element_evidence

Source body lines: `consultation_v2/drivers/claude.py:1999-1999`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4823-4823`.

NO BODY DIFF

### ClaudeConsultationDriver._fresh_url_with_nonce -> ClaudeConsultationDriver._fresh_url_with_nonce

Source body lines: `consultation_v2/drivers/claude.py:507-510`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3331-3334`.

NO BODY DIFF

### ClaudeConsultationDriver._is_answer_thread_url -> ClaudeConsultationDriver._is_answer_thread_url

Source body lines: `consultation_v2/drivers/claude.py:1261-1261`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4085-4085`.

NO BODY DIFF

### ClaudeConsultationDriver._is_broad_scope_root -> ClaudeConsultationDriver._is_broad_scope_root

Source body lines: `consultation_v2/drivers/claude.py:291-295`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3115-3119`.

NO BODY DIFF

### ClaudeConsultationDriver._is_incidental_base_unknown -> ClaudeConsultationDriver._is_incidental_base_unknown

Source body lines: `consultation_v2/drivers/claude.py:148-157`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2972-2981`.

NO BODY DIFF

### ClaudeConsultationDriver._looks_like_paste_chip -> ClaudeConsultationDriver._looks_like_paste_chip

Source body lines: `consultation_v2/drivers/claude.py:183-215`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3007-3039`.

NO BODY DIFF

### ClaudeConsultationDriver._monitor_completion_cycle -> ClaudeConsultationDriver._monitor_completion_cycle

Source body lines: `consultation_v2/drivers/claude.py:1034-1251`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3858-4075`.

NO BODY DIFF

### ClaudeConsultationDriver._monitor_exception_state -> ClaudeConsultationDriver._monitor_exception_state

Source body lines: `consultation_v2/drivers/claude.py:401-427`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3225-3251`.

NO BODY DIFF

### ClaudeConsultationDriver._monitor_exception_states -> ClaudeConsultationDriver._monitor_exception_states

Source body lines: `consultation_v2/drivers/claude.py:371-398`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3195-3222`.

NO BODY DIFF

### ClaudeConsultationDriver._navigation_snapshot_clean -> ClaudeConsultationDriver._navigation_snapshot_clean

Source body lines: `consultation_v2/drivers/claude.py:523-538`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3347-3362`.

NO BODY DIFF

### ClaudeConsultationDriver._page_selection_artifact_search_start -> ClaudeConsultationDriver._page_selection_artifact_search_start

Source body lines: `consultation_v2/drivers/claude.py:1879-1894`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4703-4718`.

NO BODY DIFF

### ClaudeConsultationDriver._paste_chip_names -> ClaudeConsultationDriver._paste_chip_names

Source body lines: `consultation_v2/drivers/claude.py:165-172`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2989-2996`.

NO BODY DIFF

### ClaudeConsultationDriver._prompt_text_status -> ClaudeConsultationDriver._prompt_text_status

Source body lines: `consultation_v2/drivers/claude.py:318-328`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3142-3152`.

NO BODY DIFF

### ClaudeConsultationDriver._read_input_text -> ClaudeConsultationDriver._read_input_text

Source body lines: `consultation_v2/drivers/claude.py:298-315`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3122-3139`.

NO BODY DIFF

### ClaudeConsultationDriver._read_xsel_clipboard -> ClaudeConsultationDriver._read_xsel_clipboard

Source body lines: `consultation_v2/drivers/claude.py:1911-1930`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4735-4754`.

NO BODY DIFF

### ClaudeConsultationDriver._request_requires_audit_substance -> ClaudeConsultationDriver._request_requires_audit_substance

Source body lines: `consultation_v2/drivers/claude.py:695-702`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3519-3526`.

NO BODY DIFF

### ClaudeConsultationDriver._response_body_without_thinking -> ClaudeConsultationDriver._response_body_without_thinking

Source body lines: `consultation_v2/drivers/claude.py:687-692`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3511-3516`.

NO BODY DIFF

### ClaudeConsultationDriver._response_expects_artifact -> ClaudeConsultationDriver._response_expects_artifact

Source body lines: `consultation_v2/drivers/claude.py:1791-1792`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4615-4616`.

NO BODY DIFF

### ClaudeConsultationDriver._scan_for_continue_button -> ClaudeConsultationDriver._scan_for_continue_button

Source body lines: `consultation_v2/drivers/claude.py:1254-1258`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4078-4082`.

NO BODY DIFF

### ClaudeConsultationDriver._screen_size -> ClaudeConsultationDriver._screen_size

Source body lines: `consultation_v2/drivers/claude.py:1989-1995`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4813-4819`.

NO BODY DIFF

### ClaudeConsultationDriver._send_blockers -> ClaudeConsultationDriver._send_blockers

Source body lines: `consultation_v2/drivers/claude.py:218-225`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3042-3049`.

NO BODY DIFF

### ClaudeConsultationDriver._slice_artifact_from_page_selection -> ClaudeConsultationDriver._slice_artifact_from_page_selection

Source body lines: `consultation_v2/drivers/claude.py:1835-1875`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4659-4699`.

NO BODY DIFF

### ClaudeConsultationDriver._snapshot_elements -> ClaudeConsultationDriver._snapshot_elements

Source body lines: `consultation_v2/drivers/claude.py:138-144`.

Target body lines: `consultation_v2/platforms/claude/driver.py:2962-2968`.

NO BODY DIFF

### ClaudeConsultationDriver._stop_keys -> ClaudeConsultationDriver._stop_keys

Source body lines: `consultation_v2/drivers/claude.py:365-368`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3189-3192`.

NO BODY DIFF

### ClaudeConsultationDriver._thinking_copy_button -> ClaudeConsultationDriver._thinking_copy_button

Source body lines: `consultation_v2/drivers/claude.py:1557-1578`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4381-4402`.

NO BODY DIFF

### ClaudeConsultationDriver._url_matches_target -> ClaudeConsultationDriver._url_matches_target

Source body lines: `consultation_v2/drivers/claude.py:514-520`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3338-3344`.

NO BODY DIFF

### ClaudeConsultationDriver._valid_artifact_text -> ClaudeConsultationDriver._valid_artifact_text

Source body lines: `consultation_v2/drivers/claude.py:1939-1972`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4763-4796`.

NO BODY DIFF

### ClaudeConsultationDriver._valid_thinking_text -> ClaudeConsultationDriver._valid_thinking_text

Source body lines: `consultation_v2/drivers/claude.py:1581-1594`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4405-4418`.

NO BODY DIFF

### ClaudeConsultationDriver._wait_for_attach_success -> ClaudeConsultationDriver._wait_for_attach_success

Source body lines: `consultation_v2/drivers/claude.py:866-879`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3690-3703`.

NO BODY DIFF

### ClaudeConsultationDriver._wait_for_upload_menu_item -> ClaudeConsultationDriver._wait_for_upload_menu_item

Source body lines: `consultation_v2/drivers/claude.py:850-863`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3674-3687`.

NO BODY DIFF

### ClaudeConsultationDriver.attach_files -> ClaudeConsultationDriver.attach_files

Source body lines: `consultation_v2/drivers/claude.py:729-736`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3553-3560`.

NO BODY DIFF

### ClaudeConsultationDriver.enter_prompt -> ClaudeConsultationDriver.enter_prompt

Source body lines: `consultation_v2/drivers/claude.py:888-927`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3712-3751`.

NO BODY DIFF

### ClaudeConsultationDriver.extract_additional -> ClaudeConsultationDriver.extract_additional

Source body lines: `consultation_v2/drivers/claude.py:1603-1655`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4427-4479`.

NO BODY DIFF

### ClaudeConsultationDriver.extract_primary -> ClaudeConsultationDriver.extract_primary

Source body lines: `consultation_v2/drivers/claude.py:1273-1397`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4097-4221`.

NO BODY DIFF

### ClaudeConsultationDriver.extract_thinking_notes -> ClaudeConsultationDriver.extract_thinking_notes

Source body lines: `consultation_v2/drivers/claude.py:1432-1549`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4256-4373`.

NO BODY DIFF

### ClaudeConsultationDriver.is_resumable_session_url -> ClaudeConsultationDriver.is_resumable_session_url

Source body lines: `consultation_v2/drivers/claude.py:1264-1264`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4088-4088`.

NO BODY DIFF

### ClaudeConsultationDriver.large_packet_substance_gate -> ClaudeConsultationDriver.large_packet_substance_gate

Source body lines: `consultation_v2/drivers/claude.py:599-683`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3423-3507`.

NO BODY DIFF

### ClaudeConsultationDriver.monitor_and_extract -> ClaudeConsultationDriver.monitor_and_extract

Source body lines: `consultation_v2/drivers/claude.py:580-592`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3404-3416`.

NO BODY DIFF

### ClaudeConsultationDriver.monitor_generation -> ClaudeConsultationDriver.monitor_generation

Source body lines: `consultation_v2/drivers/claude.py:1014-1021`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3838-3845`.

NO BODY DIFF

### ClaudeConsultationDriver.send_prompt -> ClaudeConsultationDriver.send_prompt

Source body lines: `consultation_v2/drivers/claude.py:938-1002`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3762-3826`.

NO BODY DIFF

### ClaudeConsultationDriver.setup_and_send -> ClaudeConsultationDriver.setup_and_send

Source body lines: `consultation_v2/drivers/claude.py:455-503`.

Target body lines: `consultation_v2/platforms/claude/driver.py:3279-3327`.

NO BODY DIFF

### ClaudeConsultationDriver.store_in_neo4j -> ClaudeConsultationDriver.store_in_neo4j

Source body lines: `consultation_v2/drivers/claude.py:2008-2019`.

Target body lines: `consultation_v2/platforms/claude/driver.py:4832-4843`.

NO BODY DIFF
