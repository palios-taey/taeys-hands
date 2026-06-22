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

## Phase: f5-lock-reclaim - Display-lock survives kill/crash (orphan-on-kill) [order: 5] [ref: consultation_v2/primitives.py:104-160]

### Task: f5-build - codex: orphaned display-lock blocks the next dispatch on that display because release lives in a `finally` that SIGTERM/SIGKILL/crash bypass (1hr TTL stuck). Root-cause shape: record holder PID (+ start time) in the lock payload; `acquire_display_lock` reclaims when the recorded holder is provably dead (not alive) — NO blind steal of a live lock, NO short-TTL band-aid [priority: 18] [owner: taeys-hands-codex] [ref: consultations/f5_orphaned_lock_rootcause_2026-06-22.md:1-40] [ref: consultation_v2/primitives.py:89-147] [ref: consultation_v2/drivers/base.py:1455-1486]

### Task: f5-validate - taeys-hands: production-validate — kill a mid-setup lane, confirm the NEXT dispatch on that display acquires (no dispatch_lock failure) AND a genuinely-live holder is still NOT stolen; my-fleet r5 + merge [priority: 19] [owner: taeys-hands] [depends: f5-build] [ref: consultation_v2/primitives.py:104-160]

## Phase: f6-connector-modal - Connector-permission modal is a mapped state, not a false-complete [order: 6] [ref: consultation_v2/completion.py:1-100]

### Task: f6-build - codex: a platform connector-permission modal (ChatGPT "Allow ChatGPT to use GitHub?"; Claude Research "Enable connectors") makes the Stop button vanish mid-run → the Stop-gone completion detector FALSE-COMPLETES and extraction then finds no finished message. Map the connector modal as a known intermediate state (exact AT-SPI names per platform YAML): for connector-required audits, dispose deterministically (Allow once) and KEEP waiting; never count it as completion [priority: 24] [owner: taeys-hands-codex] [ref: consultation_v2/platforms/chatgpt.yaml:240-260] [ref: consultation_v2/completion.py:1-100]

### Task: f6-validate - taeys-hands: production-validate a real git-connector repo-audit consult drives THROUGH the modal to a true completion + correct extract, zero manual click; my-fleet r5 + merge [priority: 25] [owner: taeys-hands] [depends: f6-build] [ref: consultation_v2/drivers/chatgpt.py:1-60]

## Phase: f7-grok-navigate - Grok navigate on a stale /c/ thread [order: 7] [ref: consultation_v2/drivers/grok.py:1-80]

### Task: f7-nav-diagnose - taeys-hands: diagnose the grok @navigate failure when :5 still holds a prior /c/ thread — is it a navigate-validation false-negative or a real failed nav? Capture live AT-SPI + screenshot evidence, then route the exact root-cause shape to codex (clean-nav precondition vs corrected validation) [priority: 28] [owner: taeys-hands] [ref: consultation_v2/drivers/grok.py:1-80]

### Task: f7-build - codex: grok new-session navigate must start a FRESH chat (grok.com/ restores the last /c/ thread; verify correctly refuses it). Add a new-chat affordance (map exact "New Chat"/"New conversation" link or Ctrl+J in grok.yaml element_map) for session_url-is-None; trigger it, then validate readiness on the COMPOSER (input present+editable+empty, no prior answer content) — not on bare-root URL equality. Leave the follow-up /c/<thread> path unchanged [priority: 30] [owner: taeys-hands-codex] [depends: f7-nav-diagnose] [ref: consultations/f7_grok_navigate_rootcause_2026-06-22.md:1-40] [ref: consultation_v2/drivers/grok.py:82-114]

### Task: f7-validate - taeys-hands: production-validate a grok new-session consult dispatched while :5 holds a prior /c/ thread — lands on a FRESH chat (empty composer, no restored content), sends+completes, response NOT appended to the old thread; zero manual intervention; my-fleet r5 + merge [priority: 32] [owner: taeys-hands] [depends: f7-build] [ref: consultation_v2/drivers/grok.py:82-114]

## Phase: f8-monitor-thread-pin - Monitor must pin the answer thread (tab-navigation false-fail) [order: 8] [ref: consultation_v2/drivers/base.py:1899-1978]

### Task: f8-diagnose - taeys-hands: OBSERVED 2026-06-22 — a ChatGPT Pro audit executed the full plan and generated correctly SERVER-SIDE (~15min, real content on /c/6a394640), but the live :2 tab navigated to chatgpt.com HOME mid-generation; the monitor (polling the navigated-away home tab) saw no answer-thread Stop button and false-failed 'did not reach Stop-gone completion'. Ruled OUT: central cycler (none running) + monitor poll (read-only). UNPINNED: the home-navigation trigger (likely a ChatGPT SPA reconnect/redirect). Pin the trigger if reproducible; capture live evidence [priority: 26] [owner: taeys-hands] [ref: consultation_v2/drivers/base.py:1899-1978]

### Task: f8-build - codex: monitor must PIN the post-send answer-thread identity (the submitted /c/<id> URL captured at send) and, each poll, verify the live tab is still on it; on drift (tab navigated away / home) RE-NAVIGATE back to the answer thread and continue monitoring rather than concluding non-completion. A genuinely-lost thread is a DISTINCT mapped state ('answer_thread_lost'), not generic 'did not reach Stop-gone'. Root-cause shape: the answer-thread URL is already known post-send; bind the monitor to it [priority: 28] [owner: taeys-hands-codex] [depends: f8-diagnose] [ref: consultations/f8_monitor_thread_pin_rootcause_2026-06-22.md:1-40] [ref: consultation_v2/drivers/base.py:1899-1978] [ref: consultation_v2/drivers/chatgpt.py:71-150]

### Task: f8-validate - taeys-hands: production-validate a long ChatGPT Pro/Extended generation where the tab is forced off the answer thread mid-run — monitor must re-navigate + still reach true Stop-gone + extract the full response; my-fleet r5 + merge [priority: 30] [owner: taeys-hands] [depends: f8-build] [ref: consultation_v2/drivers/base.py:1899-1978]

## Phase: f9-gemini-url - Gemini send must capture the conversation URL, not generic /app [order: 9] [ref: consultations/f9_gemini_url_capture_rootcause_2026-06-22.md:1-40]

### Task: f9-build - codex: Gemini send captures session_url_after = generic https://gemini.google.com/app (home) instead of the /app/<conversation-id>, so f8 thread-pin is a no-op for Gemini and the response is lost when the tab resets to a new chat (extract_primary 'copy button not found' on the home page). Settle current_url() post-send to a real /app/<id> before recording; make gemini _is_answer_thread_url distinguish bare /app from /app/<id>; resolve the open question (does Gemini assign /app/<id>? if not, keep-tab-put + history recovery). Consider extending f8 thread-pin to the pre-extract phase (shared) [priority: 34] [owner: taeys-hands-codex] [depends: f7-build] [ref: consultations/f9_gemini_url_capture_rootcause_2026-06-22.md:1-40] [ref: consultation_v2/drivers/gemini.py:260-275]

### Task: f9-validate - taeys-hands: production-validate a Gemini Pro-Thinking consult — session_url_after is a real /app/<id>, tab forced off conversation mid-run re-navigates back, monitor completes, extract returns FULL response hands-off; my-fleet r5 + merge [priority: 36] [owner: taeys-hands] [depends: f9-build] [ref: consultation_v2/drivers/gemini.py:260-275]

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
