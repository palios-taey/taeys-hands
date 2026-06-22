# Claude lane fix — navigate (Ctrl+L→Ctrl+T) + model-select YAML drift (root-cause, for codex)

**Builder:** taeys-hands-codex. **Gate:** taeys-hands production-validate on :3. **Date:** 2026-06-22.
**Account is CONFIRMED WORKING** — :3 logged into Jesse's main account, Max plan, "Jesse returns!", Opus 4.8 Max ready (evidence screenshot /tmp/claude_fail.png). The earlier "hit your limit" banner is GONE. The lane's failures are ENGINE defects, not the account.

## Defect 1 — NAVIGATE: Claude intercepts the address-bar focus key (Ctrl+L)
- Fresh-navigate fails loud: `navigate: composer still focused after address-bar key; refusing to paste URL`. Claude.ai intercepts Ctrl+L, so the composer keeps focus and the engine (correctly) refuses to type the URL into the chat box.
- Even via `--session-url` bypass, the address bar / awesome-bar dropdown is left **OPEN**, polluting every subsequent snapshot: `page_ready`/`select` snapshots show `account_settings_button` mapped to **"Search with Google or enter address"** (the Firefox address bar) and awesome-bar entries (Wikipedia/YouTube/Reddit).
- **FIX (root-cause) — IN-PLACE navigation only. Ctrl+T is FORBIDDEN.** Ctrl+T opens a NEW TAB, violating one-tab-per-window (taeys-hands rule 5); Jesse observed the 2-tab state on :3 from a Ctrl+T smoke (2026-06-22) and the display_readiness gate correctly fails it (`display_readiness.py:309` tabs!=1 → ready=False). Navigate the EXISTING tab in place — e.g. `runtime.navigate('https://claude.ai/new?taey_fresh=<nonce>')` (the in-place cache-busting fresh-marker load already adopted), OR click Claude's own in-app **"New chat"** element (sidebar `New chat`, captured live) to start a fresh chat with no tab/address-bar change at all. After navigate, ensure the address bar/awesome-bar is dismissed (Escape) and the composer/page is focused BEFORE page_ready proceeds; assert NO address-bar element AND exactly ONE tab in the post-navigate snapshot (fail loud otherwise). A clean, single-tab page is the precondition for select.

## Defect 2 — MODEL-SELECT YAML drift (exact AT-SPI names captured live 2026-06-22)
- `select` fails `claude selection expected element model_opus missing after menu open`. The menu DOES open (screenshot); the `element_map` names are STALE. EXACT live AT-SPI tree:

| key | exact name | role | states |
|---|---|---|---|
| model_selector (trigger) | `Model: Opus 4.8 Max` | push button | enabled |
| model_opus | `Opus 4.8 For complex tasks` | radio menu item | **checked**, enabled |
| model_sonnet | `Sonnet 4.6 Most efficient for everyday tasks` | radio menu item | enabled |
| model_haiku | `Haiku 4.5 Fastest for quick answers` | radio menu item | enabled |
| model_fable (unavailable) | `Fable 5Currently unavailable For your toughest challenges` | radio menu item | (disabled/none) |
| effort | `Effort Max` | menu item | enabled |
| more_models | `More models` | menu item | enabled |

- **FIX:** update `consultation_v2/platforms/claude.yaml` `element_map` model options to these EXACT names+roles (`radio menu item`). NOTE: Opus 4.8 is **already checked** — the select must confirm-on-`checked` (no re-click needed when the target option already carries `checked`), not require a click that then fails validation.

## Files
- `consultation_v2/drivers/claude.py` — navigate via Ctrl+T + dismiss address bar + assert clean page before page_ready.
- `consultation_v2/platforms/claude.yaml` — model `element_map` exact names above.

## Validation bar (production, taeys-hands)
A FRESH Claude consult on :3 (no --session-url): navigates clean (no open awesome-bar in snapshot) → confirms Opus 4.8 (already-checked) → attaches → sends → monitors (stop-button) → extracts the FULL response hands-off. Account is Max-plan working, so a clean engine path completes 5/5.
