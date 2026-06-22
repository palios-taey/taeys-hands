# f8 — Monitor must PIN the answer thread — ROOT-CAUSE spec (codex)

**Builder:** taeys-hands-codex. **Gate:** my-fleet r5 + production-validate (taeys-hands). **Date:** 2026-06-22. **Sequence:** build ON TOP of f6 (a4f0fdf8) — both edit `base.py` `monitor_generation`; rebase after f6 merges to avoid conflict.

## Symptom (observed live, 2026-06-22)
A ChatGPT `model=pro` `tools=none` audit (hunter rc-audit, packet attached) executed the ENTIRE plan (navigate→fresh-chat→attach→select→send→monitor_register all ✓) and **generated correctly server-side** — re-navigating to `/c/6a394640` showed real on-topic content still streaming at ~15 min (Stop-answering present). But the engine reported `monitor=False` *"ChatGPT response did not reach Stop-gone completion"* at ~13 min, and the live `:2` tab was on the chatgpt.com **home page** (monitor evidence snapshot showed idle home composer controls).

## Root cause
`monitor_generation` (`consultation_v2/drivers/base.py` ~2040, `_poll`) snapshots **whatever the tab currently shows** and checks `stop_key` presence on it. It does NOT pin the post-send answer thread. So when the live tab navigates away from the answer thread (here: to home — trigger unpinned, likely a ChatGPT SPA reconnect/redirect; NOT the central cycler [none running] and NOT the monitor poll [read-only]), the poll sees no answer-thread Stop button and the detector concludes non-completion — **a FALSE failure of a healthy generation.** Compounding: `result.session_url` was **None** for this run — the engine never captured the submitted `/c/<id>` URL, so it has nothing to pin to.

## Fix shape (root-cause; trigger-agnostic — robust regardless of WHAT navigates the tab)
1. **Capture the answer-thread identity at send.** In the ChatGPT (and shared) send-success path, when the new-chat URL becomes `/c/<id>`, record it on the result/monitor context (the submitted answer-thread URL). This is the pin target. (Fixes the `session_url=None` gap too.)
2. **Pin + re-navigate in the monitor poll.** In `_poll`, before reading `stop_present`: read `runtime.current_url()`; if it has DRIFTED off the pinned answer-thread URL (e.g. to home `/` or another `/c/<other>`), **re-navigate back to the pinned answer-thread URL** (`runtime.navigate(answer_url, verify_change=False)`), settle, re-snapshot, and continue monitoring — do NOT count drift as completion or failure. Bound the re-nav attempts (e.g. small max) so an unrecoverable thread doesn't loop forever.
3. **Distinct mapped failure state.** If the answer thread is genuinely unrecoverable (re-nav repeatedly fails to land back on the pinned `/c/<id>` with the response present), report a DISTINCT `answer_thread_lost` step/state — NOT generic "did not reach Stop-gone." (Per the bar: failures must communicate the PRECISE root cause.)
4. Completion logic otherwise UNCHANGED (Stop present→gone on the *pinned* thread). The f6 intermediate-state handling stays; this adds thread-pinning around it.

## Files
- `consultation_v2/drivers/base.py` ~2040 `monitor_generation`/`_poll` — add pin-check + re-nav (build on f6's edits here)
- `consultation_v2/drivers/chatgpt.py:71-150` `monitor_and_extract` / send path — capture the `/c/<id>` answer-thread URL at send
- `consultation_v2/runtime.py:647` `navigate` / `current_url` — reuse as-is for the pin-check + re-nav

## Validation bar (production, taeys-hands)
A long ChatGPT `tools=none` Pro/Extended generation where the tab is FORCED off the answer thread mid-run (navigate `:2` to home while generating): the monitor must detect drift, **re-navigate back to the pinned thread**, reach true Stop-gone, and extract the FULL response — zero manual intervention. my-fleet r5 + merge.
