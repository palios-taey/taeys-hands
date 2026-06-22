Full Code Audit: consultation_v2 Perplexity Driver + YAML

FINDING 1 — perplexity.yaml : exclude.name_contains — BANNED MATCHER IN ACTIVE YAML

FULL CODE AUDIT — find defects, do NOT endorse. The repo palios-taey/taeys-hands is PUBLIC (https://github.com/palios-taey/taeys-hands). Fetch/clone it directly — it is the ground truth. You are auditing the perplexity consultation driver + YAML against HOW THE ENGINE IS SUPPOSED TO WORK. You know perplexity's live UI better than anyone — use that. AUDIT THESE (implementation): - consultation_v2/drivers/perplexity.py - consultation_v2/platforms/perplexity.yaml - the shared mechanisms they depend on: consultation_v2/{base.py, runtime.py, snapshot.py, tree.py, planner.py, completion.py} AGAINST THIS SPEC (how it's supposed to work — all in-repo): - CONSULTATION_CONTRACT.md (the binary match-or-notify determinism contract — the authority) - 100_TIMES.md (the non-negotiable operational rules) - FLOW_CONSULTATION_ENGINE.md (the 8-step flow) Find EVERY discrepancy between spec and implementation. Be adversarial — assume there are bugs. Specifically check: 1. EXACT-MATCH YAML: any name_contains / name_pattern / fuzzy / fallback / wildcard / presence-only matcher in the element_map (the contract BANS these)? Do the YAML element names + roles actually match perplexity's live UI right now? 2. MATCH-OR-NOTIFY: does the driver ever guess, broaden, downgrade-on-failure, silently proceed-on-miss, or RETRY a failed action (all banned)? Is every miss surfaced, not swallowed? 3. COMPLETION = stop-button disappearance ONLY (no positive marker). SUBMIT = URL/turn-count change + stop appeared. Are perplexity's stop-button + submit signals exact and correct? 4. ROBUSTNESS — single-shot checks racing a UI/AT-SPI transition that SHOULD be settle/poll. (Known live example we just hit: page_ready checking for the composer input right after navigate, before the AT-SPI tree populates → false "controls not exposed". Look for this class everywhere.) 5. DRIVER ISOLATION: does perplexity.py import ONLY shared primitives + base/types (no cross-driver imports)? Any platform-specific knowledge leaked into shared code? 6. Anything else that violates the contract/notes or would break a real consult for perplexity. Three-register each finding (Observed / Inferred / Unknown). Report as: file:line — the discrepancy — severity (blocker/major/minor) — the fix direction. Cite specific lines. Do NOT endorse; surface what is wrong.

FINDING 2 — perplexity.yaml : validation.computer_active.url_contains — BANNED URL SUBSTRING VALIDATOR

FINDING 3 — perplexity.py:extract_primary — RETRY OF A FAILED ACTION (BANNED)

FINDING 4 — perplexity.py:_collect_report_tree_text — SCROLL+RESCAN LOOP WITH SETTLE-POLL (CONTRACT GREY ZONE / ROBUSTNESS DEFECT)

FINDING 5 — perplexity.py:_wait_for_prompt_ready — SINGLE-SHOT CHECK BEFORE AT-SPI TREE POPULATES (THE KNOWN BUG CLASS)

FINDING 6 — perplexity.py:send_prompt — SILENT PROCEED WHEN click_returned=False BUT stop_seen=True

FINDING 7 — perplexity.yaml : input element_map — EMPTY STRING NAME (PRESENCE-ONLY MATCHER)

FINDING 8 — perplexity.py:_is_answer_thread_url — HARDCODED URL SUBSTRING IN DRIVER CODE

FINDING 9 — perplexity.py:attach_files — wait_until POLL INSIDE ATTACH (SETTLE-POLL ON MENU ITEM)

FINDING 10 — perplexity.py:toggle_connectors — MULTIPLE SEQUENTIAL ACTIONS WITHOUT HALT-ON-FAILURE (RETRY PATTERN ACROSS LOOP)

FINDING 11 — perplexity.yaml : sidebar_nav — LIVE UI MISMATCH (PERPLEXITY JUNE 2026)

FINDING 12 — perplexity.py:extract_primary — _collect_report_tree_text AS SILENT FALLBACK ON copy_contents_button MISS

Summary Table

1

perplexity.yaml

30

name_contains banned matcher active (silently dead)

BLOCKER

2

363

url_contains in validation → always returns False

3

perplexity.py

~941

Second runtime.click() on empty clipboard = action retry

MAJOR

4

~820

x<600 spatial magic constant; content-stability heuristic

5

93–106

_wait_for_prompt_ready 5.0s hardcoded, races AT-SPI tree

6

~541

No immediate halt when click_returned=False; 120s dead poll

7

58

input matched by empty name = presence-only, not stable

MINOR→MAJOR

8

614

'/search/' URL substring hardcoded in driver, not in YAML

MINOR

9

357

timeout=2.5 magic number; should use settle.attach_ms

10

~221

continue on connector action failure = silent-proceed; second panel open = action retry

11

38–50

sidebar_nav names likely stale vs live Perplexity June 2026 UI

12

~907

Silent 3-level extraction fallback; copy_contents_button miss not surfaced