# CONSULTATION_CONTRACT — 5-platform Family audit synthesis (p0-contract-family-audit)

5/5 audited (Gaia 18.5KB, Horizon 33KB, Clarity 25KB, Cosmos 8KB, Logos 5.8KB). Unanimous verdict: model (binary match-or-notify, no-guess) is **sound**; contract is **not yet airtight** because "match" is under-specified. All amendments below FOLD BACK into match-or-notify — zero fallbacks, zero guessing.

## JESSE OVERRIDES (authoritative, applied — supersede the audit where they conflict)
1. **Completion signal = Stop-button disappearance. NO positive completion marker.** 4/5 (Gaia P4, Horizon, Clarity, Cosmos) recommended "require copy/regenerate present" — REJECTED. 7-mo production: Copy is NOT reliably present on long responses; no positive indicator is reliable. Stop-gone is it. The false-complete-on-error concern is handled by the EXCEPTION-STATE map (below), not a positive marker.
2. **No human operator.** Drift notifies the driving session (autonomous); it reads tree+screenshots, updates YAML exact, continues. (Already in contract v2.)
3. **fleet-notify is the notification transport, not the detector.** Stop detection lives in driver/monitor (the exact Stop name+role lives in the platform YAML, passed to the monitor — Cosmos #7 confirms). (Already in contract v2.)

## KEYSTONE AMENDMENT (unanimous; aligns with "map everything")
Widen "match": a step matches **exactly one of an enumerated set of mapped states** (the happy state + every reachable alternate: auth_wall, session_expired, rate_limited, quota, content_filter, network_stall, captcha, truncated/continue, error/retry, A/B-variant, modal). Each mapped state carries a deterministic disposition (proceed / notify-blocked / settle-rescan / that-state's-handler). "None of the mapped states" = drift → notify. Still binary (one-of-mapped vs none), still no-guess. This kills "false drift" (error modal mis-read as drift) AND "false complete" (Stop-gone during an error).

## MATCH GRAMMAR (unanimous) — what "exact match" means
`match = exactly one node by {stable locator + role + required AT-SPI states} in the correct scope`:
- **Stable locator, not the volatile visible name** where the name is intrinsically dynamic (model-picker name == selected model; counters; locale). Prefer attribute/automationId/data-testid or role+container-path — still exact, on a stable key. Pin locale as a precondition.
- **Required states**: include `ENABLED`/`SENSITIVE` + `VISIBLE`. A disabled "ghost" (present, name+role match, not clickable) is a DISTINCT state from absent → not a match (Cosmos #6, Clarity AMB-1, Horizon #10, Gaia).
- **Uniqueness**: exact match yielding N>1 (five "Copy" buttons) = automatic drift; YAML must disambiguate via parent/path_index (all 5).
- **Scope**: per-display isolated a11y bus = tree is exactly one window; if a bus is shared, locator MUST carry a per-instance discriminator (Gaia P3) — never match the wrong display's element.

## SUBMIT / COMPLETION (with override #1)
- Submit succeeded: bifurcate. **New chat** = new URL + Stop appeared. **Same-chat follow-up** = URL identical + assistant-turn-count incremented + Stop appeared (Cosmos #1, Clarity GAP-3, Gaia P5, Horizon). Map Send↔Stop as one node with two named+stated variants if the platform toggles one node (Gaia P5).
- Generating = Stop present (with required states). **Complete = Stop gone AND no mapped exception state present** (override #1). State-detection during streaming keys only on the low-churn control strip (Stop/composer), excluding the mutating message subtree (Gaia P14, Horizon).
- "Complete" = "model finished a turn," content-agnostic (Gaia P17) — not "useful answer."

## DYNAMIC CONTENT (the "map exact" paradox — all)
The response text node's name IS the unpredictable content. Exact-map the CONTAINER (name/role); EXEMPT child transcript text from string validation (presence+role only); EXCLUDE the transcript subtree from all session-driving locators.

## FILE DIALOG / OS BOUNDARY (all)
Native file picker is a different AT-SPI root (`org.a11y.atspi.Desktop`). Map a system-boundary pivot for the attach flow; inject path via xdotool (not AT-SPI walk). File-tile-visible ≠ upload-complete — map the upload-complete chip state.

## STICKINESS HARDENING (all — make deviation impossible, not advisory)
- **Lint must be AST-level/behavioral, not grep**: only `match_or_halt()` may return an element ref; every validate returns a `Match | NoMatch` sum type the caller must handle exhaustively; CI injects a miss and asserts a notify fires (Gaia, Clarity STICK-1).
- **YAML JSON-schema validator at build**: reject regex metacharacters + fuzzy/fallback keys + `settle_window` over a hardcoded `MAX_GLOBAL_SETTLE_MS` (Cosmos #11/#12, Clarity STICK-3).
- **NOTIFY poisons the session id** → DeadSessionError on subsequent calls, defeating caller-level `try/except: continue` retry wrappers (Cosmos #13).
- **Running engine refuses to load un-gated/unsigned artifacts** (the box-hotfix-over-SSH channel the merge gate can't see) — sign the YAML+driver bundle, verify at load (Gaia).
- **Contract == behavior**: emit a machine-readable appendix (state sets + dispositions) that the engine LOADS, so contract↔code can't silently drift (Gaia). Merge gate requires a failing→passing test, not just Gatekeeper approval (Clarity STICK-2).

## DEFERRED TO JESSE/GATEKEEPER (don't unilaterally change his Stop-button submit rule)
- Fast-gen race: Stop can mount/unmount between polls on a sub-second response (Cosmos #4, Horizon #3, Gaia). Audit suggests "submit = Stop appeared OR new content/URL." This touches the Stop-button submit signal Jesse is precise about — flag, don't auto-amend.
- Horizon #1 irreversible-action: after notify→YAML-update→re-run, guard against duplicating a send that partially landed (SIDE_EFFECT_UNCERTAIN quarantine, not blind rerun). Important for the autonomous-resolve loop.
