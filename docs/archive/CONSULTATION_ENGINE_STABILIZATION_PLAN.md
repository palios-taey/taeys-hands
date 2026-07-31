# Project: consult-engine-stz - Consultation Engine: all 5 platforms hands-off reliable
> THE BAR (Jesse): dispatch a plan → the engine EXECUTES it hands-off; a failure STOPS the process and is communicated back immediately with full root-cause via extraction. "One at a time" = dispatch sequentially (trace each setup→send), but concurrent MONITORS across isolated displays are fine. Builder: taeys-hands-codex (build-only, no browser). Validation: taeys-hands on the real displays (serial dispatch). Gate: my-fleet r5 + production. SEND + MONITOR are now reliable on ALL platforms via shared f5(lock-reclaim)+f8(thread-pin)+f1(long-run monitor) — every lane's send+monitor passes. The dominant REMAINING work is per-platform EXTRACTION + the f11 lock-keying that was force-serializing dispatch.

<!-- Non-negotiable: NO TESTS — production consults / live AT-SPI only. STOP BUTTON = completion. Verify real end-state not flags. First error = full stop + 6SIGMA root-cause (simplify, never patch). Drivers carry ZERO platform knowledge — exact-match YAML only. -->

## Phase: shared - Shared engine (done, benefits all platforms) [order: 1]

### Task: shared-f5 - DONE: orphaned display-lock reclaim (PID+starttime liveness). Merged 58ce76cd, production-validated (real kill-9), r5 [priority: 10] [owner: taeys-hands]
### Task: shared-f8 - DONE: monitor pins post-send answer-thread URL + re-navigates on drift + distinct answer_thread_lost. Merged a18aa549, production-validated hands-off (forced drift), r5 [priority: 10] [owner: taeys-hands]

## Phase: f11-concurrency - Dispatch lock keys on launch-DISPLAY (:0), force-serializing all consults [order: 2] [ref: consultation_v2/primitives.py:89-147]

### Task: f11-build - codex: _plan_lock_key() keys on os.environ['DISPLAY']=:0 (launch env) not the consult's TARGET display, so every consult contends on ONE shared :0 lock regardless of which isolated display it drives (OBSERVED: ChatGPT@:2 held taey:plan_active::0 blocking Gemini@:4). Key the lock on the resolved target display (platform->machine.env, the same source the runtime drives the browser from). Workaround in use: launch each consult with DISPLAY=<target> [priority: 12] [owner: taeys-hands-codex] [ref: consultation_v2/primitives.py:89-147]
### Task: f11-validate - taeys-hands: two consults on different displays run CONCURRENTLY with distinct per-display locks, neither blocks the other; my-fleet r5 + merge [priority: 14] [owner: taeys-hands-codex] [depends: f11-build] [ref: consultation_v2/primitives.py:89-147]

## Phase: chatgpt - ChatGPT (:2): send+monitor OK; extract intermittently flaky [order: 3] [ref: consultation_v2/drivers/chatgpt.py:300-540]

### Task: cg-extract-reliability - codex: ChatGPT extract_primary intermittently fails 'copy button not found / only prompt echo' — the Copy-response button is hover-mounted and the hover probe is unreliable (passed on one run, failed after 5 probes on another). Make extraction robust: read the assistant message text directly from the mapped response container as the primary path (the Copy-response clipboard route as secondary), so extraction does not depend on a flaky hover-mount. Exact-match the response-text container element [priority: 20] [owner: taeys-hands-codex] [ref: consultation_v2/drivers/chatgpt.py:300-540]
### Task: cg-extract-validate - taeys-hands: 3 consecutive ChatGPT consults extract the FULL response hands-off (no manual recovery); my-fleet r5 + merge [priority: 22] [owner: taeys-hands] [depends: cg-extract-reliability] [ref: consultation_v2/drivers/chatgpt.py:300-540]
### Task: cg-monitor-toolcall - codex: ChatGPT does mid-generation TOOL CALLS (Gmail/GitHub connectors, web search) during which the Stop button transiently VANISHES then reappears — the completion detector false-completes on that transient gap (OBSERVED: a Gmail connector tool-call 'Access denied for Gmail' mid-run made monitor report complete while ChatGPT kept generating; f6 only handles the GitHub 'Allow once' MODAL, not the general tool-call stop-vanish or other connectors). HARDEN: ChatGPT completion must require SUSTAINED stop-gone (longer debounce) AND/OR treat a tool-call-in-progress indicator as an intermediate 'keep waiting' state; broaden connector handling beyond GitHub. This is the dominant ChatGPT reliability gap [priority: 18] [owner: taeys-hands-codex] [ref: consultation_v2/drivers/base.py:2040-2120] [ref: consultation_v2/drivers/chatgpt.py:300-540]
### Task: cg-connector-live - taeys-hands: confirm f6 connector-modal disposal (Allow once) on a real connector consult when one naturally triggers it (verified by smoke+exact-match so far, not live) [priority: 30] [owner: taeys-hands] [ref: consultation_v2/platforms/chatgpt.yaml:255-545]

## Phase: gemini - Gemini (:4): DONE [order: 4]

### Task: gemini-done - DONE: f9 URL-capture (/app/<id>) + reassert-before-extract. Merged b2a81ff8; production-validated hands-off (ok=True 8314 chars, real /app/<id> captured, concurrent with ChatGPT) [priority: 10] [owner: taeys-hands]

## Phase: perplexity - Perplexity (:6): send+monitor OK; extract built, needs validation [order: 5] [ref: consultation_v2/drivers/perplexity.py:700-840]

### Task: ppx-f10-validate - taeys-hands: production-validate f10 (commit 3ad55ccb on peer branch — Copy-contents made load-bearing via pre-copy scroll, extraction_failed if clipboard empty). A real Perplexity DR consult extracts the FULL report hands-off (non-empty, >> prompt). Then cherry-pick f10 to main; my-fleet r5 [priority: 20] [owner: taeys-hands] [ref: consultation_v2/drivers/perplexity.py:700-840]

## Phase: grok - Grok (:5): navigate fixed (revised), extract AT-SPI-blind [order: 6] [ref: consultation_v2/drivers/grok.py:82-200]

### Task: grok-f7-verify - taeys-hands: re-verify the f7 REVISION (commit 79d46cf0 — fresh-readiness now requires positive grok.com/ root URL after new-chat + editable empty composer; removed AT-SPI-absence discriminator per r5 HOLD). r5 re-review the positive-signal logic [priority: 20] [owner: taeys-hands] [ref: consultation_v2/drivers/grok.py:82-200]
### Task: grok-f7-validate - taeys-hands: production-validate a grok new-session consult dispatched while :5 holds a prior /c/ thread lands FRESH (root URL, empty composer), sends+completes, not appended to old thread. Then handle grok extract (AT-SPI-blind: response/chip invisible — needs screenshot-or-DOM extract path, NOT AT-SPI absence). Cherry-pick f7 to main; my-fleet r5 [priority: 22] [owner: taeys-hands] [depends: grok-f7-verify] [ref: consultation_v2/drivers/grok.py:82-200]

## Phase: claude - Claude (:3): connector modal + degraded display [order: 7] [ref: consultation_v2/platforms/claude.yaml:190-475]

### Task: claude-capture - taeys-hands: capture the LIVE :3 Claude Research connector-modal AT-SPI tree (exact element names of the Enable-connectors/Confirm flow) so codex can build the intermediate_state. Flag infra if :3 needs a restart (degraded attach/extract/mode-select is an infra issue, not engine code) [priority: 20] [owner: taeys-hands] [ref: consultation_v2/platforms/claude.yaml:190-475]
### Task: claude-connector-build - codex: add the Claude Research connector-modal intermediate_state (exact live names from claude-capture) so the monitor disposes it instead of false-completing (mirror the ChatGPT f6 shape) [priority: 22] [owner: taeys-hands-codex] [depends: claude-capture] [ref: consultation_v2/platforms/claude.yaml:460-475]
### Task: claude-validate - taeys-hands: production-validate a Claude consult sends+monitors+extracts hands-off on a healthy :3; my-fleet r5 + merge [priority: 24] [owner: taeys-hands] [depends: claude-connector-build] [ref: consultation_v2/drivers/claude.py:1-60]

## Phase: all5-sweep - Final all-5 proof [order: 8] [ref: CONSULTATION_CONTRACT.md:1-56]

### Task: all5-sweep - taeys-hands: each of the 5 platforms clears the bar — dispatch a plan, engine executes hands-off, full extract delivered to requester, zero manual recovery. Dispatch sequentially, monitors concurrent. This is DONE only when all 5 pass [priority: 40] [owner: taeys-hands] [depends: cg-extract-validate] [depends: ppx-f10-validate] [depends: grok-f7-validate] [depends: claude-validate] [ref: CONSULTATION_CONTRACT.md:1-56]

## Phase: p6-jesse-defects - Jesse-flagged consult-engine defects (careers R2, 2026-06-24) [order: 9] [ref: consultation_v2/identity.py:45-195]

### Task: defect-chunking-build - codex: REMOVE Claude file-chunking. identity.py:50-51 (_CLAUDE_CHUNK_THRESHOLD_BYTES=45000 / _CLAUDE_CHUNK_TARGET_BYTES=22000) + _write_package_chunks (161-195) split a Claude package >45KB into 22KB _partNNNofNNN.md parts; a 123KB careers package became 6 parts -> 6 attach ops, looks duplicated, and DEGRADES the answer (Claude mid-stream: 'only have chunk 6 in context'). Root-cause shape: DELETE the Claude-special branch in _write_package_chunks so it ALWAYS writes ONE file (Claude.ai accepts a large single .md fine); drop the threshold or raise it far above any real package. Jesse-flagged verbatim: 'there does not need to be chunking of files.' [priority: 16] [owner: taeys-hands-codex] [depends: cg-monitor-toolcall] [ref: consultation_v2/identity.py:45-195]

### Task: defect-chunking-validate - taeys-hands: production-validate a LARGE-attach Claude consult (>45KB package) attaches as ONE file (not N parts) and Claude answers coherently hands-off (no chunk-reassembly confusion); my-fleet r5 + merge. No synthetic test. [priority: 17] [owner: taeys-hands] [depends: defect-chunking-build] [ref: consultation_v2/identity.py:45-195]

### Task: defect-pastechip-build - codex: message text-OR-PASTED-chip send handling (Claude AND ChatGPT). When a long --message pasted into the composer auto-converts to a 'PASTED' attachment chip leaving composer text empty, the send step HANGS (careers-Claude stalled ~23min, never sent). FIX: treat 'message became a PASTED chip + empty composer' as a valid sent-ready state and submit (the chip carries the message), not wait for composer text. Apply to claude.py + chatgpt.py send. Sequenced after chunking-build (both touch claude.py). [priority: 16] [owner: taeys-hands-codex] [depends: defect-chunking-build] [ref: consultation_v2/drivers/claude.py:1-60] [ref: consultation_v2/drivers/chatgpt.py:300-540]

### Task: defect-pastechip-validate - taeys-hands: production-validate a long-message Claude AND ChatGPT consult SENDS hands-off (no hang) whether the message lands as composer text or a PASTED chip; my-fleet r5 + merge. No synthetic test. [priority: 17] [owner: taeys-hands] [depends: defect-pastechip-build] [ref: consultation_v2/drivers/claude.py:1-60]

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
