# Overnight Static Audit: Claude + Grok Consult-Engine Files

**Date**: 2026-06 (session time)  
**Auditor**: Grok (LOGOS peer) — observation/audit only, no code or YAML edits performed.  
**Targets**:  
- `consultation_v2/drivers/claude.py`  
- `consultation_v2/platforms/claude.yaml`  
- `consultation_v2/drivers/grok.py`  
- `consultation_v2/platforms/grok.yaml`  

**Rules / Gold Standard used for comparison** (statically referenced):  
- STABILIZATION_FREEZE.md (forbidden constructs, identities-only + states-live, recognition-rules, conformance per surface, no lint-allow / best_effort / fuzzy, UNKNOWN=0 invariant, nested menu discipline)  
- CONSULTATION_CONTRACT.md (binary match-or-notify, exact, no guess/fallback, Stop as completion signal, no copy-button fallback for completion)  
- 100_TIMES.md (STOP = generate/complete, EXTRACT = scroll + exact copy button, YAML = EXACT name+role only, no name_contains etc., no retries, validate with tree/screenshot)  
- consultation_v2/yaml_contract.py (IDENTITY_FORBIDDEN_KEYS including name_contains, names_any_of, best_effort, stop_present, stored_state, states_include in identity context, etc.; IDENTITY_ELEMENT_KEYS limited to exact; schema identity_v1)  
- ChatGPT gold-standard (main d51e0e5): `schema: identity_v1`, `tree.schema: identity_v1`, `conformance.scopes.*.expected` lists of exact keys, element_map with exact `name` + `role` + `scope`, no legacy `validation:` _active sections, no names_any_of for core controls, structural only when qualified "itself is exact" for dynamic leaves, states read LIVE.

**Format**: Per-platform. For each category, list with exact line refs + 3-register (Observed from the files / Inferred from rules+gold / Unknown-needs-live-tree).  
This is the rebuild worklist.

---

## Claude Findings

### (1) Every forbidden construct (line refs)

- `platforms/claude.yaml:17`: `name_contains:` (with comment `# lint-allow: known p1 debt; sidebar/noise exclusions still rely on substring until exact live map rewrite`)
  - Observed: Direct substring exclusion list.
  - Inferred: Violates yaml_contract.py FORBIDDEN_MATCHER_KEYS and STABILIZATION_FREEZE "Schema REJECTS ... fuzzy matchers (`name_contains`...)"; also 100_TIMES "NO `name_contains`".
  - Unknown-needs-live-tree: Whether current live sidebar items still require this or can be exact-mapped.

- `platforms/claude.yaml:58`: `names_any_of:` under stop_button
  - Observed: `names_any_of: [ "Stop", "Stop response" ]`
  - Inferred: `names_any_of` is in IDENTITY_FORBIDDEN_KEYS in yaml_contract.py; gold uses exact single `name`.
  - Unknown: Whether one exact name is now stable in live tree.

- `platforms/claude.yaml:81`: `names_any_of:` under prompt_tab
  - Observed: `names_any_of: [ "Write", "Learn", "Code", "Life stuff", "Claude’s choice" ]`
  - Inferred: Fuzzy for enumerated control; should be exact enumerated_set per schema and gold (see chatgpt model_instant etc.).

- `platforms/claude.yaml:152`: `names_any_of: [Effort Low, Effort Medium, Effort High, Effort Extra, Effort Max]` under effort_menu + `# lint-allow: known p5 debt; dynamic-name effort menu needs structural/stable locator remap`
  - Observed + lint-allow.
  - Inferred: Direct violation of ban on names_any_of + lint-allow for controls; effort is a classic case for enumerated_set or structural.

- `platforms/claude.yaml:244`: `names_any_of:` in send_success indicators (Stop / Stop response)

- `platforms/claude.yaml:254`: `sonnet_active: {}`
  - Observed: Empty dict with comment "Persistent Sonnet active-state is not mapped in the current live tree."
  - Inferred: Presence-only / stored-state placeholder; banned in IDENTITY_FORBIDDEN_KEYS and STABILIZATION_FREEZE (no stored 'active' flags).

- `platforms/claude.yaml:257-265`: `opus_active:` with `indicators: - names_any_of:` + multiple dynamic "Model: Opus ..." strings

- `platforms/claude.yaml:266`: `haiku_active: {}` (comment: not mapped)

- `platforms/claude.yaml:269`: `fable_active: {}` (comment about unavailable)

- `platforms/claude.yaml:275-278`: `extended_thinking_active:` with `indicators: - name: "Model: Opus 4.8 Extra" # lint-allow: known p5 debt...`

- `platforms/claude.yaml:253`: `stop_absent: stop_button` (presence-only validation in response_complete)

- `platforms/claude.yaml:198`: workflow reference to `validation: extended_thinking_active`

- Multiple in `drivers/claude.py` (e.g. 321, 343, 396, 437, 582): `self.validation_passes(verify_snap, f'{requested_model}_active')` or `mode_active_key`
  - Observed: Reliance on the legacy _active validation keys.
  - Inferred: Uses the forbidden stored/presence state mechanism instead of live tree states or conformance.

### (2) Deviations from identities-only + states-live + recognition-rules (vs gold ChatGPT d51e0e5)

- No top-level `schema: identity_v1` and no `tree: schema: identity_v1` (gold has both at top).
- Still uses legacy `validation:` section with `_active: {}` and `indicators: names_any_of` (gold removed this in favor of `conformance.scopes.*.expected` exact lists + element_map exact + live states).
- Effort and many model actives use `names_any_of` + lint-allow instead of exact single `name` + `active_state: checked` or enumerated exact list.
- Model selector uses structural (partially aligned), but active-state logic falls back to fuzzy/dynamic names + presence instead of recognition rule + live read.
- Many active states are empty dicts with comments admitting they are "not mapped" — opposite of gold's complete expected lists.
- Workflow still references legacy validation keys for mode targets (e.g. extended_thinking_active).
- No `conformance:` section at all (gold has rich scopes for base/model_menu/etc. with exact expected keys).

Observed: Direct structural comparison of the two YAMLs + yaml_contract schema definition.  
Inferred: The files are still in the pre-rebuild "legacy validation + fuzzy + stored active flags" state that STABILIZATION_FREEZE and the ChatGPT rebuild explicitly replaced.  
Unknown-needs-live-tree: Current exact live names for effort levels and model active states (comments claim p5 debt).

### (3) Structural gaps — menus/options likely present but not mapped, nested not represented

- Effort submenu: trigger uses `names_any_of` (fuzzy) instead of exact; subs are listed but the opened "effort options" state is not modeled with its own conformance scope or full expected set.
- Persistent active states for Sonnet / Haiku / Fable: empty or incomplete (comments explicitly say "not mapped in the current live tree").
- Git connector repo dropdown: comment at lines 112-114: "AT-SPI name is empty — needs a live re-scan in the open modal to capture an exact matchable name/role".
- Fable 5: name is polluted with "Currently unavailable For your toughest challenges" — no separate recognition for unavailable/disabled state.
- Sidebar items (Artifacts, Code, more models, prompt categories/tabs, thinking_toggle, model_more): listed at top level but full nested flows (artifacts panel per 100_TIMES/EXTRACTION, full GitHub connector modals) lack complete exact mapping or dedicated scopes.
- No explicit modeling of the "More models" flyout or its contents.
- No `conformance.scopes` for model menu / effort / artifacts equivalent to gold ChatGPT (which has model_menu.pro_effort etc.).
- From STABILIZATION_FREEZE discipline notes: claude effort/artifact/connector flows were expected to be walked; current file shows partial top-level + debt comments, indicating nested sub-states after hover/click are not yet represented as exact enumerated sets.

Observed: Comments + incomplete sections in the YAML itself + contrast to gold ChatGPT nested effort structure.  
Inferred: These will produce UNKNOWN > 0 on live tree conformance for those surfaces, or force use of banned fuzzy.  
Unknown-needs-live-tree: Full current AT-SPI tree inside effort flyout, artifacts panel, GitHub modals, "More models", and whether Fable is still present as disabled.

---

## Grok Findings

### (1) Forbidden constructs (line refs)

- `platforms/grok.yaml:169-192`: Four `_active` entries (`auto_active`, `fast_active`, `expert_active`, `heavy_active`) using `indicators` + `states_include: - selected`
  - Observed: Classic legacy active-state validation pattern.
- `platforms/grok.yaml:202`: `send_fired: stop_present: stop_button`
- `platforms/grok.yaml:205`: `response_complete: stop_absent: stop_button`
- `drivers/grok.py:154,163`: `self.validation_passes(..., active_validation_key)`
- `drivers/grok.py:272`: `self.validation_passes(..., 'attach_present')`
- `drivers/grok.py:348`: `self.validation_passes(..., 'send_fired')`

(No `name_contains` / `names_any_of` / `lint-allow` / `best_effort` visible in grok files from greps.)

### (2) Deviations from identities-only + states-live + recognition-rules (vs gold)

- No top-level or tree `schema: identity_v1`
- Still uses legacy `validation:` section with `_active` blocks and `stop_present` / `stop_absent` (explicitly called out in query and yaml_contract.py as forbidden presence-only for active-state).
- Active states wrapped in validation indicators instead of direct `states_include` on the element_map entry itself or conformance expected + live read.
- Model/mode share the same keys and menu items (intentional comment, but deviates from gold's clean separation of enumerated model options).
- No `conformance.scopes` at all (gold has them for every surface).
- Relies on `validation_passes` after opening menu rather than the new conformance gate + exact identities.

Observed: Direct content + structure vs gold d51e0e5 and schema rules.  
Inferred: Still pre-rebuild state using the exact patterns STABILIZATION_FREEZE says were replaced in ChatGPT (legacy validation, presence-only stop_present, _active).  
Unknown-needs-live-tree: Whether the "selected" state is still the reliable live signal for all four modes on current grok.com tree.

### (3) Structural gaps — menus/options likely present but not mapped, nested not represented

- Explicit "Imagine" surface (lines 216+): declared "out of scope for consultation_v2 chat runs. No coordinate fallback defined here" — separate flow with its own panel grid, but not mapped for any consultation use.
- Model options (auto/fast/expert/heavy) are flat direct menu items; no representation of any nested sub-states or "Heavy Team of Experts" sub-options if they exist in the UI.
- Sidebar nav items (Projects, History, Voice, Imagine) mapped at top level only. Full sub-flows (project creation UI, history search results, voice mode entry, imagine grid/panels) have no dedicated element_map entries or scopes.
- Skills / Connectors / Recent sub-items in attach menu are mapped at trigger level, but deeper portal trees are not enumerated.
- No `conformance.scopes` for model_menu or any submenu (unlike gold ChatGPT which has model_menu.pro_effort etc.).
- Heavy mode may have special stop-label variants (historical notes in rules); current map has only the top item.
- From rules (100_TIMES, STABILIZATION_FREEZE): heavy mode and possible sub-menus were expected to be walked; file shows only flat top-level + separate Imagine out-of-scope note.

Observed: Explicit out-of-scope note + flat structure + lack of sub-scopes in the YAML + comments in driver.  
Inferred: Any actual nested or sub-flow UI elements will be UNKNOWN or force banned patterns/coordinates.  
Unknown-needs-live-tree: Current live tree inside imagine panels, heavy dropdown (if any), projects/voice/history sub UIs, and skills/connectors deeper menus.

---

## Summary Rebuild Worklist (per-platform)

**Claude (high volume of p1/p5 debt):**
- Remove every `name_contains`, `names_any_of`, `lint-allow` from effort, active states, send, tabs.
- Delete or empty the legacy `validation:` _active entries (replace with conformance.scopes + exact recognition rules like gold).
- Add `schema: identity_v1` + `tree.schema: identity_v1`.
- Add full `conformance.scopes` for base, model_menu, effort, artifacts, etc. with exact expected lists.
- Map persistent active states for sonnet/haiku/fable (or mark unavailable properly).
- Replace effort_menu with exact enumerated or proper structural + live scan for exact trigger name.
- Fix git connector repo dropdown (exact name/role via live re-scan).
- Update workflow to stop referencing legacy _active validations.
- Add nested effort/artifact/connector surfaces as first-class scopes.

**Grok (mostly exact names, legacy validation remains the main issue):**
- Remove `stop_present` / `stop_absent` from validation section (use `stop_key` + conformance or direct states).
- Convert the four `_active` blocks to conformance.scopes.expected or direct states_include on the element_map items themselves.
- Add `schema: identity_v1` + `conformance.scopes` (model_menu and any sub surfaces).
- Decide scope for Imagine (integrate with exact mapping or keep explicitly out + document).
- Add any missing sub-flow items for Projects, Voice, History, skills/connectors if they are in chat scope.
- Ensure driver uses the new tree_conformance_gate instead of (or in addition to) legacy validation_passes for actives.

All items above are derived strictly from static content of the four files + the listed rule documents + gold ChatGPT. No live tree was consulted (hence the Unknown registers). No files were edited.

Path written: `audit_logs/claude_grok_overnight_audit.md`
