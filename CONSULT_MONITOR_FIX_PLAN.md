# Project: consult-monitor-fix - Consult-engine completion-monitor regression fix
> P0, Jesse-directed 2026-07-01. The completion monitor false-completes (DT interim-ACK), false-fails (DR answer-thread-lost), and mis-navigates (grok wrong/stale thread). It worked for months → REGRESSION, root-cause the breaking change. NO TESTS — a real production consult on the live displays is the only oracle. Engine code changes go through the peer fleet (codex) + Conductor; taeys-hands audits + runs production validation.

## Phase: p1-audit - Pin the regression [order: 1]

### Task: bisect-regression - git bisect / GitNexus archaeology against a REAL DR/DT consult to pin the exact commit that broke monitor reliability; confirm or refute the two suspects (e132bf15 "Pin monitor to submitted answer thread", 2026-06-22; and the Deep-Think ack-phase completion path incl. 37bd3485/2ef15351). Deliver the breaking commit + the minimal shape that regressed. [priority: 10] [owner: codex] [ref: CONSULT_MONITOR_AUDIT_2026-07-01.md]

## Phase: p2-improve - Root-cause fix on a branch (SIMPLIFY) [order: 2]

### Task: fix-answer-thread-pin - Replace the monitor's pin-and-re-navigate with "watch/extract the thread the SEND created" (captured send URL); the monitor must never resolve or navigate to a stale/other thread. Root-cause shape = remove the coupling that regressed, not a guard around it. [priority: 10] [owner: codex] [depends: bisect-regression]

### Task: fix-dt-ack-falsecomplete - The Deep-Think two-phase lifecycle (interim "I'm on it" ACK with stop present→gone, THEN real generation) must not let the ack-phase stop-gone count as COMPLETE; an ack-length (~80 char) extract can never be a terminal answer. Keep the stop-button oracle; gate the first stop-gone until real generation has started (enforce the deep generation floor for deep_think, or require post-ack thread content). [priority: 10] [owner: codex] [depends: bisect-regression]

## Phase: p3-production - Production validation, NO TESTS [order: 3]

### Task: prod-validate - On the live displays, run one REAL consult per long mode (Perplexity DR, Gemini Deep Think, ChatGPT Pro-ET, Grok Heavy). Confirm for each: send lands → monitor tracks the CORRECT (send-created) thread → declares COMPLETE only on the real multi-KB answer (never an ack stub, never a false-fail) → extracts it. Paste the production observations (thread URL + extracted char counts) as evidence. [priority: 10] [owner: taeys-hands] [depends: fix-answer-thread-pin, fix-dt-ack-falsecomplete]

## Phase: p4-control - Conductor verify + merge [order: 4]

### Task: conductor-merge - Conductor independently verifies the production evidence and merges the fix to main (producer != merge-verifier). Closes the regression. [priority: 10] [owner: conductor] [depends: prod-validate]

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
