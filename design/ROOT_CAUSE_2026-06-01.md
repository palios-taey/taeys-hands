# Root cause of the 5-chat dispatch instability — 2026-06-01

Established empirically tonight via live production runs + AT-SPI scans. No theory.

## The meta-bug: TWO config trees, running code reads the one nobody maintains

- **Live/working path** = `scripts/consultation.py` (synchronous) → loads config via `core.config.get_platform_config` → reads **`<OPERATOR_HOME>/taeys-hands/platforms/*.yaml`** (core).
- **The "production-grade" rewrite** = `consultation_v2/cli.py` + `consultation_v2/drivers/*` → reads **`consultation_v2/platforms/*.yaml`**.
- These are **different directories with different specs.** Months of "production-grade" YAML edits went into `consultation_v2/platforms/` — which the running code never loads. And the consultation_v2 driver path itself is incomplete (proof run mapped 0/95 elements, died at mode-select).
- **Net:** the system that actually drives the chats reads `platforms/` (core); the effort to harden it edited `consultation_v2/platforms/`. Fixes didn't stick because they were applied to unused files.

## What actually works (live production runs tonight, via scripts/consultation.py)

| Platform | Result |
|---|---|
| Grok (heavy) | ✅ full loop: mode verified → attach verified → send → debounced-complete 45s → extracted 5282 chars |
| Perplexity (deep_research) | ✅ full loop: verified → generating → complete 160s → 10711 chars |
| Gemini (deep_think) | ✅ mode verified by composition → extracted 8352 chars |
| Claude (extended_thinking) | ✅ mode verified (`Model: Opus 4.8 High`) → attached → sent (on a settled page) |
| ChatGPT (pro_extended) | ❌ see below |

So **4/5 work end-to-end.** The completion-wait in `wait_for_response` ALREADY debounces (stop-absent → wait 2s → re-scan fresh tree → complete only if still absent; reappear → keep generating). The false-positive "monitor" alarms were the DEAD MCP `monitor/central.py` daemon, not this path.

## The two real bugs (for codex IMPROVE, NOT hand-edited)

1. **ChatGPT model_selector stale (HARD FAIL).** `platforms/chatgpt.yaml` has `model_selector: {name: 'Switch model', role: 'push button'}`. ChatGPT removed that element; the model/mode selector now lives in the composer as `[push button] 'Extended Pro'` (label is DYNAMIC — reflects current model+mode, so an exact-name match is fragile; needs a stable locator strategy, e.g. role+position in composer or the stable aria pattern). Fix in `platforms/chatgpt.yaml`.

2. **Cold-start timing race (INTERMITTENT).** Mode-selection scans for `model_selector` immediately after navigation; if the composer hasn't settled into the AT-SPI tree yet, it reports "not found" and HALTs. Claude failed this way in the parallel cold batch, then passed on a settled page. Fix: a settle-wait / retry-until-present (temporal quiescence) on the model_selector lookup before HALT — small, in the mode-selection path (`core/mode_select.py` / `tools/mode_select.py`).

## Decision implied by the evidence
The working sync path (`scripts/consultation.py` + `platforms/` core config) is the thing to FINISH and harden — not the `consultation_v2/` rewrite (which the running code doesn't use and which is incomplete). Either delete/quarantine `consultation_v2/` or make `core.config` the single source — but stop maintaining two trees. Cosmos's WebExtension-sensor idea is optional future work; it is NOT required to reach 5/5 — 4/5 already work and ChatGPT is one config fix away.

## Mode keys (verified live, for the fleet)
gemini=`deep_think`, grok=`heavy`, perplexity=`deep_research`, claude=`extended_thinking`, chatgpt=`pro_extended`.
Invocation (no MCP): `DISPLAY=:N python3 scripts/consultation.py --platform X --mode <key> [--attach F] --message "..." --requester <node>` → blocks → extracts → notifies requester.
