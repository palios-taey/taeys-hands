# Grok Package Fix Ledger and Guard-Preservation Checklist

Pinned implementation commit: `81d3d921`.

| Finding / Guard | Fix / Preservation | Citation |
| --- | --- | --- |
| Package imports `consultation_v2.drivers.base` | Absent by design. Driver lifecycle base copied into package-local `_GrokInlineBase`; old driver path is a shim. | `consultation_v2/platforms/grok/driver.py:38`, `consultation_v2/drivers/grok.py:3` |
| Package imports `consultation_v2.completion` | Absent by design. Completion detector copied into package monitor as `GrokCompletionDetector`. | `consultation_v2/platforms/grok/monitor.py:48` |
| Out-of-package inheritance | Absent by design. `GrokConsultationDriver` inherits only package-local `_GrokInlineBase`; setup timeouts use built-in `TimeoutError`. | `consultation_v2/platforms/grok/driver.py:2851`, `consultation_v2/platforms/grok/driver.py:2934` |
| Package entry contract rejects prompt echo | Preserved. Package `run()` calls `reject_prompt_echo_response` after monitor/extract delivery. | `consultation_v2/platforms/grok/driver.py:2826` |
| Prompt echo guard on copy candidates | Preserved. Candidate copy text is checked before assigning `response_text`. | `consultation_v2/platforms/grok/driver.py:3746`, `consultation_v2/platforms/grok/driver.py:3758` |
| Grok YAML package ownership | Preserved by move. Loader checks `platforms/grok/grok.yaml` before flat legacy YAML. | `consultation_v2/platforms/grok/grok.yaml:1`, `consultation_v2/yaml_contract.py:243` |
| Validator gates include package YAML | Preserved. Contract, exact-match, and YAML fallback lints recursively discover YAML. | `consultation_v2/validators/lint_exact_match.py:40`, `consultation_v2/validators/lint_no_yaml_silent_fallbacks.py:91`, `consultation_v2/validators/lint_consultation_v2_contract.py:60` |
| Idempotent send / duplicate-send guard | Preserved. Setup phase calls `guarded_send`, which checks durable run-state before irreversible send and checkpoints only proven sends. | `consultation_v2/platforms/grok/driver.py:1841`, `consultation_v2/platforms/grok/driver.py:2885` |
| Setup step loud timeout | Preserved. Each setup step runs through bounded `_run_setup_step`; timeout raises `TimeoutError`. | `consultation_v2/platforms/grok/driver.py:2920`, `consultation_v2/platforms/grok/driver.py:2934` |
| Stop-button completion oracle | Preserved. Package monitor requires stop seen then gone; no content fallback. | `consultation_v2/platforms/grok/monitor.py:66`, `consultation_v2/platforms/grok/driver.py:3495` |
| Deep-mode debounce and floor | Preserved. Deep modes require two stop-gone cycles and carry the 1800s generation floor. | `consultation_v2/platforms/grok/monitor.py:64`, `consultation_v2/platforms/grok/driver.py:33` |
| Starved AT-SPI read is not completion | Preserved. Near-empty reads below the healthy raw-count floor are skipped instead of fed as stop-gone. | `consultation_v2/platforms/grok/driver.py:34`, `consultation_v2/platforms/grok/driver.py:2667` |
| Generation stalled maps to stop condition | Preserved. Visible stop after bounded monitor timeout records `generation_stalled` when configured. | `consultation_v2/platforms/grok/driver.py:2733`, `consultation_v2/platforms/grok/driver.py:28` |
| Answer-thread URL proof | Preserved. Send verification requires stop seen plus answer-thread URL proof; new sessions also require URL change. | `consultation_v2/platforms/grok/driver.py:3459`, `consultation_v2/platforms/grok/driver.py:3448` |
| Pre-send copy baseline | Preserved. Extraction refuses stale copy buttons and only considers new copy buttons since baseline. | `consultation_v2/platforms/grok/driver.py:3413`, `consultation_v2/platforms/grok/driver.py:3582` |
| Extraction via AT-SPI copy action | Preserved. Driver scrolls each new copy control into view and clicks via `atspi_only` before reading clipboard. | `consultation_v2/platforms/grok/driver.py:3719`, `consultation_v2/platforms/grok/driver.py:3720` |
| Result storage guard | Preserved. Store uses guarded delivery storage after extraction sets non-echo response text. | `consultation_v2/platforms/grok/driver.py:3794`, `consultation_v2/platforms/grok/driver.py:3798` |

Verification commands for this ledger are in the PR body and should be rerun before merge.
