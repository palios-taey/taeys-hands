# Consult-engine completion-MONITOR audit — 2026-07-01 (taeys-hands)

**Verdict:** the completion monitor is UNRELIABLE across long-running modes (DR / Deep Think / Pro-ET / Heavy). It worked for months, so this is a REGRESSION — root-cause the breaking change, do not patch around it. Jesse-directed P0. NO TESTS — a real production consult on the actual displays is the only oracle.

## Observed failure modes (all this session, real dispatches)
1. **Wrong-thread navigation (Grok, ×2 — 2026-07-01):** monitor step `monitor_answer_thread` = "grok monitor re-navigated to pinned answer thread" but landed on a STALE thread (`grok.com/c/3292e25e`, an unrelated old chat), while the real send created `grok.com/c/9638a060`. Then `extract` failed ("Copy button did not appear"). The real answer was intact on the fresh thread; the monitor pinned/navigated to the wrong one.
2. **False-FAIL (Gemini DR + earlier brand/cross/jobs DR):** monitor = "gemini monitor lost pinned answer thread" / perplexity "not on an answer thread; refusing extract from home" → engine declared FAILED, while the Deep Research actually COMPLETED and persisted at its own thread URL. Every one had to be hand-harvested from the thread.
3. **False-COMPLETE (Gemini Deep Think, 2026-07-01):** monitor declared COMPLETE and the engine auto-extracted + auto-delivered an **80-char interim ACK** ("I'm on it. Responses with Deep Think can take some time, so check back in a bit.") as the answer. Real DT answer was still generating.

## Code state (Observed)
- `consultation_v2/completion.py` (stop-transition detector) — logic is SOUND in isolation: sticky `ever_seen_stop`, present→gone TRANSITION debounced `required_stop_cycles` (deep modes=2), NO content-freeze heuristic (the old content_stable false-complete regression from 23562ae/329384b was already fixed, #145). So the pure stop-button detector is not the current bug.
- **`consultation_v2/drivers/base.py` answer-thread pinning — introduced by commit `e132bf15` "Pin monitor to submitted answer thread" (Jesse, 2026-06-22, +93 lines base.py, cherry-pick of 345ddd21).** This is the PRIME REGRESSION SUSPECT for failure modes 1 & 2: the pin/re-navigate logic resolves the WRONG thread (stale) on grok, and "loses" the thread on gemini/perplexity DR → false-fail. Pre-e132bf15 the monitor watched the current thread and (per Jesse) worked for months.
- Deep-Think two-phase lifecycle vs the transition detector (failure mode 3): DT emits an interim ACK ("I'm on it") with the stop button briefly present then GONE, THEN starts real generation (stop reappears). The single present→gone transition fires COMPLETE on the ACK phase. `37bd3485` added `DEEP_GENERATION_FLOOR_SECONDS` / `generation_stalled` — verify it is actually wired to gate DT ack-phase completion; tonight it did NOT save the DT case.
- Most-recent monitor change: `2ef15351` "fix(consult-monitor): root-cause false generation_stalled — thread mode + gate stop-absence on healthy read (#4)" — confirm it did not further entangle the answer-thread coupling.

## Regression window (Inferred)
"Worked for months" → the break is after that. Candidate window centers on `e132bf15` (2026-06-22, answer-thread pinning) and the per-mode-timeout / generation_stalled changes (`37bd3485`, `2ef15351`). A `git bisect` / GitNexus archaeology against a real DR/DT consult (the oracle) should pin the exact breaking commit before any fix.

## Fix direction (root-cause, SIMPLIFY — for the implementer, not prescriptive)
- Answer-thread handling: the send already captures the real thread URL (`session_url_after` / the new-chat URL at send validation). The monitor should watch/extract from THAT captured URL and never "re-navigate to a pinned thread" that can resolve stale. Prefer removing/replacing the pin-and-renavigate with "stay on the thread the send created" — that is the simpler shape that worked before.
- DT/ack completion: do not honor the first stop-gone until real generation has demonstrably started (e.g., generation floor actually enforced for deep_think, or require the answer thread to show post-ack content), so an 80-char interim ACK can never be extracted as COMPLETE. Keep the stop-button-only oracle; just don't let the ACK phase's stop-gone count.

## Constraints
- NO TESTS. Validate ONLY by a real production consult on the live displays (DR + Deep Think + Pro-ET + Heavy), confirming: send lands → monitor tracks the correct thread → completes on the REAL answer (multi-KB, not an ack) → extracts it. Producer (taeys-hands) runs the production validation; Conductor verifies + merges (producer ≠ merge-verifier).
- Engine code changes go through the peer fleet (codex) + Conductor, not taeys-hands directly.
