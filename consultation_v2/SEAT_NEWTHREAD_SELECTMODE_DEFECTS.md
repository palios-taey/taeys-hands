# Seat defects blocking autonomous end-to-end consult (consult-connect)

> **⚠ ENGINE-ERA REFERENCE (2026-08-13): read `README.md` "the three layers" first.** This documents
> Layer-3-engine (autonomous consult) defects. The engine is a WIP **not run autonomously**; production is
> Layer 2 (`drive_chat` step-by-step over the Layer-1 primitives). Kept as reference for making the engine
> reliable, not as a live to-do for autonomous operation.

Owner: taeys-hands (identifies + CONTROL-verifies + merges). Implementer: taeys-hands-codex (Rule 7).
Discovered 2026-07-30 while proving the CONNECT bar (one autonomous Taey consult end-to-end via
`scripts/run_taey_consult_extract.py` → `consultation_v2/taey_extract.py`).

**What already works (do NOT regress):** Taey (ep3) drives the seat autonomously. On a clean Gemini :4
the model authored the correct sequence — new_thread → open Upload&tools → upload_item → paste_path →
`attachment_present == "CONSULT_ENGINE_MAP"` (file upload VERIFIED) → composer_input → paste_prompt.
Receipt: `.consult-work/connect-proof-gemini/turns.jsonl` (fsync'd, per-turn `at` timestamp, raw model
generations in `generation_NNNN.json`). The blockers below are element/flow drift, not model errors.

## Defect 1 — ChatGPT `new_thread` depends on a sidebar element no longer a11y-exposed
- **Observed:** seat full_consult step `new_thread` → `new_chat_shortcut`
  (`consultation_v2/platforms/chatgpt/chatgpt.yaml`: `name: "New chat Control Shift O"`, `role: link`,
  `scope: base.sidebar`). On :2 the seat loops `find new_thread → found=None`; every later action is
  "out of phase".
- **Root cause (verified):** ChatGPT's entire left sidebar is NOT in the AT-SPI tree — `snapshot()` sees
  only the ~16–20 center-composer elements; `menu_snapshot()` = 0; a raw `Atspi` walk from the firefox
  root finds 0 "New chat" nodes. Persists across page reload AND a full `taey-display-2` restart;
  `accessibility.force_disabled = 0` (a11y enabled). The composer center panel IS exposed. Contrast:
  Gemini :4 exposes 157 elements incl. `link "New chat"` — so this is ChatGPT-specific, not systemic.
- **Why the deterministic engine is immune:** `run_consultation_v2.py` step 1 is `navigate` (open the
  base platform URL = a fresh thread) — it never touches the sidebar. Verified live: tutor's r12 consult
  navigated to a fresh `chatgpt.com/c/6a6be242…` thread, attached, sent, and completed (14884-char answer).
- **Root-cause fix (6SIGMA, SIMPLIFIES):** the seat's `new_thread` should create a fresh thread by
  navigating to the base URL (as the engine does), removing the `new_chat_shortcut` find/click entirely.
  This deletes a fragile find+click and aligns the seat with the engine's proven mechanism. Decide whether
  to generalize navigate-fresh `new_thread` across all seat platforms or scope to ChatGPT (Gemini/others
  currently expose their `new_thread` element, so are not broken by this).

## Defect 2 — Gemini `select_mode` cannot find the deep-research mode target
- **Observed:** after paste_prompt the seat raises `TaeyConsultExtractionError: gemini mode target
  'tool_deep_research' was not found` at `taey_extract.py:_open_mode_selection` (→ `_select_mode_step`
  → `_execute_select_mode`).
- **Candidate causes (root-cause, don't patch):** (a) YAML element drift for `tool_deep_research`
  vs the live tree, or (b) the known intermittent Gemini mode-picker (the DR mode lives behind a menu
  that must be opened first; see the `gemini_mode_picker` / DR-2-phase notes). Verify against the live
  `:4` tree; correct the element_map or the open-then-select sequence so the mode target resolves.

## Defect 3 — dirty composer state from prior runs (hygiene)
- **Observed:** on both :2 and :4 the composer retained stale attachment chips (`CAPABILITY_GAPS(2).md`)
  and leftover draft text from earlier runs; `new_thread` (where it worked, Gemini) did NOT clear them,
  so a subsequent paste-verify (`paste → Ctrl+A → Ctrl+C → compare`) correctly failed on stale+new content.
  A `taey-display-N` restart clears it (Gemini draft is client-side).
- **Root-cause fix:** the seat's new_thread / pre-consult step must guarantee a clean composer (clear any
  existing attachment chips + draft) before attach/paste — folds naturally into the Defect-1 navigate-fresh
  fix if navigate yields a clean thread; verify it does on each platform.

## Verify (production is the oracle — NO synthetic tests)
A real Taey-seat consult that reaches a fresh clean thread, attaches, selects the deepest mode, sends,
and extracts a non-echo answer — on ChatGPT AND Gemini. taeys-hands re-runs the seat proof and merges.
