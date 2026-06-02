# p1-chatgpt-map — ChatGPT full YAML map (IN PROGRESS)

Live AT-SPI scan on display :2, 2026-06-01. EXACT names+roles from the live tree (100_TIMES rule 3). One platform at a time; single-attempt-then-manual-escalate; zero automated retries.

## Composer top-level (VERIFIED live, [Observed])
| purpose | exact name | role |
|---|---|---|
| model picker | `Switch model` | push button |
| reasoning/mode toggle | `Extended Pro` | push button |
| attach trigger | `Add files and more` | push button |
| extract (response copy) | `Copy response` | push button |
| (user msg copy) | `Copy message` | push button |
| more actions | `More actions` | push button |
| sources | `Sources` | push button |
| dictation | `Start dictation` | push button |
| voice | `Start Voice` | push button |

**CORRECTION to chatgpt.yaml:** current `element_map.model_selector` = `'Extended Pro'`. Live tree shows `'Switch model'` (the actual MODEL picker) AND `'Extended Pro'` (the reasoning/mode toggle) as TWO distinct buttons — they were conflated. The model picker is `Switch model`; the Extended-vs-Standard reasoning level is `Extended Pro`. **Both verified present this scan.** (Earlier ROOT_CAUSE note said `Switch model` was removed — it is NOT; it is back / present now. Re-verify which the driver should click for model vs mode.)

## ENUMERATION COMPLETE (live :2, fresh settled composer, 2026-06-02) [Observed — exact AT-SPI names]

**Method that worked (blocker resolved):** New chat → settled "Ready when you are." composer → single readiness scan confirms controls present → ONE click per control → app-root menu scan (`Atspi.get_desktop(0).clear_cache_single()` + `find_elements(firefox)`, NOT document scan) → capture exact menu-item names → Escape. No retries. The fresh-chat settle eliminates the intermittent-tree reads.

### Composer bottom row (fresh chat) [Observed]
| purpose | exact name | role |
|---|---|---|
| model + reasoning picker | `Extended Pro` | push button |
| attach + tools trigger | `Add files and more` | push button |
| dictation | `Start dictation` | push button |
| voice | `Start Voice` | push button |
| input | `Ask anything` (ProseMirror entry; no usable extents) | — |
**No `Switch model` on a fresh composer** — it only appears as a per-response regenerate action on an assistant row. `Extended Pro` IS the model/mode picker.

### `Extended Pro` menu — MODELS / REASONING [Observed]
Header (static, not a menu item): `Latest • 5.5`
| exact name | role | meaning |
|---|---|---|
| `Instant` | radio menu item | fast / no-reasoning |
| `Thinking` | radio menu item | standard reasoning |
| `Pro• Extended` | radio menu item | Pro model + Extended reasoning (the consultation default; currently selected) |
| `Configure...` | menu item | opens model config / legacy models |

### `Add files and more` menu — TOOLS + FILES [Observed]
| exact name | role | meaning |
|---|---|---|
| `Add photos & files Control U` | menu item | file upload (Ctrl+U accel) |
| `Recent files` | menu item | (submenu ›) |
| `Create image` | radio menu item | tool toggle |
| `Deep research` | radio menu item | tool toggle |
| `Web search` | radio menu item | tool toggle |
| `More` | menu item | (submenu › — see below) |
| `Projects` | menu item | (submenu ›) |

### `Add files and more` → `More` submenu — EXTRA TOOLS + CONNECTORS [Observed]
| exact name | role | class |
|---|---|---|
| `Agent mode` | radio menu item | tool |
| `Create task` | radio menu item | tool |
| `Finances` | radio menu item | tool |
| `GitHub` | radio menu item | **connector** |
| `Gmail` | radio menu item | **connector** |
| `OpenAI Platform` | radio menu item | **connector** |

### Send / Stop [Observed earlier, see §11 of 100_TIMES]
- `Send prompt` [push button] — present only with text staged; NO usable Component extents, NO Action interface → presence-verification only; **send = focus composer + Enter**.
- `Stop answering` [push button] — present only while generating (completion-detection signal).

## → chatgpt.yaml fixes for CONDUCTOR (6SIGMA — taeys-hands does not edit YAML directly)
1. `element_map.model_selector`: should be `Extended Pro` (model+reasoning picker), NOT `Switch model` (that's a per-response regenerate action that vanishes). Mode targets: `Instant` / `Thinking` / `Pro• Extended` (radio menu items) — consultation default = `Pro• Extended`.
2. `element_map` tool toggles (radio menu items, reached via `Add files and more`): `Create image`, `Deep research`, `Web search`; via `More` submenu: `Agent mode`, `Create task`, `Finances`.
3. `element_map` connectors (radio menu items, via `More`): `GitHub`, `Gmail`, `OpenAI Platform`.
4. attach trigger = `Add files and more` → `Add photos & files Control U` (or the `Ctrl+U` accelerator directly).
5. All names above are EXACT live AT-SPI (100_TIMES §3) — no broadening.

Sidebar/history elements (Close sidebar, Search chats, Open conversation options …) are EXCLUDED per element_filter — not part of the composer map.

## [Observed] enumeration blocker (this pass)
- `Switch model` was a PER-RESPONSE action (regenerate-with-different-model) on the assistant message row — NOT the composer model picker. It vanished when message state changed.
- The composer model/mode control is `Extended Pro`. BUT on re-scan, both `Extended Pro` and `Switch model` returned NOT_FOUND from `get_platform_document` even though the first full scan found all 55 — i.e. the composer controls read INTERMITTENTLY from the AT-SPI tree depending on page/render state (100_TIMES §1: trees refresh at different rates).
- CONSEQUENCE: clean model/mode/tool enumeration requires a SETTLED fresh-chat composer + a readiness check (single, not a poll) that the target control is present BEFORE the one click. Enumerate via exact AT-SPI extents (not guessed screenshot coords — scaled screenshots are unreliable for clicks).
- NEXT (focused pass, fresh composer): readiness-confirm `Extended Pro` present → single click → app-root/menu scan reasoning levels; then the model picker; then `Add files and more` → tools/connectors. Single-attempt-then-manual per 100_TIMES §4a.
