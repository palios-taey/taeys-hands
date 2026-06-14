# p1-production-prove — per-platform safe-break DESIGN (2026-06-14)

Root-causes the gemini methodology error and designs the correct, **send-safe** break-test per
platform (break-element + expected halt-point + send-mechanic + send-risk). Derived from reading
each driver's `run()` on codex branch `4e40802`. **No live tests in this doc — analysis only.**

## Engine invariant confirmed (by code read)
Every driver's `run()` is **fail-stop**: each step (`navigate → select → attach → enter_prompt → send`)
returns `False` on a missing element and `run()` returns immediately — it NEVER falls through to send.
So a broken element on a step's critical path halts BEFORE send. Proven live on chatgpt; confirmed
in code for all 5.

## Per-platform safe-break matrix
| platform | break element (mode-critical) | --mode | expected HALT step | send mechanic | send-risk |
|---|---|---|---|---|---|
| **chatgpt** | `model_selector` | `pro_extended` | `select_1` (composite trigger) | click `send_button` | **NONE — PROVEN LIVE** (halted at select_1, :2 verified fresh, no send) |
| **gemini** | `deep_think` item (or `more_tools`) | `deep_think` | `select_mode` | click + stop-confirm | NONE — halts at select_mode. ⚠️ NOT `mode_picker` (model-gated, skipped without `--model` — my error) |
| **grok** | `input` (`Ask Grok anything`) **or** `model_selector` + `--mode heavy` | `heavy` | `enter_prompt`/`send_prompt` (`_focus_input`) **or** `select_mode` | `press('Return')` AFTER `_focus_input` succeeds | NONE — see grok safety verdict below |
| **perplexity** | `deep_research_toggle` (`Deep research`) | `deep_research` | mode-toggle step (driver line ~270) | click `submit_button` (`Submit`) | NONE — halts at toggle, well before submit |
| **claude** | DEFER — driver in-flux (codex unstaged `claude.py`) | `extended_thinking` | — | — | wait for claude.py to stabilize, then design |

## GROK SAFETY VERDICT — NO GAP (resolves conductor's concern)
Earlier worry ("empty `model_targets` → reaches send with no halt checkpoint") was based on a **wrong key**:
the grok driver reads `workflow.mode_targets`, which IS populated: `{auto, fast, expert, heavy}`.
- `select_mode`: requested mode **not in** `mode_targets` → `add_step(False)` → **HALT** (no silent downgrade). Requested mode mapped → opens `model_selector`; not found → HALT.
- With **default** mode (`mode=None`), `select_mode` no-ops, BUT `enter_prompt` and `send_prompt` both call `_focus_input`, which returns `None` if the `input` element is missing → **HALT before the `Return`**. grok sends by `press('Return')` only *after* `_focus_input` succeeds.
- **Conclusion: grok cannot reach SEND without a halt-able checkpoint** (select_mode when a mode is requested; `input` always). Binary-detect is present. **No config change needed; no cannot-lie risk on the V2 safety promise for grok.**

## Live-run protocol (per platform, when executed)
1. Worktree at codex branch tip (exact maps). Back up the platform YAML.
2. Break ONLY the mode-critical element above (verify it's the right key + on the critical path first).
3. `cli --platform X --mode <max> --no-neo4j --message "<benign>"`; expect HALT at the listed step, **no `send` step**, `ok=False`.
4. Screenshot the display → confirm composer empty / no message sent / no wrong-model (verify-real-end-state).
5. ABORT-AND-RECOVER if any send/wrong-action occurs (conductor mandate) → recover account, report BLOCK.
6. Restore the YAML.

## FINDINGS LOGGED
- **F1 — gemini attach success=False w/ chip rendered:** in the (mis-targeted) gemini run, `attach` reported `success=False` while the file chip visibly rendered on :4. Possible `attach_success` validation drift (the validation indicator/file_chip spec doesn't match the live post-attach tree). Investigate when the gemini break-test runs correctly; may be a real validation-spec drift to fix.
- **F2 — per-platform break-design methodology:** break the **mode-critical** element (the one on the requested mode's actual path), NOT a model-gated element (gemini `mode_picker` is only reached with `--model`). Confirm the driver fail-stops on that element *by code read* before any live run. Send mechanics vary (chatgpt/perplexity = button click; grok = `Return` after focus; gemini = click+stop) — the break must precede the send action on that platform's path.

## F3 — PERPLEXITY SEND-FALLBACK = REAL BINARY-DETECT GAP (BLOCK, found 2026-06-14 by code-read)
`consultation_v2/drivers/perplexity.py` `send_prompt` (~L741-745):
```python
send_button = self.find_last(snap, 'submit_button')
if send_button:
    clicked = self.runtime.click(send_button)
else:
    clicked = self.runtime.press('Return')   # ← FALLBACK: missing submit_button → SENDS
```
A drifted/missing `submit_button` does **NOT halt** — it falls back to `press('Return')`, which **submits the message**. This violates the contract's match-or-halt + no-fallback at the SEND step, and is a **cannot-lie risk** on V2's binary-halt-on-every-platform promise. Caught by code-read; the `submit_button` break-test was NOT run (it would have sent the probe to the real account — the Enter-fallback IS the gap).
**FIX (codex):** remove the `else: press('Return')` branch; on missing `submit_button` → `add_step('send', False, 'Perplexity submit button not found')` + `return False` (halt + notify). Then re-prove perplexity (break submit_button → must HALT, no send).
Also re-check the other drivers for the same Enter-fallback pattern (chatgpt/gemini/grok send used button-click / focus+Return-after-input-found — confirmed no missing-element Return-fallback; perplexity is the one with the unconditional else-Return).

## STATUS (live prove executed per conductor GO, 2026-06-14)
- **chatgpt — PASS** (broke model_selector → HALT at select_1, :2 verified fresh/empty, no send).
- **gemini — PASS** (broke more_tools → HALT at select_mode "tool item deep_think not found", :4 verified empty, no send).
- **grok — PASS** (broke model_selector + --mode heavy → HALT at select_mode "model selector not found", :5 verified fresh/empty, no send; confirms grok safety = no gap).
- **perplexity — BLOCK** (F3 send-fallback; needs codex fix + re-prove).
- **claude — DEFERRED** (driver in-flux).
**3/5 proven; engine fail-stop confirmed on 4/5 drivers. V2 merge-gate WAITS on: perplexity F3 fix + re-prove, and claude (after its driver stabilizes).**

## F4 — PERPLEXITY deep_research MAP DRIFT (functional, found 2026-06-14 by live re-prove)
The perplexity re-prove (broke `submit_button`, `--mode deep_research`) HALTED at `select_mode`
("Perplexity toggle button deep_research_toggle not found") — BEFORE reaching send. Screenshot of
the FRESH :6 page shows DR is engaged via the **"Search ⌄" dropdown** (→ Deep research item), NOT a
direct `'Deep research'` **toggle button**. That direct toggle only exists in the COMPLETED-DR state
(what p2-map-perplexity scanned). So:
- **F3 send-fix VERIFIED** (code-read: `else` now halts with 'submit button not found' + returns False, no `press('Return')`; + codex regression test `test_perplexity_submit_selection.py` 4 passed). Live-reach to the send step was blocked by F4 (DR didn't engage), so the send-halt is code+regression-verified, not live-exercised.
- **Perplexity SAFETY confirmed**: `select_mode` fail-stopped on the missing mapped toggle (NO send), and the send-fallback is removed → no path reaches send without a checkpoint. The cannot-lie binary-halt promise HOLDS for perplexity.
- **F4 (functional, not safety):** `deep_research_toggle` map is wrong for the fresh dispatch page. DR engagement = "Search ⌄" dropdown → "Deep research" (portal item), matching memory `feedback_grok_driver_not_manual`/`feedback_manual_dispatch_attach_drift`. Needs a FRESH-PAGE rescan + remap (taeys-hands MEASURE) so perplexity DR actually engages; currently a fresh perplexity DR dispatch fail-stops at select_mode (fail-SAFE, but functionally can't engage DR).

## REVISED STATUS (2026-06-14)
- chatgpt / gemini / grok — live PASS (mode-drift → HALT, screenshot-verified no send).
- perplexity — SAFETY PASS (mode-checkpoint halts live; F3 send-fallback fixed/code+regression-verified). FUNCTIONAL F4: DR map drift (fresh page = Search dropdown) → remap needed before DR dispatches engage.
- claude — DEFERRED (driver in-flux).
Binary-halt SAFETY now established on 4/5 (chatgpt/gemini/grok live + perplexity mode-halt live + send-fix verified). Merge-gate follow-ups: F4 perplexity DR remap, claude driver + prove.

### F4 precision note (fresh :6 scan, 2026-06-14)
Fresh-page perplexity composer exposes `'Search'` as a **toggle button [pressed]** + a dropdown caret (`Search ⌄`), `'Model'` push button, and composer hint "Type / for search modes". DR mode = the Search split-button DROPDOWN (or `/` mode menu) → "Deep research" — NOT the completed-state direct `'Deep research'` toggle the map currently holds. **Follow-up scan must target perplexity's `Search` toggle/its dropdown caret specifically (role=toggle button), NOT match substring "Search" (which also hits Firefox's "Search with Google or enter address" address bar — caused a mis-target this pass; harmless, no navigation).** Remap `deep_research_toggle` → the Search-dropdown "Deep research" item for the fresh dispatch path.

### F4 — DEEPER than a name-swap: perplexity DR mode-select is a PORTAL (design question, 2026-06-14)
Precise fresh-:6 composer scan (role-filtered, chrome-excluded) exposes ONLY: `'Add files or tools'`,
`'Model'` (push button), `'Search'` (**toggle button [pressed]**) — plus voice/incognito/notifications
+ prompt-starter cards. There is **NO distinct AT-SPI element** for the Search-mode dropdown (the `⌄`
caret) or its "Deep research" portal item. Clicking the `'Search'` toggle would toggle search OFF
(state change), not open the mode menu. So the fresh-page DR selector is a **portal/popover behind the
Search `⌄` caret**, not a mappable element — matches memory `feedback_grok_driver_not_manual`
("Perplexity DR = Search-toggle dropdown → 'Deep research', portal items, **click by screenshot**").
**This is a design question, not a quick remap. Candidate resolutions (a careful dedicated pass):**
1. **`/`-modes menu** — composer hint reads "Type / for search modes"; typing `/` MAY open an AT-SPI-visible mode list (cleanest if so). PROBE FIRST (focus composer → `/` → menu_snapshot); risk: `/` could hit find-bar.
2. **Caret coordinate** — click the `⌄` region of the `Search` split-button by coordinate (the historical perplexity-DR approach), then scan the popover. Coordinate-based = contract-discouraged but perplexity-precedented.
3. **Contract exception** — if the DR portal items are genuinely AT-SPI-invisible, perplexity DR mode-select is an OUT-OF-SCOPE/exception per the contract's "genuinely-invisible critical control" clause (NO OCR), documented as such.
NOT attempted live this pass (fiddly coordinate-clicks on a real account, deep in session = mis-interaction risk). Perplexity SAFETY is unaffected (still fail-stops; F3 fixed). F4 blocks perplexity DR FUNCTIONALITY (fresh DR dispatch fail-SAFE-halts until resolved).

## F4 RESOLVED (live) + F1 UNIFIED with perplexity attach (2026-06-14 real run)
**F4 perplexity DR — VALIDATED LIVE.** Real consultation_v2 run (codex 9d9a74d slash-menu) on :6:
`select_mode: success=True "Perplexity mode set to deep_research"` + screenshot shows the "🔬 Deep research"
PILL engaged. Element-driven slash-menu DR works. F4 closed.

**F1 is UNIFIED with perplexity attach — one root cause.** The same real run failed at `attach` (success=False)
WHILE the file chip RENDERED (screenshot: `taey_package_perplexity_...md 49.8 KB` chip + X). Live :6 scan of the
rendered chip:
- chip element = `'taey_package_perplexity_...md 49.8 KB' | push button` (filename TRUNCATED with `...` + size).
- remove affordance = an **unnamed `'' | push button`** (the X) — NOT named "Remove".
So `validation.attach_success` `indicators: [{name_contains: "Remove", role_contains: button}]` (perplexity AND gemini)
can NEVER match → attach false-fails even though the file IS attached → halts before send. (Also a banned loose matcher.)
**FIX (codex), both perplexity.yaml + gemini.yaml:** drop the `name_contains "Remove"` indicator; validate attach by the
CHIP element — a `push button` whose name contains the attached filename. NOTE the display TRUNCATES the filename
(`taey_package_perplexity_...md`), so a full-name `file_chip` probe may miss; match the stable filename PREFIX
(`taey_package_<platform>_`) or `.md`/`KB` + role, or a structural locator for the composer attachment chip. The base
`validation_passes` already supports a `file_chip` spec (roles + filename probes) — wire attach_success to use it
truncation-aware, not the "Remove" button.

## p3-mon — STOP-MONITOR COPY-GATING BUG (systemic, 3/4 drivers, 2026-06-14)
The contract + 7-month rule: **completion = Stop-button GONE; NO reliable positive marker (Copy is absent on long responses).** Audit of V2 `monitor_generation` + `response_complete`:
- **chatgpt** (driver: `seen_stop and copy_button and not stop_button`; yaml response_complete: `name_contains Copy` + stop_absent) — COPY-GATED ✗
- **gemini** (driver: `return seen_stop and snap.has('copy_button')` — also MISSING the `not stop_button` check → can false-complete mid-stream; yaml: `name_contains Copy` + stop_absent) — COPY-GATED + false-complete-risk ✗✗
- **perplexity** (driver: `seen_stop and copy_button and not stop_button`; yaml: `name: Copy` + stop_absent) — COPY-GATED ✗
- **grok** (yaml response_complete: `stop_absent: stop_button` ONLY, no Copy) — **CORRECT ✓ — the reference.**
**Consequence:** on a long response where Copy doesn't render, completion never fires → false-hang/timeout (the exact failure the no-positive-marker rule prevents).
**FIX (codex), chatgpt/gemini/perplexity to match grok:**
1. `monitor_generation` poll completion = `seen_stop and not snap.has('stop_button')` (stop-gone). DROP the `copy_button` requirement. (gemini: ADD the `not stop_button`.)
2. `response_complete` validation = `stop_absent: stop_button` ONLY. DROP the Copy `indicators`.
3. Disambiguate a bad stop-vanish via MAPPED-EXCEPTION states (rate-limit/error/etc.) checked alongside stop-gone — NOT a positive Copy marker (per contract). Also clears the `name_contains Copy` banned-matcher debt in response_complete.

## F5 — GEMINI attach chip NOT AT-SPI-name-exposed (per-platform, found 2026-06-14 real run)
perplexity DR run on 5a5e221 = FULL PASS (all fixes work). gemini run FAILED at attach again — BUT the file
DID attach (screenshot: chip visible top-left of composer + "Deselect Deep think" pill + "Send message" present).
Full :4 tree dump: the composer attachment region exposes only unnamed `'' | panel` elements — NO element whose
name contains the filename / `taey_package_` / `.md`. So gemini's chip filename is NOT AT-SPI-name-readable
(consistent with gemini's documented React contenteditable blindness; entry.get_text false-negatives). The unified
`file_chip: {roles:[push button]}` + filename-prefix probes work for PERPLEXITY (named chip button) but CANNOT match
gemini (unnamed panel). The chip is a CONFIRMATION, not a control we click.
**FIX (codex) — gemini.yaml attach_success only (perplexity is correct/proven):** validate gemini attach by a signal
gemini DOES expose post-attach, NOT the filename chip. Options, pick the most robust:
  (1) structural locator for the attachment panel (role=panel in the composer attachment container, position-based), or
  (2) validate by composer send-readiness state change (e.g. `Send message` button present that wasn't pre-attach), or
  (3) per CONTRACT "genuinely AT-SPI-invisible critical control" clause: gemini attach-chip confirmation is
     screenshot/out-of-scope, and attach success = the upload-action (menu-item click + file-dialog accept) completed
     without error (the action is what matters; chip render is unverifiable on gemini).
perplexity attach validation (file_chip) STAYS — it's proven. This is gemini-specific.

## STATUS (real-run, 5a5e221, 2026-06-14)
- **perplexity — FULL PASS** (end-to-end real DR: engage+attach+send+stop-gone-complete+extract "7.83 Hz"+fleet-notify). All 3 fixes (F4 DR, unified attach, stop-monitor) validated live. ✓
- **gemini — attach BLOCK (F5)**: DT engage ✓, but attach validation can't see the (real, attached) chip → needs the gemini-specific signal above. Then re-run.
- chatgpt / grok — stop-monitor fix code-verified (grok was already the reference); real-run pending. [SUPERSEDED — see FINAL SCOPE below: grok later PROVEN e2e (Avogadro 8/8); chatgpt F7 send defect found+fixed, confirming.]

## F6 — CHATGPT pro_extended_active validation drift (found 2026-06-14 real run)
Real chatgpt --mode pro_extended run on 5a5e221 failed at select_1 "tile model_pro not visible after trigger".
Root cause (live :2 scan): Pro Extended is ALREADY the active model (composer model button = 'Pro Extended'),
but the composite-mode short-circuit didn't fire, so it tried to RE-SELECT and failed. Why: `pro_extended_active`
validation looks for `name: 'Pro Extended, click to remove' | push button` — that toolbar indicator is NOT present
in the live tree. The actual active-state signal IS present: `model_selector` button `name: 'Pro Extended'`
(name == selected model). So the active-check never matches → composite re-select runs against an already-active
state → the dropdown/tile lookup fails (the "remove"-style re-pick path differs when already selected).
**FIX (codex) chatgpt.yaml:** `pro_extended_active` should validate by the live signal — `model_selector` button
whose name == 'Pro Extended' (read_from: model_selector, name == Pro Extended), NOT the nonexistent
'Pro Extended, click to remove' toolbar indicator. Then an already-Pro-Extended account SHORT-CIRCUITS (no
re-select). (pro_indicator/extended_pro elements that reference 'Pro Extended, click to remove' are also suspect —
verify against live tree; current :2 has no such element.)

## STATUS (real-run cycle, 2026-06-14) — perplexity proven; 3 platform validation-drifts found+dispatched
- **perplexity — FULL PASS** (real DR end-to-end: all 3 fixes live). ✓ PROVEN
- **gemini** — attach action-only fix landed (codex 679cb3a); re-run in flight.
- **chatgpt** — F6 pro_extended_active validation drift (already-active not detected); dispatched to codex.
- **grok** — stop-monitor code-verified (was the reference); real-run pending. [SUPERSEDED — grok later PROVEN e2e, see FINAL SCOPE.]
PATTERN: real runs surface per-platform validation-spec drifts (attach-chip, mode-active) that synthetic tests miss; codex fixes; re-validate. perplexity is the proven exemplar of the full robust path.

## CHAT AUDIT ROUND (Family audit of consultation_v2 @ 56160f8, 2026-06-14) — Jesse-directed method
Dispatched full system (rules+monitor+per-platform tree/YAML/driver) to Grok Heavy / Gemini DeepThink / ChatGPT ProExtended for adversarial contract audit. I (engine owner) FILTER every finding against CONSULTATION_CONTRACT — reject anything that would itself break a rule (per Jesse: don't follow rule-breaking feedback, don't ask).

### GROK (LOGOS) audit — verdict filtered (saved: consultations/v2_audit_responses/grok_logos_audit.md)
**ACCEPTED (verified vs code, contract-grounded → route to codex):**
- AUD-1: chatgpt.yaml 6 fuzzy control matchers (lint-allow debt) — `stop_button name_contains Stop`, `thinking_mode name_pattern '*, click to remove'`, `attach_success name_contains Remove`, `send_success name_contains 'Stop streaming'`, connector `name_contains 'GitHub, click to remove'`, extended-thinking badge `name_pattern ', click to remove'`. Contract bans fuzzy on CONTROL elements. Need exact name+role (or structural) from LIVE scans. NOTE: chatgpt attach_success still `Remove` (the unified attach fix covered perplexity+gemini, NOT chatgpt) — confirmed real gap.
- AUD-2: grok.yaml `imagine:` section + flow uses coordinate fallbacks (hardcoded pixels). Violates element-driven/never-coordinates. Decide: full AT-SPI path OR declare imagine OUT-OF-SCOPE for consultations (it's a separate grok.com/imagine surface, not the chat consultation path).
**REJECTED (would break contract / misreads it — NOT routed):**
- R-1: "every wait_until = retry violation" → contract ALLOWS a single bounded readiness wait before a single action (settle+rescan-once). Ripping them breaks allowed settle. Rejected.
- R-2: "file_chip attach validation = positive-marker completion bleed" → misread; file_chip is ATTACH validation (intended), completion is stop_absent (fixed 5a5e221). Rejected.
- R-3: "extract_additional `if not export: return True` = silent-proceed" → that step is genuinely OPTIONAL (extra export beyond primary); True-on-absent is correct, not critical-path. Rejected.
- R-4: grok.py `coordinate_only` composer click (L267) flagged as coords — this is the DOCUMENTED grok focus technique (coordinate_only strategy is a deliberate runtime primitive for grok's composer, not a hardcoded UI-element guess); contract's concern is guessing CONTROL LOCATIONS, not the focus-click strategy. Rejected as a violation (keep, it's the proven grok focus path).
PENDING: cross-check vs Gemini + ChatGPT audits (in flight) before finalizing the routed set.

### CHATGPT audit-run (F6 confirmed + send-path finding, 2026-06-14)
The chatgpt audit consultation (6-file attach) on 56160f8:
- **F6 FIX CONFIRMED WORKING**: select_model_mode True "ChatGPT pro_extended already active" — the active-state short-circuit now fires (no re-select, no select_1 failure). codex 56160f8 verified live. ✓
- attach True, prompt True, but **send FALSE** ("validated by stop/copy button"). Screenshot: composer still holds the typed prompt + file chip, NOT sent ("What are you working on?" = no turn started). So send did not complete.
  - Contributing: send_success uses fuzzy `name_contains 'Stop streaming'` (AUD-1) — even if send fired, validation could miss a "Stop answering"-labelled button. AND the send-click may not have landed (possibly the 6-file mega-attach was still settling). NEEDS codex diagnosis: (a) exact send_success indicator (map the real stop name(s) or structural), (b) confirm send-click lands after a large attach (attach-settle before send). This is a real chatgpt send-path robustness gap. NOTE: caveat — 6-file mega-attach is heavier than a normal 1-file consult; re-validate with a normal consult, not just the audit payload.

### GEMINI (COSMOS) audit — VERIFIED vs code @56160f8 (saved: consultations/v2_audit_responses/gemini_cosmos_audit.md)
All 4 high-value findings VERIFIED against code + my live maps (concrete exact-match drifts probe-runs missed because they're on non-primary/short-circuited paths):
- AUD-G1: perplexity.yaml deep_research_toggle `role: push button` → live = `toggle button` (my p2 map confirms). find_first misses on the already-active check.
- AUD-G2: chatgpt.yaml model_instant/medium/high/extra_high/model_pro `role: menu item` → live = `radio menu item` (p2 map confirms). THIS is the latent cause of the pre-F6 "tile model_pro not visible" select_1 failure.
- AUD-G3: gemini.yaml mode_fast `name: '3.5 Flash'` / mode_thinking `name: '3.5 Thinking'` → live = '3.5 Flash All-around help New' / '3.5 Thinking Solves complex problems' (p2 map confirms). Fast/Thinking mode-select would miss (deep_think unaffected).
- AUD-G4: perplexity.py `_dr_select_all_copy` uses find_first(snap,'response_body') 3× but `response_body` is ABSENT from perplexity.yaml (orphan driver key → always misses; violates driver-carries-zero-platform-knowledge / all-keys-in-YAML).
Cross-check: Grok + Gemini both independently flag the fuzzy-matcher family (AUD-1) = 2/2 confirmed. Gemini adds the role/name/orphan drifts (verified). All routed to codex.
AUDIT ROUND COMPLETE: Grok (filtered) + Gemini (verified) harvested; ChatGPT audit-consult failed-to-send (mega-attach) but confirmed F6 works + the send-path finding. Perplexity=DR/web (not used for code audit), Claude=deferred driver. 2 strong analytical audits = sufficient panel.

### AUDIT-FIX SET VERIFIED (codex 4e9ae38, 2026-06-14) — contract-compliant
Code-read verification (not codex's pytest):
- Contract lint CLEAN (23 files, 0 findings).
- names_any_of (NEW primitive codex added) is CONTRACT-COMPLIANT: snapshot.py matches by EXACT equality (`name_lower == candidate`), name_contains/name_pattern stay FORBIDDEN. It expresses the contract's "exactly one of an enumerated set of mapped states" in YAML — the correct fix for a genuinely-varying-but-finite label (chatgpt stop = [Stop streaming, Stop answering]; perplexity stop = [Stop response (Esc), Stop response]). NOT a fuzzy backdoor (verified the match logic).
- AUD-G1 deep_research_toggle role -> toggle button ✓; AUD-G2 chatgpt model_* role -> radio menu item ✓ (fixes the latent select_1 bug); AUD-G3 gemini mode_fast/thinking -> full live names ✓; AUD-G4 response_body orphan REMOVED (driver _dr_select_all_copy now uses the mapped copy_button) ✓; AUD-1 chatgpt fuzzy stop/attach -> enumerated-exact / file_chip ✓; AUD-2 grok imagine guarded ✓.
CONTRACT NOTE (for future audits): names_any_of = sanctioned enumerated-EXACT-set primitive (exact-equality per entry), distinct from the BANNED fuzzy name_contains/name_pattern. Future Family audits should NOT flag names_any_of-with-exact-names as fuzzy — it IS the binary model.

## CONSOLIDATED STATE (consult-v2 robustness, 2026-06-14)
Two-platform PROVEN end-to-end (perplexity DR + gemini DeepThink: engage+attach+send+stop-gone+extract+fleet-notify). All audit/real-run findings F1-F6 + AUD-1/2 + AUD-G1-4 fixed by codex (5a5e221, 679cb3a, 56160f8, 4e9ae38) + VERIFIED by me (code-read + lint + 2 live full passes). chatgpt F6 confirmed live; chatgpt send-path on mega-attach is the one open item (re-validate with a NORMAL 1-file consult, not the 6-file audit payload). claude = deferred-pending-driver. Ready for r5 merge-gate (grok + gatekeeper) with claude flagged deferred.

## GATEKEEPER MERGE-GATE BLOCK — resolution (2026-06-14 @4e9ae38)
Gatekeeper CLEARED the engineering (lint 23/0 reproduced, names_any_of exact-equality confirmed, both Jesse-overrides enforced — stop-gone-no-positive-marker + no-human-operator, perplexity+gemini e2e). BLOCK on 3 items, resolving:
1. **chatgpt send unproven** → doing one normal 1-file consult confirm (the 6-file audit mega-attach was the anomaly; normal consults attach 1 consolidated packet). [in progress]
2. **grok e2e unattested** → RESOLVED. I have the full run: grok Heavy "Avogadro's number" consult, ALL 8 steps True (navigate, select_mode heavy, attach, prompt, send, monitor stop-gone-completion, extract 252 chars real content, store), ok=True, fleet-notify COMPLETED with the real answer. grok DR/Heavy PROVEN e2e.
3. **provenance: docs not in branch** → RESOLVED. Merged codex 4e9ae38 into consultation-v2-isolated-drivers (8d35a56): the branch now carries BOTH the V2 fixes AND CONSULTATION_CONTRACT.md + p1_production_prove_design.md + p2 maps + v2_audit_responses. Lint re-verified CLEAN (23 files). Self-auditable merge artifact.
PROVEN e2e (3/4): perplexity DR, gemini DeepThink, grok Heavy. chatgpt = confirming. claude = deferred-pending-driver (V1 fallback claude-only; gatekeeper OK'd).

## F7 — CHATGPT send-path defect (REPRODUCED 1-file + 6-file, 2026-06-14)
chatgpt send fails on BOTH a normal 1-file consult AND the 6-file audit — NOT mega-attach-specific. Steps: navigate✓ select_model_mode✓ (F6 already-active short-circuit works) attach✓ prompt✓ → **send FALSE**. Screenshot (both runs): composer RETAINS the typed prompt + file chip, "What's on the agenda today?" header = NO turn started → the message genuinely did NOT submit.
Root cause (driver read, send_prompt @4e9ae38): `clicked = self._click(send_button)` on the "Send prompt" React element + waits stop_button/copy_button/url-change. The _click (xdotool coord on the React portal element) does NOT submit — composer-retains-text proves the submit didn't fire (not just a validation false-fail).
**FIX (codex) chatgpt driver send_prompt:** chatgpt's reliable submit is ENTER on the focused composer (per memory: ChatGPT ProseMirror input retains focus; the send button is a React element that doesn't reliably click-submit via coord). Re-focus the input element (find_first 'input' + click/grab_focus) then press Enter (Return) to submit — like the grok/proven pattern — instead of (or as the primary over) the send_button coord-click. Keep the stop/url send-confirm. Reproduced twice; this is the one open functional gap blocking chatgpt's e2e attestation.

## FINAL SCOPE (gatekeeper re-gate, 2026-06-14)
PROVEN e2e live (MERGE-READY): perplexity DR, gemini DeepThink, grok Heavy — all full pass (engage+attach+send+stop-gone-completion+real-extract+fleet-notify). DEFERRED: chatgpt (F7 send-path defect, routed to codex), claude (driver in-flux). Merge scope = the 3 proven platforms; chatgpt+claude flagged deferred-pending (V1 fallback for both).

## GATEKEEPER R5 PASS @035b3e2 (2026-06-14) + chatgpt F7 e2e CONFIRMED
GATEKEEPER VERDICT: **PASS** on the 3-platform scope (perplexity DR + gemini DeepThink + grok Heavy); chatgpt+claude deferred. Gatekeeper reproduced: contract lint 23/23, no-silent-fallbacks 23/23, 13 contract tests pass, override-1 (stop-gone, no positive marker) intact across all 3 merge-scope drivers, doc internally consistent, grok attestation present+specific. Oracle note: live browser runs routed to taeys-hands as production oracle (gatekeeper attests artifact consistency + code/contract cleanliness, not an independent browser repro). Saved: consultations/v2_audit_responses/gatekeeper_r5_PASS.md.
**chatgpt F7 fix (518b552) e2e CONFIRMED** (real run after PASS): chatgpt --mode pro_extended, ok=True, ALL 9 steps — navigate, select_model_mode (F6 short-circuit), attach, prompt, send (Return-submit, F7 fix WORKS), monitor (stop-gone completion), extract_primary (real content), store. So chatgpt now PROVEN e2e too. Per gatekeeper: this is a SEPARATE widen-to-4 re-gate (NOT folded into the 3-platform PASS silently). chatgpt → re-gate for widen-to-4.
