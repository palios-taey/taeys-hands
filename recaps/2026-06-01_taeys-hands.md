# taeys-hands — Family-dispatch delivery + driver-reliability discipline
## 2026-06-01

**Voice:** taeys-hands (browser automation / AT-SPI driver + Family-Chat dispatch conduit)
**Scope:** delivered three conductor Family audits + a hunter synthesis across the 5 Chats; authored the recurring-rules canon; root-caused several per-platform driver bugs; started the ChatGPT YAML map. Every claim below traces to a commit or a live artifact (cannot-lie).

---

### Shipped
- **4 multi-Chat dispatches delivered + harvested** (one platform at a time where the auto-path was unreliable; screenshot-validated; no prompt-echoes shipped):
  - Hunter **Sprint-8 novel-approach synthesis** — 5/5 (Clarity/Horizon/Logos/Cosmos/Gaia-CVP). Surfaced a real 4-vs-1 split (RoCEv2-RPC-fuzz moat vs Claude-CVP "moat is irrelevant, use single-process ASAN, verify payability first").
  - Conductor **keystone stop-discipline audit** — 5/5.
  - Conductor **adoption-design review** — 5/5.
  - Conductor **p2 ref-pointer + lifecycle audit** — 4/5 (Grok deferred on its mode-select bug).
- **`100_TIMES.md`** authored + committed (`5b33a63`, `118a9cc`) + wired into CLAUDE.md (`a4b1da8`): the recurring rules — stop-button completion detection; scroll-to-bottom + copy-button (+artifacts) extract; **exact-match YAML only** (no name_contains/fallbacks); validate every action by tree/screenshot; **one tab per window**; **dispatch sequentially, never parallel**; **zero automated retries → single failure escalates to manual + RCA (bot-detection / ban risk)**.
- **`grok.yaml` stop_button fixed** to the single exact live AT-SPI name `Stop model response` (was 4 made-up names matching nothing → let a 30s copy-button fallback grab a prompt-echo). Validated live ("Stop button appeared").
- **Stale a11y-bus-file root cause** found + fixed (`/tmp/a11y_bus_:N` guid drifts vs live X `AT_SPI_BUS` after a display restart; rewrite from xprop, don't restart blindly) — memory `feedback_stale_a11y_bus_file`.
- **`p1-chatgpt-map` started** (`9c46357`, `020cce4`): ChatGPT composer element map captured live — `Switch model` (model picker) vs `Extended Pro` (mode toggle) are TWO distinct buttons the YAML had conflated; `Add files and more` (attach), `Copy response` (extract).

### Failed / blocked
- **Per-platform driver bugs** (the real "make it work" blockers, all now pinned): Grok `attach_trigger` opens the nav menu not file-upload; Grok mode-select **cold-start render race**; Claude attach (ctrl+u / toggle_menu) opens the wrong menu + leaves a stuck file dialog; **automated SEND flaky on ChatGPT + Grok** (manual click works); `switch_to_platform` unreliable (direct per-display AT-SPI extract works).
- **`p1-chatgpt-map` enumeration blocked** (`blocker-found`): composer model/mode controls read **intermittently** from the AT-SPI tree — needs a settled fresh-composer + single readiness-check before the one click.
- **My own discipline failures, corrected by Jesse mid-session** (logged so they don't recur): automated re-dispatches of Grok/Perplexity (ban-risk retries — now hard-banned by rule 4a); Ctrl+T tab-stacking; a double-paste; a hardcoded-path throwaway script that clobbered the hunter Claude file.
- 5-simultaneous dispatch caused contention (crashed Gemini's Firefox) → confirmed the **dispatch-sequentially** rule.

### Queued
- Finish `p1-chatgpt-map` enumeration on a settled composer (single readiness-check → one click → scan; models / reasoning levels / tools / connectors).
- Driver fixes (#145 + attach/send/mode-select): root-cause shapes per `100_TIMES` — e.g. Grok mode-select needs a **single readiness-wait, not a retry loop**.
- Weaver's ISMA **p1-family full-code audit** dispatch (packet incoming) — run sequentially.

### Build-in-public worthy
- **`100_TIMES.md` — discipline-as-code.** What it actually takes to make undetectable AT-SPI multi-AI dispatch reliable isn't cleverness; it's exact-match-to-the-live-tree, validate-everything, and never papering over drift with fallbacks.
- **Zero automated retries as a ban-avoidance principle.** Repeated automated attempts read as a bot and get accounts banned — so a single failure must stop and escalate to a human-paced manual recovery + root-cause, never a loop. (Counterintuitive: the *safe* automation refuses to retry.)
- **Monitor completion-detection is conceptually trivial** — stop button present = generating, gone = complete — and stays trivial *if* the YAML name is the exact live one and you debounce for tree-refresh timing. The bugs come from drift + fallbacks, not from the idea.
- **"Genuinely-actionable only" orchestration** (became design req D4): an auto-continue engine should nudge a worker only toward tasks in its lane with inputs present — not just pending+owned. Refusing irreversible public posting from an auto-nudge is correct every time.
