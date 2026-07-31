# EXTRACT conformance reference — per-platform FROZEN-good + regression-gate assertions

**Owner:** taeys-hands (capability knowledge). **Wired by:** conductor (non-bypassable ship-gate + sabotage-validation). **Implemented against by:** codex (task-e67474eb `copy_and_read`).
**Status:** first stabilization artifact (EXTRACT = first capability driven to full conformance). Authored from THIS session's production evidence (14+ consults across all 5 platforms, 2026-06-26) + `STABILIZATION_FREEZE.md` + memory `feedback_consult_extract_hardening_manual_recover`.
**Provenance:** every per-platform claim below is [Observed] this session unless labeled [Inferred]/[Unknown].

---

## 0. The cross-cutting §4a code-level rule (extract loops)

The extract path re-scans; the contract must classify that explicitly so it cannot drift into a banned settle-poll:

- **ALLOWED:** re-scan / extract-retry that targets a **READ-ONLY control** (the response Copy button, scroll-to-bottom, AT-SPI tree scan, cache refresh). These handle a stale / incomplete / below-fold tree — the §1 debounce/observation class. Gating must be on **copy-button PRESENCE** (an extract precondition).
- **BANNED:** re-acting on a **mutating / bot-detection control** (send / type / navigate / attach / mode-select), OR polling a **completion signal** to fake "complete" (the stop-button is the only completion oracle; never substitute a settle timer).
- **Worked classification (authoritative, cross-checked vs DCM council):**
  - `consultation_v2/atspi.py:46` `for attempt in range(2)` — ALLOWED. attempt 0 scans the AT-SPI desktop for Firefox; if none, attempt 1 does `clear_cache_single()` then re-scans. Pure observation / stale-cache refresh, zero platform action.
  - `consultation_v2/drivers/claude.py:1227` `for attempt in range(5)` — ALLOWED extract-scan-retry. Each pass scroll-to-bottoms and re-scans for the response Copy button (it enters the AT-SPI tree only when scrolled on-screen; on a long answer it sits below the fold), then clicks an idempotent READ-ONLY Copy control. NOT §4a-banned. Required guard: stays gated on copy-button presence, never on a faked completion; any re-click-on-empty stays scoped to the read-only Copy control.

---

## 1. Universal regression assertions (every platform, every extract)

A capability change that breaks ANY of these BLOCKS at the ship-gate (the destroy-by-changing fix):

1. **NON-EMPTY** — extracted text length > 0 after the engine reports success. (A fail-CLOSED refusal is acceptable and must surface; a success with empty text is a regression.)
2. **ON-TOPIC / len >> prompt** — extracted length is substantially greater than a trivial echo AND matches the lens/topic (not boilerplate).
3. **NOT a PROMPT-ECHO** — the extract must NOT be the user's own message. Reject if it starts with the dispatched ask's opening line, or contains the inline-packet marker `===== GROUND-TRUTH DOCUMENT` / `## Deliverable`, or equals `request.message`.
4. **Completion is the stop-button, never a timer** — extract only runs after stop-button-disappearance (+ debounce), never after a settle window substituting for it.

**Sabotage fixtures (for conductor to validate the gate is non-vacuous):** feed (a) an empty clipboard, (b) the prompt echo, (c) a ~93-char intro stub, (d) a truncated half-response — each MUST fail its assertion; neutering the assertion must make the known-bad fixture pass.

---

## 2. Per-platform FROZEN-good extract + platform-specific assertions

### ChatGPT (:2)
- **FROZEN-good method:** scroll-to-bottom + the response's Copy button (lowest/newest turn).
- **[Observed] KNOWN GAP this session (every dispatch):** `extract_primary` "Copy response did not yield non-empty text" / newest-user-turn anchor not found — because a large inline `--message` becomes a "Pasted markdown" CHIP, so the prompt isn't a visible user turn. Fail-CLOSED (response exists on the answer thread).
- **Recovery (until copy_and_read):** per-button capture on the answer thread, pick the assistant Copy (not the prompt-echo).
- **Assertion add:** must capture the assistant turn even when the user turn is a paste-chip; reject prompt-echo.

### Claude (:3)
- **FROZEN-good method:** scroll-to-bottom + Copy; **for ARTIFACT/canvas answers the full deliverable is the artifact, NOT the chat bubble.**
- **[Observed] this session:** engine captured the artifact at `extractions[0].content` (kind=artifact, 22–46 KB) while the inline chat bubble was only a ~3–8 KB cover-note ("the short version… full reasoning is in the file"). Strip the leading UI chrome lines (`Claude finished the response` / a time like `4:17 PM` / `Prepared …`).
- **Assertion add:** when the inline bubble matches a cover-note pattern (contains "in the file"/"below" AND is small) AND an artifact exists, the delivered text MUST be the artifact (length == artifact length, not the cover-note). Reject delivering the cover-note as the answer.

### Gemini (:4)
- **FROZEN-good method:** Copy (`extract_primary`) — clean this session (9–10 KB each, no recovery needed).
- **[Observed] mode flag caveat:** engine sometimes reports `mode=deep_think` selected; treat as an unverified flag (relay honestly), not proof DT was on. Does not affect extract correctness.
- **Assertion:** universal set only.

### Grok (:5)
- **FROZEN-good method:** navigate the answer-thread URL, wait for thread-load (copy buttons appear), scroll-to-bottom + Copy.
- **[Observed] KNOWN GAP this session (every dispatch):** `extract` "new Copy button did not appear before settle timeout" though the monitor saw the response COMPLETED — the copy button renders AFTER the settle window. Fail-CLOSED (response exists on the captured `/c/<id>` answer thread; the captured URL is sometimes stale-home — use the monitor's answer-thread URL).
- **[Observed] SHORT-ANSWER trap (linkedin-watchdog-post):** a thread has 2 copy buttons (user-msg ~5 KB prompt echo + assistant ~900 chars). "keep LONGEST" grabs the PROMPT ECHO. Recovery: per-button capture, pick the assistant button (the clipboard that does NOT start with the prompt's first line / has no `GROUND-TRUTH` marker).
- **Assertion add:** for short answers, selection must be the assistant button, not the longest. Verify EXACT clipboard, never transcribe off a screenshot.

### Perplexity (:6)
- **FROZEN-good method:** Deep Research → the full-report copy. The standard "Copy" button (n=1) recovers the full rendered report.
- **[Observed] KNOWN GAP this session:** DR rendered the FULL report but the engine's mapped `copy_contents_button` was ABSENT → `extract_primary` fails-CLOSED; the standard Copy button recovered the full 27 KB report.
- **[Observed] DISTINCT failure — thin-render:** the report did NOT render (intro-only, <500 chars / "I'll now deliver…"); copy yields the stub. Do NOT deliver the stub → flag requester → ONE fresh spaced re-dispatch (in-thread recovery fails at page_ready). This is NOT the same as the control-gap.
- **HARD: scrub before save** — DR output embeds transient AWS presigned URLs. Strip every URL containing `amazonaws`/`ppl-ai-file-upload`, THEN nuke any whole line still containing `AWSAccessKeyId`/`x-amz`/`Signature=`/`Expires=`, hard-assert 0 tokens remain.
- **Assertion add:** delivered text is the full report (reject the <500-char intro stub); 0 AWS-presigned tokens present.

---

## 3. What this artifact feeds

- **conductor:** wire §0 (the read-only-vs-mutating extract-loop rule) + §1 (universal assertions) + §2 (per-platform asserts) as a **non-bypassable ship-gate** code-level conformance check, sabotage-validated per §1.
- **codex:** `task-e67474eb copy_and_read` must productionize the per-platform recoveries in §2 (paste-chip assistant anchor, Claude artifact-over-cover-note, Grok late-copy + short-answer assistant-button, Perplexity DR control-gap + thin-render distinction + scrub) so the manual `/tmp/dcm_consult/manual_extract.py` recovery is no longer needed.
- **taeys-hands (me):** run PRODUCTION-VERIFY on the IMPROVE branch — a real consult per platform, asserting §1+§2 against live output — before conductor merges. No self-authored test substitutes for the real consult.
