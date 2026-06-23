# Conformance scope fix — Claude model_menu false-fail (RUNTIME-OBSERVED root cause)

**Status:** root cause CONFIRMED by runtime observation on :3 (2026-06-23). NOT a guess.
**Do NOT delete the conformance gate.** The gate is correct; the YAML *scope model* is wrong.

## What was observed (not inferred)

Runtime trace on live Claude (:3), menu opened via `model_selector`:

```
OPEN present: ['model_opus', 'effort_menu', 'model_more']
_conformance_findings(snapshot, 'model_menu') -> missing=[model_sonnet, model_haiku, model_fable], discrepancies=0
```

Screenshot agrees: the open model menu shows exactly **"Opus 4.8" (selected ✓), "Effort", "More models"**.
`discrepancies=0` ⇒ **no name drift** on the items that ARE present — the gate fails *only* because it
expects three items that are not rendered at this surface.

## Root cause

Claude's model picker is a **two-tier menu**:
- **top surface** (renders on open): `model_opus`, `effort_menu`, `model_more`
- **deeper surface** (renders only after clicking `model_more` / "More models"): `model_sonnet`, `model_haiku`, `model_fable`

But `claude.yaml` `tree.conformance.scopes.model_menu.expected` **flat-lists all 6** as if co-rendered:
```yaml
model_menu:
  expected: [model_opus, model_sonnet, model_haiku, model_fable, effort_menu, model_more]
```
So selecting Opus (the only model Family consults use) opens the menu, the anchor-wait correctly finds it open,
then `_selection_conformance_gate` validates the WHOLE `model_menu` expected set and reports
sonnet/haiku/fable "missing" → false-fail. The two checks "disagree on the same open" precisely because the
conformance scope spans a submenu level the open does not reveal.

## The fix (root-cause shape — SIMPLIFIES, keeps drift detection)

Split the conformance scope to match the real UI surface topology. Each surface validates only what it actually renders:

```yaml
model_menu:           # validated on open of model_selector
  expected: [model_opus, effort_menu, model_more]
model_more_menu:      # validated when model_more ("More models") is expanded
  expected: [model_sonnet, model_haiku, model_fable]
```

- KEEPS drift detection on every option (each is still validated against the YAML when its surface is open).
- SIMPLIFIES: the scope now matches reality instead of conflating two menu levels — no `if missing: skip`,
  no gate deletion, no broadening.
- Opus selection: open `model_selector` → validate `model_menu` (Opus present ✓) → select. PASSES.
- Sonnet/Haiku/Fable selection (rare for us): open `model_selector` → click `model_more` →
  validate `model_more_menu` → select.

## Driver side (per-platform validate-on-open — the over-generalization Jesse flagged)

`_open_selection_menu` / `_selection_conformance_gate` (base.py) must validate the scope of the **surface that is
currently open**, derived from the target's surface, NOT a single flat scope per menu. For a target on a deeper
surface (sonnet/haiku/fable), the open sequence is two steps (open model_selector, then expand model_more), and
each step validates its own scope. Claude is the platform with a two-tier model picker; encode that surface
sequence in the **claude driver** (per-platform behavior), not as a shared assumption in base.py.

## Validation (no tests — production is the oracle)

Validate by a REAL Family consult on Claude :3 selecting Opus through the engine: the model-select step passes
the conformance gate (no false-fail), Opus pill confirmed in screenshot, consult lands. The next real backlogged
consult IS the validation. Do not fire a synthetic/ACK probe.
