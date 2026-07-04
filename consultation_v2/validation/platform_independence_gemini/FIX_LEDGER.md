# Gemini Package Fix Ledger and Guard-Preservation Checklist

Pinned source SHA: `ddc55dc89538bffddd9622ae03103cbcc48a133a`.

| Finding / Guard | Fix / Preservation | Citation |
| --- | --- | --- |
| Package imports `consultation_v2.drivers.base` | Absent by design. Driver lifecycle base is copied into package-local `_GeminiInlineBase`; old driver path is a compatibility shim. | `consultation_v2/platforms/gemini/driver.py:53`, `consultation_v2/drivers/gemini.py:3` |
| Package imports `consultation_v2.completion` | Absent by design. Completion detector is copied into package monitor as `GeminiCompletionDetector`. | `consultation_v2/platforms/gemini/monitor.py:48` |
| Out-of-package inheritance | Absent by design. `GeminiConsultationDriver` inherits only package-local `_GeminiInlineBase`. | `consultation_v2/platforms/gemini/driver.py:2889` |
| Package entry contract rejects prompt echo | Preserved. Package `run()` invokes `reject_prompt_echo_response` after monitor/extract delivery before returning `result`. | `consultation_v2/platforms/gemini/driver.py:2836` |
| Prompt echo guard on response assignment | Preserved. `set_response_text_if_not_prompt_echo` calls `reject_prompt_echo_response` before assigning `result.response_text`. | `consultation_v2/platforms/gemini/driver.py:2435`, `consultation_v2/platforms/gemini/driver.py:2468` |
| Gemini Deep Think interim-ACK guard | Preserved as-is from main. Deep Think monitor waits for interim ACK absence, post-ACK Stop observation, and real answer evidence before completion. | `consultation_v2/platforms/gemini/driver.py:3186`, `consultation_v2/platforms/gemini/driver.py:3263`, `consultation_v2/platforms/gemini/driver.py:3355`, `consultation_v2/platforms/gemini/gemini.yaml:249` |
| Gemini interim marker behavior | Preserved as moved constants, including the curly-apostrophe `i’m on it` marker validated by import smoke. | `consultation_v2/platforms/gemini/driver.py:2867` |
| Gemini Deep Research extraction behavior | Preserved as-is. Deep Research still uses Share & Export -> Copy content path rather than the chat-bubble copy stub. | `consultation_v2/platforms/gemini/driver.py:3502`, `consultation_v2/platforms/gemini/gemini.yaml:314` |
| Idempotent send / duplicate-send guard | Preserved. Gemini setup still delegates irreversible send through `guarded_send`, which checks durable run-state and checkpoints only proven sends. | `consultation_v2/platforms/gemini/driver.py:1856`, `consultation_v2/platforms/gemini/driver.py:2930` |
| Stop-button completion oracle | Preserved. `GeminiCompletionDetector.observe()` only completes after stop was seen and then absent for the required debounce cycles; Gemini Deep Think adds stricter ACK/real-answer gates on top. | `consultation_v2/platforms/gemini/monitor.py:64`, `consultation_v2/platforms/gemini/monitor.py:84`, `consultation_v2/platforms/gemini/driver.py:3358` |
| Deep-mode debounce and floor | Preserved. Deep modes require two stop-gone cycles and Gemini monitor retains the 1800-second floor. | `consultation_v2/platforms/gemini/monitor.py:64`, `consultation_v2/platforms/gemini/driver.py:3295` |
| Starved AT-SPI read is not completion | Preserved in the package-local base monitor. Reads below the healthy raw-count floor are skipped instead of counted as stop-absent completion. | `consultation_v2/platforms/gemini/driver.py:49`, `consultation_v2/platforms/gemini/driver.py:2670` |
| Generation stalled is loud | Preserved in both package-local base monitor and Gemini Deep Think monitor. A visible stop button after timeout records `generation_stalled` when configured. | `consultation_v2/platforms/gemini/driver.py:2744`, `consultation_v2/platforms/gemini/driver.py:3365` |
| Scroll before extract | Preserved. Normal Gemini extraction scrolls to bottom before resolving the response copy button. | `consultation_v2/platforms/gemini/driver.py:3552` |
| Detection-in-YAML discipline | Preserved for Gemini mode/ACK/extraction controls. The mode active elements and interim ACK key remain YAML-owned. | `consultation_v2/platforms/gemini/gemini.yaml:223`, `consultation_v2/platforms/gemini/gemini.yaml:249`, `consultation_v2/platforms/gemini/gemini.yaml:320` |
| Shared structural ordinal/index typo discipline | Fixed in the shared leaf loader. `structural.ordinal` must be one of `first`/`last`; `structural.index` must be a non-negative integer and not boolean, so typoed locators fail loud instead of falling through to midpoint selection. | `consultation_v2/yaml_contract.py:51`, `consultation_v2/yaml_contract.py:386`, `consultation_v2/yaml_contract.py:396` |
| Leaf isolation lint covers routing core | Preserved from current main and cited here for this package. `_routing_core.py` is in `LEAF_MODULES`. | `consultation_v2/validators/lint_platform_independence.py:40` |
| Manual leaf-cleanliness check | Per task supplement, not relying on isolation lint alone. Manual AST scan found no per-platform behavior branches; eight raw hits were classified as document-presence checks or declared-registry data checks. | `consultation_v2/validation/platform_independence_gemini/LEAF_CLEANLINESS_AUDIT.md:1` |

## Verification Commands

```text
python3 -m py_compile consultation_v2/platforms/gemini/driver.py consultation_v2/platforms/gemini/monitor.py consultation_v2/drivers/gemini.py consultation_v2/orchestrator.py consultation_v2/yaml_contract.py
python3 consultation_v2/validators/lint_platform_independence.py --all
python3 consultation_v2/validators/lint_platform_independence.py --self-test
python3 consultation_v2/validators/lint_consultation_v2_contract.py --all
python3 consultation_v2/validators/lint_exact_match.py
python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all
python3 - <<'SMOKE'
from consultation_v2.platforms.gemini.driver import GeminiConsultationDriver, GEMINI_DEEP_THINK_INTERIM_MARKERS
from consultation_v2.drivers.gemini import GeminiConsultationDriver as Shim
from consultation_v2.orchestrator import _REGISTRY
from consultation_v2.yaml_contract import load_platform_yaml
cfg = load_platform_yaml('gemini')
print(GeminiConsultationDriver.platform)
print(Shim is GeminiConsultationDriver)
print(_REGISTRY['gemini'] is GeminiConsultationDriver)
print(cfg['platform'])
print('i’m on it' in GEMINI_DEEP_THINK_INTERIM_MARKERS)
SMOKE
```

Observed local results: py_compile exited 0; platform isolation lint CLEAN with 5 package(s), 12 leaf module(s), 0 findings; platform isolation self-test PASS; contract lint CLEAN with 54 file(s), 0 findings; exact-match lint PASS with 7 file(s), 0 loose matchers; YAML silent fallback gate CLEAN with 54 file(s), 0 findings; Gemini import/YAML smoke printed `gemini`, `True`, `True`, `gemini`, `True`; bad structural `ordinal`, negative `index`, and boolean `index` all raised `ValueError` via `_validate_chat_yaml`.

Unknown: no live Gemini browser consultation was run from this peer worktree. Production Deep Think CONTROL validation remains supervisor-owned.
