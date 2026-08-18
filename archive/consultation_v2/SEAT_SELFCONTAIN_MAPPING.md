# Seat self-contain mapping (task-cd7f8711 — remove treasurer/act.py dependency)

> **SUPERSEDED AS AN OPERATING MAPPING — HISTORICAL EVIDENCE ONLY.** This is Engine/Layer-3 mapping
> context; the engine is a WIP **not run autonomously**. Production is Layer 2 (`drive_chat` step-by-step
> over the Layer-1 primitives). Do not implement from this file.
> **Archived here on 2026-08-18** after committed inbound references were enumerated and updated. Read
> [`../../consultation_v2/README.md`](../../consultation_v2/README.md) for current authority and status.

**Goal (conductor RULING b):** the Taey consult seat (`taey_extract.py`) must drive via THIS repo's
own primitives, not `_load_act()` from `/home/mira/treasurer/scripts/loop/act.py` (private, not
shipped → a downloaded Taey can't load it → CONNECT broken off-machine). Do NOT vendor act.py
(two-copies-that-diverge). Replace the `self.act.*` calls with a thin in-repo adapter over the
engine primitives that already drive `run_consultation_v2.py`.

**Scope is small — the seat calls only these 8 `act.*` methods** (counts from `grep self.act.`):

| seat call (usage) | act.py signature | engine primitive to build it from |
|---|---|---|
| `self.act.find` (3×) | `find(name, role, display, contains, must_show, scroll)` → element dict | `runtime.snapshot()` (or `menu_snapshot`) + `tree.find_elements(scope, name/role/contains spec)`; apply `must_show`/scroll via `input.scroll_wheel` then re-snapshot. Returns the matched element dict (x,y,name,role,states). |
| `self.act.click` (2×) | `click(name, role, display, contains)` | `find` (above) → `interact.atspi_click(element)`; fall back to `input.click_at(element.x, element.y)` if atspi_click fails (same 2-path strategy act.py uses). |
| `self.act.do` (1×) | `do(...)` = **activate** action variant of click | `find` → the AT-SPI `activate` action on the element (interact layer); this is the `activate` vs `click` branch already present at seat ~L1547 (`self.act.do if action=='activate' else self.act.click`). |
| `self.act.key` (5×) | `key(keyname, display, post_delay)` | `input.set_display(display)` then `input.press_key(keyname)` + post-delay. |
| `self.act.paste_into` (1×) | `paste_into(name, text, role, display, contains, clear)` | `find` → focus (`interact.atspi_focus` or `input.focus_firefox` + click) → set clipboard (existing `clipboard.py`) → `input.press_key('ctrl+v')`; optional clear = `ctrl+a` then `Delete` first. |
| `self.act.node_label` (1×) | returns an element's accessible name/label | read `element['name']` (or the AT-SPI name accessor the snapshot already exposes) — no new code, it's a field on the tree element. |
| `self.act.firefox_app` (1×) | the Firefox app-root accessible | `atspi.find_firefox()` (already the engine's Firefox handle; `runtime` holds it). |
| `self.act.prune_inactive_document` (1×) | prune stale/inactive doc subtrees before scan | `runtime.close_stale_dialogs()` + the existing snapshot freshness path (`wait_for_stable_snapshot`); if a doc-specific prune is needed, add it in `tree.py`, not the seat. |

**Shape:** add a small `consultation_v2/seat_actions.py` (a `SeatActions` class taking `display` +
the runtime) exposing exactly these 8 methods over the engine primitives, and replace
`self.act = _load_act(self.act_path)` with `self.act = SeatActions(self.display, self.runtime)`.
Delete `_load_act` + `DEFAULT_ACT_PATH` + `TAEY_CONSULT_ACT_PATH`. No behavior change — same
action semantics, sourced from this repo.

**CONNECT proof (VALIDATE):** a real Taey drive-through consult with `TAEY_CONSULT_ACT_PATH` unset
AND `/home/mira/treasurer` NOT on the path — the seat must drive using only the public repo.

**Sequence:** dispatch after task-9f27db5f (GAP-1+2) merges — same file. Rule 7: codex implements +
production-verifies, taeys-hands merges.

_Confirm before implementing (I mapped from signatures, not full bodies): `node_label`,
`prune_inactive_document`, `firefox_app` — check act.py's actual bodies match the engine equivalents
above; adjust the mapping if a body does more than the signature implies._
