# Consult-engine PR#2 — e2e validation attestation (in-artifact, per-platform)

**Purpose:** these 7 fixes are live-browser AT-SPI behaviors; r5 auditors have no display/Firefox/AT-SPI and cannot reproduce them. This log is the operator (taeys-hands) attestation — the real per-platform consult evidence run against THIS chain's code, with an explicit assertion of which fix each consult proves. Per ORCHESTRATION_INTEGRITY: evidence in-artifact, never a self-report.

**Engine code under test:** branch `consult-engine-combined-chain` (this PR). Consults driven on Mira displays :2 (ChatGPT), :3 (Claude), :6 (Perplexity), :5 (Grok), each its own Firefox + isolated AT-SPI bus. Raw consult JSON paths cited per lane (operator-local; content snippets + char-counts inlined here for the auditor).

---

## ChatGPT (:2) — proves cg-monitor (#1), inline-context (#2), extract-simplify (#4), paste-chip send (#5)
- **Consult:** numpy#31651 v2 re-audit, 14KB inline message (no file attach → exercises inline-context), purpose `hunter-numpy31651-v2-reaudit-chatgpt-VALIDATE`. Raw: `/tmp/cc-validate/chatgpt.json`.
- **Observed end-state:** `ok=true`, extracted **12,330 chars**. New-thread URL `chatgpt.com/c/6a3d22a9-...` (send landed). Screenshot confirmed the 14KB paste auto-converted to a **"Pasted markdown(38).md" chip** with empty composer and STILL sent (the exact paste-chip path that pre-fix hung ~23min).
- **Response head:** `"# Verdict: **NO-GO**\nV2 fixes the reported float16 bypass, but the unconditional asanyarray(y,dtype=float64)..."` — substantive, on-topic, contains multiple ```python code blocks.
- **Assertions:**
  - **#5 paste-chip:** long inline paste → PASTED chip + empty composer → send LANDED (new thread, generation began). PROVEN.
  - **#2 inline-context:** the 14KB packet content reached ChatGPT inline (no attach); the answer is on-topic to the inlined numpy diff. PROVEN.
  - **#1 cg-monitor:** completion was detected correctly (consult returned a complete 12,330-char response; no false-complete mid-generation). PROVEN.
  - **#4 extract-simplify:** the response CONTAINS code blocks, yet the full **12,330-char message** was extracted (not a code fragment) — empirically confirms the `Copy response` exact-name matcher selects the message-level copy, not a code-block "Copy code". PROVEN (corroborates gatekeeper's static refutation of the code-fence concern).

## Claude (:3) — proves paste-chip send (#5), inline-context, chunking-removal one-file path
- **Consult:** engine-reliability review, 50KB inline message (the 7-fix diff inlined → far exceeds the old 45KB chunk threshold + auto-chips), purpose `consult-engine-7fix-reliability-review-claude-VALIDATE`. Raw: `/tmp/cc-validate/claude.json`.
- **Observed end-state:** `ok=true`, **9,673 chars**. Thread auto-titled "Production failure modes and sentinel implementation" (from the prompt content → the 50KB message was received + sent + answered).
- **Assertions:**
  - **#5 paste-chip:** 50KB inline message auto-chipped + sent hands-off → on-topic 9,673-char response. PROVEN.
  - **#3 chunking-removal:** verified two ways — (a) code-audit: `identity.py:125-129` `_write_package_chunks` unconditionally writes ONE `.md` and returns a single-element list (the >45KB→22KB split branch is gone for all platforms); (b) production: a prior Claude consult attached a single consolidated `taey_package_claude_1782389118.md` (one file, not `_partNofM`). PROVEN.

## Perplexity (:6) — proves perplexity-extract bounded clipboard poll (#6)
- **Consult A:** perplexity-extract production validation, Deep Research. Raw: `/tmp/perplexity_extract_task-08e35e00.json`. `ok=true`, **18,950 chars** ("NCCL All-Reduce Hang Diagnosis" DR report) extracted via `Copy contents`.
- **Consult B:** tutor SecureBoot Deep Research (independent real consult). Raw: `/tmp/cc-e2e/tutor_secureboot.json`. `ok=true`, **23,154 chars** ("Safe Loading of gdrdrv on DGX Spark GB10" full report), ends with a complete recommendation (not truncated).
- **Assertion #6:** the bounded clipboard read-poll (`perplexity.py` primary + report-card paths, with clipboard-clear before each poll per gatekeeper) extracted full ~19KB and ~23KB DR reports cleanly. The old single-shot `sleep(1.0); read()` returned empty on ~20KB reports. PROVEN twice.

## Grok (:5) — proves grok-extract-settle (#7)
- **Consult:** grok-extract-settle production validation, Heavy. Raw: `/tmp/grok_extract_task-a3e463ee.json`. `ok=true`, **1,300 chars** complete on-topic response (4 structured bullets).
- **Assertion #7:** the extract found the `Copy` button AFTER settling for a non-generic conversation title (the thread-load race that previously returned "copy button not found" is handled). Extract succeeded; complete content (not a thin fragment). PROVEN.

---

## Paste-chip DISABLED-button path (#5 hardening) — re-validated at the hardened SHA (1667ce97)
The fix-5 hardening makes the mapped send button's ENABLED state authoritative (`ready = send_button and has_coordinates and state_ready`); paste-chip detection is evidence-only and can no longer assert readiness on a disabled button.
- **(a) ENABLED button + paste-chip → SENDS (production):** real ChatGPT consult on `1667ce97`, 69KB inline reliability-read message (`--select tools=none`), purpose `consult-engine-pr2-revalidate-pastechip-toolsnone`. Raw: `/tmp/cc-validate/chatgpt_reval2.json`. Observed: the 69KB paste auto-converted to a **"Pasted markdown(40).md" chip** with empty composer and STILL SENT — new thread `chatgpt.com/c/6a3d321b-495c-...`, generation began (Stop button present). The hardened readiness did NOT re-introduce the paste-chip hang. PROVEN.
- **(b) DISABLED button + chip → NOT ready (fail-open closed):** peer focused readiness smoke at the hardened SHA: `disabled send + paste chip => ready=false`; `enabled send + paste chip => ready=true`; bare `content`/`text` chip terms rejected (tightened). The gatekeeper-flagged correctness inversion is closed.
- **Note on `tools=none`:** this consult used explicit `tools=none` because the ChatGPT `+` tools menu is AT-SPI-broken; web_search-as-default stalls the tools-selection step before the paste. The ChatGPT default is being set to `tools=none` (justified) so the DEFAULT consult path takes this working route. Default-path (no `--select`) re-validation appended below after that commit.

## Default ChatGPT path (no --select) — PROVEN at the tools=none-default commit
- Real ChatGPT consult, **NO `--select`** (so it takes the YAML default), purpose `pr2-revalidate-multiturn-t1-defaultpath`. Raw: `/tmp/cc-validate/mt_t1.json`. Observed: `ok=true`, `session_url_after=https://chatgpt.com/c/6a3d397d-...`, **421-char on-topic response** — the no-select consult navigated to a fresh thread, the `default_for_fresh: none` routed to tools=none (the engine did NOT open the broken `+` tools menu), reached paste/send, and returned a real answer. The web_search-default regression is closed; the default ChatGPT path works hands-off. PROVEN.

## reval2 folds (conductor Option B) — #3 ChatGPT-extract-correlation + #4 Grok-new-copy-baseline @ commit 7add819b
These two folds close correctness regressions reval2 (Horizon) found that the gatekeeper code-fence trace missed. (Numbering here is reval2's finding numbers, distinct from the 7-fix table below.)
- **reval2-#3 ChatGPT extract (chatgpt.py):** scroll-result now FATAL (raises if `_scroll_chatgpt_thread_to_bottom()` did not reach bottom — no silent stale-bottom take) + Copy-response candidates filtered BELOW the newest user-turn anchor (correlated to the just-sent prompt, prefer exact prompt text, fallback `user_message_actions_panel`). Code-audit PASS (the over-engineered code-fragment/near-echo reject-heuristic was NOT restored; exact-name `Copy response` matcher kept). **Production:** single-turn extract-correctness is proven across every successful consult (turn-1 421ch + the 12,330ch numpy + others each returned the CORRECT response, i.e. the correlation returns the right turn). **Multi-turn production repro of the distinguishing case was BLOCKED by a SEPARATE pre-existing limitation** — a ChatGPT `--session-url` follow-up (turn-2, `/tmp/cc-validate/mt_t2.json`) failed at `tree_conformance` ("12 unknown live element(s), 1 expected missing" on a loaded thread; the conformance baseline is fresh-page-oriented). That is NOT a #3/#4 regression and NOT an extract-guard failure (it halted before send, correctly notify-and-halt). The multi-turn extract-correlation is therefore validated by code-audit + the gatekeeper scroll-path code-trace (r5 this round). The `--session-url` tree-conformance limitation is flagged as a separate follow-up.
- **reval2-#4 Grok extract (grok.py):** pre-send Copy-button baseline captured immediately before Return; readiness requires a NEW copy vs that baseline (not ANY copy) + non-generic title; settle TIMEOUT is now FATAL (returns None → fail-loud, no last-snapshot/stale proceed); extraction clicks only `_new_copy_buttons_since_baseline`. Code-audit PASS. **Production:** Grok normal-case extract re-validated on 7add819b — real Grok-Heavy consult `pr2-revalidate-grok-newcopy-baseline` (`/tmp/cc-validate/grok_v4val.json`) `ok=true`, **2,679 chars** extracted via the new-copy baseline; the baseline + fatal-timeout did NOT break normal extract. (The stale-copy-avoidance edge — an existing conversation with prior copies — is code-audited + r5-traced; a fresh consult has no stale copies to repro it.)

---

## Summary
| Fix | Proven by | Evidence |
|---|---|---|
| #1 cg-monitor | ChatGPT consult | 12,330ch complete, no false-complete |
| #2 inline-context | ChatGPT consult | on-topic to inlined packet, no attach |
| #3 chunking-removal | code-audit + prior one-file pkg | identity.py:125 one-file; taey_package_claude_*.md |
| #4 extract-simplify | ChatGPT consult | 12,330ch incl code blocks = full message, not fragment |
| #5 paste-chip send | ChatGPT + Claude consults | 14KB + 50KB pastes auto-chipped + sent |
| #5 disabled-button (hardened) | reval2 consult + peer smoke | 69KB paste-chip sent under enabled-button readiness; disabled+chip→ready=false |
| #6 perplexity-extract | 2 Perplexity DR consults | 18,950 + 23,154 chars full reports |
| #7 grok-extract-settle | Grok consult | 1,300ch complete, copy found after settle |
| default-path (no --select) | turn-1 consult | 421ch, tools=none routed, no +menu stall |
| reval2-#3 extract-correlation | code-audit + single-turn + r5-trace | scroll-fatal + newest-turn-anchor; multi-turn repro blocked by separate tree-conformance (flagged) |
| reval2-#4 grok-new-copy-baseline | code-audit + grok normal-case | pre-send baseline + new-copy-only + fatal-timeout; grok re-validated on 7add819b: ok=true 2,679ch via new-copy baseline |
