# CONSULTATION CONTRACT — the deterministic model (canonical, graded-against)

This is THE model the consultation engine must obey. Everything in the codebase is graded against this file. If code, a skill, or a memory contradicts it, they are wrong.

## The invariant: binary match-or-notify. Never guess, downgrade, or fall back.

At every step the live AT-SPI tree matches **exactly one of an enumerated set of mapped states, or none.** (Family audit keystone, 5/5: the binary is sound, but "match = the ONE happy element, any miss = drift" is too narrow — it mis-reads an error/auth/rate-limit screen as "drift" and a Stop-that-vanished-on-error as "complete." Widen "match" to the happy state **plus every reachable alternate state** — auth_wall, session_expired, rate_limited, quota, content_filter, captcha, network_stall, truncated/continue, error/retry, modal — each mapped exact with a deterministic disposition. Still fully binary: one-of-mapped vs none. Still no-guess.)
- **Matched the happy state** → proceed.
- **Matched a mapped alternate state** → take that state's deterministic disposition (e.g. rate_limited → notify-blocked; truncated → its handler). Not drift, not a guess — a known mapped state.
- **None of the mapped states** → it is drift. Settle once and re-scan (timing, below); if still none → **NOTIFY the driving session (the Claude/fleet session — there is NO human operator in the loop) and HALT that step.** The session already has the live tree + screenshots; it explores them, finds the new **exact** name/option, updates the YAML, and re-runs. Resolution is autonomous: detect → notify-self → read tree/screenshot → update YAML exact → continue. **The re-run is idempotency-guarded (REQUIRED, Gatekeeper ruling):** durable run-state checkpoints (`submitted` / `url` / `completed`) are written as the flow progresses; if drift hit AFTER a send may have landed, the re-run RESUMES from the captured chat URL and NEVER replays a possibly-landed send (`SIDE_EFFECT_UNCERTAIN` quarantine) — the autonomous loop must never introduce a duplicate irreversible turn.

**What "match" means (exact, but precise):** exactly one node by **{stable locator + role + required AT-SPI states} in the correct window scope**. (1) Locate by a STABLE key, not an intrinsically-dynamic visible name (the model-picker's name == the selected model; counters; locale) — attribute/testid or role+container-path, still exact. (2) Required states include `ENABLED`/`SENSITIVE` + `VISIBLE`: a disabled "ghost" (name+role present, not clickable) is a DISTINCT state, not a match. (3) Exact match yielding **N>1** (e.g. five "Copy" buttons) = automatic drift — disambiguate via parent/path_index in YAML. (4) Per-display isolated a11y bus = scope is exactly one window; if a bus is ever shared, the locator MUST carry a per-instance discriminator. The exhaustive per-platform state+element catalog lives in each YAML (see consultations/contract_audit_SYNTHESIS.md).

There is no third path. Specifically **BANNED** (in code and in behavior):
- No fuzzy/heuristic discovery ("looks model-ish"), no `name_contains`/`name_pattern`/substring matching for control elements.
- No downgrade (e.g. extended_thinking fails → run default). Proper mode or notify.
- No silent "proceed on miss." A miss is surfaced, never swallowed — and **"surfaced" requires delivery-ACK** (Gatekeeper item 2): the NOTIFY must be acknowledged as received by the driving session. An unacked notify is itself an error → durable local log + retry + secondary channel + a queryable **parked/needs-attention** state. A notify into the void (fleet-notify down/unacked) is a silently-swallowed miss at the single chokepoint — forbidden.
- No retrying the *action* on a miss (re-click/re-send) — that is the ban-risk + it doesn't fix drift.

## The map is finite, known, and complete

Per platform: **1 YAML + 1 driver. No overlap.** Drivers carry zero platform knowledge; they call shared primitives only (click, click-react, **hover/pointer_move**, paste, snapshot, menu_snapshot, settle). (hover/pointer_move is REQUIRED — Gatekeeper item 3: a hover-only flyout is otherwise unreachable, a notify-forever dead end no YAML edit can resolve.)

The YAML maps **everything** exact-match:
- The chat: sidebar previous-chats are filtered out; **every other element** is mapped exact — EXCEPT the response transcript: map the transcript CONTAINER (name/role), exempt its child text nodes from string validation (presence+role only), and exclude the transcript subtree from all session-driving locators. The response text is unbounded/unpredictable — it cannot be exact-mapped and must never be a control locator.
- **Every menu and submenu** (model picker, tools, attach, mode flyouts) — exact names + roles, plus each flyout's **trigger type** (click vs hover/pointer_move) and its tree-attachment point.
- The **generating** screen and the **completed** screen.
- Validation specs for each step (what persistent element proves the step succeeded).

You know where every option is, under which menu, and its exact name. Drift is the only unknown, and drift is handled by match-or-notify.

## Timing is known, not a failure

A no-match is often just the tree not refreshed yet (attach menu slow to open, React portal lag, post-click tree delay). The rule: **don't retry the action — let it settle a beat and RE-SCAN the tree**, then validate again. Only a *second* no-match (after settle+rescan) is real drift → notify. Settle windows are per-platform constants in the YAML, not guesses.

## Submit + completion are deterministic signals

- **Submit succeeded** = new URL on a new chat **AND** the Stop button appeared.
- **Generating** = Stop button present. **Complete** = Stop button gone. **This is the signal — there is no reliable positive completion indicator.** (Jesse, 7 months production: the Copy button is NOT always present on long responses; "Regenerate"/copy/etc. are unreliable. Do NOT gate completion on a positive marker — the Family audit's "require a positive completion element" recommendation is REJECTED on this ground.)
- The only thing that disambiguates a true completion from a Stop-button that vanished for a bad reason (rate-limit, content filter, disconnect) is the **mapped exception/error states**: complete = Stop gone AND no mapped exception state present; Stop gone WITH a mapped exception present = that exception state (notify), never "complete." The completion SIGNAL stays Stop-gone; exception states are checked alongside it, not replaced by a positive marker.
- **Stop-button detection lives in the driver/monitor code** — it reads the tree, that is where the detection belongs. When the monitor detects completion (Stop gone), it **notifies through the claude-code-fleet-notify system** (the shared notification transport) — NOT a separate/bespoke notification path. fleet-notify is the notification channel; it is NOT the detector.
- **Generation watchdog — no silent infinite stall** (Gatekeeper item 1): Stop-present = "generating" only while there is progress. A hang with Stop STILL present, no streaming, no error screen, would match "generating" forever — never completing, never drifting (an invisible infinite stall the no-fallback model otherwise has no exit for). Each platform YAML declares a `generation_timeout`; Stop-present past it with no progress = a mapped `generation_stalled` state → notify. Never a silent forever-wait.
- **Fast-gen Stop race — RESOLVED (Jesse ruling 2026-06-14): NOT AN ISSUE, no change, keep it simple.** There is no genuine sub-second reply in production — we send gigantic packages to top thinking models on every prompt, so generation is always multi-second. A sub-second "reply" only happens on a FAILURE, and we run NO synthetic tests, so the race the audit raised is a test-only artifact that never occurs here. **If the Stop button is not detected after a send, that is a real failure to INVESTIGATE (→ drift / notify-halt), never assumed to be a missed fast reply.** Rule stays: Stop appeared = submitted, Stop gone = complete, ordinary observation. No event-driven machinery, no turn-count corroboration — rejected as overcomplication.

## Nothing critical is hidden — by enforced precondition, not assumption (Gatekeeper item 4)

The file tile shows on screen; every selected option shows on screen. If something "isn't there," the tree hasn't refreshed (settle+rescan) or the YAML drifted (notify). But "nothing is ever hidden" is only TRUE because we ENFORCE it — it is a precondition, not a hope. At build and at launch, force renderer accessibility ON and **assert every critical-path control is AT-SPI-visible**. Canvas-drawn controls, the Wayland-portal file chooser, and lazily-computed Chromium a11y can break the axiom. For any critical-path control that is genuinely AT-SPI-invisible, that control/flow is declared **OUT OF SCOPE** for that platform — we do NOT guess at it (no vision/OCR fallback; that would leave the deterministic model). The engine drives only what AT-SPI exposes; the precondition guarantees that is everything critical, or the platform is honestly out of scope.

## How this stays true (enforcement, not memory) — hardened per the audit

1. The driver/dispatch code makes match-or-notify the **only** path — no fallback/downgrade/fuzzy branches exist to take. Every validate returns a `Match | NoMatch` sum type the caller must handle exhaustively (so a silent `return matches[0]`/`try-except-continue` can't masquerade as proceed).
2. Enforcement is **AST-level + behavioral, not grep**: lint asserts only `match_or_halt()` may return an element ref; CI injects a miss and asserts a notify fires. The YAML is **JSON-schema-validated at build** — rejects regex metacharacters, fuzzy/fallback keys, and any `settle_window` above a hardcoded `MAX_GLOBAL_SETTLE_MS` (closes the "set settle=5min to mask drift" loophole).
3. A **NOTIFY poisons the session id** → subsequent driver calls on it throw `DeadSessionError`, defeating caller-level retry wrappers outside the driver.
4. These surfaces "drive a session" → **risky path** → cannot merge without `audit/grok` + `audit/gatekeeper` execute-verify (r5-audit-gate); the gate requires a failing→passing test, not just approval.
5. The **running engine refuses to load un-gated/unsigned YAML+driver bundles** (closes the box-hotfix-over-SSH channel the merge gate can't see).
6. **Contract == behavior**: the engine LOADS a machine-readable appendix (the per-step mapped-state sets + dispositions) emitted from this contract, so contract↔code cannot silently drift. This file is canonical; skills point at it; stale trap-lists are subordinate.
