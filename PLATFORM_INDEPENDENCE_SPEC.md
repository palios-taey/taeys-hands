# PLATFORM_INDEPENDENCE_SPEC — per-platform driver + YAML + monitor
v4, 2026-07-03, taeys-hands (Fable). Jesse-directed architecture: "everyone needs their own YAML, their own driver and their own monitor... Each platform is completely independent."
Status: v1 BLOCKED (8) → v2 resolved-8/BLOCKED-3 → v3 resolved-3/BLOCKED on the CLASS (piecemeal curation: each round exposed the next uncovered fix — 9761aee0, f991d951, 2da240dd) → v4 replaces enumeration with GENERATIVE disposition machinery (section 6) + fleet-allocation correction (sections 4/7) → re-review → ratification. Council logs archived in task evidence. Gates all `consult-platform-independence` work.

## 1. Why (Observed evidence, not opinion)
The shared behavioral base couples all five platforms: one shared-monitor change (`e132bf15`, Jun-22) simultaneously broke Grok, Gemini DR, and Perplexity DR (`MONITOR_REGRESSION_ARCHAEOLOGY_2026-07-03.md`); the audit-fix plan had to serialize every `base.py` fix into a depends-chain because each touched all platforms. `drivers/base.py` is 2,856 lines of shared behavior — every line is shared blast-radius.
**Precedent (council git-historian, Observed):** isolation was ALREADY achieved once — `90de2d6b` (2026-06-03) built an isolated grok driver with exact-match YAML and "no platform skip-hack" — and today's `drivers/grok.py:34` inherits `BaseConsultationDriver` again with **no revert commit**: isolation without a mechanical gate silently re-couples. Therefore the isolation lint is load-bearing and must land BEFORE the first package merges (§5, §6-order).

## 2. Target layout
```
consultation_v2/platforms/<p>/          # p ∈ {chatgpt, claude, gemini, grok, perplexity}
    driver.py      # the 8-step flow for THIS platform only
    monitor.py     # completion detection for THIS platform only
    <p>.yaml       # THIS platform's exact-match element_map/workflow/validation
```
Five packages, five owners of their own behavior. **Duplication across packages is the intended shape** — five independently-editable copies; a fix to one is a fix to one. DRY across platforms is explicitly rejected: it is the coupling that keeps breaking production.

## 3. monitor.py is per-platform CODE — and an EXPLICIT, NAMED supersession of D2
Everything that decides "complete / stalled / failed" lives in the platform package: stop-button identity (from that platform's YAML), stop-gone debounce, deep-mode floors, interim-ACK guards (gemini), answer-thread assertion, exception-state mapping (rate_limited / content_filter / auth_wall / generation_stalled), degraded-read guards.
**Supersession record (council-required):** removing shared `completion.py` knowingly REVERSES D2 (`8c8d20c9`, 2026-06-15, "unify completion detection into one shared stop-transition detector"), which was itself a deliberate fix for five drifting detectors. We re-accept the drifting-detectors defect class **eyes-open**, in exchange for eliminating the cross-platform blast radius (e132bf15 class), with two mitigations: (a) the §6 guard-preservation checklist proves each package carries the detector logic at extraction time; (b) post-migration, detector drift within one package can only break that package. This trade is the architecture decision, named, not a silent undo.

## 4. Shared code: the LEAF whitelist (corrected per council ground-runner/blast-shield)
A module is **leaf** iff it contains zero platform-conditional BEHAVIOR (no branches on platform identity, no per-platform policy). **Declared-registry carve-out:** pure DATA registries of platform identifiers and per-platform file/URL constants (`KNOWN_PLATFORMS`/`CHAT_PLATFORMS` in `yaml_contract.py`, the platform→IDENTITY-file map in `identity.py`, the platform list/alias map in `ingest.py`) are permitted in leaves and are exempt from §5.4 — data, not behavior.

**Leaf (importable by platform packages):** `clipboard.py`, `tree.py`, `yaml_contract.py` (loader, fail-closed), `types.py`, `notify.py`, `identity.py`, `storage_policy.py`, `ingest.py`, `stop_conditions.py`.

**NOT leaf — must be dispositioned during migration (each package task states its disposition):**
- `input.py`, `atspi.py` (council blast-shield, Observed): `input.py:186-297 switch_to_platform()` branches on per-platform URL_PATTERNS/TAB_SHORTCUTS/display routing, and `atspi.py:143-146` detects platform via URL_PATTERN iteration — platform-routing BEHAVIOR, not leaf. Disposition: during the grok extraction audit, the platform-routing functions split into the owning packages (each package navigates/finds its own Firefox using its own URL/display data from the registry); the residual mechanical core (raw key/click/type mechanics in input.py; bus/desktop plumbing + raw find_elements in atspi.py) is re-classified leaf by the grok PR review.
- `runtime.py`, `snapshot.py` — mechanical action/scan surface; audit during grok extraction: any platform-conditional behavior found is pushed into packages; the residual mechanical core is then re-classified leaf by the grok PR (the pattern-setting review).
- `platforms_runtime.py` — split BY KIND (council scope-sentinel/blast-shield correction): per-platform DATA (URL_PATTERNS, TAB_SHORTCUTS, display candidate lists) moves to the owning packages and/or declared registry; **fleet-level display ALLOCATION (`select_platform_display` lock-aware selection, the 9761aee0 two-display-set coordination) is ORCHESTRATOR-RETAINED (section 7)** — packages never allocate displays; they receive an allocated display. Module retires only after its retained functions are re-homed to an orchestrator-owned module.
- `planner.py`, `interact.py`, `primitives.py` — same audit rule as runtime.py.
- `cli.py:172` / `orchestrator.py:147` `if platform=='chatgpt'` identity branch (council-observed) — pushed down into the chatgpt package as part of pkg-chatgpt; the orchestrator keeps zero platform branches (§7).
- `display_readiness.py` / `display_watchdog.py` — infra-side, out of scope.

**Removed from the live path at decommission:** `drivers/base.py`, `completion.py` (per §3 supersession). Archived, not history-deleted.

## 5. Banned (build-failing isolation lint — MUST be CI-live BEFORE the first package merges)
1. `platforms/<a>/**` importing `platforms/<b>/**` for any a≠b.
2. Any platform package importing `drivers.base` or `completion`.
3. Any class in a platform package inheriting from a class defined outside that package (except `types.py` dataclasses). *(Council-verified: the live coupling is pure inheritance — zero `platform ==` branches exist in base/runtime/snapshot/primitives/planner/interact/completion — so this rule is the load-bearing one.)*
4. Any platform-conditional BRANCH in a leaf module (behavior, not the §4 declared-registry data carve-out).
5. Existing lints keep applying inside each package: exact-match YAML, no fuzzy/fallbacks, settle caps in the loader.
**Ordering (council-required):** the lint lands as its own task, CI-enforced and build-failing, and `pkg-grok` `depends:` on it. History (`90de2d6b` → silent re-coupling) is the proof this ordering is production-critical, not style.

## 6. Migration rules (behavior-preserving; NO logic rewrites) — with mechanical parity proof
- Source trees (pinned; inline ONLY from these SHAs, never older method versions — protects deliberate reverts `a89566d0`/`6f1f8602`/`5b69a1e3`): **chatgpt** @`599074da`; **claude** @`a04da10a`; **gemini/grok/perplexity** from `main` at branch time.
- Extraction = inline the platform's effective behavior (driver subclass + the base methods it actually reaches + its slice of monitor logic) into the package. Each PR attaches a **slice-diff artifact**: the inlined code diffed against the pinned source SHA's effective method bodies, byte-comparable.
- **GENERATIVE DISPOSITION TABLE (v4 — supersedes curated scoping; council-required root-cause shape):** parity is NOT proven against a hand-curated ledger or a named module subset — every council round against curated lists found the next uncovered fix (9761aee0, f991d951, 2da240dd). Instead, mechanically: for EVERY module code is moved out of or retired from (`drivers/base.py`, `completion.py`, AND every section-4 conditionally-leaf module touched by the audit-push or split — `runtime.py`, `snapshot.py`, `planner.py`, `interact.py`, `primitives.py`, `platforms_runtime.py`, `input.py`, `atspi.py`, plus the `cli.py`/`orchestrator.py` push-downs), run `git log --since=2026-05-25 --oneline -- <module>` at the pinned source SHA and give EVERY commit a disposition row: **inlined** (file:line citation in the package), **retained-in-orchestrator** (named in section 7), **data-moved-to-registry**, or **unreached-with-evidence** (call-graph/grep citation). The table + the slice-diff (inclusion parity) + the omission manifest (every un-inlined method of the moved surface) ship in the PR and are reviewed at the r5 gate. A commit with no row fails the gate. Nothing is dropped by unaudited judgment, and there is no curated subset left to be incomplete.
- The named ledger below REMAINS as the highest-stakes subset requiring explicit per-package citations (it seeds the table; it does not bound it):
- **THE FIX LEDGER (council-required; the checklist every package must clear):** each guard below is either evidenced PRESENT in the package (file:line citation against the pinned source) or recorded ABSENT-BY-DESIGN with rationale in the PR. A happy-path consult alone NEVER closes a package task.
  - `a4201f0c` anti-echo (reject_prompt_echo_response + evidence)
  - `5746f250` duplicate-send quarantine (possibly-landed gate before any (re)send)
  - `2ef15351` healthy-read gate on stop-absence (degraded-read guard) + thread-mode detector read
  - `37bd3485` + `9c4e41b4` per-mode timeout floors + `generation_stalled` mapping
  - `8caaf75e` scroll-to-absolute-bottom before extract
  - `503a0c47` stop-gone + attach-verify send gates
  - `420e0638` / `a21290a5` / `ac11bde2` Gemini interim-ACK gates (gemini package)
  - `fea887b9` / `707e7eeb` Claude Max deep-mode gate (claude package)
  - `c86bf4de` duplicate-exact-match (N>1 drift) guard
  - `46fed0f5` / `fd875ed4` / `2f80f252` navigation settle chain
  - `838421fd` dry-run dispatch guard
  - DBus transient-retry + stop-gone debounce (base.py/completion.py slices)
- Order: grok first (pattern-setter; also re-classifies the §4 conditionally-leaf residue). Packages otherwise independent — no cross-platform ordering deps.
- Each package on branch `platform-independence-<p>`, merged by conductor via gated PR + r5 at the SHA a real production consult validated (validated-tree == merge-tree).
- **Known-defect carry (council-required):** the chatgpt tree @`599074da` carries the DR-postcondition exact-name locator brittleness recorded in `010b7ed4`; pkg-chatgpt copies it faithfully (behavior-preserving) and a tracked follow-up task is created at migration time so its green validation is not read as defect-free.

## 7. Entry contract (callers unchanged; anti-echo gate survival)
`cli.py`/`orchestrator.py` keep the exact CLI surface and dispatch to `platforms/<p>.driver.run()`. The orchestrator retains only routing, identity consolidation, notify, and store policy — zero platform branches (the chatgpt identity special-case moves into pkg-chatgpt per §4).
**Fleet-gate survival (council-required, v3+v4):** all FLEET-LEVEL state stays ORCHESTRATOR/SHARED-retained, never fragmented into packages, each named retained-in-orchestrator in the decommission PR's disposition table: display-keyed dispatch locks (`5de5c6dd`); dead-session poisoning (`d9c1de09`); **lock-aware display-set allocation `select_platform_display` (`9761aee0` — packages receive an allocated display, never choose one)**; **run-state idempotency/resume guard (`f991d951` — never double-dispatch a landed send)**; the orchestrator-side hook of the Claude large-packet delivery gate (`2da240dd`; its in-driver `large_packet_substance_gate` is inside the pinned claude tree @a04da10a and appears in the claude package's disposition table). Two packages must never be able to de-serialize dispatch onto the displays (invariant 5).
**Delivery-gate survival (council red-team-required):** every package driver exposes the uniform delivery-gate method (`reject_prompt_echo_response`) as part of the entry contract; the orchestrator continues to invoke it before notify, and each package also enforces it at its own `run()` exit. The untrusted-extract → notify → fleet-Redis injection path stays double-gated; decommissioning base.py may not orphan this gate (lint 5.2 + entry-contract check both fail the build if a package lacks it).

## 8. Validation oracle (per THE RULE / NO TESTS) — happy path AND guard parity
A package is done only when BOTH hold:
1. **Production consult:** ONE real consult runs e2e on that platform's display (navigate → select → attach → send → per-platform monitor completion on stop-gone → extract → notify) with step evidence + screenshots. Executed by an Opus 4.8 subagent or CLI peer; Fable judges evidence only.
2. **Guard-preservation checklist (§6 ledger) complete** in the PR: every ledger item cited present (file:line vs pinned SHA) or absent-by-design with rationale — reviewed at the r5 gate.
Plan exit oracle: after decommission, a 5-platform fan-out (sequential sends) runs green without intervention on one tree, and the isolation lint is green in CI.
