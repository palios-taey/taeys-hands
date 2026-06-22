# Project: consult-engine-stz - Consultation Engine Stabilization → Release
> Make consultation_v2 production-reliable so every fleet instance runs it hands-off — natively handling the NORMAL behavior of these platforms (long generations, multi-path Perplexity DR extraction, Gemini DR two-step) WITHOUT a human manual-fallback. Base: current main (determinism line). Builder: taeys-hands-codex. Production validation: taeys-hands on the real 5 displays with REAL long-DR prompts (no toy prompts, no tests). Gate/merge: taeys-hands' own fleet (grok adversarial + gemini structural, r5) — NOT conductor (Jesse standing instruction). Superseded: the old p1-issues/#154-#160 + p2-audit/p3-merge tasks were framed on the 7-month-divergent tree-conformance line and are obsoleted by today's determinism main bfba7d38; the only real remaining work is the 3 core fixes below (root-caused 2026-06-22 from the p8 audit, where 3/5 lanes needed manual recovery).

<!-- Non-negotiable rules (plain text, not refs): NO TESTS EVER — production consults / live AT-SPI only. STOP BUTTON = completion (exact AT-SPI name). Verify real end-state, not flags. First error = full stop + 6SIGMA root-cause (simplify, never patch-around). Root-cause spec for all 3 fixes: consultations/stz_core_fixes_2026-06-22.md. -->

## Phase: f1-monitor - Monitor: progress/stall-aware, not flat-timeout [order: 1] [ref: consultations/stz_core_fixes_2026-06-22.md:1-40]

### Task: f1-build - codex: make monitor_generation progress/stall-aware — keep waiting while stop_present AND response growing; fail only on generation_stalled (wire the dead stop_conditions.py); completion stays stop-gone-only [priority: 10] [owner: taeys-hands-codex] [ref: consultation_v2/drivers/base.py:1899-1978] [ref: consultation_v2/completion.py:1-100]

### Task: f1-validate - taeys-hands: production-validate F1 with a REAL multi-minute DR/Pro-Extended run that exceeds the old flat timeout — confirm it COMPLETES (not false-fails) and a true stall NOTIFIES; my-fleet r5 + merge to main [priority: 12] [owner: taeys-hands] [depends: f1-build] [ref: consultations/stz_core_fixes_2026-06-22.md:1-40]

## Phase: f2-px-extract - Perplexity DR extraction: multi-path mapped states [order: 2] [ref: consultations/stz_core_fixes_2026-06-22.md:1-40]

### Task: f2-build - codex: Perplexity extract_primary — stop hardcoding copy_contents_button for DR; enumerate mapped DR output states (report-card copy_contents / inline copy_button / Download / report-tree) and extract via the one present [priority: 20] [owner: taeys-hands-codex] [ref: consultation_v2/drivers/perplexity.py:700-840]

### Task: f2-validate - taeys-hands: validate BOTH the inline-answer and report-card DR shapes extract full content (the p8 failure was the inline shape); my-fleet r5 + merge [priority: 22] [owner: taeys-hands] [depends: f2-build] [ref: consultations/stz_core_fixes_2026-06-22.md:1-40]

## Phase: f3-gemini-dr - Gemini DR two-step + full-report extract [order: 3] [ref: consultations/stz_core_fixes_2026-06-22.md:1-40]

### Task: f3-build - codex: Gemini DR — click start_research via atspi_only + validate research ACTUALLY started (not stop+url); make Share&Export popover visible so menu_snapshot resolves copy_content_item (raw do_action got 22814ch vs 89ch stub) [priority: 20] [owner: taeys-hands-codex] [ref: consultation_v2/drivers/gemini.py:200-340]

### Task: f3-validate - taeys-hands: validate native plan→Start-research two-step + FULL-report extract (not the 89-char stub) on a real Gemini DR; my-fleet r5 + merge [priority: 22] [owner: taeys-hands] [depends: f3-build] [ref: consultations/stz_core_fixes_2026-06-22.md:1-40]

## Phase: f4-sweep - Real-prompt all-5 unattended sweep [order: 4] [ref: CONSULTATION_CONTRACT.md:1-56]

### Task: f4-sweep - taeys-hands: one clean unattended all-5 cycle with REAL long-DR prompts (submitted URL + Stop seen/gone + correct extract + requester delivery), ZERO manual intervention — the bar that the p8 audit failed [priority: 40] [owner: taeys-hands] [depends: f1-validate] [depends: f2-validate] [depends: f3-validate] [ref: FLOW_CONSULTATION_ENGINE.md:1-60] [ref: CONSULTATION_CONTRACT.md:1-56]

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
