# ChatGPT Package Fix Ledger and Guard-Preservation Checklist

Pinned source SHA: `599074da8dde0f4f3337f32275da15d252c60e95`.

| Finding / Guard | Fix / Preservation | Citation |
| --- | --- | --- |
| Package imports `consultation_v2.drivers.base` | Absent by design. Driver lifecycle base is copied into package-local `_ChatGPTInlineBase`; old driver path is a compatibility shim. | `consultation_v2/platforms/chatgpt/driver.py:38`, `consultation_v2/drivers/chatgpt.py:3` |
| Package imports `consultation_v2.completion` | Absent by design. Completion detector is copied into package monitor as `ChatGPTCompletionDetector`; driver imports only the package monitor constants/class. | `consultation_v2/platforms/chatgpt/monitor.py:48`, `consultation_v2/platforms/chatgpt/driver.py:17` |
| Out-of-package inheritance | Absent by design. `ChatGPTConsultationDriver` inherits only package-local `_ChatGPTInlineBase`. | `consultation_v2/platforms/chatgpt/driver.py:3008` |
| Package entry contract rejects prompt echo | Preserved. Package `run()` invokes `reject_prompt_echo_response` after monitor/extract delivery before returning `result`. | `consultation_v2/platforms/chatgpt/driver.py:2978` |
| Prompt echo guard on response assignment | Preserved. `set_response_text_if_not_prompt_echo` calls `reject_prompt_echo_response` before assigning `result.response_text`. | `consultation_v2/platforms/chatgpt/driver.py:2577`, `consultation_v2/platforms/chatgpt/driver.py:2600`, `consultation_v2/platforms/chatgpt/driver.py:2610` |
| Idempotent send / duplicate-send quarantine | Preserved. ChatGPT setup delegates irreversible send through `guarded_send`, which checks durable run-state and checkpoints only proven sends. | `consultation_v2/platforms/chatgpt/driver.py:1998`, `consultation_v2/platforms/chatgpt/driver.py:3142` |
| Stop-button completion oracle | Preserved. Package monitor completes only after stop was seen and then absent for required debounce cycles; ChatGPT subclass monitor uses `ChatGPTCompletionDetector` and Stop-gone-only completion. | `consultation_v2/platforms/chatgpt/monitor.py:48`, `consultation_v2/platforms/chatgpt/monitor.py:64`, `consultation_v2/platforms/chatgpt/driver.py:4282`, `consultation_v2/platforms/chatgpt/driver.py:4538` |
| Deep-mode debounce and floor | Preserved. Deep modes require two stop-gone cycles and the effective generation timeout floors deep modes to `DEEP_GENERATION_FLOOR_SECONDS = 1800.0`. | `consultation_v2/platforms/chatgpt/monitor.py:64`, `consultation_v2/platforms/chatgpt/driver.py:32`, `consultation_v2/platforms/chatgpt/driver.py:3332` |
| Starved AT-SPI read is not completion | Parity-preserved with source split nuance. The package-local base monitor carries the `MONITOR_MIN_HEALTHY_RAW_COUNT` guard, but ChatGPT's active subclass monitor override from the pinned W2E driver remains the active path and does not use that raw-count guard. This is not claimed as newly fixed; it is an honest parity-preserved gap. | `consultation_v2/platforms/chatgpt/driver.py:33`, `consultation_v2/platforms/chatgpt/driver.py:2824`, `consultation_v2/platforms/chatgpt/driver.py:4282` |
| Generation stalled is loud | Preserved. Visible Stop after timeout records `generation_stalled` when configured, in both inlined base and ChatGPT subclass monitor paths. | `consultation_v2/platforms/chatgpt/driver.py:2895`, `consultation_v2/platforms/chatgpt/driver.py:4513` |
| Scroll before extract | Preserved. ChatGPT extraction scrolls the thread to bottom before resolving/clicking response copy controls. | `consultation_v2/platforms/chatgpt/driver.py:4596`, `consultation_v2/platforms/chatgpt/driver.py:5137`, `consultation_v2/platforms/chatgpt/chatgpt.yaml:613` |
| W2E focus-and-key-open tools menu | Preserved. Runtime owns the generic `focus_and_key_open` primitive; ChatGPT tool selection and attachment paths opt into it through package YAML and package driver code. | `consultation_v2/runtime.py:456`, `consultation_v2/platforms/chatgpt/chatgpt.yaml:506`, `consultation_v2/platforms/chatgpt/chatgpt.yaml:562`, `consultation_v2/platforms/chatgpt/driver.py:1110`, `consultation_v2/platforms/chatgpt/driver.py:4026` |
| W2E typeahead + mapped postcondition | Preserved. Planner propagates `typeahead_label`/`postcondition`, YAML contract validates them fail-closed, and ChatGPT package applies typeahead only with mapped postcondition proof. | `consultation_v2/planner.py:269`, `consultation_v2/yaml_contract.py:88`, `consultation_v2/yaml_contract.py:101`, `consultation_v2/yaml_contract.py:972`, `consultation_v2/platforms/chatgpt/driver.py:1073`, `consultation_v2/platforms/chatgpt/chatgpt.yaml:517` |
| Deep Research active marker from W2E validation | Preserved. `tool_deep_research_active` is mapped to the live-observed `Deep Research tabs` page-tab-list postcondition. | `consultation_v2/platforms/chatgpt/chatgpt.yaml:376`, `consultation_v2/platforms/chatgpt/chatgpt.yaml:519` |
| ChatGPT inline identity branch pushed down | Completed. Shared `cli.py`/`orchestrator.py` no longer branch on `platform == 'chatgpt'`; they call the generic optional driver hook, and ChatGPT owns inline identity construction. | `consultation_v2/orchestrator.py:61`, `consultation_v2/cli.py:174`, `consultation_v2/platforms/chatgpt/driver.py:3075` |
| Residue-split routing imports | Preserved from current main. ChatGPT package uses `consultation_v2.platforms.routing` for Firefox/document lookup, not stale `consultation_v2.atspi` moved symbols. | `consultation_v2/platforms/chatgpt/driver.py:4591`, `consultation_v2/platforms/chatgpt/driver.py:5125` |
| Detection-in-YAML discipline | Preserved. ChatGPT mode/tool active recognition and DR postcondition live in package YAML, while driver code reads element keys through the plan/YAML maps. | `consultation_v2/platforms/chatgpt/chatgpt.yaml:376`, `consultation_v2/platforms/chatgpt/chatgpt.yaml:491`, `consultation_v2/platforms/chatgpt/chatgpt.yaml:517` |
| Leaf isolation lint covers routing core | Satisfied. `_routing_core.py` is in `LEAF_MODULES`. | `consultation_v2/validators/lint_platform_independence.py:28`, `consultation_v2/validators/lint_platform_independence.py:40` |
| Manual leaf-cleanliness check | Performed per gatekeeper instruction; raw hits are declared-registry checks or document-presence checks, not platform-policy branches. | `consultation_v2/validation/platform_independence_chatgpt/LEAF_CLEANLINESS_AUDIT.md:1` |
| Defined-sweep for uppercase constants | Passed. `DEEP_GENERATION_FLOOR_SECONDS`, `MONITOR_MIN_HEALTHY_RAW_COUNT`, `PROMPT_ECHO_FAILURE_MESSAGE`, and `INLINE_IDENTITY_ATTACHMENT` are module-defined; `COMPLETE` and `DEEP_MODES` are imported from package monitor where they are module-defined. | `consultation_v2/platforms/chatgpt/driver.py:32`, `consultation_v2/platforms/chatgpt/driver.py:33`, `consultation_v2/platforms/chatgpt/driver.py:34`, `consultation_v2/platforms/chatgpt/driver.py:35`, `consultation_v2/platforms/chatgpt/monitor.py:24`, `consultation_v2/platforms/chatgpt/monitor.py:45` |

## Verification Commands

```text
python3 -m py_compile consultation_v2/platforms/chatgpt/driver.py consultation_v2/platforms/chatgpt/monitor.py consultation_v2/drivers/chatgpt.py consultation_v2/runtime.py consultation_v2/planner.py consultation_v2/yaml_contract.py consultation_v2/orchestrator.py consultation_v2/cli.py
python3 -c 'import consultation_v2.platforms.chatgpt.driver; print("driver import ok")'
python3 consultation_v2/validators/lint_platform_independence.py --all
python3 consultation_v2/validators/lint_consultation_v2_contract.py --all
python3 -m consultation_v2.cli --platform chatgpt --message hello --dry-run
python3 - <<'SMOKE'  # planner + constant/import sweeps, see PR body for output
SMOKE
```

Observed local results: py_compile exited 0; driver import smoke printed `driver import ok`; platform isolation lint CLEAN with 5 package(s), 12 leaf module(s), 0 findings; contract lint CLEAN with 58 file(s), 0 findings; ChatGPT dry-run returned `identity_inline` from the package hook and `platform_contact=false`; planner smoke for `tools=['deep_research']` produced `typeahead_label='Deep research'` plus postcondition `tool_deep_research_active` in `app_root_snapshot`.

Unknown: no live ChatGPT browser consultation was run from this peer worktree. Production ChatGPT attach+Deep Research CONTROL validation remains supervisor-owned.
