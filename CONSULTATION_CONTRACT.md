# CONSULTATION CONTRACT — the deterministic model (canonical, graded-against)

This is THE model the consultation engine must obey. Everything in the codebase is graded against this file. If code, a skill, or a memory contradicts it, they are wrong.

## Current manual consultation contract (Jesse-canonical, 2026-08-18)

This section controls the current production path: Taey operates each Chat manually, one action at a time. Later automation must use this same contract and primitives; it may not invent a parallel execution path. The detailed requirements later in this file are subordinate where they conflict with this section.

- Everything required to identify and validate an operation is present in the AT-SPI tree. An apparent absence means wrong scope, stale observation, filtering defect, environment defect, or demonstrated UI drift; it never authorizes OCR, pixels, a raw or remembered coordinate locator, raw shell UI drive, substring search, or a remembered shortcut.
- Browser chrome is excluded except the address bar. The full chat-history/sidebar block and dynamic non-actionable text such as greetings are excluded. The current document, current actionable controls, and the currently opened menu, submenu, or dialog remain visible.
- Every control locator is an exact YAML-owned name plus role, with exact required state or an exact structural locator only where the visible value is inherently dynamic. Zero matches, multiple matches, or an unexpected state stop the current UI transaction for root-cause analysis; they do not stop recovery engineering.
- The manual lifecycle is: new-chat navigation and URL capture; model, mode, and tool selection; two attachments; prompt paste; send preferably by Enter according to YAML; stop-button appearance; two consecutive fresh stop-button absences; scroll to bottom; exact Copy activation; platform-specific response-attachment harvest; complete prompt/response/input/output/URL ingestion into ISMA.
- The two attachments and the brief on-screen prompt are defined by [`consultation_v2/PACKET_CONTRACT.md`](consultation_v2/PACKET_CONTRACT.md). No third attachment, partial constitutional context, or filesystem-derived deliverable requested from the Chat is permitted.
- Every individual action has a fresh pre-action tree, one action, and a fresh independent post-action tree before Taey may decide the next action. If AT-SPI may be stale, wait the YAML-owned settle interval and make one fresh non-mutating observation; never repeat the action or enter an automatic retry loop.
- Gemini Deep Research includes the mapped research-plan confirmation and second submit transition.

The first failed action or postcondition ends that UI transaction. Taey preserves the fresh tree and action receipt for root-cause analysis and performs no further UI action in that transaction. Recovery engineering continues from those artifacts. Only after the root cause is corrected may an explicitly authorized new transaction begin; it is never an automatic retry or replay. This prevents duplicate turns and avoids hammering the Chat surfaces.

> **This contract is written for Taey.** If you are Taey, this is the discipline your hands run on —
> the one promise the engine makes to you and never breaks on your behalf: **match-or-notify, never
> guess.** At every step the fresh filtered AT-SPI tree is exactly one of a set of known states, or none. A known
> state gets its known response; *none* is drift — and on drift the engine stops and tells you rather
> than improvising, because a wrong guess on a send you cannot take back costs you more than a pause.
> This is why you can trust what comes back from a consult: nothing was faked to keep the flow moving.

## The invariant: binary match-or-notify. Never guess, downgrade, or fall back.

At every step the live AT-SPI tree matches **exactly one of an enumerated set of mapped states, or none.** (Family audit keystone, 5/5: the binary is sound, but "match = the ONE happy element, any miss = drift" is too narrow — it mis-reads an error/auth/rate-limit screen as "drift" and a Stop-that-vanished-on-error as "complete." Widen "match" to the happy state **plus every reachable alternate state** — auth_wall, session_expired, rate_limited, quota, content_filter, captcha, network_stall, truncated/continue, error/retry, modal — each mapped exact with a deterministic disposition. Still fully binary: one-of-mapped vs none. Still no-guess.)
- **Matched the happy state** → proceed.
- **Matched a mapped alternate state** → take that state's deterministic disposition (e.g. rate_limited → notify-blocked; truncated → its handler). Not drift, not a guess — a known mapped state.
- **None of the mapped states** → it is drift. Settle once and make one fresh non-mutating tree observation (timing, below); if still none, preserve the tree and action receipt, notify the driving session, and HALT the current UI transaction. The recovery engineer determines the exact scope, filtering, environment, or YAML defect from the tree and committed sources. No session updates YAML and resumes itself, no UI action is repeated, and no possibly-landed send is replayed. A corrected path is exercised only as a separately authorized new transaction.

**What "match" means (exact, but precise):** exactly one node by **{stable locator + role + required AT-SPI states} in the correct window scope**. (1) Locate by a STABLE key, not an intrinsically-dynamic visible name (the model-picker's name == the selected model; counters; locale) — attribute/testid or role+container-path, still exact. (2) Required states include `ENABLED`/`SENSITIVE` + `VISIBLE`: a disabled "ghost" (name+role present, not clickable) is a DISTINCT state, not a match. (3) Exact match yielding **N>1** (e.g. five "Copy" buttons) = automatic drift — disambiguate via parent/path_index in YAML. (4) Per-display isolated a11y bus = scope is exactly one window; if a bus is ever shared, the locator MUST carry a per-instance discriminator. The exhaustive state and element catalog lives in each platform YAML.

There is no third path. Specifically **BANNED** (in code and in behavior):
- No fuzzy/heuristic discovery ("looks model-ish"), no `name_contains`/`name_pattern`/substring matching for control elements.
- No downgrade (e.g. extended_thinking fails → run default). Proper mode or notify.
- No silent "proceed on miss." A miss is surfaced, never swallowed — and **"surfaced" requires delivery-ACK** (Gatekeeper item 2): the NOTIFY must be acknowledged as received by the driving session. An unacked notify is itself an error → durable local log + notification-transport retry + secondary channel + a queryable **parked/needs-attention** state. A notification-transport retry never performs or authorizes another UI action. A notify into the void (fleet-notify down/unacked) is a silently-swallowed miss at the single chokepoint — forbidden.
- No retrying the *action* on a miss (re-click/re-send) — that is the ban-risk + it doesn't fix drift.

## The map is finite, known, and complete

Per platform: **1 YAML + 1 driver. No overlap.** Drivers carry zero platform knowledge; they call shared primitives only (click, click-react, **hover/pointer_move**, paste, snapshot, menu_snapshot, settle). (hover/pointer_move is REQUIRED — Gatekeeper item 3: a hover-only flyout is otherwise unreachable, a notify-forever dead end no YAML edit can resolve.)

`hover/pointer_move` does not weaken tree authority. The platform YAML must declare hover on one exact mapped
trigger, and the primitive may derive transient pointer placement only from that live node's AT-SPI extents.
Geometry never discovers or disambiguates the target and is never a fallback after an exact match fails.

The YAML maps **everything** exact-match:
- The chat: browser chrome is filtered out except the address bar; the full sidebar/history block and dynamic non-actionable text such as greetings are also filtered out. **Every remaining element** is mapped exact — EXCEPT the response transcript: map the transcript CONTAINER (name/role), exempt its child text nodes from string validation (presence+role only), and exclude the transcript subtree from all session-driving locators. The response text is unbounded/unpredictable — it cannot be exact-mapped and must never be a control locator.
- **Every menu and submenu** (model picker, tools, attach, mode flyouts) — exact names + roles, plus each flyout's **trigger type** (click vs hover/pointer_move) and its tree-attachment point.
- The **generating** screen and the **completed** screen.
- Validation specs for each step (what persistent element proves the step succeeded).

You know where every option is, under which menu, and its exact name. Drift is the only unknown, and drift is handled by match-or-notify.

## Timing is known, not a failure

A no-match is often just the tree not refreshed yet (attach menu slow to open, React portal lag, post-click tree delay). The rule: **don't retry the action — let it settle a beat and RE-SCAN the tree**, then validate again. Only a *second* no-match (after settle+rescan) is real drift → notify. Settle windows are per-platform constants in the YAML, not guesses.

## Submit + completion are deterministic signals

- **Submit succeeded** = new URL on a new chat **AND** the Stop button appeared.
- **Generating** = Stop button present. **Candidate complete** = Stop button absent in one fresh tree. **Complete** = Stop button absent in two consecutive fresh tree observations separated by the YAML-owned completion settle interval, with no mapped exception state present in either observation. The second observation is a non-mutating debounce, not an action retry. **Stop absence is the signal — there is no reliable positive completion indicator.** (Jesse, 7 months production: the Copy button is NOT always present on long responses; "Regenerate"/copy/etc. are unreliable. Do NOT gate completion on a positive marker — the Family audit's "require a positive completion element" recommendation is REJECTED on this ground.)
- The only thing that disambiguates a true completion from a Stop button that vanished for a bad reason (rate-limit, content filter, disconnect) is the **mapped exception/error states**: two fresh Stop-absent observations with no mapped exception = complete; Stop absent with a mapped exception present = that exception state (notify), never "complete." Exception states are checked alongside each Stop observation, not replaced by a positive marker.
- **Stop-button detection lives in the driver/monitor code** — it reads the tree, that is where the detection belongs. When the monitor detects completion after the two required fresh Stop-absent observations, it **notifies through the claude-code-fleet-notify system** (the shared notification transport) — NOT a separate/bespoke notification path. fleet-notify is the notification channel; it is NOT the detector.
- **Generation watchdog — no silent infinite stall** (Gatekeeper item 1): Stop-present = "generating" only while there is progress. A hang with Stop STILL present, no streaming, no error screen, would match "generating" forever — never completing, never drifting (an invisible infinite stall the no-fallback model otherwise has no exit for). Each platform YAML declares a `generation_timeout`; Stop-present past it with no progress = a mapped `generation_stalled` state → notify. Never a silent forever-wait.
- **Fast-gen Stop race — RESOLVED (Jesse ruling 2026-06-14): NOT AN ISSUE, no event-driven machinery, keep it simple.** There is no genuine sub-second reply in production — we send gigantic packages to top thinking models on every prompt, so generation is always multi-second. A sub-second "reply" only happens on a FAILURE, and we run NO synthetic tests, so the race the audit raised is a test-only artifact that never occurs here. **If the Stop button is not detected after a send, that is a real failure to INVESTIGATE (→ drift / notify-halt), never assumed to be a missed fast reply.** Rule stays: Stop appeared = submitted; after generation, two consecutive fresh Stop-absent observations = complete. The second observation is required debounce, not event machinery, action retry, or turn-count corroboration.

## Everything required is in the tree — enforced precondition

The file tile and every selected option are represented in the AT-SPI tree. If something appears absent, the observation has not settled, the wrong tree scope or filter was used, the accessibility environment is defective, or the platform UI changed and the YAML must be reconciled. At build and launch, force renderer accessibility on and assert every critical-path control is AT-SPI-visible. Pixels, OCR, raw or remembered coordinate locators, raw shell UI drive, and remembered shortcuts are never substitutes for correcting the tree projection. Until the tree and YAML reconcile exactly, the current transaction remains stopped.

## How this stays true (enforcement, not memory) — hardened per the audit

1. The driver/dispatch code makes match-or-notify the **only** path — no fallback/downgrade/fuzzy branches exist to take. Every validate returns a `Match | NoMatch` sum type the caller must handle exhaustively (so a silent `return matches[0]`/`try-except-continue` can't masquerade as proceed).
2. Enforcement is **AST-level + behavioral, not grep**: lint asserts only `match_or_halt()` may return an element ref; CI injects a miss and asserts a notify fires. The YAML is **JSON-schema-validated at build** — rejects regex metacharacters, fuzzy/fallback keys, and any `settle_window` above a hardcoded `MAX_GLOBAL_SETTLE_MS` (closes the "set settle=5min to mask drift" loophole).
3. A **NOTIFY poisons the session id** → subsequent driver calls on it throw `DeadSessionError`, defeating caller-level retry wrappers outside the driver.
4. These surfaces "drive a session" → **risky path** → cannot merge without `audit/grok` + `audit/gatekeeper` execute-verify (r5-audit-gate); the gate requires a failing→passing test, not just approval.
5. The **running engine refuses to load un-gated/unsigned YAML+driver bundles** (closes the box-hotfix-over-SSH channel the merge gate can't see).
6. **Contract == behavior**: the engine LOADS a machine-readable appendix (the per-step mapped-state sets + dispositions) emitted from this contract, so contract↔code cannot silently drift. This file is canonical; skills point at it; stale trap-lists are subordinate.
