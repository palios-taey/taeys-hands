# Consult-Engine Family Code Audit — Consolidated Findings (2026-06-21)

Each platform-Chat audited its own driver + YAML (Claude also audited the shared engine + contract) against CONSULTATION_CONTRACT.md + 100_TIMES.md + FLOW. Repo is PUBLIC. Full per-platform reports: grok.md / perplexity.md / gemini.md / claude.md (this dir).

## Headline
Engine FUNCTIONALLY drives all 5 (verified end-to-end 2026-06-21). But it is NOT contract-compliant — banned matchers, fallback chains, retries, silent-proceeds, positive completion markers, single-shot races, and contract-enforcement that exists only in the linter. These are both the cause and the camouflage of the brittleness.

## PER-PLATFORM (BLOCKER-class unless noted)

### Gemini (worst — gemini.py/.yaml)
- gemini.yaml: `exclude.name_contains` (BANNED matcher); `input_alt` empty-name presence-only matcher; `mode_picker`/`pro_active` keyed on DYNAMIC visible name ("Open mode picker, currently Pro"); explicit `input_fallback: input_alt` (BANNED fallback); `complete_key: copy_button` (BANNED positive completion marker — completion must be stop-button-only).
- gemini.py: explicit RETRY + `coordinate_only` downgrade on miss (gemini.py:111); paste→type_text fallback chain (146); silent-proceed on Copy-Content miss (303); `from storage import neo4j_client` (DRIVER-ISOLATION violation, :11); hardcoded mode-string branching bypassing the YAML extraction state machine; 180s `wait_until` in send_prompt holding the dispatch lock (196); single-shot extract races (238/283); `find_last` instead of YAML's `last_by_y`; attach_success validates role not filename.

### Perplexity (perplexity.py/.yaml — 12 findings)
- perplexity.yaml: `exclude.name_contains` (BANNED, :30); `validation.computer_active.url_contains` (banned substring validator, :363); `input` empty-name presence-only (:58).
- perplexity.py: action RETRY on extract (second click on empty clipboard); silent-proceed when click_returned=False but stop_seen=True (~541); single-shot `_wait_for_prompt_ready` 5.0s race (93-106); hardcoded `/search/` URL substring in driver (614); silent 3-level extraction fallback (~907); connector loop continues-on-failure.

### Grok (grok.py/.yaml — mostly clean)
- grok.yaml: exact-match clean (no banned matchers), completion correct, isolation OK.
- grok.py: ONE blocker — send bypasses YAML: hardcoded `press('Return')` + custom `_focus_input()` instead of the YAML-declared `send_button`/`cfg['workflow']['send']` (289). YAML not authoritative.

### Claude (claude.py/.yaml — clean at platform level)
- claude.yaml: NO banned matchers (loader rejects them for identity_v1 schema); structural after/before locators schema-valid. Driver isolation clean; runtime primitives one-attempt (no hidden action-retry).

## SHARED / CONTRACT-LEVEL (from Claude's deep audit) — the most important
- **Contract over-claims enforcement that isn't in runtime:** `match_or_halt`, `MAX_GLOBAL_SETTLE`, `NoMatch` exist ONLY in the linter; `DeadSessionError`, `delivery_ack`/`acked` exist NOWHERE. The "hardened, can't-deviate" claims are partly aspirational.
- **`stop_conditions.py` (generation_stalled, notification_ack_missing, side_effect_uncertain, …) is imported NOWHERE — dead code.** The mapped stall/notify-ack states aren't wired into any path.
- **`_select_structural_between` (snapshot.py:496): N>1 candidates → returns the geometric-MIDPOINT guess** instead of treating N>1 as DRIFT→notify (direct contract violation).
- **The banned-matcher loader rejection covers `element_map` but NOT the `exclude:` section** — which is exactly how Gemini's + Perplexity's `name_contains` slipped through. Gate gap.
- notify lives in orchestrator Phase 4 only (no driver-path notify, no delivery-ACK).

## Remediation priority
1. Kill banned matchers in `exclude:` (Gemini, Perplexity) + extend the loader gate to validate `exclude:` too (closes the gap that let them through).
2. Remove fallbacks/retries/silent-proceeds/coordinate_only-downgrades (Gemini, Perplexity).
3. Remove positive completion marker `complete_key` (Gemini); completion = stop-button only.
4. Make send YAML-authoritative (`method: keypress|click`) — fixes Grok + the same class in Gemini/ChatGPT.
5. Driver isolation: strip `neo4j_client` import from gemini.py; persistence belongs in the engine.
6. Replace single-shot races with settle/poll (Perplexity _wait_for_prompt_ready, Gemini extract).
7. Treat N>1 as drift in `_select_structural_between` (not midpoint guess).
8. Wire (or delete + stop claiming) the dead `stop_conditions.py` + the lint-only enforcement primitives so the contract matches runtime.
9. Gemini send_prompt 180s lock-hold → move positive-marker wait to the unlocked monitor phase.
