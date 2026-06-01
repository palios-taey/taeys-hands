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

## OPEN enumeration items (next steps — each = ONE click on a confirmed-ready composer, then menu_snapshot, capture exact item names; single attempt, on failure STOP + manual)
- [ ] **models**: click `Switch model` → capture exact model menu items (Instant / Thinking / Pro Extended / Pro NOT-Extended / Configure / "More models"…) with roles.
- [ ] **reasoning levels**: click `Extended Pro` → capture the level menu items (Light / Standard / Extended / Heavy?) exact names.
- [ ] **tools + connectors**: click `Add files and more` → capture menu items (file upload item exact name, connectors, etc.). NOTE: this trigger has opened the NAV menu in some states — verify the composer (not sidebar) trigger.
- [ ] **input field**: capture the entry element exact name + states (ProseMirror; not a button).
- [ ] **send button**: appears only with text staged — capture exact name when present.
- [ ] **stop button**: appears only while generating — exact name (`element_map.stop_button` currently lists Stop answering/response/streaming/generating; verify which is live).

Sidebar/history elements (Close sidebar, Search chats, Open conversation options …) are EXCLUDED per element_filter — not part of the composer map.
