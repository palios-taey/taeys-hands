# Platform Surface Mapping — reliable AT-SPI maps for edit/act surfaces

*Reusable methodology for mapping ANY web app's edit/act surfaces (forms, dialogs, composers, action buttons) to deterministic AT-SPI locators + safe click-sequences — the same discipline the `consultation_v2/` Chat engine uses, generalized for LinkedIn / Sales Nav / Upwork / future sites.*

**Audience:** any fleet session driving a browser surface via AT-SPI (`gi.repository.Atspi`) on an Xvfb display. **Companion:** `consultation_v2/CLAUDE.md` (the Chat-engine rules this generalizes), `100_TIMES.md` (the non-negotiables).

---

## 0. The one principle

**Locate by a STABLE anchor, validate the resulting STATE, act once, re-scan. Never by a dynamic visible name, never by memorized coordinates, never blind-chained, never retried.**

Everything below is that principle applied to the parts that actually break.

---

## 1. Read surfaces vs edit/act surfaces — why the latter is harder

Read surfaces (a feed, a profile view) expose their text in the tree; you map them by name+role and read. **Edit/act surfaces fail differently:**

- The controls that *trigger* edits (pencils, "Edit", "Add") often have **no stable accessible name** — they're icon buttons whose name is empty, generic ("Edit"), or a dynamic string. A name-search misses them. → §2.
- The **fields** are usually React-controlled — `get_text()` returns empty even though text is on screen, and a naive paste merges instead of replaces. → §5.
- Actions are **multi-step** (open dialog → fill → Save) and each step changes the tree. Blind-chaining the next click against a stale tree clicks the wrong thing. → §3.

---

## 2. Locating non-name-stable controls (the unnamed pencils)

When the target has no reliable name, do NOT fall back to coordinates or a fuzzy name match. Use a **stable anchor** — something about the node that does not change run-to-run:

Pick the first of these that uniquely identifies it:
1. **Role + a stable labeled sibling/ancestor.** The pencil itself is unnamed, but it sits inside a section whose heading IS stable ("About", "Featured", "Skills"). Find the heading node, then take its container's edit-role child. (`heading "About"` → walk to its section → the lone `push button` in that section.)
2. **Role + structural position within a stable container.** "The Nth `push button` of the `region` named X." Stable as long as the container's shape is stable (verify it is — screenshot two page loads).
3. **A stable `aria`-derived attribute** other than the visible name — sometimes the accessible *description* or a relation (`labelled-by`/`described-by`) is stable even when the name isn't.
4. **The action it exposes.** Many icon controls still expose an Action interface even with an empty name — match on `role == 'push button'` within the right container, then confirm via its action set (§ mechanics).

Then **act via the Action interface, not coordinates** — `do_action` works even when the node has NO geometry (some React controls report no extents at all; see the Grok worked example). Coordinate-clicking a node whose `y` is document-space (not screen-space) clicks empty air or the wrong row.

**Map artifact (what you write to the YAML):** a stable key + role + required states + the anchor description, e.g.:
```yaml
about_edit_pencil:
  role: push button
  anchor: { heading: "About", scope: section }   # not a visible name
  # located as: the edit push-button inside the section whose heading is "About"
```

---

## 3. Multi-step click sequences, safely

A sequence is: **act → re-scan a fresh tree → validate the new state on a PERSISTENT element → act next.** Never queue the next click against the tree you scanned before the previous click.

```
1. scan()                         # fresh tree
2. find anchor → do_action        # ONE action (open the dialog)
3. settle, then scan() AGAIN      # the dialog mounted new nodes; old refs are stale
4. validate: a PERSISTENT dialog element is present (e.g. the dialog's Save button,
   role=push button name="Save") — NOT a transient you're about to dismiss
5. only now find the next target in the NEW tree → act
```

- **Validation must target a persistent element**, not the thing you just clicked away. After a dropdown closes, its items are GONE from the tree — validate on the resulting toolbar/badge state instead.
- **Two scan scopes** (same split as the Chat engine): the document subtree for in-page elements; the app-root for dialogs/menus rendered in React **portals** (they mount outside the document subtree). If a dialog "isn't in the tree," you're scanning the wrong scope — rescan at app-root.

Record the sequence in the map as an ordered list of `{anchor, action, validate}` steps — that IS the reusable click-sequence.

---

## 4. Relevance-filter the chrome

Map ONLY the act/edit targets and their validation anchors — exactly like the Chat YAMLs map send/stop/copy and skip the sidebar/nav. For each surface, the map is: the trigger control, the fields, the Save/Submit control, and the one persistent element that proves each step landed. Everything else (nav rail, footers, suggestions) is noise — leaving it in the map makes drift-detection lie.

---

## 5. React-controlled fields (textareas / contenteditables) — the gotcha

React keeps field text in the DOM, **not** in the AT-SPI accessible value. So:

**READING the current value** (when `entry.get_text()` returns empty):
1. Open the EDIT surface (the dialog's field holds the full current text — more reliable than a "…more"-collapsed read-only render).
2. Focus the field (Action/grabFocus; if that lands on a wrapper, click the visible field region — same focus subtlety as a ProseMirror composer).
3. `Ctrl+A` → `Ctrl+C` → read the clipboard (`xsel -b -o`). That's the full text. *(This is the same reason the Chat engine extracts responses via the Copy button, not tree text.)*

**WRITING a full replacement** (clear-before-paste, then verify):
1. Focus the field.
2. `Ctrl+A` → `Delete` — **clear first**, or you append/merge into existing text.
3. Set clipboard to the new content (`xsel -b -i`), `Ctrl+V` — **paste, never per-char type** (per-char triggers React onChange storms / autocomplete; and "/" etc. can hit page hotkeys).
4. **Verify by copy-back:** `Ctrl+A` → `Ctrl+C` → read clipboard → compare char-count + head/tail to intended. React silently drops a paste if focus was on a wrapper — copy-back is the ONLY trustworthy verify. Do **not** trust `get_text` to verify.
5. Only then click Save, and **screenshot-confirm** the saved state.

---

## 6. Screenshot + tree cross-check (every step)

After each action: `DISPLAY=:N scrot /tmp/x.png` and READ it, and re-scan the tree. **They must agree.** If the screen shows a dialog the tree doesn't (or vice-versa), the tree is **stale** — refresh (re-scan; switching focus/scope forces Firefox to rebuild the a11y subtree) before trusting it. The screen is ground truth; the tree is a cache that lags the DOM.

---

## 7. Halt-on-anomaly — zero blind retries

A single failed action (click/type/paste/navigate/submit) is retried **exactly zero times**. Retry loops read as bot behavior and get accounts flagged/banned. One failure → **STOP**, screenshot, scan, diagnose the visible state, fix the map (the real cause is almost always a stale tree or a wrong anchor), then redo deliberately. Re-*scanning* is observation (allowed); re-*acting* on a guess is banned.

---

## 8. Worked examples (production, this fleet)

- **No-geometry control, acted via the Action interface (Grok thread link).** A history-thread link reported `y=9999` / no usable extents (AT-SPI-blind), so coordinates were impossible. Located it by exact name among `role=link`, then `node.get_action_iface().do_action(i)` on its `jump` action — opened the thread cleanly. *Lesson: no geometry ≠ unclickable; use the Action interface.*
- **React copy button needing scroll-into-view + settle (Claude/Grok response copy).** `do_action` on the copy button returned `True` but the clipboard stayed empty — the button needed `component.scroll_to(Atspi.ScrollType.ANYWHERE)` + a short settle BEFORE `do_action`, and the *response* copy button was `hits[-1]`, not the prompt-echo copy `hits[0]`. *Lesson: scroll the target into view + settle before acting; disambiguate duplicate controls by position.*
- **React textarea read/write (Upwork profile overview).** `get_text()` React-empty → read via select-all+copy+clipboard; write via focus→Ctrl+A→Delete→paste→verify-copy-back (§5).
- **Long-paste auto-converts to a chip.** A long message pasted into a composer was auto-converted by the app into a "PASTED" attachment chip, leaving the field empty and the send hanging. *Lesson: keep pasted-as-text content short; treat "became a chip + empty field" as a real state to handle, not a hang.*

---

## 9. Mechanics reference (`gi.repository.Atspi`)

```python
import gi; gi.require_version('Atspi','2.0'); from gi.repository import Atspi
Atspi.init()
# bus per display: AT_SPI_BUS_ADDRESS = contents of /tmp/a11y_bus_:N (== xprop -display :N -root AT_SPI_BUS)

# find by role (+ filter by stable anchor in your walk):
def walk(n, hits):
    try: role, name = n.get_role_name(), n.get_name()
    except Exception: return
    # ... match role + your stable anchor, append n ...
    for i in range(n.get_child_count()):
        c = n.get_child_at_index(i)
        if c is not None: walk(c, hits)

# ACT (works with no geometry):
act = node.get_action_iface()
for i in range(act.get_n_actions()):
    if act.get_action_name(i) in ('click','activate','press','jump'):
        act.do_action(i); break

# scroll into view before acting on a viewport-mounted control:
node.get_component_iface().scroll_to(Atspi.ScrollType.ANYWHERE)

# states (for validation): grabFocus, and read state via the state set;
# screen-space extents (NOT document-space) for any geometry need:
node.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
```

**Never:** `xdotool type` a URL or long text (autocomplete/hotkey hijack), coordinate-click a document-space `y`, `name_contains`/fuzzy matching, or retry a failed action. **Always:** stable anchor, one action, re-scan, validate on a persistent element, screenshot cross-check, halt-on-anomaly.
