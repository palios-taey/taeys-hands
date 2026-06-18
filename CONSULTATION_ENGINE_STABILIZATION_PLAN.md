# Project: consult-engine-stz - Consultation Engine Stabilization → Release
> Make consultation_v2 stable per the rules so it can be released to every fleet instance to operate autonomously: full model/mode/submenu selection coverage on all 5 platforms, reliable send/monitor/extract, every defect filed as a GitHub Issue, gated by a no-tests production sweep. Supervisor: taeys-hands (self). Builder: taeys-hands-codex. CONTROL/merge: conductor.

## Phase: p1-issues - File all production-observed defects as GitHub Issues [order: 1] [ref: 100_TIMES.md:1-40]
<!-- Global non-negotiable rules (plain text so the ref-parser does not try to resolve them):
NO TESTS EVER (production consults or live AT-SPI audit only; see 100_TIMES.md).
IDLE CHAT = AUDIT the implementation until perfect (see CLAUDE.md).
OBSERVER-ONLY on code/YAML: scan -> document -> GitHub Issue -> route to codex; conductor merges (CLAUDE.md).
SEQUENTIAL dispatch, monitors concurrent; STOP BUTTON = completion (exact AT-SPI name); verify real end-state not flags; first error = full stop + 6SIGMA (CONSULTATION_CONTRACT.md, 100_TIMES.md). -->

### Task: p1-t1 - ChatGPT send-robustness (issue #154, corrected): YAML is correct; focus+Enter retry before send=False [priority: 88] [owner: taeys-hands] [ref: consultation_v2/platforms/chatgpt.yaml:1-60] [ref: 100_TIMES.md:1-40]

### Task: p1-t2 - Perplexity DR mode-select FP/FN (issue #155) — driver logic; fixed by e7c4374 [priority: 86] [owner: taeys-hands] [ref: consultation_v2/drivers/perplexity.py:1-120] [ref: consultation_v2/platforms/perplexity.yaml:1-60]

### Task: p1-t3 - Perplexity attach false-negative (issue #156) — fixed by e7c4374 [priority: 80] [owner: taeys-hands] [ref: consultation_v2/drivers/base.py:1-176] [ref: consultation_v2/drivers/perplexity.py:120-240]

### Task: p1-t4 - Perplexity Submit no-op (issue #157) — fixed by b86c230/2aa8b6e [priority: 78] [owner: taeys-hands] [ref: consultation_v2/drivers/perplexity.py:240-360] [ref: 100_TIMES.md:1-40]

### Task: p1-t5 - Perplexity DR extract empty (issue #158) — fixed by e7c4374 (Copy-contents path) [priority: 78] [owner: taeys-hands] [ref: consultation_v2/drivers/perplexity.py:360-520] [ref: CONSULTATION_CONTRACT.md:1-56]

### Task: p1-t6 - p2 selection-coverage gaps (issue #160): Claude name_contains+effort+model; Gemini deep_think; Grok schema [priority: 75] [owner: taeys-hands] [ref: consultation_v2/platforms/claude.yaml:1-180] [ref: CONSULTATION_CONTRACT.md:1-56]

## Phase: p2-audit - Per-platform implementation audit: full model/mode/submenu selection coverage [order: 2] [depends: p1-t1] [ref: CONSULTATION_CONTRACT.md:1-56]

### Task: p2-chatgpt - ChatGPT selectors audited vs YAML — DONE, full coverage confirmed [priority: 70] [owner: taeys-hands] [ref: consultation_v2/platforms/chatgpt.yaml:1-326]

### Task: p2-claude - Claude effort-submenu + exact copy matcher + 4th model (issue #160 / task #170) [priority: 70] [owner: taeys-hands] [ref: consultation_v2/platforms/claude.yaml:1-252]

### Task: p2-gemini - Gemini Deep Think driver wiring (f801471) or mark unsupported (issue #160) [priority: 70] [owner: taeys-hands] [ref: consultation_v2/platforms/gemini.yaml:1-261]

### Task: p2-grok - Grok normalize mode_targets under workflow.selection + add model_targets (issue #160) [priority: 68] [owner: taeys-hands] [ref: consultation_v2/platforms/grok.yaml:1-292]

### Task: p2-perplexity - Perplexity selectors audited — YAML correct; driver fixes in e7c4374 [priority: 68] [owner: taeys-hands] [depends: p1-t2] [ref: consultation_v2/platforms/perplexity.yaml:1-352]

## Phase: p3-fix - Builder fixes + CONTROL merge [order: 3] [depends: p2-perplexity] [ref: CLAUDE.md:1-60]

### Task: p3-merge - Conductor verifies + merges peer/taeys-hands-codex-perplexity-submit-scope (e7c4374) + #154/#160 fixes [priority: 85] [owner: conductor] [ref: CLAUDE.md:1-60]

## Phase: p4-gate - No-tests production sweep: one clean autonomous cycle per platform [order: 4] [depends: p3-merge] [ref: CONSULTATION_CONTRACT.md:1-56]

### Task: p4-sweep - Clean unattended full-cycle on all 5 (submitted URL + Stop seen/gone + extract + notify ACK + storage), ZERO manual intervention, NO TESTS [priority: 95] [owner: taeys-hands] [ref: FLOW_CONSULTATION_ENGINE.md:1-60] [ref: CONSULTATION_CONTRACT.md:1-56]

### Task: p4-concurrency - Concurrency run: sequential sends, monitors simultaneous, independent completions while later sends in flight [priority: 90] [owner: taeys-hands] [depends: p4-sweep] [ref: 100_TIMES.md:1-40]

## Phase: p5-release - Release to fleet instances [order: 5] [depends: p4-concurrency] [ref: FLOW_CONSULTATION_ENGINE.md:1-60]

### Task: p5-docs - Confirm FLOW + CONTRACT + 100_TIMES let an instance run hands-off from docs alone [priority: 80] [owner: taeys-hands] [ref: FLOW_CONSULTATION_ENGINE.md:1-740] [ref: CONSULTATION_CONTRACT.md:1-56]

### Task: p5-go - Go/no-go: engine perfect on all 5 (full model/mode/submenu selection + send/monitor/extract), all issues closed, gate evidence on record [priority: 99] [owner: taeys-hands] [depends: p5-docs] [ref: CLAUDE.md:1-60]

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
