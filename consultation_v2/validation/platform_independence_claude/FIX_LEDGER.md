# Claude Package Fix Ledger and Guard-Preservation Checklist

Pinned source SHA: `a04da10a4154247f122ef68cb0c3db65f1c0a26d`.

| Finding / Guard | Fix / Preservation | Citation |
| --- | --- | --- |
| Package imports `consultation_v2.drivers.base` | Absent by design. Driver lifecycle base is copied into package-local `_ClaudeInlineBase`; old driver path is a compatibility shim. | `consultation_v2/platforms/claude/driver.py:31`, `consultation_v2/drivers/claude.py:3` |
| Package imports `consultation_v2.completion` | Absent by design. Completion detector is copied into package monitor as `ClaudeCompletionDetector`. | `consultation_v2/platforms/claude/monitor.py:48` |
| Out-of-package inheritance | `ClaudeConsultationDriver` inherits only package-local `_ClaudeInlineBase`. | `consultation_v2/platforms/claude/driver.py:2844` |
| Package entry contract rejects prompt echo | Preserved with package-run delivery gate after monitor/extract before returning `result`. | `consultation_v2/platforms/claude/driver.py:2818` |
| Prompt echo guard on response assignment | Preserved. `set_response_text_if_not_prompt_echo` calls `reject_prompt_echo_response` before assigning `result.response_text`. | `consultation_v2/platforms/claude/driver.py:2413`, `consultation_v2/platforms/claude/driver.py:2436` |
| Idempotent send / duplicate-send quarantine | Preserved. Claude setup delegates irreversible send through `guarded_send`, which checks durable run-state and checkpoints only proven sends. | `consultation_v2/platforms/claude/driver.py:1834`, `consultation_v2/platforms/claude/driver.py:3325` |
| Stop-button completion oracle | Preserved. Package monitor completes only after stop was seen and then absent for required debounce cycles; Claude monitor adds Continue-button veto and mapped exception-state checks. | `consultation_v2/platforms/claude/monitor.py:66`, `consultation_v2/platforms/claude/driver.py:3847` |
| Deep-mode debounce and floor | Preserved. Deep modes require two stop-gone cycles and Claude effective generation timeout floors deep modes to `DEEP_GENERATION_FLOOR_SECONDS`. | `consultation_v2/platforms/claude/monitor.py:64`, `consultation_v2/platforms/claude/driver.py:3253` |
| Starved AT-SPI read is not completion | Preserved in the package-local base monitor: degraded raw reads are skipped rather than counted as stop-absent completion. | `consultation_v2/platforms/claude/driver.py:2655`, `consultation_v2/platforms/claude/driver.py:2660` |
| Generation stalled is loud | Preserved in both package-local base monitor and Claude monitor. A visible Stop after timeout records `generation_stalled` when configured. | `consultation_v2/platforms/claude/driver.py:2726`, `consultation_v2/platforms/claude/driver.py:4046` |
| Mapped exception-state checks at completion boundary | Preserved from w2d. Claude monitor checks `workflow.monitor.exception_states` before accepting stop-gone completion and records mapped stop conditions. | `consultation_v2/platforms/claude/driver.py:3194`, `consultation_v2/platforms/claude/driver.py:3224`, `consultation_v2/platforms/claude/claude.yaml:596` |
| Claude artifact extraction uses mapped controls, not blind coordinates | Preserved from w2d. Additional extraction uses YAML `artifact_copy_keys` and raw AT-SPI candidates; the blind focus/ratio helper from main is absent. | `consultation_v2/platforms/claude/driver.py:4481`, `consultation_v2/platforms/claude/driver.py:4555`, `consultation_v2/platforms/claude/claude.yaml:631` |
| Claude hardcoded artifact copy-name list removed | `_ARTIFACT_COPY_NAMES` is absent from the package driver; copy labels live in package YAML element_map. | `consultation_v2/platforms/claude/claude.yaml:137` |
| Claude large-packet substance gate | Preserved. Claude retains the w2d/audit large-packet gate after artifact extraction and before storage. | `consultation_v2/platforms/claude/driver.py:3418`, `consultation_v2/platforms/claude/driver.py:3412` |
| Claude `--session-url` effort-submenu limitation | Handled fail-loud. Claude mode/effort is `resettable_on_followup: false`, and the shared planner rejects explicit follow-up changes for non-resettable menus. | `consultation_v2/platforms/claude/claude.yaml:530`, `consultation_v2/planner.py:148` |
| Detection-in-YAML discipline | Preserved. Claude model/mode/tool active recognition and artifact/exception controls live in YAML element_map/workflow, not hardcoded package selectors. | `consultation_v2/platforms/claude/claude.yaml:87`, `consultation_v2/platforms/claude/claude.yaml:631` |
| Leaf isolation lint covers routing core | Preserved from current main. `_routing_core.py` is in `LEAF_MODULES`. | `consultation_v2/validators/lint_platform_independence.py:40` |
| Manual leaf-cleanliness check | Performed per gatekeeper instruction; raw hits are declared-registry checks or document-presence checks, not platform-policy branches. | `consultation_v2/validation/platform_independence_claude/LEAF_CLEANLINESS_AUDIT.md:1` |

## Verification Commands

```text
python3 -m py_compile consultation_v2/planner.py consultation_v2/platforms/claude/driver.py consultation_v2/platforms/claude/monitor.py consultation_v2/drivers/claude.py consultation_v2/orchestrator.py
python3 consultation_v2/validators/lint_platform_independence.py --all
python3 consultation_v2/validators/lint_platform_independence.py --self-test
python3 consultation_v2/validators/lint_consultation_v2_contract.py --all
python3 consultation_v2/validators/lint_exact_match.py
python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all
python3 - <<'SMOKE'  # import/YAML/planner smoke, see PR body for output
SMOKE
```

Observed local results: py_compile exited 0; platform isolation lint CLEAN with 5 package(s), 12 leaf module(s), 0 findings; platform isolation self-test PASS; contract lint CLEAN with 56 file(s), 0 findings; exact-match lint PASS with 7 file(s), 0 loose matchers; YAML silent fallback gate CLEAN with 56 file(s), 0 findings. Import/YAML/planner smoke printed `import claude True True claude`, `artifact_keys True False`, `detector 2 complete`, fresh plan includes `model`, `mode`, and `tools`; follow-up plan includes only `model`; explicit follow-up mode change failed loud with `selection menu 'mode' cannot be changed on follow-up sessions`.

Unknown: no live Claude browser consultation was run from this peer worktree. Production Claude opus+max CONTROL validation remains supervisor-owned.
