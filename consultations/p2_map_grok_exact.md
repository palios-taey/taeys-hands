# p2-map-grok — exact AT-SPI map (live :5 scan, 2026-06-14)

Live scan of Grok on :5 via `ConsultationRuntime("grok")`. MEASURE for `consult-v2-determinism::p2-map-grok`
— codex applies to `consultation_v2/platforms/grok.yaml`. **Correction to prior memory:** Grok's *control
locators* DO expose to AT-SPI (composer entry, model button, attach, response actions all mapped). The
"AT-SPI-blind" note is about **content readback** — typed composer text and response text are not reliably
readable (`get_text` empty), and the file chip may not render. So: locate/click via AT-SPI; VERIFY
state/content by SCREENSHOT + stop-button, never by reading text.

## element_map (controls)
| key | exact name | role | notes |
|---|---|---|---|
| `input` | `Ask Grok anything` | entry | editable, multi-line. Composer locatable; typed text not readable (screenshot to verify). |
| `model_selector` | `Model select` | push button | |
| `attach_trigger` | `Attach` | push button | GTK file dialog needs the "Open" BUTTON clicked (xdotool coord), not Enter (memory). |
| `search` | `Search` | push button | DeepSearch/search toggle |
| `copy_button` | `Copy` | push button | response copy |
| `more_actions` | `More actions` | push button | |
| `regenerate` | `Regenerate` | push button | |
| `send_button` | (text-in-composer only) | push button | confirm during p1-production-prove; memory: send arrow moves DOWN as composer grows |
| `stop_button` | (generating only) | push button | confirm during p1-production-prove; completion = gone |

## model select dropdown (open `Model select`) — menu item
| exact name | role | note |
|---|---|---|
| `Auto Chooses Fast or Expert` | menu item | |
| `Fast Powered by Grok 4.3` | menu item | |
| `Expert Powered by Grok 4.3` | menu item | |
| `Heavy Team of Experts` | menu item | **MAX mode (Heavy)** |

## attach menu (open `Attach`) — menu item
`Upload a file` (the UPLOAD trigger), `Recent`, `Skills`, `Connectors`.

## exclude (noise)
- Firefox chrome (standard set) + `Enter Reader View`.
- `New Project`, `See all`, `pfp Jesse LaRose jesse@taey.ai`, `History`, `Dictation (Ctrl+D)`, `Enter voice mode (Ctrl+⇧O)`, `Like`, `Dislike`, `Create share link`, `<N> sources` (dynamic → structural), suggested-followup buttons (`Explore HMM motif annotations...`, `Investigate Bekenstein-Hawking...`, `Refine verdict...` — dynamic suggestions, exclude).

## states
- generating = stop_button present; completed = stop_button absent. **Verify by SCREENSHOT (content readback blind).** No positive marker (contract).

## still-needs-live (folds into p1-production-prove)
send_button / stop_button exact names during a generation — and because content is screenshot-only, the p1-production-prove halt/complete checks for grok rely on stop-button presence + screenshot, never text.
