# p2-map-gemini — exact AT-SPI map (live :4 scan, 2026-06-14)

Live scan of Gemini on :4 via `ConsultationRuntime("gemini")`. MEASURE deliverable for
`consult-v2-determinism::p2-map-gemini` — codex applies to `consultation_v2/platforms/gemini.yaml`.
Exact live `name | role`. Confirms the Deep Think dispatch path (mode 3.1 Pro → Upload&tools → More tools → Deep think).

## element_map (controls)
| key | exact name | role | notes |
|---|---|---|---|
| `input` | `Enter a prompt for Gemini` | entry | editable, multi-line |
| `mode_picker` | `Open mode picker, currently Pro` | push button | label dynamic (current model) — locate by role+container |
| `tools_button` / `upload_menu` | `Upload & tools` | push button | attach + tools + Deep Think entry |
| `copy_button` | `Copy` | push button | **EXACT — `Copy prompt` is the USER-turn copy (N>1 drift). Response copy = `Copy`.** |
| `send_button` | (text-in-composer only) | push button | confirm during p1-production-prove |
| `stop_button` | (generating only) | push button | confirm during p1-production-prove; completion = gone |

## mode picker (open `Open mode picker, currently Pro`) — menu item
| exact name | role | note |
|---|---|---|
| `3.5 Flash All-around help New` | menu item | |
| `3.5 Thinking Solves complex problems` | menu item | |
| `Selected 3.1 Pro Advanced math and code` | menu item | currently selected; **Deep Think REQUIRES 3.1 Pro**. Unselected label is `3.1 Pro Advanced math and code` (the `Selected ` prefix is state — match on the stable tail or by role+position). |

## Upload & tools menu (open `Upload & tools`) — menu item / check menu item
`Upload files. Documents, data, code files` (menu item — the UPLOAD trigger), `Add from Drive. Sheets, Docs, Slides` (menu item), `Create image New` / `Create video` / `Canvas` / `Deep research` / `Create music New` (check menu item).

## More tools (within Upload & tools — expands full tool list) — check menu item
Adds `Guided learning` and **`Deep think`** (check menu item) — **the max-mode toggle**.
Deep Think dispatch path (matches gemini-deepthink-dispatch skill): mode_picker→`Selected 3.1 Pro Advanced math and code`, then `Upload & tools`→`More tools`→`Deep think`. Validate via the "✦ Deep think" pill (screenshot), not a flag.

## exclude (noise)
- Firefox chrome (standard set).
- `Open menu for conversation actions.`, `Toggle Recents`, `Settings`, conversation chips, uploaded-file chip (`taey_package_gemini_*.md`), `Edit`, `Good response`/`Bad response`, `Redo`, `Show more options`, `Microphone`.

## states
- generating = stop_button present; completed = stop_button absent. No positive marker (contract). entry.get_text false-negatives on Gemini's React contenteditable — validate composer by screenshot.

## still-needs-live (folds into p1-production-prove)
copy `Copy` confirmed on a response; send/stop exact during a generation.
