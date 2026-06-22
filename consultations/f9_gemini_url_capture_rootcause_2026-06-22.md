# f9 — Gemini send captures the generic /app URL, not the conversation URL — ROOT-CAUSE spec (codex)

**Builder:** taeys-hands-codex. **Gate:** my-fleet r5 + production-validate (taeys-hands). **Date:** 2026-06-22. **Depends:** sequence after f7 (one task per peer); independent files from f7 (gemini.py vs grok.py).

## Symptom (observed live, 2026-06-22)
A Gemini Pro-Thinking consult (rc-audit-d4218-gemini) executed the full plan — navigate→select→attach→send→monitor_register→**monitor_answer_thread=True**→**monitor=True** (generated + completed) — then failed at `extract_primary: "Gemini copy button not found."` At extract time `:4` was on the Gemini **home/new-chat page** (`gemini.google.com/app`, "The mic is yours, Jesse", empty composer), not the answer conversation. The response was unrecoverable by URL.

## Root cause
`result.session_url_after` for Gemini was captured as **`https://gemini.google.com/app`** — the **generic app/home URL**, NOT a unique conversation URL. Every other platform captures a real conversation URL (ChatGPT `/c/<id>`, Claude `/chat/<id>`, Grok `/c/<id>`, Perplexity `/search/<id>`), which is why f8's thread-pin works for them. For Gemini:
1. **f8 thread-pin is a NO-OP** — `_urls_equivalent(current, '.../app')` is trivially true even on the home page (both are `/app`), so `monitor_answer_thread` "passes" without actually verifying the conversation.
2. When the tab resets to a new chat (Gemini-side, or any drift), the conversation is **not URL-addressable** (only `/app` was captured), so extract lands on the home page → no copy button → fail.

(Gemini's per-turn copy control is also hover-mounted — but that's moot until the tab is actually ON the conversation; the URL-capture defect is upstream.)

## Fix shape (codex — Gemini send step)
1. **Capture the real conversation URL after it settles.** In `consultation_v2/drivers/gemini.py` `send_prompt` (~267 `result.session_url_after = after or self.runtime.current_url()`), Gemini assigns a `gemini.google.com/app/<conversation-id>` URL shortly AFTER the first response begins — poll/settle `current_url()` until it becomes a real conversation URL (`/app/<id>`, not bare `/app`) before recording `session_url_after`. Use a bounded settle (e.g. `wait_until` for a `/app/<id>` shape, small timeout).
2. **Gemini `_is_answer_thread_url` / predicate** must distinguish bare `/app` (NOT an answer thread) from `/app/<id>` (IS one), so f8's reassert can detect drift and re-navigate correctly. (Mirror chatgpt `_is_answer_thread_url` `/c/` substring → gemini `/app/<id>` with a non-empty id segment.)
3. **OPEN QUESTION for codex to resolve at build:** confirm Gemini actually assigns a `/app/<id>` URL for a conversation (it does for saved chats). If a given conversation genuinely stays on bare `/app` (client-side state, no URL), then URL-pinning cannot work and the fallback is: do NOT navigate away during monitor/extract for Gemini (keep the tab put) + recover via the most-recent history entry. Determine which during the build by watching a live Gemini conversation's URL.
4. **Extract thread-pin (shared, benefits all):** the EXTRACT phase currently runs without f8's thread-pin — a drift between monitor-complete and extract loses the conversation. Consider extending the reassert to a pre-extract check (re-navigate to the pinned conversation URL before `extract_primary`). This helps every platform, not just Gemini.

## Files
- `consultation_v2/drivers/gemini.py:267` — `send_prompt` URL capture (settle to `/app/<id>`)
- `consultation_v2/drivers/gemini.py` — `_is_answer_thread_url` (distinguish `/app` vs `/app/<id>`)
- `consultation_v2/drivers/base.py` — optional: pre-extract thread reassert (shared)

## Validation bar (production, taeys-hands)
A Gemini Pro-Thinking consult: `session_url_after` is a real `/app/<id>`; the tab forced off the conversation mid-run is re-navigated back; monitor completes; extract returns the FULL response hands-off. my-fleet r5 + merge.
