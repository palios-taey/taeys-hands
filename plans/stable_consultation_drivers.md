# Project: stable-drivers — Per-platform isolated consultation drivers (exact-match, YAML-exclusive, de-umbilical)
> Rebuild the 5-platform consultation system as isolated per-platform drivers over a tiny shared-primitive core. Each driver reads its YAML EXCLUSIVELY; YAML uses EXACT-MATCH ONLY (name + role) for every element, for both actions AND validations. NO name_contains / names_any_of / role_contains anywhere. NO platform knowledge in shared code. De-umbilical: any user can point a Claude Code / any CLI at this repo and run it with zero operator-specific paths. Private repo for now → every Chat audit sends FULL CODE inline (no claims). One platform at a time. Git clean, one commit per unit. 100_TIMES.md principles are the driver contract.

## Phase: p0-contract — Shared primitives + exact-match contract  [order: 1]

### Task: p0-primitives — Extract the tiny shared-primitive core (ZERO platform knowledge)  [priority: 90] [owner: taeys-hands] [tags: build,primitives]
- Inventory + lock the only shared primitives: AT-SPI find/snapshot/menu-snapshot, click-by-element, type, clipboard read, scrot, a11y-bus capture, display resolution. These contain NO platform names/keys/strings.
- Anything platform-specific that currently lives in core/ (core/mode_select.py `if platform==`, scripts/consultation.py platform branches) is OUT of the primitives — it moves into the per-platform driver.

### Task: p0-yaml-schema — Define + enforce EXACT-MATCH-ONLY YAML schema  [priority: 90] [owner: taeys-hands] [tags: build,contract] [depends: p0-primitives]
- element_map entries: EXACTLY `name:` (verbatim AT-SPI string) + `role:`. NO name_contains, names_any_of, role_contains, wildcards, fallbacks.
- DYNAMIC-VALUE EXCEPTION (the ONLY exception): when a value is inherently dynamic — file chips with the timestamped filename, the response text, a generated id — match the STRUCTURAL element instead: role + container/parent + position/ordinal in the tree. This is structural matching, NOT name_contains. The structural locator is itself exact (exact role, exact parent key, exact ordinal); only the leaf text is allowed to vary because it must.
- VALIDATION THROUGH THE TREE on EVERYTHING: every validation (mode set, attach present, send fired, response complete, etc.) is checked by reading the live AT-SPI tree for an exact element + state — never a screenshot-as-truth, never an assumption, never a substring. The tree is the oracle.
- base driver's matcher REJECTS any non-exact key (lint + runtime assert) so the rule cannot regress; structural locators are an explicit typed locator (`role`+`parent`+`index`), not a loosened string match.
- Add a repo lint (`tools/lint_exact_match.py`) wired into .githooks/pre-commit that FAILS the commit on any name_contains/names_any_of/role_contains/url_contains in platforms YAML.

### Task: p0-100times — Bake 100_TIMES.md principles into the driver contract + base  [priority: 85] [owner: taeys-hands] [tags: build,contract] [depends: p0-yaml-schema]
- YAML = exact AT-SPI truth; driver = zero platform knowledge; YAML drives driver never reverse; two scan scopes (snapshot vs menu_snapshot); validation targets persistent elements; URL gate for new sessions; no fallbacks/broadening; one-tab-per-window; diagnose by SCREENSHOT + live AT-SPI scan before any code change.

## Phase: p1-drivers — One isolated driver + exact-match YAML per platform  [order: 2]
> Per platform, in order, repeat the SAME unit: (1) taeys-hands live AT-SPI scan + screenshot of the real tree → capture EXACT name/role for every action + validation element; (2) taeys-hands-codex builds the isolated driver + exact-match YAML (reads YAML exclusively, no hardcoding, exact validations); (3) taeys-hands PRODUCTION-verifies on the live display (real navigate→mode→attach→send→monitor→extract, no tests); (4) FULL-CODE Chat audit — send the driver + YAML + primitives inline to all 5 Chats, ENDORSE/BLOCK + file:line, no claims; (5) merge on clean audit, one commit.

### Task: p1-grok — Grok isolated driver + exact-match YAML  [priority: 80] [owner: taeys-hands] [tags: platform,driver] [depends: p0-100times]
- Live-scan :5 for exact elements (model selector, mode items, attach trigger, send, stop, copy, validations). Replace all name_contains + the `if platform=='grok'` shared branches with driver-local exact-match logic. Production-verify + full-code Chat audit + merge.

### Task: p1-perplexity — Perplexity isolated driver + exact-match YAML  [priority: 80] [owner: taeys-hands] [tags: platform,driver] [depends: p1-grok]
- Live-scan :6. Deep Research is the SAME dropdown/element it has always been — capture its EXACT name/role, no broadening. Driver-local mode select. Production-verify + full-code audit + merge.

### Task: p1-claude — Claude isolated driver + exact-match YAML  [priority: 80] [owner: taeys-hands] [tags: platform,driver] [depends: p1-perplexity]
- Live-scan :3/:13. Ctrl+T navigation, extended-thinking selection, send, extract (scroll-to-bottom + copy). Exact-match only. Production-verify + full-code audit + merge.

### Task: p1-gemini — Gemini isolated driver + exact-match YAML  [priority: 80] [owner: taeys-hands] [tags: platform,driver] [depends: p1-claude]
- Live-scan :4. Mode picker + Deep Think tool, attach, send, extract. Exact-match only. Production-verify + full-code audit + merge.

### Task: p1-chatgpt — ChatGPT isolated driver + exact-match YAML  [priority: 80] [owner: taeys-hands] [tags: platform,driver] [depends: p1-gemini]
- Live-scan :2. Model selector (Pro) + Extended Thinking, attach (upload), send, extract. Exact-match only (chatgpt has the most name_contains today — 22). Production-verify + full-code audit + merge.

## Phase: p2-cutover — Make isolated drivers the LIVE path; delete the shared-branch path  [order: 3]

### Task: p2-make-live — Route the live entrypoint through consultation_v2 isolated drivers  [priority: 75] [owner: taeys-hands] [tags: cutover] [depends: p1-chatgpt]
- The live entrypoint (consultation CLI) dispatches to the per-platform driver. Single config tree (delete the dead/duplicate tree per task #171).

### Task: p2-delete-shared-branches — Remove all platform branches + name_contains from the old path  [priority: 75] [owner: taeys-hands] [tags: cutover] [depends: p2-make-live]
- Delete core/mode_select.py `if platform==` branches + scripts/consultation.py platform branches + every name_contains in the live YAMLs. The lint gate (p0) stays green.

## Phase: p3-portable — De-umbilical + per-supervisor displays  [order: 4]

### Task: p3-deumbilical — No operator-specific paths; any CLI can run it  [priority: 70] [owner: taeys-hands] [tags: portable] [depends: p2-delete-shared-branches]
- No hardcoded <OPERATOR_HOME>, IPs, profile paths in committed code — env-driven, fail-loud. A fresh clone + documented setup runs the drivers with zero edits.

### Task: p3-per-supervisor — Per-supervisor display sets, one window/tab each, no central conduit  [priority: 70] [owner: taeys-hands] [tags: portable] [depends: p3-deumbilical]
- Each supervisor gets their own 5 displays (own profiles/windows, one tab each) + drives + monitors their own. No cross-session monitor, no central dispatch point.

## Phase: p4-stress — Stress-test + keep moving  [order: 5]

### Task: p4-stress-test — Repeated real consults across all 5, measure reliability  [priority: 65] [owner: taeys-hands] [tags: stress] [depends: p1-chatgpt]
- Run real navigate→mode→attach→send→monitor→extract cycles across all 5 platforms repeatedly with NO hand-holding; record failures; any failure = first-error-full-stop → diagnose by screenshot/scan → fix the driver/YAML (never broaden). Loop until stable.
