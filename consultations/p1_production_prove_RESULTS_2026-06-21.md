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

Per-platform sweep — each platform had ONE selection-target element name broken, then a run, then `git checkout` restore (tree clean after each). Every one HALTED at `select` with `notify_operator_failure`, never reached send, never downgraded:

| Platform | broken element | HALT message | reached send? | downgraded? |
|---|---|---|---|---|
| Grok | `model_heavy` | "grok selection expected element model_heavy missing after menu open" | No | No (model_auto/expert present, refused) |
| ChatGPT | `model_instant` | "chatgpt selection expected element model_instant missing after menu open" | No | No (model_medium/high/pro present, refused) |
| Claude | `model_opus` | "claude selection expected element model_opus missing after menu open" | No | No |
| Gemini | `tool_deep_research` | "gemini selection expected element tool_deep_research missing after menu open" (after model select passed) | No | No |
| Perplexity | `deep_research` | "perplexity mode=deep_research did not expose active element after bounded settle-rescan" | No | No |

The halt-on-drift / notify-with-candidates / no-downgrade behavior is the **shared** `base.py` match-or-notify path, now proven on all 5 platforms across structurally different selection drivers (simple menu, hover-path menu, More-tools flyout, search-mode trigger). Perplexity's message confirms the contract's settle+rescan-ONCE-then-halt window. Combined with the static contract gate (no banned matchers anywhere) and the happy-path 5/5, the determinism invariant is established per-platform across the engine.

## Fixes that landed this session (all on the branch)
- `e00a7584` — Perplexity `input` re-anchored `before: attach_trigger` (was `before: submit_button`, which is absent on an empty composer → page_ready could never resolve the nameless composer).
- `fca0f1af` (codex) — page_ready limited to composer interaction controls (was importing the full base-surface key set incl. sidebar nav, which ChatGPT's snapshot scope excludes).
- `34bf8281` — ChatGPT conformance `base.expected` reconciled to the 8 controls that survive the snapshot `exclude` rules (was demanding 13 sidebar-nav keys that `exclude.roles` prunes).
- `f2b06a38` (codex) — Gemini `extra_extract` made Deep-Research-only optional (Deep Think has no Share&Export surface).
- `7f7c9e8b` — Gemini `mode_picker` anchored `after: input` (name changes with selected model).
