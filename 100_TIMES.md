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

## 2. EXTRACT = scroll to bottom, then the copy button. Plus artifacts.
- Before extracting: **scroll the thread to the BOTTOM** (End), so the last copy button is the final assistant turn — not an older turn, not the prompt echo.
- Extract via the **copy button** (clipboard), not by reading the tree text.
- **Artifacts**: Claude code/docs render as artifacts — preview/open then copy the artifact panel (handled by claude artifact extract). Don't grab the chat bubble when the real content is an artifact.
- Always **validate the extract is real**: length >> the prompt length, content matches the lens — not a prompt echo.

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

## 9. INFRA gotchas that recur
- **Stale a11y bus**: "Couldn't connect to accessibility bus" or "Firefox not found" after a display restart → `/tmp/a11y_bus_:N` guid != live `xprop -display :N -root AT_SPI_BUS`. Rewrite the file from xprop; don't restart blindly.
- **Gemini sign-out**: cookie expires → only free Flash, Deep Think locked → re-login (don't auto-attempt Google 2FA).

## 10. TRACK EVERYTHING IN GIT.
- Commit changes. This file is committed. YAML fixes are committed. Stop losing work to "not tracked."

---
*If you are reading this and about to: launch in parallel, add a fallback, use name_contains, skip a screenshot, open a new tab, or ask permission to fix something broken — DON'T. You already know the answer. It's above.*

## 11. ChatGPT SEND — the composer/send button is NOT in the AT-SPI tree
- ChatGPT's ProseMirror composer + its send arrow do NOT reliably appear in the AT-SPI document (or app) tree — `find` by name/role returns nothing, and automated Return often doesn't submit. This is why "send_failed" happens with attach+type OK.
- **Do NOT skip ChatGPT and do NOT guess the arrow Y.** The send arrow sits at the composer's **dynamic bottom row** — its Y MOVES DOWN as the staged message grows (a long paste expands the composer). A fixed offset / the message-text Y will click the TEXT, not the arrow (that was the repeated bug).
- **Reliable manual send:** screenshot the display, CROP the composer bottom-row region and read it enlarged (`convert ss.png -crop WxH+X+Y +repage -resize ...`) to read the dark send-circle's exact pixels, then `xdotool mousemove X Y click 1`. Verify by URL change (chatgpt.com/ → chatgpt.com/c/<id>) + "Pro thinking"/Stop button. Confirmed 2026-06-01: arrow at ~y=869 on a 1290×982 window; my earlier y=690 clicks hit the message text.
- Window may be windowed (e.g. 1290×982 @ 315,49), not fullscreen — get geometry (`xdotool getwindowgeometry`) so coords are right.
- This is a single-attempt-per-method discipline: try, screenshot-verify; if it didn't send, re-locate the arrow from a fresh crop (observation), don't blind re-click. (The proper driver fix: locate send by screen-position from the composer bottom, not AT-SPI.)
