# ChatGPT Package Slice Diff

Pinned source SHA: `599074da8dde0f4f3337f32275da15d252c60e95`.

Comparison scope: AST method bodies for every inlined method, plus ChatGPT class constants because they are moved behavioral data.

Source files: `consultation_v2/drivers/base.py`, `consultation_v2/completion.py`, and `consultation_v2/drivers/chatgpt.py` at the pinned W2E tree.

Target files: `consultation_v2/platforms/chatgpt/driver.py` and `consultation_v2/platforms/chatgpt/monitor.py` in this working tree.

Intentional non-parity entries are explicit: package delivery gate, current-main routing split imports, and ChatGPT-owned inline identity hook.

## ChatGPT Class Constants

Source class assignments from `consultation_v2/drivers/chatgpt.py::ChatGPTConsultationDriver` compared to package target.

NO BODY DIFF

## Shared lifecycle base

Source class: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py`::BaseConsultationDriver. Target class: `consultation_v2/platforms/chatgpt/driver.py`::_ChatGPTInlineBase.

Method count: source `114`, target `114`.

### BaseConsultationDriver.__init__ -> _ChatGPTInlineBase.__init__
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:74-76`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:60-62`.

NO BODY DIFF

### BaseConsultationDriver._activate_selection_path_element -> _ChatGPTInlineBase._activate_selection_path_element
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1554-1559`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1540-1545`.

NO BODY DIFF

### BaseConsultationDriver._apply_selection_step -> _ChatGPTInlineBase._apply_selection_step
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:822-1078`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:808-1064`.

NO BODY DIFF

### BaseConsultationDriver._apply_typeahead_selection_step -> _ChatGPTInlineBase._apply_typeahead_selection_step
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1091-1197`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1077-1183`.

NO BODY DIFF

### BaseConsultationDriver._assert_monitor_answer_thread -> _ChatGPTInlineBase._assert_monitor_answer_thread
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2647-2681`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2633-2667`.

NO BODY DIFF

### BaseConsultationDriver._conformance_anchor_key -> _ChatGPTInlineBase._conformance_anchor_key
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:318-333`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:304-319`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancies_still_present -> _ChatGPTInlineBase._conformance_discrepancies_still_present
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:307-308`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:293-294`.

NO BODY DIFF

### BaseConsultationDriver._conformance_discrepancy_key -> _ChatGPTInlineBase._conformance_discrepancy_key
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:312-315`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:298-301`.

NO BODY DIFF

### BaseConsultationDriver._conformance_findings -> _ChatGPTInlineBase._conformance_findings
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:203-213`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:189-199`.

NO BODY DIFF

### BaseConsultationDriver._conformance_menu_surface_closed -> _ChatGPTInlineBase._conformance_menu_surface_closed
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:358-362`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:344-348`.

NO BODY DIFF

### BaseConsultationDriver._conformance_snapshot -> _ChatGPTInlineBase._conformance_snapshot
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:238-250`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:224-236`.

NO BODY DIFF

### BaseConsultationDriver._conformance_surface_is_menu_only -> _ChatGPTInlineBase._conformance_surface_is_menu_only
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:369-374`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:355-360`.

NO BODY DIFF

### BaseConsultationDriver._conformance_unknown_discrepancies -> _ChatGPTInlineBase._conformance_unknown_discrepancies
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:220-227`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:206-213`.

NO BODY DIFF

### BaseConsultationDriver._display -> _ChatGPTInlineBase._display
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1898-1898`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1884-1884`.

NO BODY DIFF

### BaseConsultationDriver._display_dispatch_lock -> _ChatGPTInlineBase._display_dispatch_lock
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1902-1931`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1888-1917`.

NO BODY DIFF

### BaseConsultationDriver._echo_tokens -> _ChatGPTInlineBase._echo_tokens
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2509-2509`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2495-2495`.

NO BODY DIFF

### BaseConsultationDriver._element_scope -> _ChatGPTInlineBase._element_scope
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1802-1806`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1788-1792`.

NO BODY DIFF

### BaseConsultationDriver._expected_keys_for_surface -> _ChatGPTInlineBase._expected_keys_for_surface
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:342-350`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:328-336`.

NO BODY DIFF

### BaseConsultationDriver._fail_duplicate_send_risk -> _ChatGPTInlineBase._fail_duplicate_send_risk
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2176-2192`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2162-2178`.

NO BODY DIFF

### BaseConsultationDriver._gate_selection_plan -> _ChatGPTInlineBase._gate_selection_plan
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1809-1822`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1795-1808`.

NO BODY DIFF

### BaseConsultationDriver._handle_monitor_intermediate_state -> _ChatGPTInlineBase._handle_monitor_intermediate_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2451-2501`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2437-2487`.

NO BODY DIFF

### BaseConsultationDriver._invalidate_unresumable_landed_send -> _ChatGPTInlineBase._invalidate_unresumable_landed_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2232-2254`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2218-2240`.

NO BODY DIFF

### BaseConsultationDriver._is_incidental_base_unknown -> _ChatGPTInlineBase._is_incidental_base_unknown
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:231-235`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:217-221`.

NO BODY DIFF

### BaseConsultationDriver._is_landed_send -> _ChatGPTInlineBase._is_landed_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2199-2211`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2185-2197`.

NO BODY DIFF

### BaseConsultationDriver._is_menu_scoped_element -> _ChatGPTInlineBase._is_menu_scoped_element
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:378-385`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:364-371`.

NO BODY DIFF

### BaseConsultationDriver._is_prompt_echo -> _ChatGPTInlineBase._is_prompt_echo
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2589-2589`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2575-2575`.

NO BODY DIFF

### BaseConsultationDriver._is_setup_complete_send_quarantine -> _ChatGPTInlineBase._is_setup_complete_send_quarantine
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2122-2126`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2108-2112`.

NO BODY DIFF

### BaseConsultationDriver._is_unresumable_landed_send -> _ChatGPTInlineBase._is_unresumable_landed_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2218-2224`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2204-2210`.

NO BODY DIFF

### BaseConsultationDriver._landed_run_state_statuses -> _ChatGPTInlineBase._landed_run_state_statuses
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2111-2115`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2097-2101`.

NO BODY DIFF

### BaseConsultationDriver._live_resumable_send_url -> _ChatGPTInlineBase._live_resumable_send_url
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2129-2132`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2115-2118`.

NO BODY DIFF

### BaseConsultationDriver._missing_expected_elements -> _ChatGPTInlineBase._missing_expected_elements
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:394-411`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:380-397`.

NO BODY DIFF

### BaseConsultationDriver._monitor_id -> _ChatGPTInlineBase._monitor_id
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1959-1962`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1945-1948`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_max_actions -> _ChatGPTInlineBase._monitor_intermediate_max_actions
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2428-2435`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2414-2421`.

NO BODY DIFF

### BaseConsultationDriver._monitor_intermediate_states -> _ChatGPTInlineBase._monitor_intermediate_states
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2397-2408`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2383-2394`.

NO BODY DIFF

### BaseConsultationDriver._monitor_state_keys -> _ChatGPTInlineBase._monitor_state_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2411-2425`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2397-2411`.

NO BODY DIFF

### BaseConsultationDriver._normalized_text -> _ChatGPTInlineBase._normalized_text
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2505-2505`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2491-2491`.

NO BODY DIFF

### BaseConsultationDriver._open_selection_menu -> _ChatGPTInlineBase._open_selection_menu
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1229-1287`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1215-1273`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_group_labels -> _ChatGPTInlineBase._page_ready_group_labels
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:590-593`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:576-579`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_key_groups -> _ChatGPTInlineBase._page_ready_key_groups
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:489-524`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:475-510`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_missing_groups -> _ChatGPTInlineBase._page_ready_missing_groups
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:600-604`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:586-590`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_optional_keys -> _ChatGPTInlineBase._page_ready_optional_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:580-580`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:566-566`.

NO BODY DIFF

### BaseConsultationDriver._page_ready_present_optional_keys -> _ChatGPTInlineBase._page_ready_present_optional_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:583-586`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:569-572`.

NO BODY DIFF

### BaseConsultationDriver._popup_recovery_settle_seconds -> _ChatGPTInlineBase._popup_recovery_settle_seconds
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:293-299`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:279-285`.

NO BODY DIFF

### BaseConsultationDriver._post_popup_recovery_findings -> _ChatGPTInlineBase._post_popup_recovery_findings
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:257-290`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:243-276`.

NO BODY DIFF

### BaseConsultationDriver._prompt_echo_evidence -> _ChatGPTInlineBase._prompt_echo_evidence
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2516-2586`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2502-2572`.

NO BODY DIFF

### BaseConsultationDriver._register_monitor -> _ChatGPTInlineBase._register_monitor
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2292-2320`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2278-2306`.

NO BODY DIFF

### BaseConsultationDriver._reset_detector_after_intermediate -> _ChatGPTInlineBase._reset_detector_after_intermediate
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2439-2441`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2425-2427`.

NO BODY DIFF

### BaseConsultationDriver._resume_landed_send -> _ChatGPTInlineBase._resume_landed_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2262-2283`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2248-2269`.

NO BODY DIFF

### BaseConsultationDriver._resume_possibly_landed_send -> _ChatGPTInlineBase._resume_possibly_landed_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2141-2168`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2127-2154`.

NO BODY DIFF

### BaseConsultationDriver._scoped_snapshot -> _ChatGPTInlineBase._scoped_snapshot
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:730-737`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:716-723`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_anchor_key -> _ChatGPTInlineBase._selection_base_anchor_key
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1396-1412`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1382-1398`.

NO BODY DIFF

### BaseConsultationDriver._selection_base_snapshot_clean -> _ChatGPTInlineBase._selection_base_snapshot_clean
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1369-1382`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1355-1368`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_base_anchor -> _ChatGPTInlineBase._selection_click_base_anchor
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1339-1349`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1325-1335`.

NO BODY DIFF

### BaseConsultationDriver._selection_click_readiness -> _ChatGPTInlineBase._selection_click_readiness
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1608-1625`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1594-1611`.

NO BODY DIFF

### BaseConsultationDriver._selection_close_active_selection_menu -> _ChatGPTInlineBase._selection_close_active_selection_menu
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1481-1489`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1467-1475`.

NO BODY DIFF

### BaseConsultationDriver._selection_conformance_gate -> _ChatGPTInlineBase._selection_conformance_gate
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1795-1799`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1781-1785`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_click_ready -> _ChatGPTInlineBase._selection_element_click_ready
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1595-1601`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1581-1587`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_has_state -> _ChatGPTInlineBase._selection_element_has_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1649-1650`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1635-1636`.

NO BODY DIFF

### BaseConsultationDriver._selection_element_matches_active_recognition -> _ChatGPTInlineBase._selection_element_matches_active_recognition
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1657-1662`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1643-1648`.

NO BODY DIFF

### BaseConsultationDriver._selection_find_once -> _ChatGPTInlineBase._selection_find_once
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1562-1562`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1548-1548`.

NO BODY DIFF

### BaseConsultationDriver._selection_prepare_base_for_menu -> _ChatGPTInlineBase._selection_prepare_base_for_menu
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1290-1336`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1276-1322`.

NO BODY DIFF

### BaseConsultationDriver._selection_settle_seconds -> _ChatGPTInlineBase._selection_settle_seconds
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1638-1646`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1624-1632`.

NO BODY DIFF

### BaseConsultationDriver._selection_snapshot -> _ChatGPTInlineBase._selection_snapshot
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1628-1635`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1614-1621`.

NO BODY DIFF

### BaseConsultationDriver._selection_stable_snapshot -> _ChatGPTInlineBase._selection_stable_snapshot
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1762-1787`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1748-1773`.

NO BODY DIFF

### BaseConsultationDriver._selection_trigger_keys -> _ChatGPTInlineBase._selection_trigger_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:527-564`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:513-550`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_element -> _ChatGPTInlineBase._selection_wait_for_active_element
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1696-1717`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1682-1703`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_state -> _ChatGPTInlineBase._selection_wait_for_active_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1670-1688`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1656-1674`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_active_trigger -> _ChatGPTInlineBase._selection_wait_for_active_trigger
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1726-1753`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1712-1739`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_clean_base -> _ChatGPTInlineBase._selection_wait_for_clean_base
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1352-1366`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1338-1352`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_click_ready -> _ChatGPTInlineBase._selection_wait_for_click_ready
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1573-1588`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1559-1574`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_hover_revealed_anchor -> _ChatGPTInlineBase._selection_wait_for_hover_revealed_anchor
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1492-1505`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1478-1491`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_menu_closed -> _ChatGPTInlineBase._selection_wait_for_menu_closed
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1385-1393`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1371-1379`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_revealed_anchor -> _ChatGPTInlineBase._selection_wait_for_revealed_anchor
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1508-1551`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1494-1537`.

NO BODY DIFF

### BaseConsultationDriver._selection_wait_for_typeahead_postcondition -> _ChatGPTInlineBase._selection_wait_for_typeahead_postcondition
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1206-1220`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1192-1206`.

NO BODY DIFF

### BaseConsultationDriver._stop_key -> _ChatGPTInlineBase._stop_key
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2393-2394`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2379-2380`.

NO BODY DIFF

### BaseConsultationDriver._urls_equivalent -> _ChatGPTInlineBase._urls_equivalent
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2638-2638`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2624-2624`.

NO BODY DIFF

### BaseConsultationDriver._uses_identity_schema -> _ChatGPTInlineBase._uses_identity_schema
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:336-339`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:322-325`.

NO BODY DIFF

### BaseConsultationDriver._walk_selection_path -> _ChatGPTInlineBase._walk_selection_path
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1422-1478`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1408-1464`.

NO BODY DIFF

### BaseConsultationDriver._workflow_prompt_keys -> _ChatGPTInlineBase._workflow_prompt_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:567-577`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:553-563`.

NO BODY DIFF

### BaseConsultationDriver.acquire_display_lock -> _ChatGPTInlineBase.acquire_display_lock
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1842-1846`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1828-1832`.

NO BODY DIFF

### BaseConsultationDriver.active_element_key -> _ChatGPTInlineBase.active_element_key
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:103-106`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:89-92`.

NO BODY DIFF

### BaseConsultationDriver.apply_selection_plan -> _ChatGPTInlineBase.apply_selection_plan
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:797-819`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:783-805`.

NO BODY DIFF

### BaseConsultationDriver.assert_session_not_dead -> _ChatGPTInlineBase.assert_session_not_dead
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1858-1858`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1844-1844`.

NO BODY DIFF

### BaseConsultationDriver.checkpoint_run_state -> _ChatGPTInlineBase.checkpoint_run_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1971-2010`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1957-1996`.

NO BODY DIFF

### BaseConsultationDriver.clear_run_state -> _ChatGPTInlineBase.clear_run_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1861-1861`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1847-1847`.

NO BODY DIFF

### BaseConsultationDriver.deregister_monitor_session -> _ChatGPTInlineBase.deregister_monitor_session
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1867-1867`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1853-1853`.

NO BODY DIFF

### BaseConsultationDriver.element_active_state -> _ChatGPTInlineBase.element_active_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:88-90`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:74-76`.

NO BODY DIFF

### BaseConsultationDriver.element_is_active -> _ChatGPTInlineBase.element_is_active
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:93-100`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:79-86`.

NO BODY DIFF

### BaseConsultationDriver.find_first -> _ChatGPTInlineBase.find_first
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:82-82`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:68-68`.

NO BODY DIFF

### BaseConsultationDriver.find_first_any -> _ChatGPTInlineBase.find_first_any
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:112-116`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:98-102`.

NO BODY DIFF

### BaseConsultationDriver.find_last -> _ChatGPTInlineBase.find_last
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:85-85`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:71-71`.

NO BODY DIFF

### BaseConsultationDriver.guarded_send -> _ChatGPTInlineBase.guarded_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2017-2105`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2003-2091`.

NO BODY DIFF

### BaseConsultationDriver.is_resumable_session_url -> _ChatGPTInlineBase.is_resumable_session_url
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2108-2108`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2094-2094`.

NO BODY DIFF

### BaseConsultationDriver.monitor_and_extract -> _ChatGPTInlineBase.monitor_and_extract
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:3009-3013`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3001-3005`.

NO BODY DIFF

### BaseConsultationDriver.monitor_generation -> _ChatGPTInlineBase.monitor_generation
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2772-2939`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2758-2925`.

```diff
--- /home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:monitor_generation
+++ consultation_v2/platforms/chatgpt/driver.py:monitor_generation
@@ -1,5 +1,5 @@
         """Poll until the response completes, using the SHARED stop-transition
-        detector (consultation_v2.completion.CompletionDetector) — the single
+        detector (`consultation_v2.platforms.chatgpt.monitor.ChatGPTCompletionDetector`) — the single
         source of truth that mirrors monitor/central.py::_detect_completion.

         Completion = the stop button was SEEN and is now GONE for the required
@@ -20,7 +20,7 @@
         detector_mode = (
             (mode if mode is not None else request.selection_value('mode', None)) or ''
         ).strip().lower()
-        detector = CompletionDetector(mode=detector_mode)
+        detector = ChatGPTCompletionDetector(mode=detector_mode)
         stop_key = self._stop_key()
         completed = False
         observed_stop = bool(seed_stop_seen)
```

### BaseConsultationDriver.read_run_state -> _ChatGPTInlineBase.read_run_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1855-1855`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1841-1841`.

NO BODY DIFF

### BaseConsultationDriver.reassert_captured_session_url -> _ChatGPTInlineBase.reassert_captured_session_url
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2690-2763`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2676-2749`.

NO BODY DIFF

### BaseConsultationDriver.register_monitor_session -> _ChatGPTInlineBase.register_monitor_session
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1864-1864`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1850-1850`.

NO BODY DIFF

### BaseConsultationDriver.reject_prompt_echo_response -> _ChatGPTInlineBase.reject_prompt_echo_response
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2601-2612`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2587-2598`.

NO BODY DIFF

### BaseConsultationDriver.release_display_lock -> _ChatGPTInlineBase.release_display_lock
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1849-1849`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1835-1835`.

NO BODY DIFF

### BaseConsultationDriver.result -> _ChatGPTInlineBase.result
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:79-79`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:65-65`.

NO BODY DIFF

### BaseConsultationDriver.run -> _ChatGPTInlineBase.run
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2947-2992`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2933-2986`.

```diff
--- /home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:run
+++ consultation_v2/platforms/chatgpt/driver.py:run
@@ -43,4 +43,12 @@
             # handed off). The display lock is now RELEASED (with-block exited), so a
             # concurrent consultation may set up/send on this display while we monitor.
             self.monitor_and_extract(request, result)
+            if result.ok and result.response_text and self.reject_prompt_echo_response(
+                request,
+                result,
+                result.response_text,
+                step='extract_primary',
+                source='chatgpt_package_run_delivery_gate',
+            ):
+                result.ok = False
             return result
```

### BaseConsultationDriver.serialize_artifacts -> _ChatGPTInlineBase.serialize_artifacts
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1825-1825`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1811-1811`.

NO BODY DIFF

### BaseConsultationDriver.set_response_text_if_not_prompt_echo -> _ChatGPTInlineBase.set_response_text_if_not_prompt_echo
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2624-2634`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2610-2620`.

NO BODY DIFF

### BaseConsultationDriver.setup_and_send -> _ChatGPTInlineBase.setup_and_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2998-3003`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2991-2996`.

NO BODY DIFF

### BaseConsultationDriver.snapshot_has_any -> _ChatGPTInlineBase.snapshot_has_any
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:109-109`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:95-95`.

NO BODY DIFF

### BaseConsultationDriver.store_consultation -> _ChatGPTInlineBase.store_consultation
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2329-2343`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2315-2329`.

NO BODY DIFF

### BaseConsultationDriver.store_response_for_delivery -> _ChatGPTInlineBase.store_response_for_delivery
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:2353-2386`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:2339-2372`.

NO BODY DIFF

### BaseConsultationDriver.tree_conformance_gate -> _ChatGPTInlineBase.tree_conformance_gate
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:124-196`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:110-182`.

NO BODY DIFF

### BaseConsultationDriver.validation_passes -> _ChatGPTInlineBase.validation_passes
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:607-727`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:593-713`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_key -> _ChatGPTInlineBase.wait_for_key
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:777-794`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:763-780`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_page_ready_after_navigation -> _ChatGPTInlineBase.wait_for_page_ready_after_navigation
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:419-486`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:405-472`.

NO BODY DIFF

### BaseConsultationDriver.wait_for_validation -> _ChatGPTInlineBase.wait_for_validation
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:748-766`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:734-752`.

NO BODY DIFF

### BaseConsultationDriver.write_run_state -> _ChatGPTInlineBase.write_run_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/base.py:1852-1852`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:1838-1838`.

NO BODY DIFF

## Completion detector

Source class: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/completion.py`::CompletionDetector. Target class: `consultation_v2/platforms/chatgpt/monitor.py`::ChatGPTCompletionDetector.

Method count: source `2`, target `2`.

### CompletionDetector.__post_init__ -> ChatGPTCompletionDetector.__post_init__
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/completion.py:63-64`.
Target body lines: `consultation_v2/platforms/chatgpt/monitor.py:63-64`.

NO BODY DIFF

### CompletionDetector.observe -> ChatGPTCompletionDetector.observe
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/completion.py:67-99`.
Target body lines: `consultation_v2/platforms/chatgpt/monitor.py:67-99`.

NO BODY DIFF

## ChatGPT platform driver

Source class: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py`::ChatGPTConsultationDriver. Target class: `consultation_v2/platforms/chatgpt/driver.py`::ChatGPTConsultationDriver.

Method count: source `73`, target `75`.

### ChatGPTConsultationDriver._atspi_object_evidence -> ChatGPTConsultationDriver._atspi_object_evidence
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:354-369`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3385-3400`.

NO BODY DIFF

### ChatGPTConsultationDriver._atspi_path_to_root -> ChatGPTConsultationDriver._atspi_path_to_root
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:824-834`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3855-3865`.

NO BODY DIFF

### ChatGPTConsultationDriver._atspi_state_names -> ChatGPTConsultationDriver._atspi_state_names
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:328-351`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3359-3382`.

NO BODY DIFF

### ChatGPTConsultationDriver._attachment_chip -> ChatGPTConsultationDriver._attachment_chip
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:688-697`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3719-3728`.

NO BODY DIFF

### ChatGPTConsultationDriver._attachment_name_matches -> ChatGPTConsultationDriver._attachment_name_matches
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:672-682`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3703-3713`.

NO BODY DIFF

### ChatGPTConsultationDriver._attachment_upload_blockers -> ChatGPTConsultationDriver._attachment_upload_blockers
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:894-917`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3925-3948`.

NO BODY DIFF

### ChatGPTConsultationDriver._attachment_visible -> ChatGPTConsultationDriver._attachment_visible
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:685-685`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3716-3716`.

NO BODY DIFF

### ChatGPTConsultationDriver._bottommost_input -> ChatGPTConsultationDriver._bottommost_input
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:311-324`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3342-3355`.

NO BODY DIFF

### ChatGPTConsultationDriver._bounded_composer_focus_target -> ChatGPTConsultationDriver._bounded_composer_focus_target
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:372-430`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3403-3461`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_action_specs -> ChatGPTConsultationDriver._chatgpt_action_specs
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1773-1778`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4804-4809`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_append_text_chunk -> ChatGPTConsultationDriver._chatgpt_append_text_chunk
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1835-1853`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4866-4884`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_bounded_response_text_fallback -> ChatGPTConsultationDriver._chatgpt_bounded_response_text_fallback
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:2020-2090`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:5051-5121`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_collect_response_band_text -> ChatGPTConsultationDriver._chatgpt_collect_response_band_text
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1949-1979`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4980-5010`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_collect_response_subtree_text -> ChatGPTConsultationDriver._chatgpt_collect_response_subtree_text
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1864-1939`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4895-4970`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_compact_node_evidence -> ChatGPTConsultationDriver._chatgpt_compact_node_evidence
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1817-1825`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4848-4856`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_document -> ChatGPTConsultationDriver._chatgpt_document
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1560-1563`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4591-4594`.

```diff
--- /home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:_chatgpt_document
+++ consultation_v2/platforms/chatgpt/driver.py:_chatgpt_document
@@ -1,4 +1,4 @@
-        from consultation_v2 import atspi as _atspi
+        from consultation_v2.platforms import routing as platform_routing

-        firefox = _atspi.find_firefox_for_platform(self.platform)
-        return _atspi.get_platform_document(firefox, self.platform) if firefox else None
+        firefox = platform_routing.find_firefox_for_platform(self.platform)
+        return platform_routing.get_platform_document(firefox, self.platform) if firefox else None
```

### ChatGPTConsultationDriver._chatgpt_extract_quality_failure -> ChatGPTConsultationDriver._chatgpt_extract_quality_failure
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1738-1763`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4769-4794`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_fallback_prompt_contamination -> ChatGPTConsultationDriver._chatgpt_fallback_prompt_contamination
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1986-1995`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:5017-5026`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_int -> ChatGPTConsultationDriver._chatgpt_int
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1767-1770`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4798-4801`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_is_response_action_element -> ChatGPTConsultationDriver._chatgpt_is_response_action_element
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1781-1791`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4812-4822`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_latest_assistant_turn_copy_candidates -> ChatGPTConsultationDriver._chatgpt_latest_assistant_turn_copy_candidates
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1680-1731`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4711-4762`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_latest_turn_copy_candidates -> ChatGPTConsultationDriver._chatgpt_latest_turn_copy_candidates
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1606-1673`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4637-4704`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_node_text -> ChatGPTConsultationDriver._chatgpt_node_text
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1794-1813`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4825-4844`.

NO BODY DIFF

### ChatGPTConsultationDriver._chatgpt_response_text_candidate_failure -> ChatGPTConsultationDriver._chatgpt_response_text_candidate_failure
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:2002-2011`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:5033-5042`.

NO BODY DIFF

### ChatGPTConsultationDriver._click -> ChatGPTConsultationDriver._click
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:139-141`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3170-3172`.

NO BODY DIFF

### ChatGPTConsultationDriver._click_strategy -> ChatGPTConsultationDriver._click_strategy
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:135-136`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3166-3167`.

NO BODY DIFF

### ChatGPTConsultationDriver._compact_stop_reading -> ChatGPTConsultationDriver._compact_stop_reading
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:252-268`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3283-3299`.

NO BODY DIFF

### ChatGPTConsultationDriver._composer_band_elements -> ChatGPTConsultationDriver._composer_band_elements
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:784-807`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3815-3838`.

NO BODY DIFF

### ChatGPTConsultationDriver._composer_focus_verification -> ChatGPTConsultationDriver._composer_focus_verification
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:466-476`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3497-3507`.

NO BODY DIFF

### ChatGPTConsultationDriver._composer_paste_chip_names -> ChatGPTConsultationDriver._composer_paste_chip_names
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:749-753`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3780-3784`.

NO BODY DIFF

### ChatGPTConsultationDriver._composer_scope_elements -> ChatGPTConsultationDriver._composer_scope_elements
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:756-763`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3787-3794`.

NO BODY DIFF

### ChatGPTConsultationDriver._composer_scope_keys -> ChatGPTConsultationDriver._composer_scope_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:810-820`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3841-3851`.

NO BODY DIFF

### ChatGPTConsultationDriver._composer_scope_root -> ChatGPTConsultationDriver._composer_scope_root
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:766-781`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3797-3812`.

NO BODY DIFF

### ChatGPTConsultationDriver._effective_generation_timeout -> ChatGPTConsultationDriver._effective_generation_timeout
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:291-302`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3322-3333`.

NO BODY DIFF

### ChatGPTConsultationDriver._element_descends_from -> ChatGPTConsultationDriver._element_descends_from
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:838-841`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3869-3872`.

NO BODY DIFF

### ChatGPTConsultationDriver._element_evidence -> ChatGPTConsultationDriver._element_evidence
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:145-153`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3176-3184`.

NO BODY DIFF

### ChatGPTConsultationDriver._element_state_set -> ChatGPTConsultationDriver._element_state_set
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:889-891`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3920-3922`.

NO BODY DIFF

### ChatGPTConsultationDriver._file_dialog_open -> ChatGPTConsultationDriver._file_dialog_open
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:852-856`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3883-3887`.

NO BODY DIFF

### ChatGPTConsultationDriver._focus_composer -> ChatGPTConsultationDriver._focus_composer
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:479-557`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3510-3588`.

NO BODY DIFF

### ChatGPTConsultationDriver._focused_editable_descendant -> ChatGPTConsultationDriver._focused_editable_descendant
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:433-463`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3464-3494`.

NO BODY DIFF

### ChatGPTConsultationDriver._is_answer_thread_url -> ChatGPTConsultationDriver._is_answer_thread_url
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1525-1525`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4556-4556`.

NO BODY DIFF

### ChatGPTConsultationDriver._is_broad_scope_root -> ChatGPTConsultationDriver._is_broad_scope_root
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:845-849`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3876-3880`.

NO BODY DIFF

### ChatGPTConsultationDriver._looks_like_paste_chip -> ChatGPTConsultationDriver._looks_like_paste_chip
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:716-746`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3747-3777`.

NO BODY DIFF

### ChatGPTConsultationDriver._minimum_stop_gone_cycles -> ChatGPTConsultationDriver._minimum_stop_gone_cycles
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:271-276`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3302-3307`.

NO BODY DIFF

### ChatGPTConsultationDriver._paste_chip_names -> ChatGPTConsultationDriver._paste_chip_names
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:705-712`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3736-3743`.

NO BODY DIFF

### ChatGPTConsultationDriver._post_complete_quiet_cycles -> ChatGPTConsultationDriver._post_complete_quiet_cycles
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:279-284`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3310-3315`.

NO BODY DIFF

### ChatGPTConsultationDriver._prompt_input_keys -> ChatGPTConsultationDriver._prompt_input_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:156-159`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3187-3190`.

NO BODY DIFF

### ChatGPTConsultationDriver._read_stop_state -> ChatGPTConsultationDriver._read_stop_state
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:229-248`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3260-3279`.

NO BODY DIFF

### ChatGPTConsultationDriver._screen_rect -> ChatGPTConsultationDriver._screen_rect
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1539-1557`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4570-4588`.

NO BODY DIFF

### ChatGPTConsultationDriver._scroll_chatgpt_thread_to_bottom -> ChatGPTConsultationDriver._scroll_chatgpt_thread_to_bottom
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1566-1598`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4597-4629`.

NO BODY DIFF

### ChatGPTConsultationDriver._send_button_keys -> ChatGPTConsultationDriver._send_button_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:305-308`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3336-3339`.

NO BODY DIFF

### ChatGPTConsultationDriver._send_button_readiness -> ChatGPTConsultationDriver._send_button_readiness
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1128-1149`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4159-4180`.

NO BODY DIFF

### ChatGPTConsultationDriver._send_failure_reason -> ChatGPTConsultationDriver._send_failure_reason
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1095-1125`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4126-4156`.

NO BODY DIFF

### ChatGPTConsultationDriver._snapshot_elements -> ChatGPTConsultationDriver._snapshot_elements
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:879-885`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3910-3916`.

NO BODY DIFF

### ChatGPTConsultationDriver._snapshot_elements_for_evidence -> ChatGPTConsultationDriver._snapshot_elements_for_evidence
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:169-175`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3200-3206`.

NO BODY DIFF

### ChatGPTConsultationDriver._stop_keys -> ChatGPTConsultationDriver._stop_keys
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:162-165`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3193-3196`.

NO BODY DIFF

### ChatGPTConsultationDriver._stop_like_candidates -> ChatGPTConsultationDriver._stop_like_candidates
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:178-187`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3209-3218`.

NO BODY DIFF

### ChatGPTConsultationDriver._stop_read_evidence -> ChatGPTConsultationDriver._stop_read_evidence
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:195-206`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3226-3237`.

NO BODY DIFF

### ChatGPTConsultationDriver._stop_snapshot_probe -> ChatGPTConsultationDriver._stop_snapshot_probe
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:209-221`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3240-3252`.

NO BODY DIFF

### ChatGPTConsultationDriver._wait_for_answer_thread_url -> ChatGPTConsultationDriver._wait_for_answer_thread_url
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1531-1535`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4562-4566`.

NO BODY DIFF

### ChatGPTConsultationDriver._wait_for_attachment_chip -> ChatGPTConsultationDriver._wait_for_attachment_chip
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:859-876`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3890-3907`.

NO BODY DIFF

### ChatGPTConsultationDriver._wait_for_attachment_upload_complete -> ChatGPTConsultationDriver._wait_for_attachment_upload_complete
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:924-979`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3955-4010`.

NO BODY DIFF

### ChatGPTConsultationDriver.attach_files -> ChatGPTConsultationDriver.attach_files
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:982-1053`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4013-4084`.

NO BODY DIFF

### ChatGPTConsultationDriver.clean_composer -> ChatGPTConsultationDriver.clean_composer
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:564-664`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3595-3695`.

NO BODY DIFF

### ChatGPTConsultationDriver.enter_prompt -> ChatGPTConsultationDriver.enter_prompt
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1067-1091`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4098-4122`.

NO BODY DIFF

### ChatGPTConsultationDriver.extract_additional -> ChatGPTConsultationDriver.extract_additional
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:2305-2306`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:5336-5337`.

NO BODY DIFF

### ChatGPTConsultationDriver.extract_primary -> ChatGPTConsultationDriver.extract_primary
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:2093-2302`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:5124-5333`.

```diff
--- /home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:extract_primary
+++ consultation_v2/platforms/chatgpt/driver.py:extract_primary
@@ -1,5 +1,5 @@
         from consultation_v2 import clipboard
-        from consultation_v2.atspi import find_firefox_for_platform, get_platform_document
+        from consultation_v2.platforms import routing as platform_routing
         from consultation_v2.interact import atspi_click
         from consultation_v2.tree import find_elements as raw_find_elements

@@ -31,7 +31,7 @@
                     snapshot=last_snapshot.serializable() if last_snapshot else {},
                 )
                 return False
-            firefox = find_firefox_for_platform(self.platform)
+            firefox = platform_routing.find_firefox_for_platform(self.platform)
             if not firefox:
                 attempts.append({
                     'attempt': attempt + 1,
@@ -43,7 +43,7 @@
                 firefox.clear_cache_single()
             except Exception:
                 pass
-            document = get_platform_document(firefox, self.platform)
+            document = platform_routing.get_platform_document(firefox, self.platform)
             if not document:
                 attempts.append({
                     'attempt': attempt + 1,
```

### ChatGPTConsultationDriver.is_resumable_session_url -> ChatGPTConsultationDriver.is_resumable_session_url
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1528-1528`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4559-4559`.

NO BODY DIFF

### ChatGPTConsultationDriver.monitor_and_extract -> ChatGPTConsultationDriver.monitor_and_extract
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:118-128`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3149-3159`.

NO BODY DIFF

### ChatGPTConsultationDriver.monitor_generation -> ChatGPTConsultationDriver.monitor_generation
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1295-1522`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4326-4553`.

```diff
--- /home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:monitor_generation
+++ consultation_v2/platforms/chatgpt/driver.py:monitor_generation
@@ -1,5 +1,5 @@
         detector_mode = str(request.selection_value('mode', '') or '').strip().lower()
-        detector = CompletionDetector(mode=detector_mode)
+        detector = ChatGPTCompletionDetector(mode=detector_mode)
         detector.required_stop_cycles = max(
             detector.required_stop_cycles,
             self._minimum_stop_gone_cycles(),
```

### ChatGPTConsultationDriver.send_prompt -> ChatGPTConsultationDriver.send_prompt
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:1154-1288`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:4185-4319`.

NO BODY DIFF

### ChatGPTConsultationDriver.setup_and_send -> ChatGPTConsultationDriver.setup_and_send
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:76-113`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:3107-3144`.

NO BODY DIFF

### ChatGPTConsultationDriver.store_in_neo4j -> ChatGPTConsultationDriver.store_in_neo4j
Source body lines: `/home/mira/.worktrees/w2e-chatgpt/consultation_v2/drivers/chatgpt.py:2313-2324`.
Target body lines: `consultation_v2/platforms/chatgpt/driver.py:5344-5355`.

NO BODY DIFF

### Target-only methods

- `ChatGPTConsultationDriver._inline_context_message` at `consultation_v2/platforms/chatgpt/driver.py:3063` — package-only hook or extraction support not present in source class.
- `ChatGPTConsultationDriver.prepare_identity_request` at `consultation_v2/platforms/chatgpt/driver.py:3075` — package-only hook or extraction support not present in source class.
