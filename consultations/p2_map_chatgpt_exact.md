# p2-map-chatgpt — exact AT-SPI map (live :2 scan, 2026-06-14)

Live scan of ChatGPT on display :2 via `consultation_v2.runtime.ConsultationRuntime("chatgpt")`
(`snapshot()` + `menu_snapshot()`). Account: Jesse LaRose (Pro), composer mode "Pro Extended".
This is the MEASURE deliverable for `consult-v2-determinism::p2-map-chatgpt` — codex applies to
`consultation_v2/platforms/chatgpt.yaml` (the V2 tree, the sole production engine per conductor
2026-06-14). Every name below is the EXACT live AT-SPI `name | role`. No substrings.

## element_map (controls — exact name + role)
| key | exact name | role | states | notes |
|---|---|---|---|---|
| `input` | `Chat with ChatGPT` | entry | editable, multi-line | composer |
| `model_selector` | `Pro Extended` | push button | enabled,focusable,showing | composer mode button; label == selected level (intrinsically dynamic — locate by role+composer-container, value reads the level) |
| `attach_trigger` | `Add files and more` | push button | enabled,focusable,showing | |
| `copy_button` | `Copy response` | push button | enabled,focusable | **EXACT — `Copy message` is the USER-turn copy → N>1 drift if substring `Copy`. Map assistant copy only.** |
| `search_chats` | `Search chats Control K` | push button | | |
| `switch_model` | `Switch model` | push button | | per-response model switcher (Response actions) |
| `more_actions` | `More actions` | push button | | per-response overflow |
| `dictation` | `Start dictation` | push button | | exclude/ignore for dispatch |
| `send_button` | `Send prompt` | push button | | **NOT present on empty composer — appears after text entered. CONFIRM exact during p1-production-prove (a live send).** |
| `stop_button` | (generating only) | push button | | **NOT present in completed state. Prior captures: `Stop answering` / `Stop streaming`. MUST confirm exact live during a generation (p1-production-prove). Completion = this gone.** |
| `thinking_expander` | `Thought for <N>s` | push button | | dynamic time → use `structural:` (role+parent), NOT name_pattern |

## model picker dropdown (open `Pro Extended`) — radio menu item
`Instant`, `Medium`, `High`, `Extra High`, `Pro Extended` (checked = max) — all `radio menu item`.
Plus `GPT-5.5` (`menu item`) = model-family header. **Max-reasoning select target = `Pro Extended` radio menu item.**
(The old root-yaml items `Auto Decides how long to think` / `Instant For everyday chats` etc. are STALE — replace.)

## attach menu (open `Add files and more`) — menu item / radio menu item
| name | role | purpose |
|---|---|---|
| `Add photos & files Control U` | menu item | the upload trigger |
| `Recent files` | menu item | |
| `Create image` | radio menu item | tool |
| `Deep research` | radio menu item | tool |
| `Web search` | radio menu item | tool |
| `More` | menu item | submenu trigger (GitHub/Gmail/Agent mode/etc. — connector p5 debt, scan when connectors are mapped) |

## sidebar — real nav (pass-through allowlist), link role
`Home`, `New chat Control Shift O`, `Apps`, `New chat`.

## exclude (noise — never surface)
- **Firefox chrome**: menu bar (File/Edit/View/History/Bookmarks/Tools/Help), window buttons (Minimize/Maximize/Close), `Browser tabs`/`Firefox View`/page tabs/`Close tab`/`Open a new tab (Ctrl+T)`/`List all tabs`, Navigation toolbar (`Sidebars`/`Back`/`Forward`/`Reload`), tracker/site-info buttons, address bar (`Search with Google or enter address`), `Bookmark this page`, `Account`, `Extensions`, `Firefox`.
- **Firefox new-tab page** (a background internal frame leaks in): `Shortcuts`, `Amazon`/`Expedia`/`Temu`/`Wikipedia`/`YouTube`/`Reddit`/`Add-ons for Firefox` + their `Open context menu for *`, `Customize`.
- **Sidebar conversation list (dynamic)**: every conversation `list item`/`link` (titles vary), `Pin <title>`, `Unpin <title>`, `Open conversation options for <title>`, `Open conversation options`, `Organize chats`, section toggles `Pinned`/`Recents`, `New project`.
- **Response-feedback noise**: `Good response`, `Bad response`, `Pro feedback`, `Share`, `Yes, I like this personality`, `No, I do not like this personality`, `Dismiss rating prompt`.
- **User-turn actions**: `Edit message`, `Copy message`, the uploaded-file chip panel.

## states
- **generating**: `stop_button` present (confirm exact name live).
- **completed**: `stop_button` ABSENT + `Response actions` panel present (`Copy response` available). No positive marker beyond stop-gone (per contract).

## still-needs-live-generation (folds into p1-production-prove)
`send_button` exact (`Send prompt`?) confirmed with text in composer; `stop_button` exact confirmed during an actual generation. Everything else above is confirmed from this scan.
