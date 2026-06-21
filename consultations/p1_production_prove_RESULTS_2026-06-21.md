# consult-v2-determinism :: p1-production-prove — RESULTS (2026-06-21)

Branch: `peer/taeys-hands-codex-contract-phase1` @ `34bf8281`
Gates: contract lint CLEAN (39 files, 0), integrity gate CLEAN (39, 0), exact-match PASS (7 YAMLs, 0 loose matchers). Working tree clean.

Production runs on the real displays (Mira :2–:6), via `scripts/run_consultation_v2.py`. No tests — production is the oracle.

## Part A — Happy-path: all 5 platforms drive end-to-end and extract a real on-topic response

Each: navigate → (clean_composer) → page_ready → select → attach → prompt → send → monitor (stop-button disappearance) → extract → store. The only non-green step on each run is `notification_parked` — an artifact of the validation harness passing no `--requester`, NOT a flow failure.

| Platform | display | mode | ok | extracted chars | non-notify failures |
|---|---|---|---|---|---|
| Grok | :5 | heavy | True | 2,676 | NONE |
| Claude | :3 | extended_thinking | True | 2,923 | NONE |
| ChatGPT | :2 | pro | True | 1,682 | NONE |
| Perplexity | :6 | deep_research (full report-card) | True | 21,602 | NONE |
| Gemini | :4 | deep_think | True | 2,909 | NONE |

Perplexity note: a substantive prompt renders the full Deep-Research **report-card** → extracted via `copy_contents_button` ("Copy contents", 21.6 KB). A trivial ask instead renders a normal-answer bubble (bottom "Copy"); the engine correctly **fails loud** (drift → notify) rather than silently extracting the wrong control — see Part B. Real consults are substantive, so the report-card path is the production path.

## Part B — Oracle test: wrong YAML name → HALT + NOTIFY with candidates, never silently proceed or downgrade

Method: temporarily set one element's `name:` to a bogus value, run, observe; restore via `git checkout` (tree clean after each).

**Grok** — broke `model_heavy` name, ran `--select model=heavy`:
- steps reached: navigate → page_ready → select → **HALT** (`notify_operator_failure`).
- did NOT reach attach/send. `ok=False`.
- HALT msg: "grok selection expected element model_heavy missing after menu open"; candidates captured (`model_auto`, `model_expert`, `model_fast` …).
- **No downgrade**: `model_auto`/`model_expert` were present in the candidate snapshot; the engine refused to silently select one.

**ChatGPT** (different, more complex selection driver) — broke `model_instant` name, ran `--select model=instant`:
- steps reached: navigate → clean_composer → page_ready → select → **HALT** (`notify_operator_failure`).
- did NOT reach prompt/attach/send. `ok=False`.
- HALT msg: "chatgpt selection expected element model_instant missing after menu open"; candidates captured (`model_medium`, `model_high`, `model_pro` …).
- **No downgrade**.

The halt-on-drift / notify-with-candidates / no-downgrade behavior is the **shared** `base.py` match-or-notify path; proven on two structurally different selection drivers. Combined with the static contract gate (no banned matchers anywhere) and the happy-path 5/5 (each platform's elements matched exactly), this establishes the determinism invariant across the engine.

### Scope note (no silent cap)
The Oracle runtime proof was run on 2 of 5 platforms (Grok simple menu + ChatGPT complex menu). The remaining 3 share the identical `base.py` selection/match-or-notify code path (driver isolation enforced; happy-path 5/5 confirms each routes through it) and pass the static exact-match gate. A per-platform Oracle sweep across all 5 can be added if the merge gate requires it.

## Fixes that landed this session (all on the branch)
- `e00a7584` — Perplexity `input` re-anchored `before: attach_trigger` (was `before: submit_button`, which is absent on an empty composer → page_ready could never resolve the nameless composer).
- `fca0f1af` (codex) — page_ready limited to composer interaction controls (was importing the full base-surface key set incl. sidebar nav, which ChatGPT's snapshot scope excludes).
- `34bf8281` — ChatGPT conformance `base.expected` reconciled to the 8 controls that survive the snapshot `exclude` rules (was demanding 13 sidebar-nav keys that `exclude.roles` prunes).
- `f2b06a38` (codex) — Gemini `extra_extract` made Deep-Research-only optional (Deep Think has no Share&Export surface).
- `7f7c9e8b` — Gemini `mode_picker` anchored `after: input` (name changes with selected model).
