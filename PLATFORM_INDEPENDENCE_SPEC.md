# PLATFORM_INDEPENDENCE_SPEC — per-platform driver + YAML + monitor
v1 draft, 2026-07-03, taeys-hands (Fable). Jesse-directed architecture: "everyone needs their own YAML, their own driver and their own monitor... Each platform is completely independent."
Status: DRAFT → DCM council review → conductor ratification. Gates all `consult-platform-independence` work.

## 1. Why (Observed evidence, not opinion)
The shared behavioral base couples all five platforms: one shared-monitor change (`e132bf15`, Jun-22) simultaneously broke Grok, Gemini DR, and Perplexity DR (`MONITOR_REGRESSION_ARCHAEOLOGY_2026-07-03.md`); the audit-fix plan had to serialize every `base.py` fix into a depends-chain because each touched all platforms. `drivers/base.py` is 2,856 lines of shared behavior — every line is shared blast-radius. After this spec, a change inside one platform package is **structurally incapable** of breaking another platform.

## 2. Target layout
```
consultation_v2/platforms/<p>/          # p ∈ {chatgpt, claude, gemini, grok, perplexity}
    driver.py      # the 8-step flow for THIS platform only
    monitor.py     # completion detection for THIS platform only
    <p>.yaml       # THIS platform's exact-match element_map/workflow/validation
```
Five packages, five owners of their own behavior. **Duplication across packages is the intended shape** — if the same 40 lines of stop-gone debounce appear five times, that is five independently-editable copies, and a fix to one is a fix to one. DRY across platforms is explicitly rejected; it is the coupling that keeps breaking production.

## 3. monitor.py is per-platform CODE
Everything that decides "this consult is complete / stalled / failed" lives in the platform package: stop-button element identity (from that platform's YAML), stop-gone debounce counts, deep-mode floors (e.g. DT/DR/heavy/pro-extended patience), interim-ACK guards (gemini), answer-thread assertion, exception-state mapping (rate_limited / content_filter / auth_wall / generation_stalled), degraded-read guards. No shared `CompletionDetector`, no inherited `monitor_generation`. A platform's monitor may only be edited in that platform's package.

## 4. Shared code: the LEAF whitelist (exhaustive)
A module is **leaf** iff it contains zero platform-conditional behavior (no `if platform == ...`, no per-platform constants, no completion/selection/extraction policy). Permitted imports for a platform package:

| Leaf module | Provides |
|---|---|
| `atspi.py` | bus/desktop plumbing, find_firefox, raw find_elements |
| `input.py` | key/click/type/paste mechanics |
| `clipboard.py` | clipboard read/write |
| `tree.py` | tree walking |
| `snapshot.py` | snapshot builders (document / app-root / menu scans) |
| `runtime.py` | the mechanical action surface (click, paste, navigate, focus_and_key_open, scrolls, waits) |
| `yaml_contract.py` | the fail-closed YAML loader + schema (loads any platform's YAML; contains no platform behavior) |
| `types.py` | ConsultationRequest/Result/Snapshot/ElementRef/StepRecord |
| `notify.py` | Redis notify + durable park (w1e shape) |
| `identity.py` | FAMILY_KERNEL/IDENTITY packet consolidation |
| `storage_policy.py`, `ingest.py` | store discipline (default-off, fail-loud) |
| `stop_conditions.py` | the stop-condition enum (names only) |

**Conditionally leaf (must be audited during migration):** `runtime.py`, `snapshot.py`, `planner.py`, `platforms_runtime.py`, `interact.py`, `primitives.py` — any platform-conditional branch found inside them is pushed DOWN into the owning platform package as part of that platform's migration task. `display_readiness.py` / `display_watchdog.py` are infra-side, out of scope.

**Removed from the live path at decommission:** `drivers/base.py` (behavioral base), `completion.py` (shared detector). Archived, not history-deleted.

## 5. Banned (build-failing isolation lint)
1. `platforms/<a>/**` importing `platforms/<b>/**` for any a≠b.
2. Any platform package importing `drivers.base` or `completion`.
3. Any class in a platform package inheriting from a class defined outside that package (except `types.py` dataclasses).
4. Any platform-name literal (`'chatgpt'`, `'gemini'`, …) appearing in a leaf module (drift back toward shared behavior).
5. Existing lints keep applying inside each package: exact-match YAML, no `name_contains`/fuzzy/fallbacks, settle caps in the loader.

## 6. Migration rules (behavior-preserving; NO logic rewrites)
- Source trees: **chatgpt** from branch `consult-engine-audit-fix-w2e-typeahead-postcondition` @`599074da` (absorbs the live-validated w2e fix); **claude** from `consult-engine-audit-fix-w2d-claude-blindcoord` @`a04da10a` (absorbs w2d); **gemini/grok/perplexity** from `main`.
- Extraction = copy the platform's current effective behavior (its driver subclass + the base methods it actually uses + its slice of the shared monitor) into the package, resolving inheritance by inlining. Same runtime behavior before/after is the review criterion; improvements are separate later tasks.
- Order: grok first (audit-clean, smallest) to establish the pattern; the other four copy the pattern. Packages are independent — no cross-platform ordering deps.
- Each package lands on its own branch (`platform-independence-<p>`), merged by conductor via gated PR + r5 at the SHA a real production consult validated (validated-tree == merge-tree).

## 7. Entry contract (callers unchanged)
`cli.py`/`orchestrator.py` keep the exact CLI surface (`--platform ... --message ... --attach ... --select ...`) and dispatch to `platforms/<p>.driver.run()`. The orchestrator retains only routing, identity consolidation, notify, and store policy — no per-platform behavior.

## 8. Validation oracle (per THE RULE / NO TESTS)
Each package is done only when ONE real consult runs e2e on that platform's display (navigate → select → attach → send → per-platform monitor completion on stop-gone → extract → notify) with step evidence + screenshots. Executed by an Opus 4.8 subagent or CLI peer; Fable judges evidence only. Plan exit oracle: after decommission, a 5-platform fan-out (sequential sends) runs green without intervention on one tree.
