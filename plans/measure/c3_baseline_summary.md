# c3 Baseline — Screenshot + AT-SPI snapshots of live UI states

Timestamp: 2026-05-31_153727 UTC
Captured by: taeys-hands direct (live display work, not codex)

## Anchor set: fresh-chat baseline (5 platforms)

| Platform | Display | Screenshot | AT-SPI snapshot | Element count | Notes |
|----------|---------|-----------|----------------|---------------|-------|
| ChatGPT | :2 | `screenshots/2026-05-31_153727_chatgpt_freshchat.png` | `atspi_snapshots/2026-05-31_153727_chatgpt_freshchat.json` | ~ | fresh chatgpt.com/?temporary-chat=true |
| Claude | :3 | `screenshots/2026-05-31_153727_claude_freshchat.png` | `atspi_snapshots/2026-05-31_153727_claude_freshchat.json` | 120 | fresh claude.ai/new |
| Gemini | :4 | `screenshots/2026-05-31_153727_gemini_freshchat.png` | `atspi_snapshots/2026-05-31_153727_gemini_freshchat.json` | ~ | fresh gemini.google.com/app |
| Grok | :5 | `screenshots/2026-05-31_153727_grok_freshchat.png` | `atspi_snapshots/2026-05-31_153727_grok_freshchat.json` | ~ | fresh grok.com; **Heavy selected by default** |
| Perplexity | :6 | `screenshots/2026-05-31_153727_perplexity_freshchat.png` | `atspi_snapshots/2026-05-31_153727_perplexity_freshchat.json` | ~ | fresh perplexity.ai |

## Visual verification of operational invariants

**Grok Heavy mode invariant (re-confirmed 2026-05-31):** Screenshot at `grok_freshchat.png` shows "SuperGrok HEAVY" branding and "Heavy" pill on the model selector. The Heavy mode item is present and operational; any future mode-selection dispatch failure on Grok with "No menu item matched 'heavy'" is a YAML-vs-runtime path issue (V1 stale yaml vs V2 correct yaml `Heavy Team of Experts`), NOT a UI drift. Reference per [[feedback_screenshot_before_claiming_ui_drift]] memory.

## Remaining c3 work (deferred to event-driven capture)

The following UI states require an active conversation or interactive sequence — capture during real production dispatches rather than synthesizing now:

- model-dropdown-open (5 platforms) — capture during next mode_setup
- tools/connectors-menu-open (5 platforms) — capture during next attach/tools flow
- attach-file-dialog (5 platforms) — capture during next attach
- assistant-response-with-copy-button (5 platforms) — capture during next extract
- Perplexity DR pre-expand + post-expand — capture during next DR dispatch
- ChatGPT "Copy response" + code-block "Copy" distinction — capture during next extract corruption repro

These will land as add-on commits to the same `2026-05-31_*_<platform>_<state>.{png,json}` naming convention.

## Pairing rule

Every screenshot has a paired AT-SPI snapshot at the same timestamp. Any future YAML-vs-UI delta investigation MUST pair both before claiming UI drift.
