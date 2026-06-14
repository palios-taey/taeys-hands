# Driver Contract — consultation_v2 (p0-100times: 100_TIMES.md baked into the driver/base rules)

> Canonical source of these rules is `<OPERATOR_HOME>/taeys-hands/100_TIMES.md` (read it first, every
> session). This file is the operational contract every per-platform driver (p1) and the shared
> base MUST satisfy. Companion: [[PRIMITIVES_CONTRACT]] (what is shared) + [[YAML_SCHEMA]] (exact-match grammar).
> Where this conflicts with 100_TIMES.md, 100_TIMES.md wins.

---

## A. Completion detection — the stop button (100_TIMES §1)
- Submit → `stop_button` appears = generating; `stop_button` disappears = complete. Same on every
  platform; it has never changed. The exact AT-SPI name lives in YAML `element_map.stop_button`.
- **Debounce, don't fallback:** stop-absent → wait → re-scan a FRESH tree → complete only if still
  absent; if it reappears, keep generating. Re-SCANNING is observation (allowed), not a retry.
- **NO fallback completion** ("after 30s assume done if copy buttons exist") — that grabs a PROMPT
  ECHO. If `stop_button` never appears → STOP + RAISE for a YAML fix. Never extract on a guess.

## B. Extraction — scroll to bottom, then the copy-button ELEMENT ACTION (100_TIMES §2)
- One method, every platform, every time: (1) scroll thread to BOTTOM (`ctrl+End`), (2) click the
  `copy_button` via its **AT-SPI element action** (doAction), NEVER raw x/y. Element `y` is
  document-space; coord-clicking a long thread lands off-screen → empty clipboard (LEN 0).
- Claude artifacts: copy the artifact panel, not the chat bubble.
- **Validate the extract is real:** length >> prompt length, content matches the requested lens,
  not a prompt echo. (This is the harvest false-positive guard.)

## C. Exact-match YAML, zero platform knowledge in driver (100_TIMES §3 → [[YAML_SCHEMA]])
- Every element = exact name+role from a live scan. NO name_contains/name_pattern/role_contains/fuzzy;
  `names_any_of` is reserved for exact alternative labels only.
- One YAML + one driver per platform, no overlap, no centralizing. Driver carries ZERO platform
  strings — all names/roles/keys come from its YAML.
- UI drift → FLAG → live-scan → update YAML with the exact new name. That is the whole maintenance loop.

## D. Validate everything against the tree (100_TIMES §4)
- Every action (navigate, model/mode select, attach, send, extract) is confirmed against the live
  AT-SPI tree (and/or screenshot) BEFORE reporting or proceeding. No "I think it sent." Look.
- Validation specs read PERSISTENT elements (toolbar push button with `states_include`), never a
  dropdown item that vanishes on close. (Two scan scopes: `snapshot()` for the document, `menu_snapshot()`
  for React-portal dropdowns/overlays.)

## E. ZERO RETRIES on an action — single failure → STOP + escalate (100_TIMES §4a) — BASE-DRIVER LAW
- A failed ACTION (click/type/send/navigate/attach/mode-select) is retried **exactly zero times**.
  One failure → STOP → escalate to Claude for manual, screenshot-validated, human-paced recovery +
  root-cause (which feeds the YAML/driver fix). **WHY: retry loops are bot-detection signal and get
  accounts BANNED** — more important than landing any single dispatch.
- **BANNED in every driver:** retry-until-present, settle-poll-the-element loops, try-then-fallback
  chains, re-dispatch-on-failure, "try once more". (The current live driver's attach that misses the
  menu then re-clicks to "self-recover" is exactly this anti-pattern — the rebuilt grok/chatgpt drivers
  must NOT re-perform the action; a first-try miss = STOP+escalate, root-caused to the exact-match YAML.)
- **ALLOWED (not a retry):** re-SCANNING the tree (observation, e.g. the §A debounce) and ONE
  readiness wait before a SINGLE action.

## F. One tab per window; never ctrl+t (100_TIMES §5)
- Each display's Firefox holds exactly ONE tab. Navigate the existing tab in-place; conversations
  persist in the platform history sidebar. Stacked tabs make extraction ambiguous.

## G. Dispatch sequentially, NEVER parallel (100_TIMES §6)
- On shared infrastructure, drive platforms ONE AT A TIME: verify page ready → dispatch → validate →
  move on. Firing many at once causes contention (crashed Firefox, raced AT-SPI buses, half-render).
- (The per-supervisor model — each supervisor's own displays, one window each, p3-per-supervisor — is
  what eventually makes concurrency safe: it is isolation, not shared-infra parallelism. Until then: sequential.)

## H. Wake while in flight; never trust the monitor alone (100_TIMES §8a)
- While any dispatch/extract is in flight, `ScheduleWakeup` ~270–300s and actively re-check
  (screenshot + tree). A waiting requester with no delivered result is never acceptable. Turn the
  wake off only after 3 consecutive working monitors PER platform (builds toward task #145).

## I. Send method is per-platform, presence-verify don't coord-click (100_TIMES §11, §8c)
- `send_button` in YAML is for presence-VERIFICATION (it's there ⇒ ready), not necessarily clickable
  (ChatGPT's composer buttons expose no Component/Action → send = focus `input` + Enter). Each driver
  encodes its own send method; the base just provides focus/press/click-element primitives.
- Re-focus the `input` entry immediately before the send keystroke (attach/large-paste steals focus).
- New-session URL gate (100_TIMES via CLAUDE.md Rule 6): for `session=new`, send success requires
  BOTH stop button appeared AND URL changed; follow-up sessions gate on stop button only.

## J. Track everything in git (100_TIMES §10)
- YAML fixes, driver changes, this contract — all committed. Stop losing work to "not tracked".

---
*p1 acceptance: a driver passes this contract only when a real production run (navigate→mode→attach→
send→complete→extract) on the live display obeys A–J with NO retry and NO loose matcher, verified by
screenshot + tree — never by a self-authored test. Production is the oracle.*
