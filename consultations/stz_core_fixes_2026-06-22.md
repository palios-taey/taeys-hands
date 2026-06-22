# consult-engine-stz — CORE production fixes (root-caused 2026-06-22)

Base: **current main `bfba7d38`** (the determinism line — NOT the divergent tree-conformance line). Builder: taeys-hands-codex. Validation: taeys-hands on the real 5 displays with REAL long-DR prompts (not toy prompts — that's how these slipped). Gate: my fleet (grok adversarial + gemini structural) r5, then merge to main.

These are NOT edge cases (Jesse, 2026-06-22): long generations, multi-path Perplexity DR extraction, and the Gemini DR two-step are the NORMAL behavior of these platforms. The engine must handle them natively; today it relies on a human manual-fallback (proven during the p8 audit, where I hand-recovered 3 of 5 lanes).

## F1 — Monitor must be progress/stall-aware, not flat-timeout
**Root cause:** `drivers/base.py:monitor_generation` (~1899) polls the stop-transition under a **flat `request.timeout`** (`wait_until(timeout=request.timeout)` at ~1940). There is NO progress/stall distinction, and `consultation_v2/stop_conditions.py` (`generation_stalled`) is imported NOWHERE (dead code — flagged in the earlier contract audit). So a run that is still legitimately generating when the timeout expires is declared "did not reach Stop-gone completion" = FAIL. Long generations are the norm → false failures are the norm.
**Root-cause shape (not a bigger timeout):**
- While `stop_present` AND the response is **growing** (response-region char count or assistant-message subtree node count increasing across polls) → KEEP WAITING; reset the stall clock. Do not fail on elapsed time while progressing.
- Only fail when `stop_present` BUT **no progress** for a per-platform `generation_stall_window` (new YAML key; default e.g. 120s) → that is the mapped `generation_stalled` state → NOTIFY (per contract), not a silent timeout. WIRE `stop_conditions.generation_stalled` into the verdict path (kill the dead-code gap).
- Completion stays **Stop-gone-only** (`ever_seen_stop` + gone for the required cycles). Progress-growth is used ONLY to decide "keep waiting" — NEVER as a positive completion marker (100_TIMES §1 / contract). Keep a very large absolute backstop ceiling (e.g. 2h) purely to prevent a truly-wedged infinite loop.

## F2 — Perplexity DR extraction is multi-path (mapped states, not one hardcoded control)
**Root cause:** `drivers/perplexity.py:extract_primary` (~719) hardcodes `target_key = 'copy_contents_button' if is_deep_research else 'copy_button'` (~738). A DR answer that renders inline (normal-answer shape) has NO "Copy contents" → extract fails (observed in p8: recovered via `copy_button`). It also ignores the Download path and the report-tree text.
**Root-cause shape:** enumerate the DR output states and extract via the one that is actually present (mapped match-or-notify, NOT a fuzzy try-each fallback):
1. report-card present (`copy_contents_button`) → that path (full report).
2. inline answer (no report-card, `copy_button` present) → `copy_button`.
3. Download button present → download-file path (read the downloaded report).
4. last-resort: read the report region text from the tree.
Pick by which mapped control/region is actually live; validate extracted length ≫ prompt; if none → drift → notify. I will supply exact live AT-SPI names/roles for the Download control + report region on request.

## F3 — Gemini DR two-step + full-report extract (structure exists, two bugs)
**Root cause A (send):** `drivers/gemini.py:send_prompt` (~222) DOES wait for `start_research` and click it, but in p8 the post-click **send-validation failed** (`start_research_clicked=True` yet send=False). The click used `strategy='atspi_first'`; a manual `atspi_only` click on the same ready plan started the research. And the validation checks stop+url, but after Start-research the correct signal is **the real-research run actually starting** (plan card replaced by research progress / the research stop button appears).
- Fix: click `start_research` with `atspi_only` (proven), and validate that the **research actually started** (research-phase stop button present / plan card gone), not the plain stop+url.
**Root cause B (extract):** `drivers/gemini.py:extract_primary` (~289) does `share_export` → `menu_snapshot` → `copy_content_item`, but `menu_snapshot` returns `[]` for the Share&Export popover (observed in p8 — the popover items are invisible to `menu_snapshot`'s scope/roles). Result: the 89-char "I've completed your research" stub instead of the report. Raw `Atspi` `do_action(0)` on the `Copy` menu item returned the full **22,814-char** report.
- Fix: make the Share&Export popover items visible to the driver's snapshot (correct the menu_snapshot scope/role filter for this portal) OR use the interaction that works, so `copy_content_item` resolves and the FULL report is copied. Validate length ≫ stub.

## Validation (taeys-hands, the oracle) — REAL prompts only
Each fix is validated with a SUBSTANTIVE prompt that reproduces the real pattern: F1 = a long DR/Pro-Extended fetch that runs many minutes (confirm it completes, not false-fails); F2 = Perplexity DR producing BOTH an inline answer and a report-card across runs (both extract); F3 = a Gemini DR that requires plan-approval (confirm native 2-step + full-report extract, not the stub). NO toy prompts. NO synthetic tests.
