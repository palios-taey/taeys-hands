# Capability Gaps — taeys-hands consult surface

Durable record of capability gaps that, if left unrecorded, get filled privately by whoever hits
them (per tutor, 2026-07-30: "A gap nobody records gets filled by whoever hits it, privately, every
time"). Recording the gap lets the next person close it properly instead of rebuilding a workaround.

Each gap: what's missing, the workaround it induces, the anti-pattern risk, and the proper fix.

**Status (2026-07-30):** GAP-1 and GAP-2 are being closed together in one codex branch
(task-9f27db5f, taeys-hands-codex) — they are two halves of one capability ("drive deepest-mode
consults on any healthy display") and touch the same engine files, so splitting them across two
branches would self-collide. The standalone GAP-2 task (task-e5c16415) was retired/folded.

---

## GAP-1: Taey seat cannot select deepest reasoning mode per platform

**Missing:** `consultation_v2/taey_extract.py` (the Taey autonomous seat) drives attach → prompt →
submit → extract, but has NO semantic step to SELECT each platform's deepest reasoning mode
(Claude Opus-Extended, ChatGPT Pro-thinking, Gemini Pro-thinking/Deep-Research, Grok Heavy,
Perplexity Deep-Research) before submit.

**Workaround it induces:** for any consult that requires deepest mode (most livelihood-critical
training consults do), Taey can't be used, so the lane is hand-driven via `act.py`
(navigate/click/type/paste/scrot-extract).

**Anti-pattern risk:** that hand-driving IS an ad-hoc driver re-implementing what
`scripts/run_consultation_v2.py` already does — the "missing helper → private path alongside the
working engine" disease (tutor, 2026-07-30; cost elsewhere in the fleet: 3 days, 2 NCCL-wedged runs).

**Proper fix (codex task, Rule 7):** add a platform-agnostic `select_mode` semantic step to the seat
state machine, resolving each platform's mode control from its YAML `element_map`/`workflow` (same
pattern as the attach generalization merged in 6d9c9ad8 / paste-path fix 1b4cbfff). Production-verify
each platform; taeys-hands merges.

---

## GAP-2: Taey seat / consult engine routing is bound to the primary display set only

**Missing:** the seat's platform→display routing (`consultation_v2/platforms/<p>/routing.py`,
`_routing_core.py`) binds each platform to its PRIMARY-set display (`:2`–`:6`). The SECOND display
set (`:20`–`:24`) is not wired into that routing. Observed failure: `run_taey_consult_extract.py
--platform perplexity --display :24` raised `perplexity route binding mismatch: expected DISPLAY
':6', got ':24'`.

**Workaround it induces:** when the primary display is broken (Grok `:5` persistent a11y fault) or
shared (Perplexity `:6` shared with careers Deep-Research), the seat can't reach a healthy second-set
display (`:23`/`:24`), so the lane is hand-driven on the second set instead.

**Anti-pattern risk:** same as GAP-1 — hand-driving fills the routing gap privately.

**Proper fix (codex task, Rule 7):** wire the second display set into the platform routing so the
seat accepts `:20`–`:24` for the matching platform (env-overridable, like the careers runner-B
`PLATFORM_DISPLAYS`). Production-verify; taeys-hands merges.

---

## The canonical dispatch tool (do NOT rebuild)

`python3 scripts/run_consultation_v2.py --platform <p> --message <framing> [--attach <file>]
[--select <menu>=<option>] --requester <node>` is the ONLY live consult engine (README.md:14).
It works by observation. Do NOT hand-build a driver around it with `act.py`. If it fails, report the
exact command + error and STOP — do not bypass. Hand-driving is only justified when the seat/engine
genuinely cannot reach a required mode/display (GAP-1/GAP-2 above) — and in that case, the gap is the
bug to fix, recorded here, not a license to make the workaround permanent.
