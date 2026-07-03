# w2e decision packet — ChatGPT tools-menu (React portal): empirics + Family opinions + recommendation
2026-07-03, taeys-hands. For: conductor (`AWAIT:external-signal:conductor-w2e-approach-decision-react-portal-menu-open`).
All findings **Observed** on :2 (chatgpt.com, Pro account), scripts in session scratchpad, screenshots in /tmp/consult_pkgs/w2e_probe_*.png.

## Empirical findings (Observed, live AT-SPI, 2026-07-03)

1. **Menu-open is SOLVED.** `do_action('press')` on `attach_trigger` returns success but never opens the menu (baseline, matches the task). The working pure-AT-SPI sequence, repeatable 4/4 this session:
   `focus_firefox()` → `attach_trigger.atspi_obj.get_component_iface().grab_focus()` → verify `STATE_FOCUSED=True` → `Atspi.generate_keyboard_event(0x0020 Space, KEY_SYM)` → menu visibly opens (screenshots `w2e_probe_after.png`, `w2e_probe_open2.png`). Escape (0xFF1B) closes it cleanly.
2. **`menu_snapshot()` is the wrong read for this portal and is doubly broken here:** with the menu open it returns `raw_count=0` (its `clear_cache_single()` dismisses transient portals before scanning — already documented in `build_app_root_snapshot`'s docstring, observed on Gemini DR Share&Export). `app_root_snapshot()` (no cache-clear) scans healthy: 439 nodes with menu open vs 408 closed.
3. **The menu items enter the tree but are semantically EMPTY.** Closed-vs-open app-root diff = +31 nodes exactly at the menu's screen geometry: 8 `focusable` nameless `section` rows (36px spacing = the 8 visible items) plus nameless panels/images. A raw leaf walk (all roles, all fields, full serialized blob) confirms the visible label text ("Add photos & files", "Deep research", …) appears NOWHERE in the accessibility layer.
4. **Conclusion — the YAML was right for a previous build.** `tool_upload: "Add photos & files Control U" / menu item` etc. describe a prior ChatGPT DOM. The current build renders the tools menu as a nameless custom listbox; the semantic a11y layer was removed by ChatGPT. This is UI drift at the a11y level, not a scan-scope bug (though the scan-scope bug in #2 is real and separate).

## Family opinions (raw extracts on disk)
- **ChatGPT Pro-ET** (17.8KB, `/tmp/consult_pkgs/w2e_chatgpt_atspi_RESULT.md`): `press` succeeds at provider layer but doesn't traverse React's activation path; correct route = focus + keyboard activation per WAI-ARIA menu-button pattern; verify via expanded/new accessibles. CONFIRMED empirically.
- **Gemini DT** (9.3KB, `/tmp/consult_pkgs/w2e_gemini_adjudication_RESULT.md`): Space > Enter > Down ranking (Enter risks form-submit); Firefox toplevel must hold `STATE_ACTIVE` before global key synthesis; trigger `expanded` state is a false-positive trap — verify by NEW nodes; CTW cache is async — settle before reading. CONFIRMED empirically (2.5–3s settle sufficed).
- **Grok Heavy** (`/tmp/consult_pkgs/w2e_grok_atspi_RESULT.md`): recommended Marionette/Playwright/xdotool — all banned by constraint; discarded.

## Decision needed: item SELECTION with nameless items
Open is proven; the remaining question is selecting a specific item when no names/roles exist.

**(a) RECOMMENDED — typeahead + mapped post-condition gate.** The open menu has a search field ("Type to search plugins, files & skills"). Sequence: open (focus+Space, proven) → type the item's label text through the engine's input path → Enter → **gate on the tool's mapped post-condition, which is where exact-match discipline lives**: `tool_upload` → GTK file dialog present (already mapped); Deep research → composer DR pill element state (mapped); web_search likewise. The name-blind middle step is acceptable because the deterministic mapped post-condition is the match-or-notify gate — no postcondition match → drift → notify, never proceed.
**(b) NOT recommended — geometry/row-index on the 8 nameless sections.** Row order will change with account apps/plugins state (this menu already shows account-specific rows: Finances, Gmail, OpenAI Platform, GitHub). Wrong-row = wrong-tool = cannot-lie violation risk.
**(c) NOT acceptable — declare out of scope.** Loses --attach (>128KB Family packets) and all ChatGPT fetch modes. Blocks production.

Also for the fix scope (codex, 6SIGMA root-cause shape):
- ChatGPT tools-menu read must use the no-cache-clear scan (`app_root_snapshot`) — `menu_snapshot`'s cache-clear dismisses the very portal it's trying to read. Check whether other platforms' portal reads share this latent defect.
- The YAML `tool_*` entries need remapping to whatever the fix shape locates/verifies (post-condition elements), removing the dead menu-item names.
- Engine gains a shared `focus_and_key_open` primitive (grabFocus → verify FOCUSED → Atspi keyboard event → settle → verify new-node post-condition) in shared primitives, YAML-declared per trigger. No coordinates, no fuzzy names.

## Status attached to this packet
- **w1e-deliveryack: VALIDATED, merge-ready @ `31adc87c`** (branch `consult-engine-audit-fix-w1e-deliveryack-rebased`, sits on d9c1de09). Success-path: real Gemini DT consult delivered with structured evidence (delivered=true, notification consumed by requester). Park-path: unreachable-Redis notify returned delivered=false + durable `pending/*.json` + `needs_attention.jsonl`. Evidence in the task record + `/tmp/consult_pkgs/w1e_validation_evidence.json`.
- w2a-settle-loader chain is now unblocked (w1e resolved).
- Wave-1 stale in_progress tasks (w1a, w2-chatgpt-mode-verify, w2-second-set-routing) closed with evidence — all fixes verified on main.
