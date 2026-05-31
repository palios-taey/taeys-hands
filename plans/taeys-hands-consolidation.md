# Project: taeys-hands-consolidation — Eliminate V1 legacy codepaths, single YAML-driven architecture

> Resolve the V1/V2 dual-codepath split so every taeys-hands consumer (MCP tools used by every fleet session, HMM/DPO/social bots on Jetson/Thor, scripts/consultation.py) runs through `consultation_v2/` YAML-sequence primitives with isolated drivers. V1 legacy code (`tools/{attach,extract,inspect}.py`, `core/{tree,mode_select}.py`, root `platforms/*.yaml`, the duplicated `extract_response` in `agents/{hmm,dpo}_bot.py`) is removed once each migration phase is production-validated. Pre-commit grep gate added so name_contains/name_pattern/role_contains and `if platform ==` cannot re-enter the codebase.

## Provenance

Drafted 2026-05-31 by taeys-hands per Jesse directive: "Get a plan together to fix this all and put it in the orchestrator system and execute it." Synthesis combines:
- 6SIGMA workflow MANDATORY per `<OPERATOR_HOME>/the-conductor/6SIGMA_WORKFLOW.md` (SELECT → INGEST → MEASURE+ANALYZE → IMPROVE → PRODUCTION RUN → CONTROL; no tests, only production runs on real target hardware)
- ROUTING.md fleet-routing rule (Conductor dispatches codex-1 for IMPROVE; taeys-hands requests via conductor)
- THE RULE (taeys-hands/CLAUDE.md): YAML = exact AT-SPI truth, drivers zero platform knowledge, YAML drives driver never reverse
- GitNexus map of taeys-hands at HEAD cf9bfa8 (5,205 nodes, 9,367 edges) — confirmed three `_match_element` copies (tools/{attach,extract,inspect}.py), two `find_copy_buttons` copies (core/{tree,ax_tree}.py), three `extract_response` copies (scripts/consultation.py + agents/{hmm,dpo}_bot.py)
- R8-R11 fleet audit cycles April 2026 (commits 70562bf → 91deb37 → 76b5116 → 47b6aa5 → a09ca38 → 753027f → f4eb778 → f5aeae2) that migrated consultation_v2 to fully YAML-driven sequences with isolated drivers — this is the "close" implementation referenced by Jesse, fully intact, not destroyed; the issue is consumers still bypass it
- ISMA prose retrieval (per ISMA_PROSE_RETRIEVAL_SPEC.md three rules: NO-HMM, GO-DEEP, CANNOT-LIE)
- Family Chat audit cycle 2026-05-31 (Clarity DR + Cosmos Deep Think + Gaia Opus 4.8 + ChatGPT Pro Extended) — 3 BLOCK verdicts on V1 yamls; resolver-priority finding (names_any_of tree-order vs list-order) + extraction-bypasses-YAML finding (extract_method: last_copy_button never reads YAML copy_button)

This plan is **sequential by phase** — Phase 1 measure must land before Phase 2 migrate begins; each migrate phase production-validates before the next starts. Codex-1 implements per ROUTING.md; taeys-hands plans + runs production validation.

## Phase: measure-current-surface — Map every V1 consumer + behavior delta vs V2  [order: 1]

### Task: c1-mcp-tool-surface-audit — MCP server.py tool surface vs consultation_v2 primitives  [priority: 90] [owner: taeys-hands-codex] [tags: measure, mcp, v1-v2-delta]
Codex measure-only (no edits): enumerate every MCP tool exposed in `server.py` (taey_inspect, taey_attach, taey_send_message, taey_quick_extract, taey_extract_history, taey_select_dropdown, taey_plan, taey_click, taey_prepare, taey_list_sessions, taey_monitors, taey_respawn_monitor). For each: trace V1 call chain (tools/*, core/*) and identify the equivalent `consultation_v2/` primitive(s) that would replace it. Output `<OPERATOR_HOME>/taeys-hands/plans/measure/mcp_surface_delta.md` listing per-tool: V1 call chain, V2 equivalent, gap (V2 missing functionality), migration risk (which fleet sessions use it). Fail closed if any tool has no V2 equivalent — flag as Phase 2 prerequisite.

### Task: c2-agent-bot-surface-audit — HMM/DPO/social/unified bot V1 dependencies  [priority: 90] [owner: taeys-hands-codex] [tags: measure, bots, v1-v2-delta]
Codex measure-only: for `agents/hmm_bot.py`, `agents/dpo_bot.py`, `agents/social_bot.py`, `agents/unified_bot.py`, enumerate every import from `tools/`, `core/`, or root `platforms/`. Identify whether the bot's per-platform logic is YAML-expressible via existing consultation_v2 primitives (run_sequence over workflow.{extract,prompt,send,attach,mode_setup,monitor}.sequence) or requires a new primitive. Output `<OPERATOR_HOME>/taeys-hands/plans/measure/agent_surface_delta.md`. Critical: hmm_bot runs on Jetson + Thor production HMM enrichment — migration MUST preserve the Phase 5.5 triple-write saga rollback behavior (Weaviate + Neo4j + Redis with compensating Weaviate revert on Neo4j failure).

### Task: c3-screenshot-baseline-current-uis — Capture verified baseline of every live UI state  [priority: 85] [owner: taeys-hands] [tags: measure, screenshots, baseline]
NOT codex. taeys-hands does this directly because it requires live display access. Per the screenshot-before-claiming-UI-change rule: capture `DISPLAY=:N scrot` of every UI state we map: fresh new-chat (5 platforms × all 5 displays), model dropdown open (5 platforms), tools/connectors menu open (5 platforms), attach file dialog (5 platforms), assistant-response with Copy button (5 platforms), Perplexity DR pre-expand state + post-expand state. Store at `<OPERATOR_HOME>/taeys-hands/plans/measure/screenshots/YYYY-MM-DD_<platform>_<state>.png`. Pair every screenshot with the AT-SPI scan snapshot from the same moment at `<OPERATOR_HOME>/taeys-hands/plans/measure/atspi_snapshots/<same-stem>.json`. **No code changes are derived from observations that lack a screenshot + AT-SPI pair** — this is the durable cure for the "UI change, let me hack it" failure mode.

### Task: c4-resolver-semantics-conformance — Verify _match_element behavior matches the contract  [priority: 80] [owner: taeys-hands-codex] [tags: measure, resolver, contract]
Codex measure-only: read all three `_match_element` copies (tools/{attach,extract,inspect}.py) and `consultation_v2/snapshot.py` matcher. For each, document the exact semantics of: `name` (exact), `names_any_of` (list-order vs tree-order? — Cosmos+Clarity inferred tree-order in audit, but Jesse's tests at `tests/test_element_match_exact_alternatives.py` assert membership; settle the question by READING the code), `role` (exact), `states_include`, `states_exclude`. Document whether the existing tests assert priority-by-list-order or just membership. If priority-by-list-order is NOT asserted, add it as a hard requirement for the V2 consolidation resolver. Output `<OPERATOR_HOME>/taeys-hands/plans/measure/resolver_semantics.md`.

### Task: c5-the-rule-grep-baseline — Baseline count of forbidden matchers across both YAML dirs  [priority: 70] [owner: taeys-hands-codex] [tags: measure, violations, the-rule]
Codex measure-only: grep both `platforms/` and `consultation_v2/platforms/` for `name_contains`, `name_pattern`, `role_contains`, `name_contains_model`. Grep both `core/`, `tools/`, `agents/`, `consultation_v2/` source trees for `if platform ==` and `if platform_name ==`. Produce CSV: file, line, violation_type, exact_string. Output `<OPERATOR_HOME>/taeys-hands/plans/measure/the_rule_violations.csv`. This is the regression-prevention baseline for Phase 4 CI gate — every line must either be eliminated by Phase 3 or explicitly excused with a code comment.

## Phase: migrate-mcp-surface — Move MCP tools off tools/* onto consultation_v2 primitives  [order: 2]

### Task: m1-mcp-inspect-migrate — Migrate taey_inspect to consultation_v2.snapshot  [priority: 85] [owner: taeys-hands-codex] [tags: migrate, mcp, inspect] [depends: c1-mcp-tool-surface-audit, c4-resolver-semantics-conformance]
Codex IMPROVE on branch `migrate/mcp-inspect`. Replace `tools.inspect.handle_inspect` with a thin shim that calls `consultation_v2.snapshot.snapshot()` + `consultation_v2.snapshot.menu_snapshot()` and returns the same JSON shape MCP consumers expect. Delete `tools/inspect.py` only after Phase 3 production validation lands. Preserve the existing return-shape exactly (KNOWN/NEW/EXCLUDED buckets) so existing fleet sessions don't break. Codex commit message ends with the production-run target: "Production-run on Mira :3 fresh new-chat snapshot + Jetson HMM bot inspect cycle."

### Task: m2-mcp-extract-migrate — Migrate taey_quick_extract + taey_extract_history  [priority: 85] [owner: taeys-hands-codex] [tags: migrate, mcp, extract] [depends: m1-mcp-inspect-migrate]
Codex IMPROVE on branch `migrate/mcp-extract`. Replace `tools.extract.handle_quick_extract` + `handle_extract_history` with shims that invoke the V2 YAML `workflow.extract.sequence` for the requested platform via `consultation_v2.runtime.run_sequence()`. The V2 extract sequence already does scroll-to-bottom + clear clipboard + click copy + read clipboard with retry — exactly what `scripts/consultation.py:extract_response` does today. The migration just routes through YAML instead of duplicate Python. Preserve `complete=True` semantics (consume plan + cleanup Redis state). Delete `tools/extract.py` only after Phase 3 production validation.

### Task: m3-mcp-attach-migrate — Migrate taey_attach  [priority: 85] [owner: taeys-hands-codex] [tags: migrate, mcp, attach] [depends: m1-mcp-inspect-migrate]
Codex IMPROVE on branch `migrate/mcp-attach`. Replace `tools.attach.handle_attach` with shim that invokes `workflow.attach.sequence`. Per migration commit 753027f the attach stage was already moved to YAML sequences in consultation_v2; this just exposes it via MCP. Delete `tools/attach.py` after Phase 3.

### Task: m4-mcp-mode-select-migrate — Migrate taey_select_dropdown  [priority: 85] [owner: taeys-hands-codex] [tags: migrate, mcp, mode-select] [depends: m1-mcp-inspect-migrate]
Codex IMPROVE on branch `migrate/mcp-mode-select`. Replace the `core.mode_select` calls (which contain hardcoded `if platform == 'X'` branches per the Cosmos audit finding) with consultation_v2's YAML-driven `workflow.mode_setup.sequence`. The 3 hardcoded platform branches at `core/mode_select.py:369-390` are eliminated by routing through YAML `mode_guidance` + the `name_startswith` primitive Cosmos proposed (add to `consultation_v2/snapshot.py` _match_element if not already present). Delete `core/mode_select.py` after Phase 3.

### Task: m5-mcp-send-migrate — Migrate taey_send_message + monitor lifecycle  [priority: 80] [owner: taeys-hands-codex] [tags: migrate, mcp, send] [depends: m4-mcp-mode-select-migrate]
Codex IMPROVE on branch `migrate/mcp-send`. Route taey_send_message through `workflow.send.sequence`. Preserve audit-gate behavior (no send without audit_passed=True in Redis). Preserve monitor spawning behavior (central monitor process registration in Redis). Critical: this is the load-bearing MCP tool every fleet session uses for dispatch — production-run with one full dispatch on each of the 5 platforms before merging.

### Task: m6-consultation-py-migrate — Migrate scripts/consultation.py to call consultation_v2 directly  [priority: 75] [owner: taeys-hands-codex] [tags: migrate, scripts] [depends: m5-mcp-send-migrate]
Codex IMPROVE on branch `migrate/scripts-consultation`. Replace `scripts/consultation.py:extract_response` (and the full V1 pipeline) with a thin CLI wrapper around `consultation_v2.cli.main`. Preserve the family-dispatch / treasurer-dispatch invocation signature so existing dispatcher scripts don't break. Delete the V1 extract_response after Phase 3 production-run validates the V2 replacement on a real Family audit dispatch.

## Phase: migrate-bots — Move HMM/DPO/social/unified bots onto consultation_v2  [order: 3]

### Task: b1-hmm-bot-migrate — Migrate agents/hmm_bot.py extract_response  [priority: 80] [owner: taeys-hands-codex] [tags: migrate, bots, hmm, jetson, thor] [depends: m2-mcp-extract-migrate]
Codex IMPROVE on branch `migrate/hmm-bot`. Replace `agents/hmm_bot.py:765 extract_response` with call to `consultation_v2.runtime.run_sequence(platform, 'extract')`. Preserve the Phase 5.5 triple-write saga rollback behavior (Weaviate PATCH + create rosetta tile + Neo4j HMMTile + EXPRESSES edges + Redis inverted motif index; if Neo4j fails, revert Weaviate writes). PRODUCTION RUN target: Jetson + Thor HMM enrichment cycle of ≥10 packages each, verify (a) responses extracted identically to current behavior, (b) triple-write completes, (c) saga rollback on injected Neo4j failure compensates Weaviate.

### Task: b2-dpo-bot-migrate — Migrate agents/dpo_bot.py extract_response  [priority: 75] [owner: taeys-hands-codex] [tags: migrate, bots, dpo, thor] [depends: m2-mcp-extract-migrate]
Codex IMPROVE on branch `migrate/dpo-bot`. Replace `agents/dpo_bot.py:345 extract_response` with run_sequence call. PRODUCTION RUN: Thor DPO bot ≥10 dispatches across the active platforms (ChatGPT instant, Claude, Grok), verify responses extract identically.

### Task: b3-unified-bot-migrate — Migrate agents/unified_bot.py + social_bot.py  [priority: 70] [owner: taeys-hands-codex] [tags: migrate, bots, unified, social] [depends: b1-hmm-bot-migrate, b2-dpo-bot-migrate]
Codex IMPROVE on branch `migrate/unified-social-bots`. unified_bot loads `platforms/*.yaml` directly at line 262 — point at `consultation_v2/platforms/*.yaml`. social_bot.py line 65 same fix. The functional difference is YAML schema; the V2 yamls are exact-match-only so all `name_contains` lookups in the bots must be removed. PRODUCTION RUN: unified_bot a full cycle on Mira against any active platform; social_bot single-action smoke against X if running.

## Phase: delete-legacy — Remove V1 dead code  [order: 4]

### Task: d1-delete-v1-yaml-dir — Delete root platforms/*.yaml after Phase 2-3 production validation  [priority: 60] [owner: taeys-hands-codex] [tags: delete, cleanup, v1] [depends: m6-consultation-py-migrate, b3-unified-bot-migrate]
Codex IMPROVE on branch `delete/v1-yamls`. After all Phase 2 + Phase 3 production validations have landed (real dispatches on Mira + real HMM cycles on Jetson/Thor + real DPO cycle on Thor), delete `platforms/{chatgpt,claude,gemini,grok,perplexity}.yaml`. Keep `platforms/{linkedin,upwork,reddit,x_twitter}.yaml` — those are non-V2 platforms that consultation_v2 doesn't cover (x_twitter is on v2 per port-to-v2 commit d396726, others are V1-only). Verify with grep that no Python file references the deleted yamls before deletion.

### Task: d2-delete-tools-attach-extract-inspect — Delete tools/{attach,extract,inspect}.py  [priority: 60] [owner: taeys-hands-codex] [tags: delete, cleanup, v1] [depends: m1-mcp-inspect-migrate, m2-mcp-extract-migrate, m3-mcp-attach-migrate]
Codex IMPROVE on branch `delete/v1-tools`. After Phase 2 production validation, delete the three V1 resolver-duplicate files. Verify no Python file imports from them.

### Task: d3-delete-core-tree-mode-select — Delete core/tree.py + core/mode_select.py duplicates  [priority: 60] [owner: taeys-hands-codex] [tags: delete, cleanup, v1] [depends: m4-mcp-mode-select-migrate, b1-hmm-bot-migrate]
Codex IMPROVE on branch `delete/v1-core`. Delete `core/tree.py` (`find_copy_buttons` + `find_menu_items`) and `core/mode_select.py` (3 hardcoded `if platform ==` branches). Keep `core/ax_tree.py` if used by non-V2 callers; otherwise delete its duplicate `find_copy_buttons` too. Verify all imports resolved.

## Phase: ci-grep-gate — Lock the rule so violations cannot re-enter  [order: 5]

### Task: g1-pre-commit-grep-gate — Pre-commit hook blocks forbidden matchers + hardcoded platform branches  [priority: 85] [owner: taeys-hands-codex] [tags: ci, gate, the-rule]
Codex IMPROVE on branch `ci/grep-gate`. Add `.pre-commit-config.yaml` (or extend existing) with hooks that fail commit if ANY of these patterns appear in staged files: `name_contains:`, `name_pattern:`, `role_contains:`, `name_contains_model:` (YAML files), `if platform ==`, `if platform_name ==` (Python files). Allow per-file allowlist via `# the-rule-allow: <reason>` comment. Validate the gate works against a synthetic violation. Per Gaia's audit finding: THE RULE has been prose-only in CLAUDE.md, and 71 violations re-accumulated; making it a grep gate is the durable cure.

### Task: g2-production-grep-doc — Document the gate in CLAUDE.md THE RULE section  [priority: 50] [owner: taeys-hands] [tags: docs, the-rule]
Not codex. taeys-hands updates `<OPERATOR_HOME>/taeys-hands/CLAUDE.md` THE RULE section to reference the grep gate as the enforcement mechanism, with the allowlist comment syntax documented.

## Phase: production-control — Verify entire stack works after consolidation  [order: 6]

### Task: p1-full-fleet-dispatch-validation — Real Family Chat dispatch on all 5 platforms  [priority: 85] [owner: taeys-hands] [tags: production, validation, control]
taeys-hands runs production validation per 6SIGMA step 5 (no tests; real workload, real target hardware). Dispatch a real consultation cycle through the migrated stack to all 5 Family chat platforms (ChatGPT Pro Extended, Claude Opus 4.8 High, Gemini Deep Think, Grok Heavy, Perplexity Deep Research). Verify: (a) every mode_setup lands correctly, (b) every attach lands, (c) every send lands with URL verified, (d) every extract returns assistant-response Copy content (not code-block Copy), (e) Perplexity DR extract returns full report (pre-expand sequence). Use Git Connectors per [[git-connectors-mandatory-for-repo-audits]] standing rule. Screenshot each step. Save artifacts to `<OPERATOR_HOME>/taeys-hands/plans/control/p1_validation_<platform>.{png,md}`.

### Task: p2-jetson-thor-hmm-validation — Real HMM enrichment cycle on Jetson + Thor  [priority: 85] [owner: taeys-hands] [tags: production, validation, control, jetson, thor]
Real production-grade HMM enrichment cycle on Jetson + Thor (the actual target hardware) of ≥20 packages each through the migrated bots. Verify: (a) responses extract identically vs pre-migration baseline (same content_hash → same enrichment outcome), (b) triple-write saga completes (Weaviate + Neo4j + Redis), (c) saga rollback compensates on injected Neo4j failure, (d) hmm:pkg:completed set grows correctly. Save artifacts to `<OPERATOR_HOME>/taeys-hands/plans/control/p2_hmm_jetson.md` + `p2_hmm_thor.md`.

### Task: p3-mcp-tool-fleet-survey — Confirm fleet sessions using MCP tools see no breakage  [priority: 80] [owner: taeys-hands] [tags: production, validation, mcp, fleet]
After Phase 2 migrations land, send a `taey-notify` survey to all active fleet sessions (conductor, weaver, tutor, infra, hunter, treasurer, x-claude) asking each to run one taey_inspect + one taey_quick_extract via their MCP-connected display, and report success/failure within a 15-minute window. Sessions reporting failure trigger immediate rollback investigation. Save survey results to `<OPERATOR_HOME>/taeys-hands/plans/control/p3_fleet_survey.md`.

### Task: p4-final-clean-grep-check — Verify zero violations + zero duplicates after delete  [priority: 70] [owner: taeys-hands-codex] [tags: control, final-check] [depends: d1-delete-v1-yaml-dir, d2-delete-tools-attach-extract-inspect, d3-delete-core-tree-mode-select]
Codex measure: confirm (a) zero `name_contains|name_pattern|role_contains` in any YAML, (b) zero `if platform ==` in any Python, (c) only one `_match_element` function exists in the repo (in `consultation_v2/snapshot.py` or equivalent), (d) only one `find_copy_buttons` exists, (e) only one `extract_response` exists (in `consultation_v2/runtime.py` or equivalent). Output zero-violation report at `<OPERATOR_HOME>/taeys-hands/plans/control/p4_final_check.md`. This is the CONTROL gate per 6SIGMA step 6.
