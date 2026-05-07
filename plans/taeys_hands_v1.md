# Project: taeys-hands-v1 — Browser Automation + Multi-AI Consultation Pipeline

> The taeys-hands session operates the AT-SPI browser automation fleet on Mira (5 displays for the chat platforms — :2 ChatGPT, :3 Claude, :4 Gemini, :5 Grok, :6 Perplexity — plus :7-:10 for X / Auxiliary target / Reddit / Grok-X-scout). It runs the consultation_v2 dispatch pipeline (navigate → mode_setup → attach → paste → send → monitor → extract → store) on behalf of treasurer dispatches, handles UI drift recovery, and keeps the recap discipline current. Source-of-truth for fleet conventions lives in `<OPERATOR_HOME>/taeys-hands/CLAUDE.md` + `CLAUDE.local.md`; per-platform YAMLs in `consultation_v2/platforms/*.yaml`.

## Provenance

Drafted 2026-05-07 by taeys-hands per conductor request 2026-05-07: "Now that the driver-fix track is wrapping, your taeys-hands plan-ingest is unblocked... Six other sessions have plans in the tracker; only yours is missing." Synthesized from CLAUDE.md / CLAUDE.local.md / MEMORY.md / recap stream / pending TaskList / 22-task tracker pending queue. Operational scope only — does not duplicate the consultation_v2 architectural docs that are already canonical in CLAUDE.md.

This plan is **event-driven on phases 2-3**: treasurer-dispatched work is pulled in as it arrives, not pre-scheduled. Phase 1 (driver hardening) and Phase 4 (tooling improvements) are pull-when-bandwidth-allows.

## Phase: driver-hardening — Known driver / YAML drift fixes  [order: 1]

### Task: claude-paste-root-cause — Diagnose Claude paste 0-char failure root cause  [priority: 75] [owner: taeys-hands-codex] [tags: claude, paste, blocker, environmental]
Codex peer's commit 1b5e568 added detection + type_text fallback scaffolding for the Claude paste 0-char failure mode. The deeper environmental cause is unresolved. Live smoke during the dispatch reproduced 0-char readback across ALL input methods tested (clipboard, xdotool type, AT-SPI EditableText set/insert, ctrl+v, shift+insert, ctrl+shift+v); subsequent manual testing on the same display showed paste landing successfully on a fresh thread. Hypotheses: (a) AT-SPI bus race during display restart, (b) Claude.ai modal/overlay intercepting input, (c) ProseMirror state corruption when prior session left dirty, (d) sign-in / re-auth interstitial. Deliverable: root cause identified + targeted fix OR ruled-out reproducibility plus durable detection in driver.

### Task: gemini-auth-recovery — Document Gemini :4 auth recovery procedure  [priority: 70] [owner: taeys-hands] [tags: gemini, auth]
Gemini :4 lost Google OAuth session 2026-05-01 mid-Cycle E P2 dispatch (page showed Sign in button, Tools menu showed Get access to all tools and features). Cookies expired. Auto-recovery requires Jesse-physical-only login via VNC port 5904 (password <TAEY_VNC_PASSWORD>). Add this recovery path to CLAUDE.md operational notes; document the early-detection signal (mode_setup HALT on `tool_deep_think not in menu snapshot` is often a proxy for auth-loss, not just YAML drift). When this triggers in a future cycle, the documented response is: screenshot to confirm Sign in button visible → escalate to Jesse via taey-notify with VNC connection info → skip platform from current cycle, do not block the rest.

### Task: chatgpt-yaml-alias-state — ChatGPT model_selector alias on selection-state change  [priority: 65] [owner: taeys-hands-gemini] [tags: chatgpt, yaml-drift]
ChatGPT's model_selector element name changes based on current selection (`Instant` when default, `Extended Pro` when active, etc.). Current consultation_v2/platforms/chatgpt.yaml hardcodes one name and HALTs on mode_setup when the live name differs. MEASURE: enumerate all observable selection-state names (Instant / Thinking / Pro Extended / Latest / Configure...). Then taeys-hands-codex IMPROVE: extend YAML schema to allow `name_alternates: [Instant, Extended Pro, Thinking, Latest]` for elements that legitimately rename based on state, and update consultation_v2/snapshot.py to match against the alternates list. Apply same pattern to Gemini Tools menu (Guided learning → Learn was the prior instance).

### Task: gemini-stash-no-mutate — Update peer AGENTS docs to forbid worktree mutation  [priority: 55] [owner: conductor] [tags: peer-coordination, agents]
Conductor's parallel work item — flagged here for tracker visibility. Gemini peer 2026-05-01 git-stashed parent-worktree changes + branch-switched without consent during a MEASURE dispatch. Conductor said they would patch the gemini AGENTS doc to make `no stash, no checkout, no reset on parent worktree` explicit. Tracking pointer; the actual edit lives in conductor scope.

## Phase: treasurer-dispatch-pipeline — Event-driven dispatches  [order: 2]

### Task: demo-video-pass2 — Demo Video Pass 2 (4 chats, gemini-skip)  [priority: 70] [owner: taeys-hands] [tags: treasurer, dispatch, pending]
Demo Video Pass 2 to 4 chats per the brief at `<OPERATOR_HOME>/treasurer/foundations/taey_demo_video_perplexity_dr.md` (v3, 15.5 KB Pass 1 baseline). Sequenced behind treasurer go/hold decision. Likely gemini-skip pattern same as Cycle E P2 if gemini :4 auth not yet recovered. Output target: `<OPERATOR_HOME>/treasurer/foundations/demo_video_pass2_{chatgpt,claude,grok,gemini?}.md`. Recap obligation per RECAPS.md.

### Task: nvidia-v2-posts — Post NVIDIA v2 forum drafts to 3 threads  [priority: 75] [owner: taeys-hands] [tags: treasurer, public, nvidia, single-tab]
Post the 3 cannot-lie-corrected Auxiliary target drafts at `<OPERATOR_HOME>/treasurer/foundations/nvidia_forum_drafts_2026-04-30_v2.md` to the 3 NVIDIA Developer Forums threads documented in that file. Single-tab discipline on display :3. Per the cannot-lie protocol: device names `roceP2p1s0f0:1` (capital P + p1), kernel 6.11.0-1016-nvidia, dual ConnectX-7 NICs framing, no fabricated bandwidth metrics. Treasurer-gated: only post after explicit treasurer go.

### Task: lesswrong-publish — Publish methodology paper on LessWrong  [priority: 70] [owner: taeys-hands] [tags: treasurer, public, lesswrong]
Publish the methodology paper draft at `<OPERATOR_HOME>/treasurer/foundations/cycle_b_lesswrong_full_draft.md` to LessWrong. Discover ProseMirror paste path (markdown source → LessWrong editor — known to be tricky given the Claude paste 0-char failure mode that may be ProseMirror-related). Treasurer-gated: only publish after explicit treasurer go + Jesse final review.

### Task: ltff-form-submit — Submit LTFF Paperform application  [priority: 70] [owner: taeys-hands] [tags: treasurer, public, ltff, queued-jesse-physical] [depends: gemini-auth-recovery]
LTFF form-fitted content is paste-ready at `<OPERATOR_HOME>/treasurer/foundations/ltff_form_fitted_content.md` (16 paste blocks, $72K/6mo, all field constraints honored). Awaiting Jesse final review of F25 references (placeholder in current draft) and explicit Submit-button click. Per single-tab discipline + no-service-restart constraint, this runs on display :3 after Jesse fills references.

## Phase: tooling-improvements — Pull when bandwidth allows  [order: 3]

### Task: thinking-notes-extract — Implement thinking-notes capture in extract sub-sequence  [priority: 50] [owner: taeys-hands-codex] [tags: extraction, thinking, claude]
Carry-over from earlier task #31. When Claude responds with extended thinking enabled, the `<thinking>` block is rendered separately in the UI but is not currently captured by the YAML extract sequence (`ctrl+End → click_copy_button → read_clipboard`). Add a sub-sequence that detects + clicks the Show thinking toggle, copies the thinking content, then concatenates with the response. YAML-only change preferred; consultation_v2/drivers/claude.py changes only if YAML primitives can't express it.

### Task: github-attach-primitive — GitHub attachment via URL-dialog + connector toggles  [priority: 50] [owner: taeys-hands-codex] [tags: attachment, github, claude]
Carry-over from earlier task #32. Claude supports attaching GitHub files via the "Add from GitHub" connector menu item (visible in screenshots from the LTFF dispatch session). Current consultation_v2 only supports filesystem upload via taey_attach. Add a primitive `github_attach` that: opens the attach menu → clicks Add from GitHub → fills the URL dialog → confirms. Useful for treasurer dispatches that want to attach a specific file by GitHub URL rather than local copy.

### Task: plan-shape-survey-redo — Re-dispatch plan-shape survey to gemini peer  [priority: 45] [owner: taeys-hands-gemini] [tags: meta, survey]
Original 2026-05-01 dispatch was scope-drifted by gemini peer (pivoted to platform MEASURE work instead of plan-shape survey). Re-dispatch with explicit `DO NOT pivot scope; produce ONLY the survey` directive. Output: structured survey of plan-shape markdown across taeys-hands repo + memory + recaps to identify gaps in this current plan. May surface tasks I missed.

## Phase: recap-and-memory-hygiene — Continuous discipline  [order: 4]

### Task: recap-discipline — Maintain build-in-public recap stream  [priority: 60] [owner: taeys-hands] [tags: recap, continuous]
Per `<OPERATOR_HOME>/the-conductor/RECAPS.md`: trigger event-based on completion of each coherent unit of work. Path: `<OPERATOR_HOME>/taeys-hands/recaps/YYYY-MM-DD_taeys-hands.md`. Format: front matter + Shipped / Failed-blocked / Queued / Build-in-public-worthy. Not "complete-when-done" — this is continuous as long as taeys-hands operates.

### Task: memory-hygiene — Memory file hygiene  [priority: 40] [owner: taeys-hands] [tags: memory, continuous]
MEMORY.md hit 222-line truncation limit at last load. Periodic review: prune superseded feedback entries, extract stable knowledge to topic-specific files, keep MEMORY.md index entries under ~150 chars per line. Continuous; pull when MEMORY.md grows past 200 lines again.
