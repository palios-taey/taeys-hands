# Consult Monitor (drive_chat era) — passive liveness reaper — SPEC

**Author:** taeys-hands (design/judgment). **Status:** spec for implementation. **Date:** 2026-08-13.
**Owner of this component:** taeys-hands (`consultation_v2`). Registration side (writing the session
records) is infra's (`taey-presence` soma_proxy/drive_chat) and is OUT OF SCOPE here.

## Why this exists
Taey now drives Family consults BY HAND via `drive_chat` (one action per call). The old consult monitor
was a feature *inside* the banned engine, so it died when the engine was retired. Nothing outside Taey
now knows a consult is in flight → no external timeout/orphan detection, and **297 leaked no-TTL session
records across 13 node sets** have accumulated (`taey:*:active_session*`, started 2026-06-23..08-03, TTL -1).
(Observed via codex live SCAN 2026-08-13: 205 in the `taey:taeys-hands` set + 92 across `infra`, `codex`,
and `d0/d2/d3/d5/d6/d20-d24`; all 297 have valid JSON + fields, 0 missing, 0 cross-prefix, 0 dup memberships.
An earlier single-set `SCARD` read only the 205 — hence the reader MUST SCAN all node sets, not one.)

## THE HARD BOUNDARY (non-negotiable — this is why it is not the banned class)
- **PASSIVE ONLY.** It reads Redis and NOTIFIES/RECORDS/CLEANS. It **NEVER** touches a display, drives a
  UI, re-dispatches, restarts a display/service, or "recovers." Recovery stays in Taey's hands — the
  monitor's only recovery action is to *notify Taey* so Taey resumes by hand.
- **It does NOT detect completion.** Taey detects completion itself (observe stop-button + harvest). This
  monitor catches ONLY what Taey cannot from inside its own turn: TIMEOUT and ORPHAN.
- No display access, no `Atspi`, no firefox, no engine import. If the implementation reaches for a display
  or a driver, it is wrong.

## What it consumes
The existing primitives in `consultation_v2/primitives.py:408`:
- Per-session key `taey:{node}:active_session:{monitor_id}` → JSON record.
- Per-node SET `taey:{node}:active_session_ids` (members are the session keys).
Record fields observed live: `platform`, `url`, `mode`, `requester`, `timeout` (int seconds; saw
1800/2400/3600), `started` (ISO8601), `started_ts` (epoch float), `monitor_id`.

## Behavior (one pass = `scan_and_reap`)
1. Discover all node SETs via **SCAN** (NOT `KEYS` — non-blocking) matching `taey:*:active_session_ids`.
   (Node variants exist: `taeys-hands`, `taeys-hands-d0`..`-d24`, `infra`, `taey`, etc. — do not hardcode.)
2. For each member session key: load the record. Compute `age = now - started_ts` (fall back to parsing
   `started`; if BOTH missing the record is malformed leaked state → treat as ancient, silent-clean).
   `timeout = record.timeout or DEFAULT_TIMEOUT (1800)`.
3. Classify:
   - `age <= timeout + GRACE (300s)` → **healthy/in-flight**, leave it alone.
   - `timeout+GRACE < age <= NOTIFY_WINDOW (default 6h)` → **live stall/orphan** → NOTIFY + clean.
   - `age > NOTIFY_WINDOW` → **ancient leak** → **silent clean, NO notify** (do not spam a requester about
     a weeks-old consult — this is the 205-leak case).
4. Action on a fire (non-dry-run):
   - **NOTIFY** (live-stall only): `taey-notify <record.requester>` with an honest message (platform, url,
     started, elapsed, "monitor marking stalled/orphaned; resume by hand if still needed"); AND
     `taey-notify taey` as an orphan-wake so Taey can resume by hand. Requester unknown → notify `taey` only.
   - **CLEAN** (both live-stall and ancient-leak): `SREM` from the node SET **and** `DEL` the session key —
     scoped to that exact key only (rule 2: scoped deletes, never unscoped). Cleaning is what stops the leak.
   - Idempotent: after DEL it cannot re-fire. No `notified_ts` needed because clean removes it.

## Modes / CLI
`python -m consultation_v2.consult_monitor`:
- `--dry-run` (DEFAULT): print the classification table (key, node, platform, requester, age, timeout,
  verdict) and what it WOULD notify/clean. **Mutates nothing.**
- `--apply`: actually notify + clean. (Explicit opt-in; default is dry-run so a stray run is harmless.)
- `--once` (default) vs `--loop --interval N`: one-shot for a systemd timer, or a poll loop. Keep the
  one-shot path clean so it can later fold into infra's `display_watchdog` timer.
- Fail-LOUD on any Redis error (raise, non-zero exit) — a monitor that silently can't read is worse than none.

## Validation (production oracle — NO synthetic-only tests)
- `--dry-run` against LIVE Redis must SCAN all node sets (13 seen live), classify the **297 leaked** records
  as ancient-leak (silent-clean), print the per-node counts + a sample, and classify any genuinely-recent
  record correctly. That dry-run output IS the production observation for the deliverable. Do not fabricate
  a test fixture as the evidence.
- Then a single `--apply` run (only when taeys-hands says go) reaps the 297 across all node sets and leaves
  every `active_session_ids` set empty; re-running `--dry-run` shows 0 stale. That is the completion
  evidence (per-node before/after counts).

## Non-goals / explicitly OUT of scope
- Writing session records (that is infra's registration side, in `taey-presence`).
- Completion detection / extraction (Taey does that).
- Any display/UI/driver/engine interaction.
- Per-mode timeout tuning beyond reading `record.timeout` — defaults are fine; tuning is a later pass.

## RED-TEAM CHECKLIST (for the independent design review, before implementation)
Attack this design; report concrete findings ranked most-severe first, each citing the spec line it hits.
Do NOT write code — design review only.
1. **Ban-adjacency:** does anything here risk being, or later becoming, the banned UI-automation class
   (no display drive / recover / re-dispatch / restart)? Is "notify Taey to resume by hand" truly passive?
2. **False-orphan:** could it reap/notify a consult that is actually still healthy (deep mode legitimately
   running 20–30m; `GRACE`/`timeout` too tight; `started_ts` set late)? Is the healthy-vs-stall cutoff right?
3. **Missed-orphan:** a consult that died but whose record was never written (registration gap) — does the
   monitor's scope honestly acknowledge it can't see that, and is that stated?
4. **Race:** Taey deregistering at delivery vs the reaper cleaning the same key — double-harvest, lost record,
   or a notify fired microseconds before Taey's clean. Is the ordering safe? Should clean be CAS/atomic?
5. **Notify storm / classification:** is the ancient-leak (silent) vs live-stall (notify) window correct so
   the 205 leaked records don't spam requesters? Edge at the 6h boundary.
6. **Clock/tz:** `started_ts` epoch vs `started` ISO with tz — any bug computing `age`? DST/utc mismatch?
7. **Coverage:** SCAN over `taey:*:active_session_ids` — cursor handling, missed nodes, huge-set blocking.
8. **Live-Redis safety:** could `--apply` ever delete a non-session key or an unintended scope?
9. **Sufficiency:** is timeout-only orphan detection enough, or is a lock-gone (`plan_active`) signal needed
   to catch orphans faster than their full timeout? Recommend if so, but keep it passive.

## RED-TEAM VERDICT & RESOLUTIONS — GATE CLOSED 2026-08-13 (taeys-hands judgment on grok task-5e8ff301)
**Verdict: design SOUND — no ban violation, no showstopper. 9 hardening items accepted and resolved
below. Build against THIS spec.** R = reader-side (codex builds it here); I = registration-side (infra).
1. **RACE (R):** before acting on a fired record, **atomically re-check** it (GETDEL the session key, or WATCH
   it) — if already gone/refreshed by Taey's delivery, SKIP. Deletes hit only the exact scanned key
   (idempotent). Worst case is one spurious stall-notify; the atomic re-check removes even that.
2. **FALSE-ORPHAN (R+I) — REFRAMED by infra's 2026-08-13 root-cause finding.** A single model generation can
   now run up to `VLLM_REQUEST_TIMEOUT_SECS = 5400s` (raised from 1800 today; the 1800 cutoff WAS the consult
   failure). So age-since-`started_ts` is a CRUDE signal — a legit multi-action consult (each action a
   generation up to 90m) outlasts any fixed value. Resolution: (R) `record.timeout` is AUTHORITATIVE;
   `DEFAULT_TIMEOUT` (only if absent) MUST exceed the model request timeout → **7200s floor** (never < 5400).
   If a `last_seen`/heartbeat field is present, the reader uses **stall = now − last_seen > (5400 + margin)**
   instead of age-since-start — the correct, non-false-flagging signal for a hung generation / dead turn.
   (I) registration should set generous per-consult timeouts AND write `last_seen` per action so the reader
   can tell a legitimately-long consult from a genuinely stalled one. Without `last_seen` the reader falls
   back to `started_ts` + the (generous) authoritative timeout and accepts it is coarse.
3. **SCAN clarification (R):** SCAN **discovers the node-set KEYS** (node names are not enumerable a priori —
   13 found live); each discovered set's members are iterated with **SSCAN**. This does NOT contradict the
   `primitives.py` "SET-based, no SCAN" note — that was reading ONE *known* node's members directly.
4. **MISSED-ORPHAN (R, scope honesty):** the monitor sees ONLY *registered* consults. A consult that dies
   before its record is written is INVISIBLE to it — a registration-side concern, minimized by
   register-at-start-fail-loud. State this limitation explicitly in the module docstring (cannot-lie).
5. **COVERAGE (R):** use **SSCAN** (cursor) for set membership and **SCAN** (cursor) for key discovery —
   never `KEYS`/`SMEMBERS` on the leak/busy case. Non-blocking.
6. **CLOCK/TZ (R):** prefer `started_ts` (epoch); tz-AWARE parse of `started` as fallback; parse failure →
   treat as malformed → ancient-leak silent-clean, NEVER crash. Single-host (Mira) so skew ≈ 0; add a code
   comment to revisit if this ever runs cross-host.
7. **NOTIFY WINDOW (R, tuning):** keep the ancient-leak(silent) vs live-stall(notify) split; document that
   live consults never approach 6h (deep max ~30–60m), so the window cleanly separates them. Tunable const.
8. **SAFETY (R):** **NEVER construct a key to delete.** Only `DEL`/`SREM` the exact keys/members returned by
   the scan. Constructing-from-`node_key`/`NODE_ID` is banned in the reaper (removes the wrong-key-DEL risk).
9. **BAN-ADJACENCY (R, two hard guards):** (a) **Import boundary** — the module imports ONLY the redis
   client + a notify shim + stdlib. It MUST NOT import `consultation_v2.platforms`, any driver, `Atspi`,
   firefox, or engine code. Add a self-check at import that asserts none are loaded by it. (b) **Notify is a
   plain STATUS message, never a command** ("consult X appears stalled/orphaned" — not `--type command`, not
   an auto-resume instruction). The monitor never drives/schedules/triggers anything; Taey's resumption is
   Taey's own supervised by-hand decision. There is NO automated closed loop (monitor→action). This is what
   keeps it clear of the engine ban.
- **Additional (I):** registration `set` has no TTL (that is WHY records leaked). Recommend registration add
  a generous **TTL backstop** (e.g. `timeout` + large margin) so records self-expire even if the reaper is
  down. The reaper stays primary; TTL is defense-in-depth.

## PRE-LIVE-MONITORING RESIDUALS (reader landed 402ed168; close these BEFORE enabling live-stall notify)
The reader's SILENT path (classify + scoped clean of the 297 leaks) is fully validated. The NOTIFY path
(LIVE_STALL) was NOT exercised (0 live stalls existed) and needs registration to exist first. Before any
`--apply` that could hit a live stall, close all three:
1. **Add `--from`** to the `taey-notify` call in `_notify_status` — a headless run has no tty, so sender is
   auto-inferred and can be misattributed. Pass an explicit sender.
2. **Reconsider clean-then-notify ordering + `check=True`** — currently the record is cleaned, THEN notified;
   a `taey-notify` failure loses the notification (record already gone) and raises out of the batch. Prefer
   notify-before-clean, or don't `check=True` the notification.
3. **Verify the notify end-to-end** against a real (or safely-staged) live stall — production is the oracle.

## Deliverable
A branch with `consultation_v2/consult_monitor.py` + `python -m` entrypoint, matching this spec, plus the
`--dry-run` live-Redis output pasted as the production observation. taeys-hands reviews before any `--apply`.
