# Known Findings — taeys-hands Audit Status Ledger

**Purpose:** This file is handed to every reviewer (Family Chats, Grok CLI, Codex) **before** they audit taeys-hands. It lists what is already known so audits spend their effort finding *novel* problems, not re-reporting these. If you are a reviewer: assume everything below is already tracked. **Report only what is NOT here.** If you believe a "fixed" item is not actually fixed, say so with the file:line evidence — that is a novel finding.

Three-register truth required on every new finding: Observed / Inferred / Unknown.

Canonical source: `<OPERATOR_HOME>/taeys-hands/plans/taeys-hands-platform-grade.md` + `<OPERATOR_HOME>/.peer-worktrees/taeys-hands-codex/plans/measure/` (c1–c5 measure artifacts).

---

## Status legend
- `OPEN` — known, not yet fixed
- `FIXED@<sha>` — fixed, verified, commit referenced
- `GATED` — now mechanically blocked by the YAML/driver integrity gate (cannot regress silently)
- `OUT_OF_SCOPE` — known, intentionally NOT addressed in this plan per Jesse 2026-05-31 directive

---

## Architecture / scope (post-Jesse 2026-05-31 redirect)

| id | severity | status | summary |
|---|---|---|---|
| T1 | CRITICAL | OPEN | V1 codepath active: `scripts/consultation.py` + `tools/{attach,extract,inspect}.py` + `core/{tree,mode_select}.py` + root `platforms/*.yaml`. Used by MCP server.py + agents/*_bot.py. Per Jesse 2026-05-31: drop V1 work entirely from scope — focus only on `consultation_v2/`. MCP / bots are out of scope. |
| T2 | HIGH | OPEN | `consultation_v2/` is the ONLY supported entrypoint going forward (`scripts/run_consultation_v2.py`). All driver isolation work targets this. |
| T3 | HIGH | OPEN | Plan `taeys-hands-consolidation` (6 phases / 23 tasks ingested 2026-05-31 earlier) is SUPERSEDED by `taeys-hands-platform-grade`. Old MCP/bot/V1-deletion scope abandoned. |

## Forbidden matchers / hardcoded platform branches (149 violations, c5 baseline)

| id | severity | status | summary |
|---|---|---|---|
| T10 | HIGH | OPEN · GATED-PENDING | 129 forbidden-matcher violations across both `platforms/` (V1 stale) and `consultation_v2/platforms/` YAMLs. Patterns: `name_contains`, `name_pattern`, `role_contains`, `name_contains_model`. Baseline CSV: `plans/measure/the_rule_violations.csv` (codex c5 commit 563cf29). |
| T11 | HIGH | OPEN · GATED-PENDING | 20 `if platform ==` / `if platform_name ==` hardcoded branches in Python driver code (`core/mode_select.py:369-390` × 3, plus elsewhere). Violates THE RULE §2 (zero driver-side platform knowledge). |
| T12 | CRITICAL | OPEN | Mechanical gate (`tools/lint_no_silent_fallbacks.py`-equivalent for taeys-hands) NOT YET BUILT. THE RULE has been prose-only in CLAUDE.md; 149 violations re-accumulated because no CI enforcement. Building this is Phase 0 destruction-pattern killer. |

## Resolver duplication

| id | severity | status | summary |
|---|---|---|---|
| T20 | HIGH | OUT_OF_SCOPE | Three `_match_element` copies (`tools/{attach,extract,inspect}.py`) drifted independently. Codex c4 commit 49fd5d0 documents semantics. Out of scope per Jesse 2026-05-31 (V1 only); V2 `consultation_v2/snapshot.py` resolver is the only one we maintain. |
| T21 | HIGH | OUT_OF_SCOPE | Two `find_copy_buttons` copies (`core/{tree,ax_tree}.py`). V1 only. Out of scope. |
| T22 | HIGH | OUT_OF_SCOPE | Three `extract_response` copies (`scripts/consultation.py:1255`, `agents/hmm_bot.py:765`, `agents/dpo_bot.py:345`). V1 + bots. Out of scope. |

## Mode / tool selection — silent-fallback bugs

| id | severity | status | summary |
|---|---|---|---|
| T30 | CRITICAL | OPEN | Gemini Deep Research two-phase send: after initial send, Gemini renders a research-plan card with "Start research" button that MUST be clicked to launch the deep research run. YAML/driver does NOT click it. Symptom: prompt visible + file chip visible + no stop button + eventually "I'm sorry, something went wrong." Memory: `feedback_gemini_deep_research_start_button_missing`. 2026-05-31 verified live (Jesse clicked manually from phone). |
| T31 | HIGH | OPEN | Grok V1 mode_select fails with "grok model_selector button not found in AT-SPI tree" when prior state has dropdown already open OR URL bar focused. Heavy IS visible/selectable per screenshot evidence. V2 yaml maps name correctly as `"Heavy Team of Experts"`. V1 vs V2 yaml string drift. |
| T32 | HIGH | OPEN | Grok V2 dispatch fails at type-prompt step (composer stays empty after attach succeeds + Heavy selected). Screenshot-verified 2026-05-31. Distinct from T31. |
| T33 | HIGH | OPEN | Per Jesse 2026-05-31: mode/tool validation must be HALT-LOUD pre-send. Current dispatch silently proceeds if YAML-declared mode/tool didn't actually toggle. No silent-fallback allowed. |
| T34 | MEDIUM | OPEN | Claude file picker (Add content from GitHub modal): per-row filenames render visually but `name`/`description`/`text` are all empty in AT-SPI. Standard path = root checkbox "Select directory" (selects all + capacity warning) — works. Per-row "select this specific file/dir by name" is NOT AT-SPI-driveable today. Memory: feedback recap 2026-05-31_claude_git_connector_map. |

## Extraction matrix — known wrong-button / bypass

| id | severity | status | summary |
|---|---|---|---|
| T40 | CRITICAL | OPEN | `core/tree.find_copy_buttons` (V1) uses substring filter `'button' in role + 'copy' in name.lower()`, Y-sorted, last-wins. ChatGPT/Claude code-block "Copy" buttons get picked over assistant-response "Copy response". Corrupt extracts observed across Stage B-Final + FULL audit cycles 2026-05-31. V1 only; out of scope but flagged. |
| T41 | CRITICAL | OPEN | V1 `extract_method: last_copy_button` in `platforms/*.yaml` does NOT read the YAML `copy_button` entry. `tools/extract.py:589` hardcodes the method; YAML field is dead config. V1 only; out of scope but flagged. |
| T42 | HIGH | OPEN | Gemini Deep Research artifact extraction: regular `Copy` button on the artifact card returns FRAMING ONLY (hallucinated-looking content). Must use `Share & Export → Copy` menu item (note: menu item name is just "Copy", NOT "Copy content"). Verified live 2026-05-31. Memory: `feedback_gemini_deep_research_extract`. |
| T43 | HIGH | OPEN | Perplexity Deep Research: must pre-expand via `Show full report` push button → then click `Copy contents` for the full markdown report. Without pre-expand, both Copy and Copy contents return summary stub. Memory + V2 yaml e68e7b3 implementation. |
| T44 | HIGH | OPEN | Multi-turn follow-up on Deep Research within same thread: currently each dispatch creates a fresh chat. Spec needs to add `--session-url` support for follow-up Q&A on a prior DR thread. Per Jesse 2026-05-31. |

## Screenshot-first discipline (anti-fabrication)

| id | severity | status | summary |
|---|---|---|---|
| T50 | CRITICAL | OPEN | Pattern: when YAML doesn't match runtime, default explanation has been "UI changed" and immediate YAML rewrite. Jesse 2026-05-31: NEVER claim UI drift without screenshot + AT-SPI scan + verify which YAML loaded. Failure mode destroyed prior working implementations 20+ times. Memory: `feedback_screenshot_before_claiming_ui_drift`. NOT YET ENFORCED — needs to be wired into dispatch failure-mode reporting. |

## Git discipline / repo hygiene

| id | severity | status | summary |
|---|---|---|---|
| T60 | HIGH | OPEN | Directory + repo not perfectly aligned. Untracked: `.archive/`, `recaps/`, `systemd/user/firefox-user.js` (now tracked @c3 commit), `consultation_v2/EXTRACTION_PATTERNS.md` (now tracked), some agent scripts. Need: .gitignore audit, .archive/ for unused, local-only vars (machine.env) separated from public template. |
| T61 | HIGH | OPEN | DBUS launch + systemd user units (`taey-display-N.service`, `taey-xvfb@N.service`) NOT in repo. Stable now, but at risk of being lost. Need to commit + document. |
| T62 | MEDIUM | OPEN | Multiple display-related scripts in random places. Need consolidation under `systemd/user/` or `scripts/display/`. |

## Multi-platform UI/state requirements (out of current MCP/V1 scope, in scope for V2 plan)

| id | severity | status | summary |
|---|---|---|---|
| T70 | HIGH | OPEN | Claude: support ALL new thinking levels (multiple, not just one). Per Jesse 2026-05-31. |
| T71 | HIGH | OPEN | Grok: support Heavy AND Beta (Grok 4.20 Beta). Per Jesse 2026-05-31. |
| T72 | HIGH | OPEN | Perplexity: support Deep Research AND Model Council. Per Jesse 2026-05-31. |
| T73 | HIGH | OPEN | ChatGPT: support all current depths (Instant / Thinking / Pro Extended / Deep Research). |
| T74 | HIGH | OPEN | Gemini: support Deep Think AND Deep Research (both). |
| T75 | MEDIUM | OPEN | Tools beyond text: Grok Imagine (X images), ChatGPT image gen, Gemini Canvas. YAML `--tool` flag support per platform. |

## OUT_OF_SCOPE — explicitly NOT addressed in this plan (Jesse 2026-05-31)

| id | severity | status | summary |
|---|---|---|---|
| T80 | — | OUT_OF_SCOPE | MCP server `server.py` tool wrappers (`taey_inspect`, `taey_attach`, etc.) — drop. |
| T81 | — | OUT_OF_SCOPE | HMM Phase 5.5 saga / Neo4j / Weaviate / Redis triple-write. "worked great for a couple weeks, destroyed, can't replicate." Don't touch. |
| T82 | — | OUT_OF_SCOPE | `agents/{hmm,dpo,social,unified}_bot.py`. Bots are V1 + HMM territory. Don't touch. |
| T83 | — | OUT_OF_SCOPE | `core/{tree,mode_select}.py` / `tools/{attach,extract,inspect}.py` migration or deletion. V1 only — leave alone or archive. |
| T84 | — | OUT_OF_SCOPE | `core/orchestrator.py`, `core/halt.py`, `core/drift.py` — used by V1 bots. Out of scope. |
| T85 | — | OUT_OF_SCOPE | Neo4j / Weaviate / ISMA writeback during consultation — "already built." Leave alone for this plan. |

---

## How to use this file as a reviewer

1. Read the table above before opening the audit packet.
2. Find a problem in the code or YAML.
3. Look it up in this file.
4. If it's here with status OPEN — silent — no report needed (it's tracked).
5. If it's here with status FIXED@<sha> and you find evidence it isn't actually fixed — REPORT with file:line evidence (novel finding).
6. If it's NOT here — REPORT as novel finding, three-register required.
7. If it's OUT_OF_SCOPE and you think it should be in scope — REPORT as scope-disagreement, three-register required.

Family ENDORSE is NOT independent verification (shared lineage). Only the mechanical gate + production observation are the oracle. Family audit is an additional lens, never the proof.
