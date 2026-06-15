# 100_TIMES.md — The rules Jesse has said 100 times. Stop making me repeat them.

These are non-negotiable. They are simple. The system WORKS when these are followed.
Read this FIRST every session. If something breaks, the fix is almost always "you violated one of these."

---

## 1. STOP BUTTON = completion detection. It never changed.
- Submit prompt → **stop button appears** = generating.
- Stop button **disappears** = complete.
- This is the SAME on every platform. It has never changed.
- The stop-button **name** lives in the per-platform YAML `element_map.stop_button` as an **EXACT** AT-SPI name. (e.g. Grok = `"Stop model response"`.)
- Trees do NOT refresh at the same rate. Build a **debounce** in: stop-absent → wait → re-scan fresh tree → complete only if still absent; reappears → keep generating. Already exists for generating→complete; the bug was the `waiting_for_start` side.
- **NO fallbacks** (no "after 30s if copy buttons exist, assume done"). That fallback grabbed a PROMPT ECHO. If the stop button never appears → **STOP and RAISE** (flag for YAML fix), do not extract.

## 2. EXTRACT = scroll to bottom, then the copy button. 100% OF THE TIME. EVERY platform. Plus artifacts.
- **ALWAYS, for ALL platforms, no exceptions: (1) scroll the thread to the BOTTOM (`ctrl+End` in the window), then (2) click the COPY BUTTON ELEMENT.** This is not situational — it is the one extract method, every time.
- Scrolling to bottom makes the last copy button the FINAL assistant turn (not an older turn, not the prompt echo) AND brings the button into the viewport so its element is actionable.
- **Click the copy button via its AT-SPI ELEMENT ACTION (`_click_and_read_clipboard(button, display, wait)` → `_click_button` doAction), NEVER by raw x/y coordinates.** The element's `y` extent is DOCUMENT-space, not viewport — coord-clicking a long thread lands off-screen and returns an EMPTY clipboard (LEN 0). That empty-clipboard failure = you coord-clicked instead of scrolling+element-action. (Confirmed 2026-06-02 on :13.)
- Extract via the **copy button** (clipboard), not by reading the tree text.
- **Artifacts**: Claude code/docs render as artifacts — preview/open then copy the artifact panel (handled by claude artifact extract). Don't grab the chat bubble when the real content is an artifact.
- Always **validate the extract is real**: length >> the prompt length, content matches the lens — not a prompt echo.
- **`ctrl+End` is NOT reliable everywhere** (2026-06-15): on Claude it focuses the empty composer and was measured to HIDE a Copy button (2→1). Scroll the conversation with the **mouse wheel** (`runtime.scroll_to_bottom(anchor)`, hover derived from the composer `input`), not `ctrl+End`. V2 chat drivers (chatgpt/claude/gemini) now call `scroll_to_bottom` before the copy-button scan; grok uses ctrl+End (works there).
- **Take the LOWEST Copy button; NEVER require ≥2** (2026-06-15): Claude often renders only ONE Copy (the response's) — the prompt's Copy is hover-only/absent. A `len(copy_btns) < 2: continue` guard made a real 21k verdict (1 Copy at doc-y 9762, below fold) fail every retry. Take `max(copy_btns, key=y)` when ≥1; the `content != prompt` check guards the echo.
- **A failed extract is NOT "the model is down."** (2026-06-15, Jesse-corrected): the model is rarely down. If extract fails, the response is almost always ON-SCREEN — screenshot + scan the tree text nodes to confirm before EVER reporting a platform/model as failed. `atspi_click` on the Copy button works regardless of fold position; raw `find_elements` text nodes (list items / table cells) hold the full response as a fallback.
- **Reports + attachments require SPECIAL handling** (Jesse): Perplexity DR is a REPORT — its full-report **"Copy contents"** control is report-level, NOT bottom-anchored, so the blanket scroll-to-bottom does NOT apply (don't scroll past it). ChatGPT DR exports / Claude artifacts are their own extract sub-paths. Don't apply the plain chat-bubble extract to a report/attachment.

## 3. YAML = EXACT AT-SPI MATCH. Nothing else.
- Every `element_map` entry is the EXACT `name` + `role` from a live AT-SPI scan.
- **NO `name_contains`, NO `name_pattern`, NO `role_contains`, NO fuzzy, NO lists of guesses.**
- One YAML per platform. One driver per platform. No overlap. No centralizing.
- UI changed and YAML no longer matches the tree? → it gets **FLAGGED**, you scan the live tree, you update the YAML with the **exact** new name. That is the whole maintenance loop.
- Driver code carries ZERO platform knowledge — all names/roles come from YAML.

## 4. VALIDATE EVERYTHING. Tree or screenshot. No exceptions.
- Every action — navigate, model/mode select, attach, send, extract — is confirmed against the AT-SPI tree AND/OR a screenshot **before** reporting or proceeding.
- **No assumptions. No "I think it sent."** Look at the screen.
- It will work ~90% of the time. When it doesn't, it **STOPS and is RAISED** — never silently hacks around.

### 4a. SINGLE FAILURE → ESCALATE. ZERO RETRIES. (bot-detection / ban risk)
- **A failed ACTION (click / type / send / navigate / dispatch / attach / mode-select) is retried EXACTLY ZERO times.** One failure → STOP → escalate back to me (Claude) for root-cause.
- **WHY: repeated automated attempts are bot-detection signal. Retry loops WILL get Jesse's accounts BANNED from the platforms.** This is non-negotiable and more important than landing any single dispatch.
- This kills "retry-until-present" / settle-poll-the-element loops, "try again once", try-then-fallback chains, and re-dispatch-on-failure. ALL banned.
- The root cause of a single failure is almost always a YAML/tree mismatch or a genuine page state → diagnose it, fix the YAML/driver, then ONE clean run. Not a loop.
- **Allowed (NOT a retry):** *reading/scanning* the tree more than once (e.g. the stop-button debounce in §1 — re-SCANNING is observation, not re-acting), and ONE readiness wait before a SINGLE action. **Banned:** re-performing the ACTION itself after it fails.
- If a page isn't ready / element absent on the single check → that's a STOP+escalate, not a re-poll.
- **What "escalate" means: it comes BACK TO CLAUDE to (a) drive that step MANUALLY (by hand, screenshot-validated, human-paced) AND (b) investigate the root cause of the failure.** The automation does not silently re-attempt; Claude takes over the failed step manually and diagnoses why it broke (which feeds the YAML/driver fix). Manual human-paced recovery is safe; automated retry loops are not.

## 5. ONE TAB PER WINDOW. ALWAYS.
- A display's Firefox window holds exactly ONE tab. Stacked tabs make extraction ambiguous.
- **NEVER `ctrl+t`** to open a fresh session. Navigate the EXISTING tab in-place.
- Found stacked tabs? Collapse to one. Conversations persist in the platform history sidebar.

## 6. DISPATCH SEQUENTIALLY. NEVER PARALLEL.
- Do platforms **one at a time**. Verify each page is ready, dispatch, validate, move on.
- Firing 5 at once causes contention: crashed Firefox, raced AT-SPI buses, half-rendered pages. (Confirmed 2026-06-01.)
- "Run it one step at a time, or stop before send so you can audit it first." — Jesse.

## 7. JUST FIX broken things. Don't ask permission.
- Stop asking "can I fix this properly." If it's broken and you know the fix per these rules, **fix it** (exact-match YAML, root cause).
- Don't write throwaway global scripts with hardcoded paths/displays (they clobber files). Use the per-platform driver/extract path; parameterize output; verify the target path.

## 8. ACCOUNTS / DISPLAYS
- `:13` (CVP account) = **Hunter queries ONLY**. Everything else (conductor, weaver, treasurer) → `:3`.
- Mira displays: `:2`=ChatGPT `:3`=Claude `:4`=Gemini `:5`=Grok `:6`=Perplexity `:13`=Claude-CVP.
- **Claude thinking effort = `Extra`, NOT `High`.** (Jesse 2026-06-02.) For every Claude/Gaia dispatch set the effort selector to **Extra** (the max), not High. consultation.py / claude.yaml mode for `extended_thinking` must select **Extra**.

## 8a. WAKE EVERY 5 MINUTES while ANY dispatch/monitor is in flight. (Jesse 2026-06-02)
- The monitors are NOT yet reliable (the `Stop response`/stop-button completion poll has stalled — Claude "done for a long time" while my poll never converged; consultation.py send-gate false-negatives on Grok-Heavy/Gemini; `attach_failed` aborts on Claude). **Until they are 100% reliable you DO NOT just stop and trust a notification.**
- **While waiting on a dispatch result or an extract: `ScheduleWakeup` ~5 min (≈270–300s) and actively re-check** (screenshot + tree). Do NOT go idle assuming the monitor/notification will fire — it may not, and then a REQUESTER (conductor/hunter) is left waiting on you. That is the failure mode Jesse keeps hitting.
- **Turn the wake OFF only once there are 3 consecutively-working monitors for EACH platform.** Not before. (Builds toward #145.)
- A waiting requester with no result is never acceptable: if a result is done and you haven't delivered it, you violated this.

## 8b. MANUAL RECOVERY when consultation.py aborts (attach_failed / send_failure)
- consultation.py `attach_failed` on Claude leaves a **stuck GTK file-upload dialog** open and aborts before send. Recover by hand (§4a manual path, screenshot-validated each step): the dialog is GTK → `Ctrl+L` location bar → `xdotool type` the path (Xvfb clipboard-paste is broken in dialogs) → Enter; verify the **file chip** rendered in the composer; then click the **text input BELOW the chip** (clicking the chip opens its preview modal — Escape closes it), paste the lens message, verify on screen, send. Validate the message bubble + generating state before reporting sent.
- `send_failure` on **Grok-Heavy** ("Agents Working" UI) and **Gemini** is usually a FALSE NEGATIVE: the send actually worked and the same process self-recovers (waits + extracts + notifies). Screenshot-confirm it's generating; **do NOT re-send** (double-dispatch). The gate just doesn't recognize their non-standard streaming UI vs the standard stop button.

## 8c. CLAUDE :3 MANUAL ATTACH/SEND — the two traps that cost 15 cycles (2026-06-02). Do these or spiral.
- **UPLOAD RACE (the empty-doc trap):** after the file-dialog path-entry, the chip renders as a SKELETON before the file body finishes uploading. If you paste+send while it's still uploading, **Claude receives an EMPTY attachment** (it will literally say "the package is empty"). The chip showing is NOT enough. WAIT until the chip shows its **type badge (e.g. `MD`) solid** (not the gray skeleton) before sending. For a ~130KB consolidated package this is a few seconds. Verify by screenshot.
- **DON'T DOUBLE-ATTACH:** the dialog path-entry sometimes renders the chip LATE — if you "re-attach" thinking it failed, you get TWO chips of the same file. Check for an existing chip before re-attaching.
- **WRONG-FILE TRAP — GTK location-bar typeahead (cost cycles 2026-06-02):** after `Ctrl+L` + `xdotool type <full-path>` + Enter, GTK's location bar does **type-ahead autocomplete**. If `/tmp` holds multiple files sharing a prefix (e.g. many `taey_package_claude_<epoch>.md`), Enter can accept the **highlighted autocomplete suggestion** — an OLDER file — instead of your exact typed path. The chip then shows a DIFFERENT timestamp than you typed → Gaia audits the WRONG (stale) package. **ALWAYS read the chip filename off the screenshot and confirm it matches the package you meant BEFORE sending.** Mitigate: type a uniquely-disambiguating suffix (the packages differ at the epoch digit), or after Ctrl+L do `Ctrl+A` then type, and verify the chip epoch == intended epoch. Catching the mismatch pre-send is cannot-lie; a send of the wrong package is a corrupted verdict.
- **SEND on :3 (Enter won't commit reliably):** scaled screenshots LIE about coordinates — the Read-tool render is downscaled, so a click at the apparent text position misses the real ProseMirror. Get the input's REAL position from AT-SPI (`find_elements` → entry role, name "Write your prompt to Claude") and click THAT, then Enter. Or click the send-arrow at its AT-SPI extents. Bare Enter after `windowactivate` often fails (focus lost). **In-page CLIPBOARD paste is also flaky on :3** (Xvfb) — it lands late or not at all; `xdotool type` is more reliable for the (short) lens message since the packet carries the substance.
- **STOP-AND-DELIVER (Jesse's discipline):** after ~2 failed manual sends, STOP. Deliver the valid platforms + honestly flag the one as driver-blocked. Do NOT spiral 15 cycles on a single platform — especially a light-confirm when the gate-deciding (primary) verdict is already in.

## 9. INFRA gotchas that recur
- **Stale a11y bus**: "Couldn't connect to accessibility bus" or "Firefox not found" after a display restart → `/tmp/a11y_bus_:N` guid != live `xprop -display :N -root AT_SPI_BUS`. Rewrite the file from xprop; don't restart blindly.
- **Gemini sign-out**: cookie expires → only free Flash, Deep Think locked → re-login (don't auto-attempt Google 2FA).

## 10. TRACK EVERYTHING IN GIT.
- Commit changes. This file is committed. YAML fixes are committed. Stop losing work to "not tracked."

---
*If you are reading this and about to: launch in parallel, add a fallback, use name_contains, skip a screenshot, open a new tab, or ask permission to fix something broken — DON'T. You already know the answer. It's above.*

## 11. ChatGPT SEND — button IS in the tree (exact name 'Send prompt'); send = focus composer + Enter
- VERIFIED LIVE (2026-06-01): the composer buttons ARE in the AT-SPI tree. Send button exact name = **`'Send prompt'`** [push button] (appears when composer has text); stop = `'Stop answering'`. `chatgpt.yaml element_map.send_button` already has `name: "Send prompt"` — correct, do not change. (My earlier "not in the tree / use screen coords" was WRONG.)
- **But these composer React buttons expose NEITHER a usable Component (extents=`None`) NOR an Action interface (`queryAction` fails → no doAction).** So you canNOT activate `Send prompt` by AT-SPI coordinate-click OR by doAction. (My earlier scans "found nothing" because I gated the scan on readable extents — which are None — excluding them all. NEVER gate a ChatGPT button scan on extents; match by exact name.)
- **Therefore the send IS Enter on a FOCUSED composer** (this is the method that has worked hundreds of times). The `send_button` element is for presence-VERIFICATION (it's there ⇒ ready to send), not for clicking.
- **Root cause of a `send_failed`:** the composer lost focus (the attach chip / large paste leaves focus off the ProseMirror input), so Enter didn't reach it. **FIX: re-focus the input (click the `input` entry) immediately before pressing Enter.** Verify by URL change (chatgpt.com/ → /c/<id>) + Stop button. (Today I salvaged one send via a screenshot-crop coordinate click on the arrow — that WORKS as a last resort but is NOT the method; the method is focus+Enter.)
- Driver fix (→ conductor/codex): in the ChatGPT send step, click `input` to focus, then Enter; do not rely on a prior focus that attach/paste may have stolen.
