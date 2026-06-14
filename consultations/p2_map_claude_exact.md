# p2-map-claude — exact AT-SPI map (live :3 scan, 2026-06-14)

Live scan of Claude on display :3 via `consultation_v2.runtime.ConsultationRuntime("claude")`.
Account: Jesse LaRose (logged in), fresh new chat (claude.ai/new), composer mode "Opus 4.8 Max".
MEASURE deliverable for `consult-v2-determinism::p2-map-claude` — codex applies to
`consultation_v2/platforms/claude.yaml` (V2 tree; note codex left claude.yaml dirty on its branch).
Every name is the EXACT live AT-SPI `name | role`.

## element_map (controls — exact name + role)
| key | exact name | role | states | notes |
|---|---|---|---|---|
| `input` | `Write your prompt to Claude` | entry | editable, multi-line | composer |
| `model_selector` | `Model: Opus 4.8 Max` | push button | enabled,expanded,focusable | composer model+effort button; label dynamic (model+effort) — locate by role+composer-container, value reads model/effort |
| `toggle_menu` (attach) | `Add files, connectors, and more` | push button | enabled,focusable | |
| `open_sidebar` | `Open sidebar` | push button | | nav |
| `incognito` | `Use incognito` | push button | | |
| `copy_button` | (completed only) | push button | | fresh chat had no response — confirm exact during p1-production-prove (prior: `Copy`) |
| `send_button` | (text-in-composer only) | push button | | confirm during p1-production-prove |
| `stop_button` | (generating only) | push button | | confirm during p1-production-prove; completion = gone |

## model dropdown (open `Model: Opus 4.8 Max`) — radio menu item (name INCLUDES description suffix)
| exact name | role | state |
|---|---|---|
| `Opus 4.8 For complex tasks` | radio menu item | checked = selected; **max-model target** |
| `Sonnet 4.6 Most efficient for everyday tasks` | radio menu item | |
| `Haiku 4.5 Fastest for quick answers` | radio menu item | |
| `Fable 5Currently unavailable For your toughest challenges` | radio menu item | unavailable (no 'showing'/'enabled') |
| `Effort Max` | menu item | **HOVER-FLYOUT submenu** (see below) |
| `More models` | menu item | submenu |

## Effort submenu — HOVER FLYOUT (CAPTURED 2026-06-14 via pointer hover)
`Effort Max` is a HOVER flyout — does NOT expand on click; expands on `xdotool mousemove` to the item
(then `Effort Max` shows state `expanded`). Driver must use a hover/pointer_move trigger (codex a0bd3d0),
NOT click. Exact levels (all `radio menu item`):
| exact name | role | note |
|---|---|---|
| `Low` | radio menu item | |
| `Medium` | radio menu item | |
| `High Default` | radio menu item | platform default |
| `Extra` | radio menu item | **consultation max-mode TARGET (task #170 — NOT High, NOT Max)** |
| `Max` | radio menu item | checked when "Opus 4.8 Max"; the literal max effort |
| `Thinking Can think for more complex tasks Thinking` | menu item | extended-thinking toggle |

**Wire (#170):** consultation max-mode = model `Opus 4.8 For complex tasks` + Effort hover→`Extra`.
The composer button label then reflects model+effort (e.g. "Model: Opus 4.8 Extra").

## attach menu (open `Add files, connectors, and more`) — menu item / check menu item
| name | role | note |
|---|---|---|
| `Add files or photos Ctrl+U` | menu item | the upload trigger |
| `Take a screenshot` | menu item | |
| `Add to project` | menu item | |
| `Add from GitHub` | menu item | connector |
| `Skills` | menu item | |
| `Connectors` | menu item | submenu |
| `Add plugins...` | menu item | |
| `Research` | check menu item | tool toggle |
| `Web search` | check menu item | (checked by default) |
| `Use style` | menu item | |

## exclude (noise)
- Firefox chrome (same set as chatgpt: menu bar, window buttons, tabs, nav toolbar, address bar, Account/Extensions/Firefox).
- Account/settings: `Jesse LaRose, Settings`, `Settings`.
- Voice: `Press and hold to record`, `Use voice mode`.
- Homepage prompt-starters: `Write`, `Learn`, `Code`, `Life stuff`, `From Gmail`.

## states
- generating = stop_button present; completed = stop_button absent (+ copy available). No positive marker (contract).

## still-needs-live (folds into p1-production-prove + the hover scan)
copy_button / send_button / stop_button exact (need a live response/generation); Effort submenu levels (need hover primitive — #170).
