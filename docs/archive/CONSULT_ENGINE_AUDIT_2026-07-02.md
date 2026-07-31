# consultation_v2 engine audit — 2026-07-02 (taeys-hands, Jesse-directed)

Engine @ main c268625a. Graded against CONSULTATION_CONTRACT.md by 5 adversarial read-audits; each finding below VERIFIED at the cited file:line by taeys-hands (grep/read), NOT taken on the agent's word. NO tests run — read + static analysis only. Mechanical layer clean first: all 5 YAMLs × 3 lints PASS, all modules py_compile OK. The findings are behavioral contract-violations the lints don't catch.

Fixes go through conductor/codex (producer≠merge-verifier; taeys-hands does not write engine code). Then production-validate.

## CRITICAL
1. **Silent `matches[0]` pick on N>1 — no drift** (contract enforcement §1 literally bans this). `types.py:187-195` `first()`=`items[0] if items`, `last()`=sorted[-1]; `base.py:81-85` delegate; no N>1/count/drift guard anywhere (verified: fairness grep found none). Ambiguous exact-match (two live "Copy", stale-vs-fresh mid-transition) → silently clicks first-in-walk instead of drift→notify. Clicked at base.py:919/1061/2200.
2. **Notify has NO delivery-ACK; RPUSH-length treated as "delivered"** (contract: "surfaced requires delivery-ACK; notify-into-void forbidden"). `notify.py:63-69` `delivered=bool(rpush length)`. `notification_ack_missing` stop-condition is enum-only, zero logic refs (verified). Dead requester → result is an unconsumed Redis entry reported as full success; teardown clears run-state.
3. **Idempotency quarantine declared but UNWIRED** (contract: never replay a possibly-landed send). `side_effect_uncertain`/`duplicate_send_risk` are enum-only (verified: only in stop_conditions.py + doc refs). `base.py:1868-1903` guarded_send calls send_prompt (irreversible Enter) with no try/except; `submitted` checkpoint written ONLY after success+URL. On a send-landed false-negative (documented failure mode) the last durable state is `setup_complete` ∉ landed-states → re-run RE-SENDS = duplicate irreversible turn.

## HIGH
4. **Substring/word-containment match on the model-selector's dynamic name → can silently skip selection → WRONG MODEL** (contract bans substring match + "don't match the dynamic model-picker name"). `base.py:1591-1604` `_selection_label_matches_any` = space-padded `in`; `base.py:846-865` a positive match short-circuits to "already active" without opening the picker. Scenario: request Opus, Sonnet active, candidate label "Claude" ∈ "Claude Sonnet 4.5" → skips → runs on Sonnet reporting Opus.
5. **Settle-window cap is lint-only; production loader does NOT enforce it** (contract: loader is the real gate). `MAX_GLOBAL_SETTLE_MS=8000` only in lint_consultation_v2_contract.py:20/143 (verified). `yaml_contract.py` load path never inspects `settle`. Hand-edited `settle: {default_ms:300000}` loads clean → perplexity.py:136 uses 300s unclamped = the "settle=5min to mask drift" loophole open on prod.
6. **No `DeadSessionError` — session id not poisoned after notify** (contract enforcement §3). Absent repo-wide (verified). Caller retry can re-drive a notified/halted session; compounds #3.
7. **Notify-failure path: no durable local log / retry / secondary channel; parked state is Redis-only** (contract requires all four). `orchestrator.py:556-583` park → Redis; `notify.py` single RPUSH no retry. When Redis is the outage, the miss survives only as an stderr log line.
8. **claude.py artifact extract uses BLIND absolute/ratio COORDINATES** (contract: AT-SPI-invisible control = OUT OF SCOPE, no coord/vision fallback; not a documented exception). `claude.py:1719-1742` (1300,450 + ratio points) → click_at → ctrl+a/ctrl+c → returns whatever's under cursor as the deliverable.
9. **claude.py hardcoded copy-button NAME list OR'd into locator** — `_ARTIFACT_COPY_NAMES` (claude.py:113-119) `or name in ...` at 1712; YAML can't govern; masks drift.

## MEDIUM
10. **`selection_ms` uncapped, escapes BOTH lint and loader** — gemini.yaml:258/grok.yaml:247; consumed base.py:1401 no clamp. `selection_ms:300000` = 300s selection settle passes everything.
11. **generation_stalled watchdog NOT declared in any YAML** (contract Gatekeeper item 1: per-YAML `generation_timeout`, else infinite Stop-present hang has no mapped exit). Verified absent from all 5 YAMLs. **This is the root of the 9-min silent grok hang I hit 2026-07-02** — no mapped stall state → the no-fallback model has no exit.
12. **gemini.py hardcoded interim/UI text substring-matched** — `GEMINI_DEEP_THINK_INTERIM_MARKERS`/`UI_TEXT` (gemini.py:14-32), `marker in lowered_text` (618-620). This IS the current dt-ack impl; conductor's own steer was "content-based gating beats enumerating interim banners" — so the merged fix is the banner-list approach the contract + conductor wanted to move past. Wording change → dt-ack misfires.
13. **chatgpt.py+claude.py hardcoded chip-name + fuzzy term-lists for attach verification** — chatgpt.py:20-28/696-728, claude.py:21-28/187-221/159-162. grok/gemini/perplexity verify attach via YAML specs; chatgpt/claude use hardcoded heuristics (a send gate on stale literals).
14. **base-surface conformance proceeds on unmapped extra interactive elements** (logs `tree_conformance_drift` True + proceeds) — base.py:155-168. Softening, not operate-on-unknown (per-step location still exact), but the one base gate that doesn't fail-closed on unmapped state.

## LOW / notes
15. chatgpt.py:572 hardcoded `ctrl+shift+o` (ChatGPT New-chat accelerator) — app-specific key in driver.
16. claude.py content markers incl. document-specific `# JESSE`/`Version: 4.0` (claude.py:35-97) — brittle, belongs in config.
17. per-driver hardcoded answer-thread URL shapes (`/c/`, `/app/`, `/search/`, host sets) — platform knowledge in code not YAML `urls`.
18. `selected_name_prefix` active-recognition = name-prefix heuristic (base.py:1416) — declared per-YAML, bounded.
19. `_has_wildcard` (yaml_contract.py:299) rejects only glob chars not regex metachars — harmless under equality matching.
20. SIGALRM store-bound is main-thread-only (storage_policy.py:128-149) — degrades to fail-fast not hang; portability note.

## SAFE (verified, honest credit)
- matches_spec exact-only + rejects forbidden matcher grammar (name_contains/regex/fuzzy) AT THE LOADER (yaml_contract.py:486 _validate_global_exactness), not just the lint.
- validation_passes fails CLOSED (unknown key/best_effort/url_contains/empty-tree → False).
- No mode/model downgrade-on-failure; no action-retry on miss; store default-OFF + store fail-loud (ISMAIngestError); resume-from-URL correct (navigate not re-send) for the landed-send case it covers.
- No cross-driver imports. grok.py + perplexity.py essentially clean (all lookups via cfg/element_map).

## COMPLETION/MONITOR (agent B — verified; also CONFIRMS the 2 recently-merged fixes hold)
H1. **ChatGPT + Claude gate completion on the Copy button (POSITIVE marker) — the exact thing the contract REJECTS** (:39). chatgpt.py:1500 `verified=... and complete_signal_seen` (complete_signal=`copy_button` via _complete_keys), gate at :1414; claude.py:1138 `verified=... and _monitor_response_rendered` where `_monitor_response_rendered = snapshot.has('copy_button')`. On a LONG response the copy button virtualizes out of the tree (documented: feedback_manual_driver_extract_recovery) → stop-gone but copy absent → verified=False → polls to timeout → FALSE-FAIL on a completed response (no scroll-scan for copy in the monitor). grok/gemini/perplexity are clean (stop_absent only). HIGH.
H2. **No mapped exception-state check at the completion boundary anywhere** (:40 — complete = stop-gone AND no mapped exception; rate_limited/content_filter/auth_wall/etc). grep of drivers+YAMLs for rate_limit/content_filter/auth_wall/etc = NOTHING. A rate-limit/filter/disconnect that removes Stop mid-stream → COMPLETE → extracts partial/error banner as the answer = FALSE-COMPLETE delivered as real. Systemic (unimplemented), fires on real rate-limit/filter. MED-HIGH.
H3. **ChatGPT + Claude drop DEEP_GENERATION_FLOOR on their DEFAULT deep modes** (base+gemini apply max(timeout, 1800s) for DEEP_MODES; chatgpt.py:1439 + claude.py:1096 use raw timeout). ChatGPT default=pro_extended, Claude=extended_thinking/max (all DEEP_MODES) → a modest --timeout false-fails a healthy still-generating deep run (the p8 bug, live in these 2 overrides). MED-HIGH.
H4. **ChatGPT + Claude never emit mapped `generation_stalled`** (base+gemini do). They bound the wait (not a silent infinite stall) but report a generic miss instead of the mapped notify state. MED.
SAFE (B verified): shared CompletionDetector clean (stop-gone-transition only, no positive-marker, deep debounce=2, the mode-read-None bug is fixed); degraded-read guard (raw_count<25 → 'unknown' not stop-gone); **gemini DT interim-ACK robustly guarded — the merged dt-ack fix cannot reintroduce the false-complete**; **grok answer-thread capture reasonably safe — the merged answer-thread fix holds (stable /c/ across 2 polls + url_changed gate)**; no unbounded waits.

---
## SUMMARY: ~14 verified contract-violations. 3 CRITICAL (silent matches[0]; notify-no-ACK; idempotency-quarantine-unwired), ~7 HIGH (substring model-match→wrong-model; settle-cap loader-hole; no DeadSessionError; notify-failure-no-durable-fallback; claude blind-coord + hardcoded-copy-names; chatgpt/claude copy-button completion gate), ~5 MED (selection_ms uncapped; generation_stalled unwired in YAMLs [=my 9-min grok hang]; gemini interim-marker substring; chatgpt/claude chip heuristics; deep-floor dropped), + lows.
The 2 fixes I recently production-validated (dt-ack, grok answer-thread) are CONFIRMED sound by the audit. grok+perplexity drivers clean. The mechanical lints pass — these are the behavioral gaps beneath them.
ROUTE: conductor→codex per 6SIGMA (root-cause shape, SIMPLIFY); taeys-hands production-validates each fix. Prioritize the 3 CRITICAL + the wrong-model + the generation_stalled (operational: caused a real hang).
