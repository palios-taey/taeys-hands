# Grok live AT-SPI scan — :5, 2026-06-03 (p1-grok step 1: exact elements for the isolated driver)

Captured from the live tree (gi/Atspi via consultation_v2 runtime), screenshot /tmp/grok_scan_baseline.png.
Every element below is an EXACT `name` + `role` — the isolated grok driver reads ONLY these from grok.yaml.

## Composer / toolbar (document snapshot — all EXACT, already correct in grok.yaml)
| key | name (verbatim) | role |
|---|---|---|
| attach_trigger | `Attach` | push button |
| model_selector | `Model select` | push button |
| copy_button | `Copy` | push button |
| regenerate | `Regenerate` | push button |
| like | `Like` | push button |
| dislike | `Dislike` | push button |
| more_actions | `More actions` | push button |
| create_share_link | `Create share link` | push button |
| search | `Search` | push button |
| history | `History` | push button |
| dictation | `Dictation (Ctrl+D)` | push button |
| voice_mode | `Enter voice mode (Ctrl+⇧O)` | push button |

## Model / mode dropdown (menu_snapshot after clicking `Model select`)
| mode target | menu item name (verbatim) | role |
|---|---|---|
| auto | `Auto Chooses Fast or Expert` | menu item |
| fast | `Fast Powered by Grok 4.3` | menu item |
| expert | `Expert Powered by Grok 4.3` | menu item |
| **heavy** | `Heavy Team of Experts` | menu item |

> The current default shown bottom-right is **Heavy** (screenshot). Driver rule: if requested mode's
> menu item is already the active model, do NOT click (state check, not the `if platform=='grok'`
> skip-hack in core/mode_select.py:102). If not active, click the EXACT menu item above. ZERO retry.

## Attach dropdown (menu_snapshot after clicking `Attach`)
| key | name (verbatim) | role |
|---|---|---|
| upload_files_item | `Upload a file` | menu item |
| (other) | `Recent` / `Skills` / `Connectors` | menu item |

> grok.yaml `upload_files_item` = `{name: "Upload a file", role: menu item}` is EXACT/correct.
> The Gate-2 attach miss (first click opened the New/+ sidebar menu: 'Search/New Chat/Imagine/Build
> New/New Project' + history, then "recovered") was the DRIVER clicking a stale/wrong trigger and
> RE-CLICKING (a §4a retry). Isolated driver: click the exact `Attach` push button ONCE → menu_snapshot
> → click exact `Upload a file` ONCE. No stale-cache, no retry; a first-miss = STOP+escalate.

## stop / send / input (to confirm in production, generating-state-only)
- stop_button: `Stop model response` (per 100_TIMES §1; appears only while generating — confirm on the production run).
- send: grok composer is a contenteditable not exposed as an `entry` (only the Firefox address bar shows as entry). Send = focus composer + Enter; the send button is presence-verify only. Confirm exact composer/send element on the production run.

## Driver build spec (→ taeys-hands-codex, p1-grok step 2)
Build `consultation_v2/drivers/grok.py` (isolated; imports only base/types/runtime) + finalize
`consultation_v2/platforms/grok.yaml` exact-match, per DRIVER_CONTRACT.md + YAML_SCHEMA.md:
- mode select: read `workflow.mode_targets[mode]` → exact menu item above; state-check active-first; click ONCE; no skip-hack, no retry.
- attach: click exact `Attach` → menu_snapshot → click exact `Upload a file` → GTK dialog path entry → verify file chip (structural locator) → ONCE each.
- send: focus composer + Enter; verify stop_button appeared (+ URL change for new session).
- completion: stop_button debounce (absent→re-scan→complete); NO fallback.
- extract: scroll-to-bottom + `Copy` element doAction; validate length >> prompt.
- ALL element names/roles from grok.yaml; driver carries ZERO grok strings.
- Replace the `if platform=='grok'` branches in core/mode_select.py (:102,:144) — driver-local.
- ACCEPTANCE: real production run on :5 (navigate→heavy→attach→send→complete→extract) obeys DRIVER_CONTRACT A–J with NO retry/loose-matcher, verified by tree+screenshot. Then full-code 5-chat audit → merge.
