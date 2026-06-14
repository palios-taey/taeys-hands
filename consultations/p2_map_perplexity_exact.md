# p2-map-perplexity — exact AT-SPI map (live :6 scan, 2026-06-14)

Live scan of Perplexity on :6 via `ConsultationRuntime("perplexity")`. Scanned in a completed
Deep-Research state (sources/copy/download present). MEASURE for `consult-v2-determinism::p2-map-perplexity`
— codex applies to `consultation_v2/platforms/perplexity.yaml`.

## element_map (controls)
| key | exact name | role | notes |
|---|---|---|---|
| `input` | `` (empty) | entry | editable — **name is empty; locate by role+composer-container, NOT name** |
| `attach_trigger` | `Add files or tools` | push button | |
| `deep_research_toggle` | `Deep research` | toggle button | **max-mode toggle; `states_include: [pressed]` = active. Direct toggle (NOT the old search-mode dropdown — UI evolved).** |
| `submit_button` | `Submit` | push button | send |
| `copy_button` | `Copy` | push button | **EXACT — `Copy table` is table-specific (N>1 drift). Main response copy = `Copy`. For a full DR report the "Copy contents"/scroll-to-component caveat still applies (see memory).** |
| `download_button` | `Download` | push button | DR export |
| `more_actions` | `More actions` | push button | |
| `stop_button` | (generating only) | push button | confirm during p1-production-prove; completion = gone |

## attach menu (open `Add files or tools`) — menu item
`Upload files or images` (the UPLOAD trigger), `Connectors`, `Spaces`.

## sources / dynamic
`<N> sources` (e.g. `31 sources`) — **dynamic count → structural locator (role+position), never the literal number.**

## exclude (noise)
- Firefox chrome (standard set).
- `Collapse sidebar`, `Expand Computer`, `Expand Spaces`, `Expand Artifacts`, `Collapse History`, `Session actions`, `Profile avatar Jesse LaRose`, `Notifications`, `Run task`, `Dismiss`, `Rewrite Session`, `Download CSV`, `Helpful`, `Not helpful`, `Share`, `Dictation`.

## states
- DR active = `Deep research` toggle `pressed`. generating = stop_button present; completed = stop_button absent (+ sources/copy/download present). No positive marker beyond stop-gone (contract).

## still-needs-live (folds into p1-production-prove)
stop_button exact during a generation; confirm `Copy` vs full-report "Copy contents" on a long DR report (per memory the full-report copy needs scroll_to before do_action or the clipboard is empty).

## DR FRESH-PAGE ELEMENT PATH (2026-06-14, element-driven — F4 resolution)
The completed-DR-state direct `'Deep research'` toggle does NOT exist on a fresh page. Fresh-page DR
engagement is ELEMENT-DRIVEN via the composer slash-menu (composer hint: "Type / for search modes"):
1. focus the `input` element (empty-name entry; locate by role+composer-container) and click it.
2. keyboard primitive `/` (slash) on the focused composer → opens the search-modes menu (portal).
3. `menu_snapshot` → click the **`'Deep research'` | menu item** element via `do_action`. (Other items: `Model council`, `Learn step by step`, `Switch to Computer`.)
NO coordinates, NO completed-state toggle. Validate DR engaged by the post-select DR pill/indicator (screenshot-confirm).
YAML: `deep_research_item: {name: "Deep research", role: "menu item"}`; perplexity `select_mode` deep_research drives steps 1-3 above (replacing the `_toggle_mode_button` direct-toggle path for the fresh page).
