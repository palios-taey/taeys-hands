# Perplexity Package Fix Ledger and Guard-Preservation Checklist

Pinned source SHA: `0aac0047dd9d0d83772d9344f95eb731f1f2aa8c`.

| Finding / Guard | Fix / Preservation | Citation |
| --- | --- | --- |
| Package imports `consultation_v2.drivers.base` | Absent by design. Driver lifecycle base is copied into package-local `_PerplexityInlineBase`; old driver path is a compatibility shim. | `consultation_v2/platforms/perplexity/driver.py:49`, `consultation_v2/drivers/perplexity.py:3` |
| Package imports `consultation_v2.completion` | Absent by design. Completion detector is copied into package monitor as `PerplexityCompletionDetector`. | `consultation_v2/platforms/perplexity/monitor.py:48` |
| Out-of-package inheritance | Absent by design. `PerplexityConsultationDriver` inherits only package-local `_PerplexityInlineBase`. | `consultation_v2/platforms/perplexity/driver.py:2859` |
| Package entry contract rejects prompt echo | Preserved and made lint-visible. Package `run()` invokes `reject_prompt_echo_response` after monitor/extract delivery before returning `result`. | `consultation_v2/platforms/perplexity/driver.py:2836` |
| Prompt echo guard on response assignment | Preserved. `set_response_text_if_not_prompt_echo` calls `reject_prompt_echo_response` before assigning `result.response_text`. | `consultation_v2/platforms/perplexity/driver.py:2435`, `consultation_v2/platforms/perplexity/driver.py:2468` |
| Known Perplexity Deep Research `copy_button` duplicate | Fixed in package YAML. `copy_button` is no longer an exact-name global match; it is a `name_agnostic_structural` push-button locator bounded by `copy_query_button` and `share_button` with `ordinal: first`, so duplicate exact `Copy` labels do not trip drift guard for the response copy action. | `consultation_v2/platforms/perplexity/perplexity.yaml:240` |
| Structural ordinal is runtime-effective | Preserved by narrow shared matcher extension. `_select_structural_between` now honors `index`/`ordinal` inside the bounded candidate set and preserves prior midpoint behavior when neither is supplied. | `consultation_v2/snapshot.py:523` |
| Perplexity YAML package ownership | Preserved by move. Loader resolves package YAML for Perplexity and the moved file still declares `platform: perplexity`. | `consultation_v2/platforms/perplexity/perplexity.yaml:1` |
| Orchestrator routes to package driver | Preserved. Perplexity registry imports `PerplexityConsultationDriver` from the package driver. | `consultation_v2/orchestrator.py:35` |
| Legacy import compatibility | Preserved. `consultation_v2.drivers.perplexity` exports the package-owned driver for older importers. | `consultation_v2/drivers/perplexity.py:3` |
| Idempotent send / duplicate-send guard | Preserved. Perplexity setup still delegates irreversible send through `guarded_send`, which checks durable run-state and checkpoints only proven sends. | `consultation_v2/platforms/perplexity/driver.py:1856`, `consultation_v2/platforms/perplexity/driver.py:2943` |
| Stop-button completion oracle | Preserved. `PerplexityCompletionDetector.observe()` only completes after stop was seen and then absent for the required debounce cycles; there is no content-freeze completion path. | `consultation_v2/platforms/perplexity/monitor.py:64`, `consultation_v2/platforms/perplexity/monitor.py:84` |
| Deep-mode debounce and floor | Preserved. Deep modes require two stop-gone cycles and the driver retains the 1800-second floor for deep generation monitoring. | `consultation_v2/platforms/perplexity/monitor.py:63`, `consultation_v2/platforms/perplexity/driver.py:27` |
| Starved AT-SPI read is not completion | Preserved. Reads below the healthy raw-count floor are skipped instead of counted as stop-absent completion. | `consultation_v2/platforms/perplexity/driver.py:39`, `consultation_v2/platforms/perplexity/driver.py:2679` |
| Generation stalled is loud | Preserved. A visible stop button after the effective timeout records `generation_stalled` when the stop condition is configured. | `consultation_v2/platforms/perplexity/driver.py:2744` |
| Answer-thread proof | Preserved. Perplexity refuses monitor/extract unless it is on a captured answer thread. | `consultation_v2/platforms/perplexity/driver.py:3623` |
| Deep Research extraction uses report copy path first | Preserved. Deep Research requests extract through the report path and use `copy_contents_button` when the report artifact is available. | `consultation_v2/platforms/perplexity/driver.py:3716`, `consultation_v2/platforms/perplexity/perplexity.yaml:381` |
| Leaf isolation lint covers routing core | Fixed. `consultation_v2/platforms/_routing_core.py` is now included in `LEAF_MODULES`, so platform-branch drift there is scanned. | `consultation_v2/validators/lint_platform_independence.py:40` |

## Verification Commands

```text
python3 -m py_compile consultation_v2/platforms/perplexity/driver.py consultation_v2/platforms/perplexity/monitor.py consultation_v2/drivers/perplexity.py consultation_v2/orchestrator.py consultation_v2/snapshot.py consultation_v2/validators/lint_platform_independence.py
python3 consultation_v2/validators/lint_platform_independence.py --all
python3 consultation_v2/validators/lint_platform_independence.py --self-test
python3 consultation_v2/validators/lint_consultation_v2_contract.py --all
python3 consultation_v2/validators/lint_exact_match.py
python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all
python3 - <<'SMOKE'
from consultation_v2.yaml_contract import load_platform_yaml
cfg = load_platform_yaml('perplexity')
print(cfg['platform'])
print(cfg['tree']['element_map']['copy_button']['structural']['ordinal'])
SMOKE
```

Observed local results: py_compile exited 0; platform isolation lint CLEAN with 5 package(s), 12 leaf module(s), 0 findings; platform isolation self-test PASS; contract lint CLEAN with 52 file(s), 0 findings; exact-match lint PASS with 7 file(s), 0 loose matchers; YAML silent fallback gate CLEAN with 52 file(s), 0 findings; YAML loader smoke printed `perplexity` and `first`; structural ordinal/index smoke printed `first second second`.

Unknown: no live Perplexity browser consultation was run from this peer worktree. Production consultation/observation remains the CONTROL gate.
