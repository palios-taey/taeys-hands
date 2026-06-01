# Production-Grade 5-Chat Browser Dispatch — Architecture Convergence Brief

**Requested by:** Jesse (at breaking point — this has been rebuilt ~20 times, 50+ point-fix branches, never converged)
**Goal:** ONE convergent architecture, driven to completion, that any Claude Code instance can use through code.

## The hard requirements (Jesse, verbatim, non-negotiable)

1. **Regular browser.** Real Firefox, not a headless API. (AT-SPI on Firefox qualifies.)
2. **Every instance drives its own display.** One isolated X display + isolated dbus + persistent profile per AI platform. No shared bus.
3. **Click all the buttons.** Model, mode (extended thinking / deep research / deep think / heavy), tools, connectors — set correctly per platform.
4. **Validate they are clicked BEFORE sending.** Pre-send state read must confirm the requested model+mode+tools are actually active. HALT-LOUD on mismatch — never send wrong-state.
5. **Know when it is complete.** Stop-button-disappearance is the completion signal (Jesse: "Submit prompt, stop button appears, always visible. Complete, stop button disappears. Has never changed.").
6. **Extract the response** through code.
7. **Tree-based** — drive via the AT-SPI accessibility tree, not screenshots and not coordinate clicks. (Jesse is ambivalent on whether 6/7 must be tree-only, but tree-based is the design intent.)
8. **Usable by any Claude Code instance through the code**, not bespoke per session.

## What we have now (consultation_v2/ isolated-driver architecture)

- `platforms/*.yaml` — per-platform element_map (exact AT-SPI name+role) + validation specs + mode workflow targets. YAML is the single source of truth.
- `drivers/*.py` — per-platform drivers with ZERO hardcoded platform knowledge; all lookups go through YAML.
- `runtime.py` — AT-SPI ops (click, paste, snapshot, menu_snapshot).
- `snapshot()` = document subtree; `menu_snapshot()` = app-root (React portals/dropdowns).
- THE RULE: exact name+role only. No name_contains, no fuzzy, no fallbacks. A mechanical lint gate (`tools/lint_no_yaml_silent_fallbacks.py`) enforces this.

## The evidence of failure (git history — this is the real record)

50+ `agent/codex-*` branches, each a point-fix for ONE platform/ONE step:
- extract: extract-nonblock, extract-simple, extract-worker, extractor, extractor2, chatgpt-extract, auto-extract (7)
- monitor: monitor-dr-false, monitor-dr-guard, monitor-modes, monitor-respawn-fix, monitor-rewrite, monitor-sendvis, monitor-strip, monitor-timeout (8)
- per-platform send/verify/attach: chatgpt-send2, chatgpt-verify, grok-verify-fix, perp-attach-fix, perp-dialog, perp-dr-detect, gemini-dr, gemini-post-send, gemini-scroll (9+)

**This is whack-a-mole.** Each fix patches a symptom; the system never reaches reliable. Tonight the monitor was corrupted again by an out-of-order live edit. The destruction pattern is real.

## The questions for you (each platform answer in your domain)

1. **Is AT-SPI-tree-driving the right primitive** for this, or is the constant breakage evidence that we should switch the underlying automation layer (e.g., Playwright/Chrome DevTools Protocol against a real browser, browser extension, or other) while keeping "real browser + per-instance display"? If switch: what exactly, and what do we lose (these are logged-in Pro/Max accounts with anti-bot — undetectability matters)?

2. **If we keep AT-SPI:** what is the ONE root-cause reason point-fixes never converge? Name the structural flaw (state model? scan timing? the snapshot/menu_snapshot split? per-platform drift?) and the single architectural change that ends the whack-a-mole.

3. **Pre-send validation (req #4):** what is the correct, platform-general design for "prove model+mode+tools are active before send, HALT-LOUD otherwise" using only tree reads? Persistent-element checks (toolbar toggle states) vs transient dropdown reads?

4. **Completion detection (req #5):** Jesse insists it's just stop-button-appears-then-disappears. The failures came from: (a) false-negative scans mid-generation reporting button gone when it isn't, (b) modes where the button is slow to first appear. What is the minimal, mode-agnostic, false-positive-proof state machine? Where does the false-negative scan come from (AT-SPI tree staleness on the active tab)?

5. **Convergent path:** Given we are exhausted and cannot afford another 20 rebuilds — do we (a) drive the existing v2 plan to completion in strict order, or (b) start over with a cleaner core? Give the SHORTEST path to production-grade that we can actually finish. Be honest if requirement #7 (tree-only, no screenshots/coords) is the thing making this intractable.

## Constraints
- 5 platforms: ChatGPT (Pro/Extended Thinking), Claude (Opus Extended), Gemini (Deep Think / Deep Research), Grok (Heavy), Perplexity (Deep Research).
- Logged-in paid accounts; anti-bot detection is a real concern (why AT-SPI was chosen — undetectable).
- Mira: displays :2–:6, one Firefox each, persistent profiles, isolated dbus.
- No tests as proof — production runs on real dispatches are the only oracle.
